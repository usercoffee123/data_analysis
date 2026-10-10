"""Checks for verification and report replacement at the shared file boundary."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from analysis_io import read_input, write_text


class AnalysisIOTests(unittest.TestCase):
    def test_verification_reports_invalid_digests_without_losing_input_metadata(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "input.data"
            content = b"sample\n"
            path.write_bytes(content)
            actual = hashlib.sha256(content).hexdigest()
            for expected, verified in (
                (actual.upper(), True),
                ("0" * 64, False),
                ("invalid", False),
                (None, False),
            ):
                with self.subTest(expected=expected):
                    data, metadata = read_input(path, expected)
                    self.assertEqual(data, content)
                    self.assertEqual(metadata["file"], str(path))
                    self.assertEqual(metadata["sha256"], actual)
                    self.assertEqual(metadata["expected_sha256"], expected)
                    self.assertEqual(metadata["digest_verified"], verified)

    def test_failed_replacement_preserves_existing_report_and_removes_temporary_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.md"
            path.write_text("previous report", encoding="utf-8")
            with patch.object(Path, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    write_text(path, "new report")
            self.assertEqual(path.read_text(encoding="utf-8"), "previous report")
            self.assertEqual(list(path.parent.iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
