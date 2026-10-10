import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from manufacturing_analysis.secom.workflow import DEFAULT_THRESHOLDS_PATH, process_secom, screen_samples
from manufacturing_analysis.secom.thresholds import inspect_row, references_from_thresholds, score_rows, validate_thresholds


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures/thresholds_2.json"


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ThresholdTests(unittest.TestCase):
    def setUp(self):
        self.artifact = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.feature_count = self.artifact["feature_count"]

    def write_thresholds(self, folder):
        path = Path(folder) / "thresholds.json"
        path.write_text(json.dumps(self.artifact), encoding="utf-8")
        return path

    def test_saved_thresholds_apply_to_single_row(self):
        with TemporaryDirectory() as folder:
            path = self.write_thresholds(folder)
            state = {
                "rows": [[100.0, None]],
                "labels": [-1],
                "timestamps": ["test"],
                "thresholds_path": path,
            }
            result = screen_samples(state)["sample_screening"]
            self.assertEqual(result["sample_count"], 1)
            self.assertEqual(result["flagged_count"], 1)
            self.assertEqual(result["samples"][0]["cohort"], "saved_thresholds")
            self.assertEqual(result["evaluation"]["held_out"]["sample_count"], 0)
            method = result["method"]
            self.assertEqual(method["anomaly_threshold"], self.artifact["anomaly_threshold"])
            self.assertEqual(method["threshold_provenance"]["sha256"], file_digest(path))

    def test_invalid_artifacts_rejected(self):
        invalid_fields = [
            {"schema_version": True},
            {"schema_version": 2},
            {"feature_count": self.feature_count + 1},
            {"feature_count": True},
            {"settings": []},
            {"anomaly_threshold": float("nan")},
            {"missing_fraction_threshold": True},
            {"missing_fraction_threshold": 1.1},
            {"features": {}},
            {"features": []},
        ]
        for fields in invalid_fields:
            artifact = copy.deepcopy(self.artifact)
            artifact.update(fields)
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate_thresholds(artifact, self.feature_count)

    def test_invalid_feature_entries_rejected(self):
        invalid_features = [
            (0, {"feature_id": "feature_001"}),
            (0, {"eligible": 1}),
            (0, {"lower": float("-inf")}),
            (0, {"lower": True}),
            (0, {"lower": self.artifact["features"][0]["upper"]}),
            (0, {"iqr": 0}),
            (1, {"lower": 0}),
        ]
        for index, fields in invalid_features:
            artifact = copy.deepcopy(self.artifact)
            artifact["features"][index].update(fields)
            with self.subTest(index=index, fields=fields), self.assertRaises(ValueError):
                validate_thresholds(artifact, self.feature_count)

    def test_scoring_uses_only_observed_eligible_features(self):
        references = references_from_thresholds(self.artifact)
        lower, upper, _ = references[0]
        rows = [[lower, None], [upper, 1000.0], [upper + 1, None], [None, 1000.0]]
        scores, missing_fractions = score_rows(rows, references)
        self.assertEqual(scores, [0.0, 0.0, 1.0, 0.0])
        self.assertEqual(missing_fractions, [0.0, 0.0, 0.0, 1.0])
        self.assertEqual(score_rows([[1000.0]], [None]), ([0.0], [1.0]))

    def test_inspection_sorts_evidence_and_keeps_bounds_unflagged(self):
        references = [(0.0, 10.0, 2.0)] * 6 + [None]
        row = [11.0, -4.0, 0.0, 10.0, None, 9.0, 1000.0]
        result = inspect_row(row, references)
        self.assertEqual(result["findings"], [
            {
                "feature_id": "feature_001",
                "value": -4.0,
                "reference_min": 0.0,
                "reference_max": 10.0,
                "direction": "below",
                "distance_in_iqr": 2.0,
            },
            {
                "feature_id": "feature_000",
                "value": 11.0,
                "reference_min": 0.0,
                "reference_max": 10.0,
                "direction": "above",
                "distance_in_iqr": 0.5,
            },
        ])
        self.assertEqual(result["anomaly_score"], 2 / 5)
        self.assertEqual(result["eligible_missing_fraction"], 1 - 5 / 6)
        self.assertEqual(
            score_rows([row], references),
            ([result["anomaly_score"]], [result["eligible_missing_fraction"]]),
        )

    def test_default_run_uses_static_file_and_verifies_input(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            data = folder / "data"
            labels = folder / "labels"
            thresholds = self.write_thresholds(folder)
            data.write_text("0 NaN\n" * 25, encoding="utf-8")
            labels.write_text("-1 19/07/2008 11:55:00\n" * 25, encoding="utf-8")
            data_digest, labels_digest = file_digest(data), file_digest(labels)

            failed = process_secom(
                data, labels, "0" * 64, labels_digest, folder / "failure.json", None,
                thresholds_path=thresholds,
            )
            self.assertEqual(failed["status"], "failure")

            with patch("manufacturing_analysis.secom.workflow.DEFAULT_THRESHOLDS_PATH", thresholds):
                default = process_secom(
                    data, labels, data_digest, labels_digest, folder / "default.json", None,
                )
            saved = process_secom(
                data, labels, data_digest, labels_digest, folder / "saved.json", None,
                thresholds_path=thresholds,
            )
            self.assertEqual(saved["status"], "success")
            default_samples = default["assessment"]["sample_screening"]["samples"]
            saved_samples = saved["assessment"]["sample_screening"]["samples"]
            self.assertEqual(default_samples, saved_samples)
            self.assertIn("No held-out evaluation", (folder / "saved.md").read_text())

            with self.assertRaises(ValueError):
                process_secom(
                    data, labels, data_digest, labels_digest, thresholds, None,
                    thresholds_path=thresholds,
                )

    def test_missing_default_threshold_file_is_an_error(self):
        with TemporaryDirectory() as folder:
            missing_path = Path(folder) / "missing.json"
            state = {"rows": [[1.0, None]], "labels": [-1], "timestamps": ["test"]}
            with patch("manufacturing_analysis.secom.workflow.DEFAULT_THRESHOLDS_PATH", missing_path):
                with self.assertRaises(FileNotFoundError):
                    screen_samples(state)

    def test_checked_in_thresholds_remain_unchanged_after_application(self):
        before = DEFAULT_THRESHOLDS_PATH.read_bytes()
        feature_count = json.loads(before)["feature_count"]
        state = {"rows": [[None] * feature_count], "labels": [-1], "timestamps": ["test"]}
        result = screen_samples(state)
        self.assertEqual(result["sample_screening"]["sample_count"], 1)
        self.assertEqual(DEFAULT_THRESHOLDS_PATH.read_bytes(), before)
