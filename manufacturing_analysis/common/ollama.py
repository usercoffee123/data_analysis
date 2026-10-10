"""One local Ollama call for interpreting already computed findings."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


OLLAMA_MODEL = "qwen3.5:9b"
OLLAMA_URL = "http://localhost:11434/api/chat"
SYSTEM_PROMPT = (
    "Analyze the sensor readings for a human operator. Use only the provided data. "
    "Do not invent causes or claim certainty. Distinguish observations from hypotheses. "
    "If given a dataset profile, explain historical outcomes and missing data; "
    "anonymous feature IDs have no known physical meaning or units. "
    "Historical labels are not predictions. Do not infer current equipment health. "
    "Return JSON with keys summary (string), observations (array of objects with "
    "sensor_id, interpretation, confidence), and limitations (string)."
)


def _build_request_body(
    readings: list[dict[str, Any]], assessments: list[dict[str, Any]]
) -> dict[str, Any]:
    prompt = {"readings": readings, "deterministic_rule_findings": assessments}
    return {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt)},
        ],
    }


def _parse_analysis(response_data: dict[str, Any]) -> dict[str, Any]:
    content = response_data.get("message", {}).get("content")
    try:
        analysis = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Ollama returned invalid JSON analysis") from exc
    if not isinstance(analysis, dict) or not isinstance(analysis.get("summary"), str):
        raise RuntimeError("Ollama response must be a JSON object containing a summary")
    analysis.setdefault("observations", [])
    analysis.setdefault(
        "limitations", "Model-generated interpretation; verify against operational context."
    )
    return analysis


def analyze_with_ollama(
    readings: list[dict[str, Any]], assessments: list[dict[str, Any]]
) -> dict[str, Any]:
    """Send evidence to Ollama and require a JSON interpretation containing a summary."""
    request = Request(
        OLLAMA_URL,
        data=json.dumps(_build_request_body(readings, assessments)).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not reach Ollama at {OLLAMA_URL}: {exc}") from exc
    return _parse_analysis(response_data)
