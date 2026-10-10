"""Sensor triage: validate input, check configured bounds, and interpret findings."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from manufacturing_analysis.common.io import read_input, write_json
from manufacturing_analysis.common.ollama import OLLAMA_MODEL, analyze_with_ollama


THRESHOLD_KEYS = ("warning_min", "warning_max", "critical_min", "critical_max")


class SensorState(TypedDict, total=False):
    payload: dict[str, Any]
    readings: list[dict[str, Any]]
    assessments: list[dict[str, Any]]
    errors: list[str]
    model_analysis: dict[str, Any]
    output: dict[str, Any]


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _validate_reading(item: Any, prefix: str) -> tuple[dict[str, Any] | None, str | None]:
    """Normalize one reading, or return its first validation error."""
    if not isinstance(item, dict):
        return None, f"{prefix} must be an object"
    sensor_id = item.get("sensor_id")
    if not isinstance(sensor_id, str) or not sensor_id.strip():
        return None, f"{prefix}.sensor_id must be a non-empty string"
    if not _is_number(item.get("value")):
        return None, f"{prefix}.value must be a finite number"

    reading = {
        "sensor_id": sensor_id,
        "value": item["value"],
        "unit": item.get("unit", ""),
    }
    for key in THRESHOLD_KEYS:
        threshold = item.get(key)
        if threshold is None:
            continue
        if not _is_number(threshold):
            return None, f"{prefix}.{key} must be a finite number"
        reading[key] = threshold

    for level in ("warning", "critical"):
        low_key, high_key = f"{level}_min", f"{level}_max"
        low, high = reading.get(low_key), reading.get(high_key)
        if low is not None and high is not None and low > high:
            return None, f"{prefix}.{low_key} must be less than or equal to {high_key}"
    return reading, None


def validate_input(state: SensorState) -> dict[str, Any]:
    payload = state.get("payload")
    if not isinstance(payload, dict):
        return {"readings": [], "errors": ["payload must be a JSON object"]}

    raw_readings = payload.get("readings")
    if not isinstance(raw_readings, list):
        return {"readings": [], "errors": ["payload.readings must be a list"]}

    readings: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(raw_readings):
        reading, error = _validate_reading(item, f"readings[{index}]")
        if error is not None:
            errors.append(error)
        elif reading is not None:
            readings.append(reading)

    return {"readings": readings, "errors": errors}


def _outside_bounds(reading: dict[str, Any], level: str) -> bool:
    low, high = reading.get(f"{level}_min"), reading.get(f"{level}_max")
    value = reading["value"]
    return (low is not None and value < low) or (high is not None and value > high)


def assess_readings(state: SensorState) -> dict[str, Any]:
    assessments = []
    for reading in state["readings"]:
        if _outside_bounds(reading, "critical"):
            status = "critical"
            evidence = "value is outside a configured critical bound"
        elif _outside_bounds(reading, "warning"):
            status = "warning"
            evidence = "value is outside a configured warning bound"
        elif any(key in reading for key in THRESHOLD_KEYS):
            status = "normal"
            evidence = "value is within configured bounds"
        else:
            status = "unknown"
            evidence = "no warning or critical bounds were configured"

        assessments.append({**reading, "status": status, "evidence": evidence})
    return {"assessments": assessments}


def _overall_decision(assessments: list[dict[str, Any]]) -> tuple[str, str]:
    """Choose the most severe status and its operator action."""
    statuses = {item["status"] for item in assessments}
    if "critical" in statuses:
        return (
            "critical",
            "Escalate using the site's approved response procedure and verify the sensor reading.",
        )
    if "warning" in statuses:
        return (
            "warning",
            "Review the flagged readings and follow the site's approved operating procedure.",
        )
    if "unknown" in statuses or not assessments:
        return (
            "needs_review",
            "Configure validated thresholds and review the readings before drawing an operational conclusion.",
        )
    return "normal", "Continue routine monitoring."


def _reading_brief(item: dict[str, Any]) -> tuple[str, str | None]:
    """Explain one assessed reading and suggest a follow-up when it needs attention."""
    sensor_id, value, status = item["sensor_id"], item["value"], item["status"]
    unit = item.get("unit", "")
    measurement = f"{value} {unit}".strip()
    if status in ("critical", "warning"):
        descriptions = []
        for direction, comparison in (("min", "below"), ("max", "above")):
            bound = item.get(f"{status}_{direction}")
            if bound is None:
                continue
            breached = value < bound if direction == "min" else value > bound
            if breached:
                limit = f"{bound} {unit}".strip()
                descriptions.append(
                    f"{sensor_id} measured {measurement}, {comparison} the "
                    f"configured {status} {direction} of {limit}."
                )
        return " ".join(descriptions), (
            f"Verify the {sensor_id} reading and sensor condition; review recent "
            "readings and operating context with the responsible operator."
        )
    if status == "unknown":
        return (
            f"{sensor_id} measured {measurement}, but no thresholds were "
            "configured, so its operational status could not be determined.",
            f"Have the responsible domain owner configure validated thresholds for {sensor_id}.",
        )
    return f"{sensor_id} measured {measurement}, within its configured bounds.", None


def create_decision_brief(state: SensorState) -> dict[str, Any]:
    assessments = state.get("assessments", [])
    overall, action = _overall_decision(assessments)
    descriptions = []
    recommendations = [action]
    for item in assessments:
        description, recommendation = _reading_brief(item)
        descriptions.append(description)
        if recommendation is not None:
            recommendations.append(recommendation)
    description = " ".join(descriptions) or "No sensor readings were available for assessment."
    description += " These readings alone do not establish a root cause or a change over time."

    return {
        "output": {
            "overall_status": overall,
            "description": description,
            "recommendations": recommendations,
            "findings": assessments,
            "model_analysis": state.get("model_analysis", {}),
            "recommended_action": action,
            "requires_human_review": True,
            "data_quality_errors": state.get("errors", []),
        }
    }


def create_review_brief(state: SensorState) -> dict[str, Any]:
    return {
        "output": {
            "overall_status": "needs_review",
            "description": "Input validation failed, so no sensor assessment was produced. "
            + " ".join(state.get("errors", [])),
            "recommendations": [
                "Correct the reported input errors and verify sensor configuration, then rerun the assessment."
            ],
            "findings": [],
            "model_analysis": {},
            "recommended_action": "Check input quality and sensor configuration; no operational conclusion was produced.",
            "requires_human_review": True,
            "data_quality_errors": state.get("errors", []),
        }
    }


def route_after_validation(state: SensorState) -> str:
    if state.get("errors") or not state.get("readings"):
        return "review"
    return "assess"


def build_graph(analyzer: Callable[..., dict[str, Any]] = analyze_with_ollama):
    def analyze_node(state: SensorState) -> dict[str, Any]:
        return {"model_analysis": analyzer(state["readings"], state["assessments"])}

    graph = StateGraph(SensorState)
    graph.add_node("validate", validate_input)
    graph.add_node("assess", assess_readings)
    graph.add_node("analyze", analyze_node)
    graph.add_node("decide", create_decision_brief)
    graph.add_node("review", create_review_brief)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validation,
        {"assess": "assess", "review": "review"},
    )
    graph.add_edge("assess", "analyze")
    graph.add_edge("analyze", "decide")
    graph.add_edge("decide", END)
    graph.add_edge("review", END)
    return graph.compile()


def run_assessment(
    payload: dict[str, Any], analyzer: Callable[..., dict[str, Any]] = analyze_with_ollama
) -> dict[str, Any]:
    result = build_graph(analyzer).invoke({"payload": payload})
    return result["output"]


def process_file(
    input_path: Path,
    expected_sha256: str | None,
    manifest_path: Path,
    analyzer: Callable[..., dict[str, Any]] = analyze_with_ollama,
) -> dict[str, Any]:
    input_bytes, verification = read_input(input_path, expected_sha256)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_file": str(input_path),
        "sha256": verification["sha256"],
        "expected_sha256": verification["expected_sha256"],
        "digest_verified": verification["digest_verified"],
        "model": OLLAMA_MODEL,
        "status": "failure",
    }

    if not verification["digest_verified"]:
        manifest["error"] = "SHA-256 verification failed or expected digest was missing/invalid"
        write_json(manifest_path, manifest)
        return manifest

    try:
        payload = json.loads(input_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("input JSON root must be an object")
        manifest["assessment"] = run_assessment(payload, analyzer)
        manifest["status"] = "success"
    except Exception as exc:
        manifest["error"] = f"{type(exc).__name__}: {exc}"

    write_json(manifest_path, manifest)
    return manifest
