"""Run the SECOM analysis graph using fixed, checked-in thresholds."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from manufacturing_analysis.common.io import read_input, write_json
from manufacturing_analysis.common.ollama import OLLAMA_MODEL, analyze_with_ollama
from manufacturing_analysis.secom.data import parse_secom, profile_secom
from manufacturing_analysis.secom.reporting import write_markdown_report
from manufacturing_analysis.secom.screening import screen_records
from manufacturing_analysis.secom.thresholds import load_thresholds, validate_thresholds
from manufacturing_analysis.secom.dataset import DEFAULT_THRESHOLDS_PATH


Analyzer = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]


class SecomState(TypedDict, total=False):
    data_text: str
    labels_text: str
    rows: list[list[float | None]]
    labels: list[int]
    timestamps: list[str]
    thresholds_path: Path
    thresholds: dict[str, Any]
    profile: dict[str, Any]
    sample_screening: dict[str, Any]
    model_analysis: dict[str, Any]
    output: dict[str, Any]


def screen_samples(state: SecomState) -> dict[str, Any]:
    """Graph node: load saved bounds and screen the entire input batch."""
    feature_count = len(state["rows"][0])
    if "thresholds" in state:
        thresholds = state["thresholds"]
        validate_thresholds(thresholds, feature_count)
        provenance = {"mode": "supplied_artifact", "fit": thresholds.get("fit", {})}
    else:
        path = state.get("thresholds_path") or DEFAULT_THRESHOLDS_PATH
        thresholds, provenance = load_thresholds(path, feature_count)
    screening = screen_records(
        state["rows"], state["labels"], state["timestamps"], thresholds, provenance
    )
    return {"sample_screening": screening}


def model_evidence(state: SecomState) -> dict[str, Any]:
    """Send aggregate evidence rather than every measurement or sample brief."""
    profile = {key: value for key, value in state["profile"].items() if key != "features"}
    profile["most_missing_features"] = sorted(
        state["profile"]["features"], key=lambda feature: feature["missing_count"], reverse=True
    )[:10]
    screening = state["sample_screening"]
    keys = ("method", "sample_count", "flagged_count", "reason_counts", "evaluation")
    profile["sample_screening_summary"] = {key: screening[key] for key in keys}
    return profile


def analyze_secom(state: SecomState, analyzer: Analyzer | None) -> dict[str, Any]:
    """Graph node: optional commentary never replaces deterministic evidence."""
    if analyzer is None:
        analysis = {"status": "skipped", "summary": "LLM commentary disabled."}
    else:
        try:
            analysis = {**analyzer([], [model_evidence(state)]), "status": "success"}
        except Exception as exc:
            analysis = {
                "status": "failure",
                "summary": "LLM commentary unavailable; deterministic evidence is retained.",
                "error": f"{type(exc).__name__}: {exc}",
            }
    return {"model_analysis": analysis}


def create_secom_brief(state: SecomState) -> dict[str, Any]:
    """Graph node: combine dataset findings, sample briefs, and model commentary."""
    profile = state["profile"]
    return {"output": {
        "overall_status": "needs_review",
        "description": (
            f"The historical dataset contains {profile['row_count']} production records with "
            f"{profile['feature_count']} anonymous features. Recorded tests show {profile['pass_count']} "
            f"passes and {profile['fail_count']} failures ({profile['failure_rate']:.2%}). "
            f"There are {profile['missing_value_count']} missing measurements. "
            "These observations do not identify a root cause or establish current equipment health."
        ),
        "recommendations": [
            "Review failed production records with the process engineer and correlate them with traceable manufacturing logs.",
            "Obtain feature names, units, equipment mapping, and approved limits before making sensor-specific decisions.",
            "Investigate missing measurements and define a documented imputation or exclusion policy.",
            "Before predicting failures, evaluate a separate classifier on held-out data, accounting for class imbalance and preventing label leakage.",
        ],
        "profile": profile,
        "sample_screening": state["sample_screening"],
        "model_analysis": state["model_analysis"],
        "requires_human_review": True,
    }}


def build_secom_graph(analyzer: Analyzer | None = analyze_with_ollama):
    def analyze_node(state: SecomState) -> dict[str, Any]:
        return analyze_secom(state, analyzer)

    graph = StateGraph(SecomState)
    nodes = (
        ("parse", parse_secom),
        ("profile", profile_secom),
        ("screen", screen_samples),
        ("analyze", analyze_node),
        ("decide", create_secom_brief),
    )
    previous = START
    for name, function in nodes:
        graph.add_node(name, function)
        graph.add_edge(previous, name)
        previous = name
    graph.add_edge(previous, END)
    return graph.compile()


def validate_report_paths(manifest_path: Path, inputs: list[Path]) -> None:
    """Prevent reports from overwriting an input or another report."""
    markdown = manifest_path.with_suffix(".md")
    reports = (manifest_path, markdown, markdown.with_name(markdown.stem + ".summary.md"))
    protected = {path.resolve() for path in inputs}
    destinations = {path.resolve() for path in reports}
    if destinations & protected:
        raise ValueError("Report destinations must differ from input and threshold files")
    if len(destinations) != len(reports):
        raise ValueError("Manifest filename must differ from Markdown destinations")


def verified_text(path: Path, digest: str, inputs: list[dict[str, Any]]) -> str:
    content, metadata = read_input(path, digest)
    inputs.append(metadata)
    if not metadata["digest_verified"]:
        raise ValueError(f"SHA-256 verification failed for {path}")
    return content.decode("utf-8")


def process_secom(
    data_path: Path,
    labels_path: Path,
    expected_data_sha256: str,
    expected_labels_sha256: str,
    manifest_path: Path,
    analyzer: Analyzer | None = analyze_with_ollama,
    thresholds_path: Path | None = None,
) -> dict[str, Any]:
    """Verify files, run the graph, and save evidence even when analysis fails."""
    thresholds_path = thresholds_path or DEFAULT_THRESHOLDS_PATH
    validate_report_paths(manifest_path, [data_path, labels_path, thresholds_path])
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "UCI SECOM",
        "source": "https://archive.ics.uci.edu/dataset/179/secom",
        "model": OLLAMA_MODEL if analyzer else "disabled",
        "status": "failure",
        "inputs": [],
    }
    try:
        state = {
            "data_text": verified_text(data_path, expected_data_sha256, manifest["inputs"]),
            "labels_text": verified_text(labels_path, expected_labels_sha256, manifest["inputs"]),
            "thresholds_path": thresholds_path,
        }
        result = build_secom_graph(analyzer).invoke(state)
        manifest["assessment"] = result["output"]
        manifest["status"] = "success"
    except Exception as exc:
        manifest["error"] = f"{type(exc).__name__}: {exc}"
    write_json(manifest_path, manifest)
    write_markdown_report(manifest, manifest_path.with_suffix(".md"))
    return manifest


def terminal_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Keep the full evidence on disk and show only aggregate results in the terminal."""
    summary = dict(manifest)
    if "assessment" not in manifest:
        return summary
    assessment = dict(manifest["assessment"])
    assessment["profile"] = {key: value for key, value in assessment["profile"].items() if key != "features"}
    assessment["sample_screening"] = {
        key: value for key, value in assessment["sample_screening"].items()
        if key not in ("samples", "flagged_sample_briefs")
    }
    summary["assessment"] = assessment
    return summary
