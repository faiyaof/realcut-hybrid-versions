import subprocess
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "vendor" / "experimental" / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_ROOT))

import _trim_segments
import realcut_hybrid


class SilencePruningTests(unittest.TestCase):
    def test_full_audio_is_scanned_once_and_edges_are_trimmed(self):
        stderr = """
        silence_start: 0
        silence_end: 1.0 | silence_duration: 1.0
        silence_start: 2.0
        silence_end: 3.0 | silence_duration: 1.0
        mean_volume: -21.5 dB
        """
        completed = subprocess.CompletedProcess([], 0, "", stderr)
        segments = [
            {
                "category": "爆点", "text": "中间有声音", "source": "asr",
                "src_start_ms": 0, "src_end_ms": 3000, "src_dur_ms": 3000,
            },
            {
                "category": "展示衣服", "text": "无需裁剪", "source": "asr",
                "src_start_ms": 4000, "src_end_ms": 6000, "src_dur_ms": 2000,
            },
        ]

        with mock.patch.object(_trim_segments, "_run", return_value=completed) as run:
            kept, dropped = _trim_segments.clean_ordered_segments(segments, "audio.mp3")

        run.assert_called_once()
        self.assertEqual(dropped, [])
        self.assertEqual((kept[0]["src_start_ms"], kept[0]["src_end_ms"]), (1000, 2000))
        self.assertEqual(kept[0]["src_dur_ms"], 1000)
        self.assertTrue(kept[0]["silence_trimmed"])
        self.assertEqual(
            (kept[0]["original_src_start_ms"], kept[0]["original_src_end_ms"]),
            (0, 3000),
        )
        self.assertNotIn("silence_trimmed", kept[1])

    def test_only_nearly_all_silent_sentence_is_dropped(self):
        analysis = {
            "vol_db": -20.0,
            "silences": [(0.0, 1.0), (2.0, 3.0), (3.0, 9.8), (11.0, 12.0)],
        }
        segments = [
            {
                "category": "爆点", "text": "仍有三分之一语音", "source": "asr",
                "src_start_ms": 0, "src_end_ms": 3000, "src_dur_ms": 3000,
            },
            {
                "category": "痛点", "text": "几乎全静音", "source": "asr",
                "src_start_ms": 3000, "src_end_ms": 10000, "src_dur_ms": 7000,
            },
            {
                "category": "展示衣服", "text": "只含句中停顿", "source": "asr",
                "src_start_ms": 10000, "src_end_ms": 13000, "src_dur_ms": 3000,
            },
        ]

        with mock.patch.object(_trim_segments, "_run") as run:
            kept, dropped = _trim_segments.clean_ordered_segments(
                segments, "audio.mp3", analysis=analysis
            )

        run.assert_not_called()
        self.assertEqual([segment["text"] for segment in kept], ["仍有三分之一语音", "只含句中停顿"])
        self.assertEqual([segment["text"] for segment in dropped], ["几乎全静音"])
        self.assertEqual((kept[1]["src_start_ms"], kept[1]["src_end_ms"]), (10000, 13000))

    def test_ffmpeg_failure_does_not_return_misleading_empty_analysis(self):
        completed = subprocess.CompletedProcess([], 1, "", "failure")
        with mock.patch.object(_trim_segments, "_run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "ffmpeg 静音分析失败"):
                _trim_segments.analyze_audio("audio.mp3")

    def test_task_report_lists_trimmed_and_dropped_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "draft"
            reports = root / "reports"
            draft.mkdir()
            reports.mkdir()
            (draft / "silence_pruning_report.json").write_text(
                json.dumps({
                    "status": "OK",
                    "silence_interval_count": 2,
                    "trimmed": [{
                        "category": "爆点", "text": "裁短句",
                        "original_src_start_ms": 0, "original_src_end_ms": 3000,
                        "src_start_ms": 1000, "src_end_ms": 2000,
                    }],
                    "dropped": [{
                        "category": "痛点", "text": "静音句",
                        "src_start_ms": 3000, "src_end_ms": 10000,
                        "speech_ratio": 0.03,
                    }],
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            old_report_dir = realcut_hybrid.REPORT_DIR
            realcut_hybrid.REPORT_DIR = reports
            try:
                report = realcut_hybrid.write_report({
                    "task_id": "test-task", "status": "completed",
                    "video": "video.mp4", "draft": str(draft),
                    "created_at": "now", "updated_at": "now", "steps": {},
                })
            finally:
                realcut_hybrid.REPORT_DIR = old_report_dir

            text = report.read_text(encoding="utf-8")
            self.assertIn("裁边段数: 1", text)
            self.assertIn("删除段数: 1", text)
            self.assertIn("裁短句", text)
            self.assertIn("静音句", text)


if __name__ == "__main__":
    unittest.main()
