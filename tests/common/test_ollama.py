"""Verify the Ollama HTTP boundary without depending on a running model."""

import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from manufacturing_analysis.common.ollama import OLLAMA_MODEL, OLLAMA_URL, analyze_with_ollama


class OllamaClientTests(unittest.TestCase):
    def response(self, content):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {"message": {"content": content}}
        ).encode("utf-8")
        return response

    def test_sends_computed_evidence_and_returns_analysis(self):
        readings = [{"sensor_id": "temperature", "value": 68}]
        findings = [{"sensor_id": "temperature", "status": "normal"}]
        with patch(
            "manufacturing_analysis.common.ollama.urlopen",
            return_value=self.response('{"summary": "Reading is within bounds."}'),
        ) as request:
            result = analyze_with_ollama(readings, findings)

        http_request = request.call_args.args[0]
        self.assertEqual(http_request.full_url, OLLAMA_URL)
        self.assertEqual(http_request.method, "POST")
        self.assertEqual(request.call_args.kwargs["timeout"], 120)
        body = json.loads(http_request.data)
        self.assertEqual(body["model"], OLLAMA_MODEL)
        self.assertEqual(body["format"], "json")
        self.assertEqual(
            json.loads(body["messages"][1]["content"]),
            {"readings": readings, "deterministic_rule_findings": findings},
        )
        self.assertEqual(result["summary"], "Reading is within bounds.")
        self.assertEqual(result["observations"], [])
        self.assertIn("verify", result["limitations"])

    def test_rejects_invalid_model_content(self):
        for content, error in (
            ("not JSON", "invalid JSON analysis"),
            ('{"summary": 123}', "containing a summary"),
            ("[]", "containing a summary"),
            (None, "invalid JSON analysis"),
        ):
            with self.subTest(content=content), patch(
                "manufacturing_analysis.common.ollama.urlopen", return_value=self.response(content)
            ):
                with self.assertRaisesRegex(RuntimeError, error):
                    analyze_with_ollama([], [])

    def test_connection_failure_has_useful_context(self):
        with patch("manufacturing_analysis.common.ollama.urlopen", side_effect=URLError("connection refused")):
            with self.assertRaisesRegex(RuntimeError, "Could not reach Ollama") as error:
                analyze_with_ollama([], [])
        self.assertIn(OLLAMA_URL, str(error.exception))


if __name__ == "__main__":
    unittest.main()
