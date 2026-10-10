"""Validate, load, and apply fixed thresholds without estimating new ones."""

import hashlib
import json
import math
from pathlib import Path
from typing import Any


ThresholdArtifact = dict[str, Any]
ThresholdProvenance = dict[str, Any]
FeatureReference = tuple[float, float, float]  # Lower bound, upper bound, IQR.
FeatureReferences = list[FeatureReference | None]
MeasurementRows = list[list[float | None]]


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _validate_header(artifact: ThresholdArtifact, feature_count: int) -> None:
    version = artifact.get("schema_version")
    if type(version) is not int or version != 1:
        raise ValueError("Unsupported threshold file schema")

    saved_count = artifact.get("feature_count")
    if type(saved_count) is not int or saved_count != feature_count:
        raise ValueError("Threshold feature count does not match the input data")

    if not isinstance(artifact.get("settings", {}), dict):
        raise ValueError("Threshold provenance settings must be an object")


def _validate_review_cutoffs(artifact: ThresholdArtifact) -> None:
    for name in ("anomaly_threshold", "missing_fraction_threshold"):
        value = artifact.get(name)
        if not _is_finite_number(value) or not 0 <= value <= 1:
            raise ValueError(f"Invalid saved {name}")


def _validate_feature(feature: Any, index: int) -> None:
    if not isinstance(feature, dict):
        raise ValueError(f"Invalid threshold entry at feature {index}")
    if feature.get("feature_id") != f"feature_{index:03d}":
        raise ValueError(f"Invalid threshold entry at feature {index}")
    if type(feature.get("eligible")) is not bool:
        raise ValueError(f"Invalid threshold entry at feature {index}")

    lower, upper, iqr = (feature.get(name) for name in ("lower", "upper", "iqr"))
    if not feature["eligible"]:
        if any(value is not None for value in (lower, upper, iqr)):
            raise ValueError(f"Skipped feature {index} must not contain bounds")
        return

    if not all(_is_finite_number(value) for value in (lower, upper, iqr)):
        raise ValueError(f"Invalid bounds at feature {index}")
    if lower >= upper or iqr <= 0:
        raise ValueError(f"Invalid bounds at feature {index}")


def validate_thresholds(artifact: dict[str, Any], feature_count: int) -> None:
    """Reject incompatible layouts, invalid bounds, and invalid review cutoffs."""
    if not isinstance(artifact, dict):
        raise ValueError("Unsupported threshold file schema")
    _validate_header(artifact, feature_count)
    _validate_review_cutoffs(artifact)

    features = artifact.get("features")
    if not isinstance(features, list) or len(features) != feature_count:
        raise ValueError("Threshold features must match the input column layout")
    for index, feature in enumerate(features):
        _validate_feature(feature, index)


def load_thresholds(
    path: Path, feature_count: int
) -> tuple[ThresholdArtifact, ThresholdProvenance]:
    """Load validated thresholds and record their file digest and provenance."""
    content = path.read_bytes()
    artifact = json.loads(content.decode("utf-8"))
    validate_thresholds(artifact, feature_count)
    provenance = {
        "file": str(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "fit": artifact.get("fit", {}),
        "source_inputs": artifact.get("source_inputs", []),
    }
    return artifact, provenance


def references_from_thresholds(artifact: ThresholdArtifact) -> FeatureReferences:
    """Return one bounds tuple per feature, or None for a skipped feature."""
    references: FeatureReferences = []
    for feature in artifact["features"]:
        if feature["eligible"]:
            references.append((feature["lower"], feature["upper"], feature["iqr"]))
        else:
            references.append(None)
    return references


def inspect_row(row: list[float | None], references: FeatureReferences) -> dict[str, Any]:
    """Collect deviation evidence and both screening scores in one feature pass.

    Anomaly scores use observed eligible features as their denominator. Missing
    fractions use all eligible features, including those with no measurement.
    """
    eligible_count = 0
    observed_count = 0
    findings = []
    for index, reference in enumerate(references):
        if reference is None:
            continue
        eligible_count += 1
        value = row[index] if index < len(row) else None
        if value is None:
            continue
        observed_count += 1
        lower, upper, iqr = reference
        if not (value < lower or value > upper):
            continue
        below = value < lower
        distance = lower - value if below else value - upper
        findings.append({
            "feature_id": f"feature_{index:03d}",
            "value": value,
            "reference_min": lower,
            "reference_max": upper,
            "direction": "below" if below else "above",
            "distance_in_iqr": distance / iqr,
        })

    findings.sort(key=lambda finding: finding["distance_in_iqr"], reverse=True)
    return {
        "findings": findings,
        "anomaly_score": len(findings) / observed_count if observed_count else 0.0,
        "eligible_missing_fraction": 1 - observed_count / eligible_count if eligible_count else 1.0,
    }


def score_rows(
    rows: MeasurementRows, references: FeatureReferences
) -> tuple[list[float], list[float]]:
    """Return anomaly scores and eligible-feature missing fractions for each row."""
    scores, missing_fractions = [], []
    for row in rows:
        result = inspect_row(row, references)
        scores.append(result["anomaly_score"])
        missing_fractions.append(result["eligible_missing_fraction"])

    return scores, missing_fractions
