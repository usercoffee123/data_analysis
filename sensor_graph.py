"""A small, deterministic LangGraph for sensor triage."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, TypedDict
from urllib.error import URLError
from urllib.request import Request, urlopen

from langgraph.graph import END, START, StateGraph


OLLAMA_MODEL = "qwen3.5:9b"
OLLAMA_URL = "http://localhost:11434/api/chat"


class SensorState(TypedDict, total=False):
    payload: dict[str, Any]
    readings: list[dict[str, Any]]
    assessments: list[dict[str, Any]]
    errors: list[str]
    model_analysis: dict[str, Any]
    output: dict[str, Any]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_input(state: SensorState) -> dict[str, Any]:
    payload = state.get("payload")
    if not isinstance(payload, dict):
        return {"readings": [], "errors": ["payload must be a JSON object"]}

    raw_readings = payload.get("readings")
    if not isinstance(raw_readings, list):
        return {"readings": [], "errors": ["payload.readings must be a list"]}

    readings: list[dict[str, Any]] = []
    errors: list[str] = []
    threshold_keys = ("warning_min", "warning_max", "critical_min", "critical_max")

    for index, item in enumerate(raw_readings):
        prefix = f"readings[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        sensor_id = item.get("sensor_id")
        value = item.get("value")
        if not isinstance(sensor_id, str) or not sensor_id.strip():
            errors.append(f"{prefix}.sensor_id must be a non-empty string")
            continue
        if not _is_number(value):
            errors.append(f"{prefix}.value must be a finite number")
            continue

        reading: dict[str, Any] = {
            "sensor_id": sensor_id,
            "value": value,
            "unit": item.get("unit", ""),
        }
        invalid_threshold = False
        for key in threshold_keys:
            threshold = item.get(key)
            if threshold is not None:
                if not _is_number(threshold):
                    errors.append(f"{prefix}.{key} must be a finite number")
                    invalid_threshold = True
                    break
                reading[key] = threshold
        if invalid_threshold:
            continue

        for low_key, high_key in (("warning_min", "warning_max"), ("critical_min", "critical_max")):
            low = reading.get(low_key)
            high = reading.get(high_key)
            if low is not None and high is not None and low > high:
                errors.append(f"{prefix}.{low_key} must be less than or equal to {high_key}")
                invalid_threshold = True
                break
        if not invalid_threshold:
            readings.append(reading)

    return {"readings": readings, "errors": errors}


def assess_readings(state: SensorState) -> dict[str, Any]:
    assessments = []
    for reading in state["readings"]:
        value = reading["value"]
        critical = (
            (reading.get("critical_min") is not None and value < reading["critical_min"])
            or (reading.get("critical_max") is not None and value > reading["critical_max"])
        )
        warning = (
            (reading.get("warning_min") is not None and value < reading["warning_min"])
            or (reading.get("warning_max") is not None and value > reading["warning_max"])
        )
        has_threshold = any(key in reading for key in ("warning_min", "warning_max", "critical_min", "critical_max"))

        if critical:
            status = "critical"
            evidence = "value is outside a configured critical bound"
        elif warning:
            status = "warning"
            evidence = "value is outside a configured warning bound"
        elif has_threshold:
            status = "normal"
            evidence = "value is within configured bounds"
        else:
            status = "unknown"
            evidence = "no warning or critical bounds were configured"

        assessments.append({**reading, "status": status, "evidence": evidence})
    return {"assessments": assessments}


def analyze_with_ollama(
    readings: list[dict[str, Any]], assessments: list[dict[str, Any]]
) -> dict[str, Any]:
    prompt = {"readings": readings, "deterministic_rule_findings": assessments}
    request_body = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Analyze the sensor readings for a human operator. Use only the provided data. "
                    "Do not invent causes or claim certainty. Distinguish observations from hypotheses. "
                    "If given a dataset profile, explain historical outcomes and missing data; "
                    "anonymous feature IDs have no known physical meaning or units. "
                    "Historical labels are not predictions. Do not infer current equipment health. "
                    "Return JSON with keys summary (string), observations (array of objects with "
                    "sensor_id, interpretation, confidence), and limitations (string)."
                ),
            },
            {"role": "user", "content": json.dumps(prompt)},
        ],
    }
    request = Request(
        OLLAMA_URL,
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not reach Ollama at {OLLAMA_URL}: {exc}") from exc

    content = response_data.get("message", {}).get("content")
    try:
        analysis = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Ollama returned invalid JSON analysis") from exc
    if not isinstance(analysis, dict) or not isinstance(analysis.get("summary"), str):
        raise RuntimeError("Ollama response must be a JSON object containing a summary")
    analysis.setdefault("observations", [])
    analysis.setdefault("limitations", "Model-generated interpretation; verify against operational context.")
    return analysis


def create_decision_brief(state: SensorState) -> dict[str, Any]:
    assessments = state.get("assessments", [])
    statuses = {item["status"] for item in assessments}
    if "critical" in statuses:
        overall = "critical"
        action = "Escalate using the site's approved response procedure and verify the sensor reading."
    elif "warning" in statuses:
        overall = "warning"
        action = "Review the flagged readings and follow the site's approved operating procedure."
    elif "unknown" in statuses or not assessments:
        overall = "needs_review"
        action = "Configure validated thresholds and review the readings before drawing an operational conclusion."
    else:
        overall = "normal"
        action = "Continue routine monitoring."

    descriptions = []
    recommendations = [action]
    for item in assessments:
        measurement = f"{item['value']} {item.get('unit', '')}".strip()
        status = item["status"]
        if status in ("critical", "warning"):
            for direction, comparison in (("min", "below"), ("max", "above")):
                bound = item.get(f"{status}_{direction}")
                if bound is not None and (
                    (direction == "min" and item["value"] < bound)
                    or (direction == "max" and item["value"] > bound)
                ):
                    limit = f"{bound} {item.get('unit', '')}".strip()
                    descriptions.append(
                        f"{item['sensor_id']} measured {measurement}, {comparison} the "
                        f"configured {status} {direction} of {limit}."
                    )
            recommendations.append(
                f"Verify the {item['sensor_id']} reading and sensor condition; review recent "
                "readings and operating context with the responsible operator."
            )
        elif status == "unknown":
            descriptions.append(
                f"{item['sensor_id']} measured {measurement}, but no thresholds were "
                "configured, so its operational status could not be determined."
            )
            recommendations.append(
                f"Have the responsible domain owner configure validated thresholds for {item['sensor_id']}."
            )
        else:
            descriptions.append(
                f"{item['sensor_id']} measured {measurement}, within its configured bounds."
            )
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


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(manifest, temporary_file, indent=2)
            temporary_file.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def process_file(
    input_path: Path,
    expected_sha256: str | None,
    manifest_path: Path,
    analyzer: Callable[..., dict[str, Any]] = analyze_with_ollama,
) -> dict[str, Any]:
    input_bytes = input_path.read_bytes()
    actual_sha256 = hashlib.sha256(input_bytes).hexdigest()
    digest_verified = bool(
        expected_sha256
        and re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256)
        and actual_sha256 == expected_sha256.lower()
    )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_file": str(input_path),
        "sha256": actual_sha256,
        "expected_sha256": expected_sha256,
        "digest_verified": digest_verified,
        "model": OLLAMA_MODEL,
        "status": "failure",
    }

    if not digest_verified:
        manifest["error"] = "SHA-256 verification failed or expected digest was missing/invalid"
        _write_manifest(manifest_path, manifest)
        return manifest

    try:
        payload = json.loads(input_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("input JSON root must be an object")
        manifest["assessment"] = run_assessment(payload, analyzer)
        manifest["status"] = "success"
    except Exception as exc:
        manifest["error"] = f"{type(exc).__name__}: {exc}"

    _write_manifest(manifest_path, manifest)
    return manifest


SAMPLE_PAYLOAD = {
    "readings": [
        {
            "sensor_id": "pump-07-vibration",
            "value": 12.4,
            "unit": "mm/s",
            "warning_max": 7.1,
            "critical_max": 11.0,
        },
        {
            "sensor_id": "pump-07-temperature",
            "value": 68.0,
            "unit": "C",
            "warning_max": 75.0,
            "critical_max": 90.0,
        },
    ]
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify and analyze sensor readings with LangGraph and Ollama.")
    parser.add_argument("input", nargs="?", type=Path, help="JSON file containing a readings array")
    parser.add_argument("--sha256", help="Expected SHA-256 digest of the exact input file bytes")
    parser.add_argument("--manifest", type=Path, help="Manifest output path")
    args = parser.parse_args()

    if args.input:
        manifest_path = args.manifest or args.input.with_suffix(args.input.suffix + ".manifest.json")
        manifest = process_file(args.input, args.sha256, manifest_path)
    else:
        sample_bytes = json.dumps(SAMPLE_PAYLOAD, separators=(",", ":")).encode("utf-8")
        sample_path = Path("sensor-sample.json")
        manifest_path = args.manifest or Path("sensor-sample.manifest.json")
        sample_path.write_bytes(sample_bytes)
        manifest = process_file(sample_path, hashlib.sha256(sample_bytes).hexdigest(), manifest_path)

    print(json.dumps(manifest, indent=2))
    if manifest["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
