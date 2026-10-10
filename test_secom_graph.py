import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from secom_graph import build_secom_graph, parse_secom, process_secom, screen_samples


def fixture_thresholds(state):
    """Use static test bounds, independent of the measurements being screened."""
    parsed = parse_secom(state) if "data_text" in state else state
    path = Path(__file__).parent / "tests" / "fixtures" / f"thresholds_{len(parsed['rows'][0])}.json"
    return {**state, "thresholds": json.loads(path.read_text())}


class SecomTests(unittest.TestCase):
    def test_optional_llm_and_outage_preserve_evidence(self):
        payload = {"data_text": "1 2\n", "labels_text": "1 19/07/2008 11:55:00\n"}
        def unavailable(*args):
            raise RuntimeError("offline")
        for analyzer, status in ((None, "skipped"), (unavailable, "failure")):
            output = build_secom_graph(analyzer).invoke(fixture_thresholds(payload))["output"]
            self.assertEqual(output["model_analysis"]["status"], status)
            self.assertEqual(output["sample_screening"]["samples"][0]["recorded_test_result"], "fail")

    def test_sample_screening_is_label_independent_and_explains_flags(self):
        rows = [[float(i % 5), 7.0, None] for i in range(24)] + [[100.0, 7.0, 2.0]]
        state = {"rows": rows, "labels": [-1] * 24 + [1], "timestamps": ["test"] * 25}
        state = fixture_thresholds(state)
        screening = screen_samples(state)["sample_screening"]
        last = screening["flagged_sample_briefs"][-1]
        self.assertEqual(last["source_line"], 25)
        self.assertEqual(last["recorded_test_result"], "fail")
        self.assertEqual(last["unusual_features"][0]["feature_id"], "feature_000")
        self.assertEqual(last["unusual_features"][0]["direction"], "above")
        self.assertEqual(screening["method"]["eligible_feature_count"], 1)
        self.assertEqual(screening["samples"][0]["flag_reasons"], [])
        self.assertEqual(screening["samples"][0]["eligible_missing_fraction"], 0)
        changed = screen_samples({**state, "labels": [-1] * 25})["sample_screening"]
        self.assertEqual(changed["flagged_sample_briefs"][-1]["unusual_features"], last["unusual_features"])
        self.assertNotIn("recorded_test_failure", changed["samples"][-1]["flag_reasons"])

    def test_passing_record_without_flags_is_not_declared_healthy(self):
        screening = screen_samples(fixture_thresholds({"rows": [[float(i % 5)] for i in range(20)], "labels": [-1] * 20,
                                    "timestamps": ["test"] * 20}))["sample_screening"]
        self.assertEqual(screening["flagged_count"], 0)
        self.assertEqual(len(screening["samples"]), 20)
        self.assertEqual(screening["flagged_sample_briefs"], [])

    def test_sample_values_do_not_change_saved_bounds_or_threshold(self):
        from datetime import datetime, timedelta
        rows = [[float(i % 5), 1.0] for i in range(80)] + [[100.0, 1.0]] * 20
        state = {"rows": rows, "labels": [-1] * 80 + [1] * 20,
                 "timestamps": [(datetime(2008, 1, 1) + timedelta(hours=i)).strftime('%d/%m/%Y %H:%M:%S') for i in range(100)]}
        state = fixture_thresholds(state)
        result = screen_samples(state)["sample_screening"]
        self.assertEqual(result["evaluation"]["all_records"]["failures_captured"], 20)
        self.assertEqual(result["samples"][80]["cohort"], "saved_thresholds")
        changed = screen_samples({**state, "rows": rows[:80] + [[10000.0, 1.0]] * 20})["sample_screening"]
        self.assertEqual(result["method"]["anomaly_threshold"], changed["method"]["anomaly_threshold"])
        self.assertEqual(result["flagged_sample_briefs"][0]["unusual_features"][0]["reference_max"],
                         changed["flagged_sample_briefs"][0]["unusual_features"][0]["reference_max"])
        # Known failures are kept in the queue but never count as independent detections.
        no_anomaly = screen_samples({**state, "rows": rows[:80] + [[2.0, 1.0]] * 20})["sample_screening"]
        self.assertEqual(no_anomaly["flagged_count"], 20)
        self.assertEqual(no_anomaly["evaluation"]["all_records"]["failures_captured"], 0)

    def test_profile(self):
        prompts = []
        def analyzer(readings, findings):
            prompts.append(findings[0])
            return {"summary": "Historical review"}
        result = build_secom_graph(analyzer).invoke(fixture_thresholds({
            "data_text": "1 NaN 4\n3 NaN 4\n",
            "labels_text": '-1 "19/07/2008 11:55:00"\n1 20/07/2008 12:00:00\n',
        }))["output"]
        p = result["profile"]
        self.assertEqual((p["row_count"], p["feature_count"]), (2, 3))
        self.assertEqual(p["failure_rate"], 0.5)
        self.assertEqual(p["missing_value_count"], 2)
        self.assertEqual(p["all_missing_feature_count"], 1)
        self.assertEqual(p["constant_feature_count"], 1)
        self.assertEqual(p["features"][0]["mean"], 2)
        self.assertNotIn("features", prompts[0])
        self.assertEqual(result["overall_status"], "needs_review")

    def test_invalid_data_skips_llm(self):
        def unexpected(*args):
            self.fail("Invalid data reached LLM")
        for data, labels in [("1 2\n3", "-1 19/07/2008 11:55:00"),
                             ("1 2", "0 19/07/2008 11:55:00"),
                             ("inf 2", "-1 19/07/2008 11:55:00"), ("1 2", "")]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                build_secom_graph(unexpected).invoke({"data_text": data, "labels_text": labels})

    def test_both_digests_verified(self):
        with TemporaryDirectory() as directory:
            data, labels, output = [Path(directory) / name for name in ("data", "labels", "manifest.json")]
            data.write_text("100 NaN\n")
            labels.write_text("-1 19/07/2008 11:55:00\n")
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            thresholds = Path(directory) / 'thresholds.json'
            thresholds.write_text((Path(__file__).parent / "tests/fixtures/thresholds_2.json").read_text())
            calls = []
            def analyzer(*args):
                calls.append(True)
                return {"summary": "Review"}
            failed = process_secom(data, labels, digest(data), "0" * 64, output, analyzer)
            self.assertEqual(failed["status"], "failure")
            self.assertIn("Processing error", output.with_suffix(".md").read_text())
            self.assertEqual(calls, [])
            success = process_secom(data, labels, digest(data), digest(labels), output, analyzer, thresholds_path=thresholds)
            self.assertEqual(success["status"], "success")
            self.assertEqual(len(calls), 1)
            self.assertTrue(all(i["digest_verified"] for i in success["inputs"]))
            self.assertEqual(json.loads(output.read_text())["status"], "success")
            markdown = output.with_suffix(".md").read_text()
            self.assertIn("## LLM output", markdown)
            self.assertIn("Review", markdown)
            self.assertIn("sample_0001", markdown)
            self.assertIn("feature_001", markdown)
            summary = output.with_name('manifest.summary.md').read_text()
            self.assertIn("Independent screening evaluation", summary)
            self.assertNotIn("### sample_0001", summary)
