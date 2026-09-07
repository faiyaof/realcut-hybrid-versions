import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "vendor" / "experimental" / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_ROOT))

import realcut_hybrid
import _price_roles
import _volc_asr


def load_step3():
    path = SCRIPT_ROOT / "步骤3-FunASR.py"
    spec = importlib.util.spec_from_file_location("realcut_step3_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VolcNormalizationTests(unittest.TestCase):
    def test_multi_character_tokens_keep_sentence_boundaries(self):
        payload = {
            "result": {
                "utterances": [{
                    "text": "衣长是72，准备好了。",
                    "start_time": 0,
                    "end_time": 900,
                    "words": [
                        {"text": "衣", "start_time": 0, "end_time": 100},
                        {"text": "长", "start_time": 100, "end_time": 200},
                        {"text": "是", "start_time": 200, "end_time": 300},
                        {"text": "72", "start_time": 300, "end_time": 500},
                        {"text": "准备好了", "start_time": 500, "end_time": 900},
                    ],
                }]
            }
        }

        words, sentences = _volc_asr.normalize_volc(payload)

        self.assertEqual("".join(word["text"] for word in words), "衣长是72准备好了")
        self.assertEqual([(s["start"], s["end"]) for s in sentences], [(0, 500), (500, 900)])
        self.assertEqual([w["start"] for w in words[3:5]], [300, 400])

    def test_english_and_repeated_characters_expand_sequentially(self):
        payload = {
            "result": {
                "utterances": [{
                    "text": "AA款，AA。",
                    "start_time": 0,
                    "end_time": 500,
                    "words": [
                        {"text": "AA", "start_time": 0, "end_time": 200},
                        {"text": "款", "start_time": 200, "end_time": 300},
                        {"text": "AA", "start_time": 300, "end_time": 500},
                    ],
                }]
            }
        }

        words, sentences = _volc_asr.normalize_volc(payload)

        self.assertEqual([word["start"] for word in words], [0, 100, 200, 300, 400])
        self.assertEqual([(s["start"], s["end"]) for s in sentences], [(0, 300), (300, 500)])


class VolcCleanupTests(unittest.TestCase):
    def setUp(self):
        self.creds = {"api_key": "api", "ak": "ak", "sk": "sk", "bucket": "b", "region": "r"}

    def test_tos_object_deleted_after_success(self):
        with mock.patch.object(_volc_asr, "_creds", return_value=self.creds), \
             mock.patch.object(_volc_asr, "_fmt_of", return_value="mp3"), \
             mock.patch.object(_volc_asr, "_upload_to_tos", return_value=("get-url", "object-url")), \
             mock.patch.object(_volc_asr, "_recognize_express", return_value={"result": {"utterances": []}}), \
             mock.patch.object(_volc_asr, "_delete_from_tos") as delete:
            _volc_asr.recognize_audio("audio.mp3")
        delete.assert_called_once_with("object-url", self.creds)

    def test_tos_object_deleted_after_recognition_failure(self):
        with mock.patch.object(_volc_asr, "_creds", return_value=self.creds), \
             mock.patch.object(_volc_asr, "_fmt_of", return_value="mp3"), \
             mock.patch.object(_volc_asr, "_upload_to_tos", return_value=("get-url", "object-url")), \
             mock.patch.object(_volc_asr, "_recognize_express", side_effect=RuntimeError("network")), \
             mock.patch.object(_volc_asr, "_delete_from_tos") as delete:
            with self.assertRaisesRegex(RuntimeError, "network"):
                _volc_asr.recognize_audio("audio.mp3")
        delete.assert_called_once_with("object-url", self.creds)


class AsrEngineTests(unittest.TestCase):
    def setUp(self):
        self.step3 = load_step3()

    def test_cache_isolated_by_requested_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp)
            audio = draft / "audio.mp3"
            audio.write_bytes(b"audio")
            cached = {
                "words": [{"text": "好", "start": 0, "end": 100}],
                "sentences": [{"text": "好。", "start": 0, "end": 100}],
                "fingerprint": self.step3._audio_fingerprint(audio),
                "requested_engine": "funasr",
                "actual_engine": "funasr",
                "asr_backend_version": "paraformer-zh-v1",
            }
            (draft / "asr_result.json").write_text(json.dumps(cached), encoding="utf-8")

            self.assertIsNone(self.step3._load_cached_asr(draft, audio, "volc"))
            self.assertIsNotNone(self.step3._load_cached_asr(draft, audio, "funasr"))

    def test_legacy_cache_never_masquerades_as_volc(self):
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp)
            audio = draft / "audio.mp3"
            audio.write_bytes(b"audio")
            cached = {
                "words": [{"text": "好", "start": 0, "end": 100}],
                "sentences": [{"text": "好。", "start": 0, "end": 100}],
                "fingerprint": self.step3._audio_fingerprint(audio),
            }
            (draft / "asr_result.json").write_text(json.dumps(cached), encoding="utf-8")

            self.assertIsNone(self.step3._load_cached_asr(draft, audio, "volc"))

    def test_fallback_result_does_not_prevent_future_volc_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp)
            audio = draft / "audio.mp3"
            audio.write_bytes(b"audio")
            cached = {
                "words": [{"text": "好", "start": 0, "end": 100}],
                "sentences": [{"text": "好。", "start": 0, "end": 100}],
                "fingerprint": self.step3._audio_fingerprint(audio),
                "requested_engine": "volc",
                "actual_engine": "funasr",
                "asr_backend_version": "paraformer-zh-v1",
                "fallback_reason": "temporary failure",
            }
            (draft / "asr_result.json").write_text(json.dumps(cached), encoding="utf-8")

            self.assertIsNone(self.step3._load_cached_asr(draft, audio, "volc"))

    def test_volc_failure_records_funasr_as_actual_engine(self):
        fallback = ([{"text": "好", "start": 0, "end": 100}], [{"text": "好。", "start": 0, "end": 100}])
        with mock.patch.object(_volc_asr, "recognize_audio", side_effect=RuntimeError("denied")), \
             mock.patch.object(self.step3, "_recognize_funasr", return_value=fallback):
            words, sentences, actual, reason = self.step3._recognize_with_engine(Path("audio.mp3"), "volc")

        self.assertEqual(actual, "funasr")
        self.assertEqual(reason, "denied")
        self.assertEqual(sentences[0]["text"], "好。")

    def test_resume_uses_saved_engine_unless_explicitly_overridden(self):
        self.assertEqual(realcut_hybrid.resolve_asr_engine(None, {"asr_engine": "volc"}), "volc")
        self.assertEqual(realcut_hybrid.resolve_asr_engine("funasr", {"asr_engine": "volc"}), "funasr")


class PriceComplianceTests(unittest.TestCase):
    def test_product_codes_are_not_treated_as_prices(self):
        self.assertFalse(_price_roles._has_price("这个款号是2771170K"))
        self.assertFalse(_price_roles._has_price("款号是90560G"))
        self.assertTrue(_price_roles._has_price("159"))
        self.assertTrue(_price_roles._has_price("100 259的"))

    def test_chinese_comma_separates_spoken_price_numbers(self):
        self.assertEqual(_price_roles._price_value("159，100 259的"), 259)
        self.assertEqual(_price_roles._price_value("原价3,999元"), 3999)

    def test_price_roles_cannot_restore_disallowed_sentence(self):
        sentences = [
            {"text": "南沙港仓库原价599元，上车379元"},
            {"text": "今天上车只要399元"},
        ]
        with mock.patch.object(_price_roles, "llm_text_with_provider", return_value=(None, None)):
            original, current, _ = _price_roles.detect_price_roles(sentences, allowed_indices={1})

        self.assertNotEqual(original, 0)
        self.assertNotEqual(current, 0)


if __name__ == "__main__":
    unittest.main()
