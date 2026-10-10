import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sensor_graph import process_file, run_assessment


def fake_analyzer(readings, assessments):
    return {
        "summary": "A sensor interpretation was generated for review.",
        "observations": [],
        "limitations": "Test analyzer; not a real model response.",
    }


class SensorGraphTests(unittest.TestCase):
    def test_critical_reading_is_escalated(self):
        result = run_assessment(
            {
                "readings": [
                    {
                        "sensor_id": "bearing-vibration",
                        "value": 12.4,
                        "unit": "mm/s",
                        "warning_max": 7.1,
                        "critical_max": 11.0,
                    }
                ]
            },
            analyzer=fake_analyzer,
        )
        self.assertEqual(result["overall_status"], "critical")
        self.assertEqual(result["findings"][0]["status"], "critical")
        self.assertTrue(result["requires_human_review"])
        self.assertIn("12.4 mm/s", result["description"])
        self.assertIn("above the configured critical max of 11.0 mm/s", result["description"])
        self.assertIn("Escalate", result["recommendations"][0])
        self.assertIn("bearing-vibration", result["recommendations"][1])

    def test_in_range_reading_is_normal(self):
        result = run_assessment(
            {"readings": [{"sensor_id": "temperature", "value": 68, "warning_max": 75}]},
            analyzer=fake_analyzer,
        )
        self.assertEqual(result["overall_status"], "normal")
        self.assertIn("within its configured bounds", result["description"])
        self.assertEqual(result["recommendations"], ["Continue routine monitoring."])

    def test_missing_thresholds_need_review(self):
        result = run_assessment(
            {"readings": [{"sensor_id": "temperature", "value": 68}]}, analyzer=fake_analyzer
        )
        self.assertEqual(result["overall_status"], "needs_review")
        self.assertEqual(result["findings"][0]["status"], "unknown")
        self.assertIn("could not be determined", result["description"])
        self.assertIn("temperature", result["recommendations"][1])

    def test_low_warning_with_unconfigured_sensor(self):
        result = run_assessment(
            {
                "readings": [
                    {
                        "sensor_id": "pressure",
                        "value": 2,
                        "unit": "bar",
                        "warning_min": 3,
                    },
                    {"sensor_id": "temperature", "value": 68},
                ]
            },
            analyzer=fake_analyzer,
        )
        self.assertEqual(result["overall_status"], "warning")
        self.assertIn("below the configured warning min of 3 bar", result["description"])
        self.assertIn("no thresholds were configured", result["description"])
        self.assertTrue(
            any("thresholds for temperature" in step for step in result["recommendations"])
        )

    def test_invalid_payload_routes_to_review(self):
        result = run_assessment(
            {"readings": [{"sensor_id": "temperature", "value": "hot"}]}, analyzer=fake_analyzer
        )
        self.assertEqual(result["overall_status"], "needs_review")
        self.assertTrue(result["data_quality_errors"])
        self.assertIn("Input validation failed", result["description"])
        self.assertIn("Correct", result["recommendations"][0])

    def test_digest_mismatch_writes_failure_manifest_without_analysis(self):
        with TemporaryDirectory() as directory:
            input_path = Path(directory) / "readings.json"
            manifest_path = Path(directory) / "manifest.json"
            analyzer_calls = []

            def tracking_analyzer(readings, assessments):
                analyzer_calls.append(True)
                return fake_analyzer(readings, assessments)

            input_path.write_text(json.dumps({"readings": []}), encoding="utf-8")
            manifest = process_file(input_path, "0" * 64, manifest_path, tracking_analyzer)

            self.assertEqual(manifest["status"], "failure")
            self.assertFalse(manifest["digest_verified"])
            self.assertTrue(manifest_path.exists())
            self.assertEqual(analyzer_calls, [])

    def test_verified_input_writes_success_manifest(self):
        with TemporaryDirectory() as directory:
            input_path = Path(directory) / "readings.json"
            manifest_path = Path(directory) / "manifest.json"
            input_bytes = json.dumps(
                {"readings": [{"sensor_id": "temperature", "value": 68, "warning_max": 75}]}
            ).encode("utf-8")
            input_path.write_bytes(input_bytes)
            digest = hashlib.sha256(input_bytes).hexdigest()

            manifest = process_file(input_path, digest, manifest_path, fake_analyzer)

            self.assertEqual(manifest["status"], "success")
            self.assertTrue(manifest["digest_verified"])
            self.assertEqual(manifest["sha256"], digest)
            self.assertEqual(json.loads(manifest_path.read_text())["status"], "success")


if __name__ == "__main__":
    unittest.main()
