"""Profile UCI SECOM manufacturing data and produce an LLM-assisted review brief."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from sensor_graph import OLLAMA_MODEL, _write_manifest, analyze_with_ollama
from secom_reporting import write_markdown_report
from secom_thresholds import (load_thresholds, references_from_thresholds,
                              score_rows, validate_thresholds)


DEFAULT_THRESHOLDS_PATH = Path(__file__).with_name("secom.thresholds.json")


class SecomState(TypedDict, total=False):
    data_text: str
    labels_text: str
    rows: list[list[float | None]]
    labels: list[int]
    timestamps: list[str]
    profile: dict[str, Any]
    sample_screening: dict[str, Any]
    model_analysis: dict[str, Any]
    output: dict[str, Any]
    thresholds_path: Path
    thresholds: dict[str, Any]


def parse_secom(state: SecomState) -> dict[str, Any]:
    rows = []
    width = None
    for line_number, line in enumerate(state["data_text"].splitlines(), 1):
        if not line.strip():
            raise ValueError(f"Empty feature row at line {line_number}")
        row = []
        for token in line.split():
            value = None if token.lower() == "nan" else float(token)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"Non-finite feature at line {line_number}")
            row.append(value)
        width = len(row) if width is None else width
        if len(row) != width:
            raise ValueError(f"Inconsistent feature count at line {line_number}")
        rows.append(row)
    labels, timestamps = [], []
    for line_number, line in enumerate(state["labels_text"].splitlines(), 1):
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or parts[0] not in ("-1", "1"):
            raise ValueError(f"Invalid label at line {line_number}; expected -1 or 1 and timestamp")
        timestamp = parts[1]
        if timestamp.startswith('"') and timestamp.endswith('"'):
            timestamp = timestamp[1:-1]
        datetime.strptime(timestamp, "%d/%m/%Y %H:%M:%S")
        labels.append(int(parts[0]))
        timestamps.append(timestamp)
    if not rows or len(rows) != len(labels):
        raise ValueError("Feature and label files must contain equal, nonzero row counts")
    return {"rows": rows, "labels": labels, "timestamps": timestamps}


def profile_secom(state: SecomState) -> dict[str, Any]:
    rows, labels = state["rows"], state["labels"]
    features = []
    for index, column in enumerate(zip(*rows)):
        observed = [value for value in column if value is not None]
        features.append({
            "feature_id": f"feature_{index:03d}",
            "missing_count": len(rows) - len(observed),
            "observed_count": len(observed),
            "min": min(observed) if observed else None,
            "max": max(observed) if observed else None,
            "mean": statistics.fmean(observed) if observed else None,
            "constant": bool(observed) and min(observed) == max(observed),
        })
    failures = labels.count(1)
    ordered_dates = sorted(datetime.strptime(t, "%d/%m/%Y %H:%M:%S") for t in state["timestamps"])
    return {"profile": {
        "dataset": "UCI SECOM",
        "row_count": len(rows),
        "feature_count": len(features),
        "pass_count": labels.count(-1),
        "fail_count": failures,
        "failure_rate": failures / len(rows),
        "missing_value_count": sum(f["missing_count"] for f in features),
        "all_missing_feature_count": sum(f["observed_count"] == 0 for f in features),
        "constant_feature_count": sum(f["constant"] for f in features),
        "test_period": {"start": ordered_dates[0].isoformat(), "end": ordered_dates[-1].isoformat()},
        "features": features,
        "limitations": "Anonymous features; units and approved operating limits are unavailable. Labels are historical test outcomes, not predictions. No causal analysis or failure predictor was fitted.",
    }}


def screen_samples(state: SecomState) -> dict[str, Any]:
    """Apply fixed thresholds to every record. Fitting is an explicit separate operation."""
    rows = state["rows"]
    order = list(range(len(rows)))
    if "thresholds" in state:
        thresholds = state["thresholds"]
        validate_thresholds(thresholds, len(rows[0]))
        provenance = {"mode": "supplied_artifact", "fit": thresholds.get("fit", {})}
    else:
        thresholds, provenance = load_thresholds(state.get("thresholds_path") or DEFAULT_THRESHOLDS_PATH, len(rows[0]))
    cohort = {i: "saved_thresholds" for i in order}
    evaluation_ids = []
    reference_description = "Saved thresholds applied to every input row without refitting. All-record evaluation is descriptive; no held-out cohort is claimed for this application run."
    references = references_from_thresholds(thresholds)
    scores, coverage_gaps = score_rows(rows, references)
    eligible_count = sum(ref is not None for ref in references)
    score_threshold = thresholds["anomaly_threshold"]
    missing_threshold = thresholds["missing_fraction_threshold"]
    samples, briefs = [], []
    for index, (row, label, timestamp) in enumerate(zip(rows, state["labels"], state["timestamps"]), 1):
        missing = [f"feature_{i:03d}" for i, value in enumerate(row) if value is None]
        unusual = []
        for feature_index, (value, reference) in enumerate(zip(row, references)):
            if value is None or reference is None:
                continue
            low, high, iqr = reference
            if value < low or value > high:
                unusual.append({
                    "feature_id": f"feature_{feature_index:03d}", "value": value,
                    "reference_min": low, "reference_max": high,
                    "direction": "below" if value < low else "above",
                    "distance_in_iqr": (low - value if value < low else value - high) / iqr,
                })
        unusual.sort(key=lambda item: item["distance_in_iqr"], reverse=True)
        reasons = []
        if label == 1:
            reasons.append("recorded_test_failure")
        if eligible_count and scores[index - 1] > score_threshold:
            reasons.append("high_anomaly_burden")
        if coverage_gaps[index - 1] > missing_threshold:
            reasons.append("low_measurement_coverage")
        if not eligible_count:
            reasons.append("insufficient_reference_data")
        sample = {
            "sample_id": f"sample_{index:04d}", "source_line": index,
            "timestamp": timestamp, "recorded_test_result": "fail" if label == 1 else "pass",
            "flagged": bool(reasons), "flag_reasons": reasons,
            "missing_count": len(missing), "missing_fraction": len(missing) / len(row),
            "unusual_feature_count": len(unusual),
            "anomaly_score": scores[index - 1], "anomaly_threshold": score_threshold,
            "eligible_missing_fraction": coverage_gaps[index - 1],
            "cohort": cohort[index - 1],
        }
        samples.append(sample)
        if not reasons:
            continue
        recommendations = []
        if label == 1:
            recommendations.append("Review the recorded failed test and trace this production entity through manufacturing and test logs.")
        if unusual:
            recommendations.append("Map the listed feature IDs to equipment signals; verify measurements and compare against approved process limits and comparable production records.")
        if missing:
            recommendations.append("Investigate the missing measurements and confirm whether acquisition gaps or unavailable tests explain them.")
        recommendations.append("Have a process engineer review the evidence; statistical differences alone do not establish a fault or root cause.")
        briefs.append({
            **sample, "overall_status": "needs_review",
            "description": (
                f"Source row {index} has a recorded {sample['recorded_test_result']} test result. "
                f"{len(unusual)} features fall outside the exploratory reference bounds; "
                f"{len(missing)} of {len(row)} measurements are missing ({sample['missing_fraction']:.1%}). "
                f"Anomaly burden is {sample['anomaly_score']:.2%} versus a {score_threshold:.2%} review threshold. "
                "This is historical screening, not a predicted failure or a diagnosis."
            ),
            "unusual_features": unusual, "missing_features": missing,
            "recommendations": recommendations, "requires_human_review": True,
        })
    def evaluate(ids):
        # Exclude known-failure flags: measuring those would artificially guarantee recall.
        selected = {i for i in ids if any(reason != "recorded_test_failure"
                                         for reason in samples[i]["flag_reasons"])}
        failures = sum(state["labels"][i] == 1 for i in ids)
        caught = sum(state["labels"][i] == 1 for i in selected)
        passing = len(ids) - failures
        return {"sample_count": len(ids), "independent_flags": len(selected),
                "recorded_failures": failures, "failures_captured": caught,
                "failures_missed": failures - caught,
                "passing_records_flagged": len(selected) - caught,
                "failure_recall": caught / failures if failures else None,
                "passing_record_flag_rate": (len(selected) - caught) / passing if passing else None}
    return {"sample_screening": {
        "method": {
            "settings": thresholds.get("settings", {}),
            "reference": reference_description,
            "threshold_provenance": provenance,
            "unusual_bounds": "Stored lower and upper bounds for each eligible feature; equality is not flagged",
            "anomaly_score": "Fraction of observed eligible features outside reference bounds",
            "anomaly_threshold": score_threshold,
            "missing_fraction_threshold": missing_threshold,
            "missing_rule": "Missing fraction among eligible features must exceed the saved missing_fraction_threshold",
            "eligible_feature_count": sum(r is not None for r in references),
            "skipped_feature_count": sum(r is None for r in references),
            "limitations": "Fixed thresholds define an exploratory review queue, not a trained failure predictor. Features marked ineligible in the file are skipped. All-record metrics are descriptive, not held-out validation. Statistical bounds are not operating limits. Unflagged records are not declared healthy.",
        },
        "evaluation": {"held_out": evaluate(evaluation_ids), "all_records": evaluate(order)},
        "sample_count": len(samples), "flagged_count": len(briefs),
        "reason_counts": {reason: sum(reason in s["flag_reasons"] for s in samples)
                          for reason in ("recorded_test_failure", "high_anomaly_burden", "low_measurement_coverage", "insufficient_reference_data")},
        "samples": samples, "flagged_sample_briefs": briefs,
    }}


def create_secom_brief(state: SecomState) -> dict[str, Any]:
    profile = state["profile"]
    recommendations = [
        "Review failed production records with the process engineer and correlate them with traceable manufacturing logs.",
        "Obtain feature names, units, equipment mapping, and approved limits before making sensor-specific decisions.",
        "Investigate missing measurements and define a documented imputation or exclusion policy.",
        "Before predicting failures, evaluate a separate classifier on held-out data, accounting for class imbalance and preventing label leakage.",
    ]
    return {"output": {
        "overall_status": "needs_review",
        "description": (
            f"The historical dataset contains {profile['row_count']} production records with "
            f"{profile['feature_count']} anonymous features. Recorded tests show {profile['pass_count']} "
            f"passes and {profile['fail_count']} failures ({profile['failure_rate']:.2%}). "
            f"There are {profile['missing_value_count']} missing measurements. "
            "These observations do not identify a root cause or establish current equipment health."
        ),
        "recommendations": recommendations,
        "profile": profile,
        "sample_screening": state["sample_screening"],
        "model_analysis": state["model_analysis"],
        "requires_human_review": True,
    }}


def build_secom_graph(analyzer: Callable | None = analyze_with_ollama):
    def analyze_node(state: SecomState) -> dict[str, Any]:
        # Send compact aggregate evidence, never all 1567 x 590 measurements.
        profile = {key: value for key, value in state["profile"].items() if key != "features"}
        profile["most_missing_features"] = sorted(
            state["profile"]["features"], key=lambda f: f["missing_count"], reverse=True
        )[:10]
        screening = state["sample_screening"]
        profile["sample_screening_summary"] = {
            key: screening[key] for key in ("method", "sample_count", "flagged_count", "reason_counts", "evaluation")
        }
        if analyzer is None:
            return {"model_analysis": {"status": "skipped", "summary": "LLM commentary disabled."}}
        try:
            return {"model_analysis": {**analyzer([], [profile]), "status": "success"}}
        except Exception as exc:
            return {"model_analysis": {"status": "failure", "summary": "LLM commentary unavailable; deterministic evidence is retained.",
                                       "error": f"{type(exc).__name__}: {exc}"}}

    graph = StateGraph(SecomState)
    graph.add_node("parse", parse_secom)
    graph.add_node("profile", profile_secom)
    graph.add_node("screen", screen_samples)
    graph.add_node("analyze", analyze_node)
    graph.add_node("decide", create_secom_brief)
    graph.add_edge(START, "parse")
    graph.add_edge("parse", "profile")
    graph.add_edge("profile", "screen")
    graph.add_edge("screen", "analyze")
    graph.add_edge("analyze", "decide")
    graph.add_edge("decide", END)
    return graph.compile()



def process_secom(data_path: Path, labels_path: Path, expected_data_sha256: str,
                  expected_labels_sha256: str, manifest_path: Path,
                  analyzer: Callable | None = analyze_with_ollama,
                  thresholds_path: Path | None = None) -> dict[str, Any]:
    thresholds_path = thresholds_path or DEFAULT_THRESHOLDS_PATH
    markdown = manifest_path.with_suffix('.md')
    output_paths = (manifest_path, markdown, markdown.with_name(markdown.stem + '.summary.md'))
    input_paths = {data_path.resolve(), labels_path.resolve()}
    if thresholds_path:
        input_paths.add(thresholds_path.resolve())
    if any(path.resolve() in input_paths for path in output_paths):
        raise ValueError("Report destinations must differ from input and threshold files")
    if len({path.resolve() for path in output_paths}) != len(output_paths):
        raise ValueError("Manifest filename must differ from Markdown destinations")
    manifest = {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "UCI SECOM", "source": "https://archive.ics.uci.edu/dataset/179/secom",
        "model": OLLAMA_MODEL if analyzer else "disabled", "status": "failure", "inputs": [],
    }
    try:
        contents = []
        for path, expected in ((data_path, expected_data_sha256), (labels_path, expected_labels_sha256)):
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            verified = isinstance(expected, str) and digest == expected.lower()
            manifest["inputs"].append({"file": str(path), "sha256": digest,
                                       "expected_sha256": expected, "digest_verified": verified})
            if not verified:
                raise ValueError(f"SHA-256 verification failed for {path}")
            contents.append(content.decode("utf-8"))
        result = build_secom_graph(analyzer).invoke({"data_text": contents[0], "labels_text": contents[1],
                                                  "thresholds_path": thresholds_path})
        manifest["assessment"] = result["output"]
        manifest["status"] = "success"
    except Exception as exc:
        manifest["error"] = f"{type(exc).__name__}: {exc}"
    _write_manifest(manifest_path, manifest)
    write_markdown_report(manifest, manifest_path.with_suffix(".md"))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze UCI SECOM data with LangGraph and local Ollama")
    parser.add_argument("data", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--sha256", required=True, help="Expected digest of secom.data")
    parser.add_argument("--labels-sha256", required=True)
    parser.add_argument("--manifest", type=Path, default=Path("secom.manifest.json"))
    parser.add_argument("--no-llm", action="store_true", help="Run screening without Ollama")
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS_PATH,
                        help="Fixed threshold file (default: checked-in secom.thresholds.json beside this script)")
    args = parser.parse_args()
    protected = {args.data.resolve(), args.labels.resolve()}
    if args.thresholds:
        protected.add(args.thresholds.resolve())
    markdown = args.manifest.with_suffix('.md')
    outputs = (args.manifest, markdown, markdown.with_name(markdown.stem + '.summary.md'))
    if any(path.resolve() in protected for path in outputs):
        parser.error('Report destinations must differ from input files')
    if len({path.resolve() for path in outputs}) != len(outputs):
        parser.error('Use a manifest filename that differs from its Markdown outputs (such as .json)')
    manifest = process_secom(args.data, args.labels, args.sha256, args.labels_sha256, args.manifest,
                             None if args.no_llm else analyze_with_ollama, thresholds_path=args.thresholds)
    # Full per-feature statistics are in the manifest; keep terminal output readable.
    brief = dict(manifest)
    if "assessment" in brief:
        brief["assessment"] = dict(brief["assessment"])
        brief["assessment"]["profile"] = {k: v for k, v in brief["assessment"]["profile"].items() if k != "features"}
        brief["assessment"]["sample_screening"] = {
            k: v for k, v in brief["assessment"]["sample_screening"].items()
            if k not in ("samples", "flagged_sample_briefs")
        }
    print(json.dumps(brief, indent=2))
    if manifest["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
