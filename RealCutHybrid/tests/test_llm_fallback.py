from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "vendor" / "experimental" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _llm


class _Response:
    status_code = 400
    text = '{"error":{"message":"unsupported model"}}'


class _Requests:
    def __init__(self):
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return _Response()


class _TimeoutRequests:
    def __init__(self):
        self.calls = 0
        self.timeouts = []

    def post(self, *args, **kwargs):
        self.calls += 1
        self.timeouts.append(kwargs.get("timeout"))
        raise TimeoutError("timed out")


class LlmFallbackTests(unittest.TestCase):
    def test_non_retryable_400_falls_back_without_repeating_attempts(self):
        requests = _Requests()
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}), mock.patch.object(
            _llm, "import_external", return_value=requests
        ):
            result = _llm._deepseek_text("test", max_retries=2)

        self.assertIsNone(result)
        self.assertEqual(requests.calls, 1)

    def test_json_mode_only_retries_once_without_response_format(self):
        requests = _Requests()
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}), mock.patch.object(
            _llm, "import_external", return_value=requests
        ):
            result = _llm._deepseek_text("test", json_mode=True, max_retries=2)

        self.assertIsNone(result)
        self.assertEqual(requests.calls, 2)

    def test_provider_forwards_deepseek_timeout_and_retry_controls(self):
        with mock.patch.object(_llm, "_deepseek_text", return_value=None) as deepseek, mock.patch.object(
            _llm, "_qwen_text", return_value="qwen result"
        ):
            result = _llm.llm_text_with_provider(
                "test",
                json_mode=True,
                deepseek_timeout=30,
                deepseek_max_retries=0,
            )

        self.assertEqual(result, ("qwen result", f"qwen:{_llm.QWEN_FALLBACK_MODEL}"))
        deepseek.assert_called_once_with(
            "test",
            system=None,
            temperature=0.1,
            json_mode=True,
            timeout=30,
            max_retries=0,
        )

    def test_timeout_does_not_repeat_when_provider_retries_are_disabled(self):
        requests = _TimeoutRequests()
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}), mock.patch.object(
            _llm, "import_external", return_value=requests
        ), mock.patch.object(_llm, "_qwen_text", return_value="fallback"):
            result = _llm.llm_text_with_provider(
                "test",
                deepseek_timeout=30,
                deepseek_max_retries=0,
            )

        self.assertEqual(requests.calls, 1)
        self.assertEqual(requests.timeouts, [30])
        self.assertEqual(result, ("fallback", f"qwen:{_llm.QWEN_FALLBACK_MODEL}"))


if __name__ == "__main__":
    unittest.main()
