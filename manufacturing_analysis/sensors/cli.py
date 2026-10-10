"""Command-line interface for the included sensor demo or custom JSON readings."""

import argparse
import hashlib
import json
from pathlib import Path

from manufacturing_analysis.paths import DATA_DIR, REPORTS_DIR
from manufacturing_analysis.sensors.workflow import process_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify and analyze sensor readings with LangGraph and Ollama."
    )
    parser.add_argument(
        "input", nargs="?", type=Path, help="JSON file containing a readings array"
    )
    parser.add_argument("--sha256", help="Expected SHA-256 digest of the exact input file bytes")
    parser.add_argument("--manifest", type=Path, help="Manifest output path")
    args = parser.parse_args()

    if args.input:
        input_path = args.input
        expected_digest = args.sha256
        manifest_path = args.manifest or input_path.with_suffix(
            input_path.suffix + ".manifest.json"
        )
    else:
        input_path = DATA_DIR / "sensors/example.json"
        expected_digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
        manifest_path = args.manifest or REPORTS_DIR / "sensors/sensor-sample.manifest.json"

    manifest = process_file(input_path, expected_digest, manifest_path)
    print(json.dumps(manifest, indent=2))
    if manifest["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
