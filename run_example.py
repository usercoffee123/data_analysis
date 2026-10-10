"""Run the included SECOM dataset with one command and print where to read results."""

import argparse
from pathlib import Path

from ollama_client import analyze_with_ollama
from secom_graph import process_secom


PROJECT_DIR = Path(__file__).resolve().parent
DATA_SHA256 = "20f0e7ee434f7dcbae0eea9ffff009a2b57f42d6b0dc9a5bd4f00782c0a3374c"
LABELS_SHA256 = "126884cf453705c9e61a903fe906f0665a3b45ce3639e621edc5c93c89627e03"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze the included manufacturing records and save readable reports."
    )
    parser.add_argument(
        "--with-llm", action="store_true",
        help="Add commentary from local Ollama (requires qwen3.5:9b).",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_DIR / "reports",
        help="Folder for reports (default: reports beside this script).",
    )
    args = parser.parse_args()
    manifest_path = args.output_dir.resolve() / "secom.manifest.json"
    print("Checking the included files and screening manufacturing records...", flush=True)
    try:
        manifest = process_secom(
            PROJECT_DIR / "data/secom/secom.data",
            PROJECT_DIR / "data/secom/secom_labels.data",
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
