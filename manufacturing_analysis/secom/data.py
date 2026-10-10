"""Parse SECOM's paired text files and summarize their measurements."""

from datetime import datetime
import math
import statistics
from typing import Any


TIMESTAMP_FORMAT = "%d/%m/%Y %H:%M:%S"
Row = list[float | None]


def parse_measurements(text: str) -> list[Row]:
    rows = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            raise ValueError(f"Empty feature row at line {line_number}")
        row = []
        for token in line.split():
            value = None if token.lower() == "nan" else float(token)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"Non-finite feature at line {line_number}")
            row.append(value)
        if rows and len(row) != len(rows[0]):
            raise ValueError(f"Inconsistent feature count at line {line_number}")
        rows.append(row)
    return rows


def parse_labels(text: str) -> tuple[list[int], list[str]]:
    labels, timestamps = [], []
    for line_number, line in enumerate(text.splitlines(), 1):
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or parts[0] not in ("-1", "1"):
            raise ValueError(f"Invalid label at line {line_number}; expected -1 or 1 and timestamp")
        timestamp = parts[1]
        if timestamp.startswith('"') and timestamp.endswith('"'):
            timestamp = timestamp[1:-1]
        datetime.strptime(timestamp, TIMESTAMP_FORMAT)
        labels.append(int(parts[0]))
        timestamps.append(timestamp)
    return labels, timestamps


def parse_secom(state: dict[str, Any]) -> dict[str, Any]:
    """Graph node: validate measurements and their corresponding test records."""
    rows = parse_measurements(state["data_text"])
    labels, timestamps = parse_labels(state["labels_text"])
    if not rows or len(rows) != len(labels):
        raise ValueError("Feature and label files must contain equal, nonzero row counts")
    return {"rows": rows, "labels": labels, "timestamps": timestamps}


def feature_statistics(index: int, values: tuple[float | None, ...]) -> dict[str, Any]:
    observed = [value for value in values if value is not None]
    minimum = min(observed) if observed else None
    maximum = max(observed) if observed else None
    return {
        "feature_id": f"feature_{index:03d}",
        "missing_count": len(values) - len(observed),
        "observed_count": len(observed),
        "min": minimum,
        "max": maximum,
        "mean": statistics.fmean(observed) if observed else None,
        "constant": bool(observed) and minimum == maximum,
    }


def profile_secom(state: dict[str, Any]) -> dict[str, Any]:
    """Graph node: calculate descriptive statistics, without changing thresholds."""
    rows, labels = state["rows"], state["labels"]
    features = [feature_statistics(i, column) for i, column in enumerate(zip(*rows))]
    dates = [datetime.strptime(t, TIMESTAMP_FORMAT) for t in state["timestamps"]]
    failures = labels.count(1)
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
        "test_period": {"start": min(dates).isoformat(), "end": max(dates).isoformat()},
        "features": features,
        "limitations": "Anonymous features; units and approved operating limits are unavailable. Labels are historical test outcomes, not predictions. No causal analysis or failure predictor was fitted.",
    }}
