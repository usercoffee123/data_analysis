"""Regression checks for relocated input files and user-facing commands."""

from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from manufacturing_analysis.paths import PROJECT_DIR
from manufacturing_analysis.sensors.cli import main as sensor_main
from manufacturing_analysis.sensors.workflow import process_file


class EntryPointTests(unittest.TestCase):
    def test_example_resolves_inputs_and_rules_from_another_working_directory(self):
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(PROJECT_DIR / "run_example.py"), "--output-dir", "results"],
                cwd=directory, capture_output=True, text=True, check=True,
            )
            output = Path(directory) / "results/secom.manifest.json"
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "success")
            assessment = manifest["assessment"]
            self.assertEqual(assessment["model_analysis"]["status"], "skipped")
            screening = assessment["sample_screening"]
            self.assertEqual(screening["sample_count"], 1567)
            self.assertEqual(screening["flagged_count"], 204)
            provenance = screening["method"]["threshold_provenance"]
            threshold_path = PROJECT_DIR / "config/secom/thresholds.json"
            self.assertEqual(Path(provenance["file"]), threshold_path)
            self.assertEqual(provenance["sha256"], hashlib.sha256(threshold_path.read_bytes()).hexdigest())
            self.assertTrue(output.with_suffix(".summary.md").is_file())
            self.assertTrue(output.with_suffix(".md").is_file())
            self.assertIn("Start here:", result.stdout)

    def test_sensor_command_reads_the_relocated_demo_input(self):
        def process_without_model(input_path, digest, manifest_path):
            return process_file(
                input_path, digest, manifest_path,
                analyzer=lambda readings, findings: {"summary": "Test commentary"},
            )

        with TemporaryDirectory() as directory:
            with patch("sys.argv", ["sensors"]), patch(
                "manufacturing_analysis.sensors.cli.REPORTS_DIR", Path(directory)
            ), patch(
                "manufacturing_analysis.sensors.cli.process_file", side_effect=process_without_model
            ), redirect_stdout(StringIO()):
                sensor_main()
            output = Path(directory) / "sensors/sensor-sample.manifest.json"
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "success")
            self.assertTrue(manifest["digest_verified"])
            self.assertEqual(Path(manifest["input_file"]), PROJECT_DIR / "data/sensors/example.json")
            self.assertEqual(manifest["assessment"]["overall_status"], "critical")
