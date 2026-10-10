"""Command-line interface for custom SECOM input files."""

import argparse
import json
from pathlib import Path

from manufacturing_analysis.common.ollama import analyze_with_ollama
from manufacturing_analysis.paths import REPORTS_DIR
from manufacturing_analysis.secom.dataset import DEFAULT_THRESHOLDS_PATH
from manufacturing_analysis.secom.workflow import process_secom, terminal_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze UCI SECOM data with LangGraph and local Ollama")
    parser.add_argument("data", type=Path, help="Measurement file: one record per row")
    parser.add_argument("labels", type=Path, help="Matching historical test labels and timestamps")
    parser.add_argument("--sha256", required=True, help="Expected digest of secom.data")
    parser.add_argument("--labels-sha256", required=True, help="Expected digest of the labels file")
    parser.add_argument(
        "--manifest", type=Path, default=REPORTS_DIR / "secom.manifest.json",
        help="JSON output path (default: project reports folder); Markdown reports are saved beside it",
    )
    parser.add_argument("--no-llm", action="store_true", help="Run screening without Ollama")
    parser.add_argument(
        "--thresholds", type=Path, default=DEFAULT_THRESHOLDS_PATH,
        help="Fixed threshold file (default: project config/secom/thresholds.json)",
    )
    args = parser.parse_args()
    try:
        manifest = process_secom(
            args.data, args.labels, args.sha256, args.labels_sha256, args.manifest,
            analyzer=None if args.no_llm else analyze_with_ollama,
            thresholds_path=args.thresholds,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(terminal_summary(manifest), indent=2))
    if manifest["status"] != "success":
        raise SystemExit(1)

