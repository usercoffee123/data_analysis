"""Load and apply fixed screening thresholds; no threshold estimation or writing."""

import hashlib
import json
import math
from pathlib import Path
from typing import Any



def score_rows(rows, references):
    scores, gaps = [], []
    eligible = sum(ref is not None for ref in references)
    for row in rows:
        available = [(value, ref) for value, ref in zip(row, references)
                     if value is not None and ref is not None]
        scores.append(sum(value < ref[0] or value > ref[1] for value, ref in available)
                      / len(available) if available else 0.0)
        gaps.append(1 - len(available) / eligible if eligible else 1.0)
    return scores, gaps


def validate_thresholds(artifact: dict[str, Any], feature_count: int) -> None:
    def finite(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if not isinstance(artifact, dict) or type(artifact.get("schema_version")) is not int or artifact["schema_version"] != 1:
        raise ValueError("Unsupported threshold file schema")
    if type(artifact.get("feature_count")) is not int or artifact["feature_count"] != feature_count:
        raise ValueError("Threshold feature count does not match the input data")
    if not isinstance(artifact.get("settings", {}), dict):
        raise ValueError("Threshold provenance settings must be an object")
    for name in ("anomaly_threshold", "missing_fraction_threshold"):
        value = artifact.get(name)
        if not finite(value) or not 0 <= value <= 1:
            raise ValueError(f"Invalid saved {name}")
    features = artifact.get("features")
    if not isinstance(features, list) or len(features) != feature_count:
        raise ValueError("Threshold features must match the input column layout")
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("feature_id") != f"feature_{index:03d}" or type(feature.get("eligible")) is not bool:
            raise ValueError(f"Invalid threshold entry at feature {index}")
        values = [feature.get(key) for key in ("lower", "upper", "iqr")]
        if feature["eligible"]:
            if not all(finite(value) for value in values) or values[0] >= values[1] or values[2] <= 0:
                raise ValueError(f"Invalid bounds at feature {index}")
        elif any(value is not None for value in values):
            raise ValueError(f"Skipped feature {index} must not contain bounds")


def load_thresholds(path: Path, feature_count: int):
    content = path.read_bytes()
    artifact = json.loads(content.decode("utf-8"))
    validate_thresholds(artifact, feature_count)
    return artifact, {"file": str(path), "sha256": hashlib.sha256(content).hexdigest(),
                      "fit": artifact.get("fit", {}), "source_inputs": artifact.get("source_inputs", [])}


def references_from_thresholds(artifact):
    return [(feature["lower"], feature["upper"], feature["iqr"]) if feature["eligible"] else None
            for feature in artifact["features"]]
