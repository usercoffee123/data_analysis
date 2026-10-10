"""Run the included SECOM dataset with one command and print where to read results."""

import argparse
from pathlib import Path

from manufacturing_analysis.common.ollama import analyze_with_ollama
from manufacturing_analysis.paths import REPORTS_DIR
from manufacturing_analysis.secom.dataset import (
    DATA_PATH,
    DATA_SHA256,
    LABELS_PATH,
    LABELS_SHA256,
)
from manufacturing_analysis.secom.workflow import process_secom


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze the included manufacturing records and save readable reports."
    )
    parser.add_argument(
        "--with-llm", action="store_true",
        help="Add commentary from local Ollama (requires qwen3.5:9b).",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=REPORTS_DIR,
        help="Folder for reports (default: the project reports folder).",
    )
    args = parser.parse_args()
    manifest_path = args.output_dir.resolve() / "secom.manifest.json"
    print("Checking the included files and screening manufacturing records...", flush=True)
    try:
        manifest = process_secom(
            DATA_PATH,
            LABELS_PATH,
            DATA_SHA256,
            LABELS_SHA256,
            manifest_path,
            analyzer=analyze_with_ollama if args.with_llm else None,
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Could not save the analysis: {exc}\n")

    if manifest["status"] != "success":
        parser.exit(1, f"Analysis failed: {manifest['error']}\nDetails: {manifest_path}\n")

    assessment = manifest["assessment"]
    screening = assessment["sample_screening"]
    print(f"Done: screened {screening['sample_count']:,} records; {screening['flagged_count']:,} need review.")
    print("A review flag is a reason to investigate, not a confirmed defect.")
    if assessment["model_analysis"]["status"] == "failure":
        print("Ollama commentary was unavailable. Screening results were saved.")
    print(f"Start here: {manifest_path.with_suffix('.summary.md')}")
    print(f"Full report: {manifest_path.with_suffix('.md')}")
    print(f"Data for programs: {manifest_path}")


if __name__ == "__main__":
    main()
