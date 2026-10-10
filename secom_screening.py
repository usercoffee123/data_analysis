"""Apply fixed feature bounds and assemble a human review queue."""

from typing import Any

from secom_thresholds import inspect_row, references_from_thresholds


FLAG_REASONS = (
    "recorded_test_failure",
    "high_anomaly_burden",
    "low_measurement_coverage",
    "insufficient_reference_data",
)


def flag_reasons(
    label: int,
    score: float,
    missing_fraction: float,
    eligible_count: int,
    thresholds: dict[str, Any],
) -> list[str]:
    reasons = []
    if label == 1:
        reasons.append("recorded_test_failure")
    if eligible_count and score > thresholds["anomaly_threshold"]:
        reasons.append("high_anomaly_burden")
    if missing_fraction > thresholds["missing_fraction_threshold"]:
        reasons.append("low_measurement_coverage")
    if not eligible_count:
        reasons.append("insufficient_reference_data")
    return reasons


def investigation_steps(
    sample: dict[str, Any], findings: list[dict[str, Any]], missing: list[str]
) -> list[str]:
    steps = []
    if sample["recorded_test_result"] == "fail":
        steps.append("Review the recorded failed test and trace this production entity through manufacturing and test logs.")
    if findings:
        steps.append("Map the listed feature IDs to equipment signals; verify measurements and compare against approved process limits and comparable production records.")
    if missing:
        steps.append("Investigate the missing measurements and confirm whether acquisition gaps or unavailable tests explain them.")
    steps.append("Have a process engineer review the evidence; statistical differences alone do not establish a fault or root cause.")
    return steps


def sample_brief(
    sample: dict[str, Any],
    findings: list[dict[str, Any]],
    missing: list[str],
    feature_count: int,
) -> dict[str, Any]:
    return {
        **sample,
        "overall_status": "needs_review",
        "description": (
            f"Source row {sample['source_line']} has a recorded {sample['recorded_test_result']} test result. "
            f"{len(findings)} features fall outside the exploratory reference bounds; "
            f"{len(missing)} of {feature_count} measurements are missing ({sample['missing_fraction']:.1%}). "
            f"Anomaly burden is {sample['anomaly_score']:.2%} versus a {sample['anomaly_threshold']:.2%} review threshold. "
            "This is historical screening, not a predicted failure or a diagnosis."
        ),
        "unusual_features": findings,
        "missing_features": missing,
        "recommendations": investigation_steps(sample, findings, missing),
        "requires_human_review": True,
    }


def evaluate_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure statistical/coverage flags independently of already-known failures."""
    selected = [s for s in samples if any(r != "recorded_test_failure" for r in s["flag_reasons"])]
    failures = sum(s["recorded_test_result"] == "fail" for s in samples)
    caught = sum(s["recorded_test_result"] == "fail" for s in selected)
    passing = len(samples) - failures
    return {
        "sample_count": len(samples),
        "independent_flags": len(selected),
        "recorded_failures": failures,
        "failures_captured": caught,
        "failures_missed": failures - caught,
        "passing_records_flagged": len(selected) - caught,
        "failure_recall": caught / failures if failures else None,
        "passing_record_flag_rate": (len(selected) - caught) / passing if passing else None,
    }


def screening_method(
    thresholds: dict[str, Any], provenance: dict[str, Any], eligible_count: int
) -> dict[str, Any]:
    return {
        "settings": thresholds.get("settings", {}),
        "reference": "Saved thresholds applied to every input row without refitting. All-record evaluation is descriptive; no held-out cohort is claimed for this application run.",
        "threshold_provenance": provenance,
        "unusual_bounds": "Stored lower and upper bounds for each eligible feature; equality is not flagged",
        "anomaly_score": "Fraction of observed eligible features outside reference bounds",
        "anomaly_threshold": thresholds["anomaly_threshold"],
        "missing_fraction_threshold": thresholds["missing_fraction_threshold"],
        "missing_rule": "Missing fraction among eligible features must exceed the saved missing_fraction_threshold",
        "eligible_feature_count": eligible_count,
        "skipped_feature_count": thresholds["feature_count"] - eligible_count,
        "limitations": "Fixed thresholds define an exploratory review queue, not a trained failure predictor. Features marked ineligible in the file are skipped. All-record metrics are descriptive, not held-out validation. Statistical bounds are not operating limits. Unflagged records are not declared healthy.",
    }


def screen_records(
    rows: list[list[float | None]],
    labels: list[int],
    timestamps: list[str],
    thresholds: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Screen every row using saved values; never estimate or write thresholds."""
    references = references_from_thresholds(thresholds)
    eligible_count = sum(reference is not None for reference in references)
    samples, briefs = [], []
    for index, (row, label, timestamp) in enumerate(zip(rows, labels, timestamps)):
        missing = [f"feature_{i:03d}" for i, value in enumerate(row) if value is None]
        inspection = inspect_row(row, references)
        findings = inspection["findings"]
        score = inspection["anomaly_score"]
        coverage_gap = inspection["eligible_missing_fraction"]
        reasons = flag_reasons(label, score, coverage_gap, eligible_count, thresholds)
        sample = {
            "sample_id": f"sample_{index + 1:04d}",
            "source_line": index + 1,
            "timestamp": timestamp,
            "recorded_test_result": "fail" if label == 1 else "pass",
            "flagged": bool(reasons),
            "flag_reasons": reasons,
            "missing_count": len(missing),
            "missing_fraction": len(missing) / len(row),
            "unusual_feature_count": len(findings),
            "anomaly_score": score,
            "anomaly_threshold": thresholds["anomaly_threshold"],
            "eligible_missing_fraction": coverage_gap,
            "cohort": "saved_thresholds",
        }
        samples.append(sample)
        if reasons:
            briefs.append(sample_brief(sample, findings, missing, len(row)))
    return {
        "method": screening_method(thresholds, provenance, eligible_count),
        # Keep the report schema stable; this application run has no held-out cohort.
        "evaluation": {"held_out": evaluate_samples([]), "all_records": evaluate_samples(samples)},
        "sample_count": len(samples),
        "flagged_count": len(briefs),
        "reason_counts": {reason: sum(reason in s["flag_reasons"] for s in samples) for reason in FLAG_REASONS},
        "samples": samples,
        "flagged_sample_briefs": briefs,
    }
