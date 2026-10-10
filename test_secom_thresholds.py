import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from secom_graph import DEFAULT_THRESHOLDS_PATH, process_secom, screen_samples
from secom_thresholds import validate_thresholds


class ThresholdTests(unittest.TestCase):
    def artifact(self):
        return json.loads((Path(__file__).parent / "tests/fixtures/thresholds_2.json").read_text())

    def test_saved_thresholds_apply_to_single_row_without_fitting(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "thresholds.json"
            artifact = self.artifact()
            path.write_text(json.dumps(artifact))
            result = screen_samples({"rows": [[100.0, None]], "labels": [-1],
                                         "timestamps": ["test"], "thresholds_path": path})["sample_screening"]
            self.assertEqual(result["sample_count"], 1)
            self.assertEqual(result["flagged_count"], 1)
            self.assertEqual(result["samples"][0]["cohort"], "saved_thresholds")
            self.assertEqual(result["evaluation"]["held_out"]["sample_count"], 0)
            self.assertEqual(result["method"]["anomaly_threshold"], artifact["anomaly_threshold"])
            self.assertEqual(result["method"]["threshold_provenance"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_invalid_artifacts_rejected(self):
        mutations = [
            lambda a: a.update(schema_version=True),
            lambda a: a.update(feature_count=3),
            lambda a: a.update(anomaly_threshold=float('nan')),
            lambda a: a.update(missing_fraction_threshold=True),
            lambda a: a['features'][0].update(feature_id='feature_001'),
            lambda a: a['features'][0].update(lower=float('-inf')),
            lambda a: a['features'][0].update(iqr=0),
            lambda a: a['features'][1].update(lower=0),
        ]
        for mutate in mutations:
            artifact = copy.deepcopy(self.artifact())
            mutate(artifact)
            with self.subTest(artifact=artifact), self.assertRaises(ValueError):
                validate_thresholds(artifact, 2)

    def test_default_run_uses_static_file_and_verifies_input(self):
        with TemporaryDirectory() as folder:
            data, labels, thresholds = [Path(folder) / name for name in ('data', 'labels', 'thresholds.json')]
            data.write_text('\n'.join(f'{i % 5} NaN' for i in range(25)) + '\n')
            labels.write_text('-1 19/07/2008 11:55:00\n' * 25)
            digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            thresholds.write_text(json.dumps(self.artifact()))
            failed = process_secom(data, labels, '0' * 64, digest(labels), Path(folder) / 'failure.json', None,
                                   thresholds_path=thresholds)
            self.assertEqual(failed['status'], 'failure')
            with patch('secom_graph.DEFAULT_THRESHOLDS_PATH', thresholds):
                automatic = process_secom(data, labels, digest(data), digest(labels), Path(folder) / 'auto.json', None)
                saved = process_secom(data, labels, digest(data), digest(labels), Path(folder) / 'saved.json', None,
                                      thresholds_path=thresholds)
            self.assertEqual(saved['status'], 'success')
            for old, new in zip(automatic['assessment']['sample_screening']['samples'], saved['assessment']['sample_screening']['samples']):
                self.assertEqual(old['anomaly_score'], new['anomaly_score'])
                self.assertEqual(old['flag_reasons'], new['flag_reasons'])
            self.assertIn('No held-out evaluation', (Path(folder) / 'saved.md').read_text())
            with self.assertRaises(ValueError):
                process_secom(data, labels, digest(data), digest(labels), thresholds, None, thresholds_path=thresholds)

    def test_missing_default_threshold_file_never_triggers_fitting(self):
        with TemporaryDirectory() as folder, patch('secom_graph.DEFAULT_THRESHOLDS_PATH', Path(folder) / 'missing.json'):
            with self.assertRaises(FileNotFoundError):
                screen_samples({'rows': [[1.0, None]], 'labels': [-1], 'timestamps': ['test']})

    def test_checked_in_thresholds_remain_unchanged_after_application(self):
        before = DEFAULT_THRESHOLDS_PATH.read_bytes()
        result = screen_samples({'rows': [[None] * 590], 'labels': [-1], 'timestamps': ['test']})
        self.assertEqual(result['sample_screening']['sample_count'], 1)
        self.assertEqual(DEFAULT_THRESHOLDS_PATH.read_bytes(), before)
