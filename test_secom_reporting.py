"""Report behavior that matters independently of the screening implementation."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from secom_reporting import render_summary, write_markdown_report


def report_manifest():
    return {
        "status": "success",
        "created_at": "2008-07-19T11:55:00Z",
        "model": "test-model",
        "source": "test dataset",
        "inputs": [],
        "assessment": {
            "description": "One record needs investigation.",
            "recommendations": ["Verify the measurement."],
            "model_analysis": {
                "status": "success",
                "summary": "Text containing ## Flagged sample briefs must not truncate a report.",
            },
            "sample_screening": {
                "sample_count": 1,
                "flagged_count": 1,
                "reason_counts": {"unusual_measurements": 1},
                "method": {"threshold_source": "saved"},
                "evaluation": {
                    "all_records": {
                        "sample_count": 1,
                        "independent_flags": 1,
                        "failures_captured": 0,
                        "failures_missed": 0,
                        "passing_records_flagged": 1,
                    },
                    "held_out": {"sample_count": 0},
                },
                "flagged_sample_briefs": [{
                    "sample_id": "sample_0001",
                    "source_line": 1,
                    "timestamp": "19/07/2008 11:55:00",
                    "flag_reasons": ["unusual_measurements"],
                    "description": "One measurement exceeds the saved bound.",
                    "recommendations": ["Compare related records."],
                    "unusual_features": [{
                        "feature_id": "feature_001|note\nextra",
                        "value": 100,
                        "reference_min": 0,
                        "reference_max": 10,
                        "direction": "above",
                    }],
                    "missing_features": [],
                }],
            },
        },
    }


class ReportingTests(unittest.TestCase):
    def test_summary_keeps_model_text_without_including_sample_briefs(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "manifest.md"
            write_markdown_report(report_manifest(), path)
            summary = path.with_name("manifest.summary.md").read_text()
            full = path.read_text()
        self.assertIn("must not truncate a report", summary)
        self.assertIn("Independent screening evaluation", summary)
        self.assertIn("No held-out evaluation", summary)
        self.assertNotIn("### sample_0001", summary)
        self.assertIn("[manifest.md](manifest.md)", summary)
        self.assertIn("### sample_0001", full)
        self.assertIn("feature_001\\|note extra | 100 | 0 | 10 | above", full)

    def test_skipped_and_failed_llm_are_not_presented_as_generated_interpretations(self):
        for status in ("skipped", "failure"):
            with self.subTest(status=status):
                manifest = report_manifest()
                manifest["assessment"]["model_analysis"] = {
                    "status": status, "summary": "Commentary unavailable.",
                    "error": "offline" if status == "failure" else "",
                }
                summary = render_summary(manifest)
                self.assertIn(f"**{status}**", summary)
                self.assertIn("Commentary unavailable.", summary)
                self.assertNotIn("interpretation was generated", summary)
                self.assertIn("Screened **1** samples", summary)
                if status == "failure":
                    self.assertIn("offline", summary)

    def test_processing_failure_writes_error_without_analysis_sections(self):
        manifest = report_manifest()
        manifest.pop("assessment")
        manifest.update(status="failure", error="Input digest mismatch.")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.md"
            write_markdown_report(manifest, path)
            for report in (path, path.with_name("manifest.summary.md")):
                text = report.read_text()
                self.assertIn("## Processing error", text)
                self.assertIn("Input digest mismatch.", text)
                self.assertNotIn("## LLM output", text)
                self.assertNotIn("## Flagged sample briefs", text)
