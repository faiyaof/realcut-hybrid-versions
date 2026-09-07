import argparse
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "vendor" / "experimental" / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_ROOT))

import realcut_hybrid
from _video_assign import assign_video_sources


_STEP6_MODULE = None


class VisualMatchSwitchTests(unittest.TestCase):
    @staticmethod
    def _load_step6():
        global _STEP6_MODULE
        if _STEP6_MODULE is not None:
            return _STEP6_MODULE
        script_path = SCRIPT_ROOT / "步骤6-画面匹配.py"
        spec = importlib.util.spec_from_file_location("realcut_step6_test", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _STEP6_MODULE = module
        return _STEP6_MODULE

    def test_orchestrator_passes_fast_mode_flags(self):
        opts = argparse.Namespace(visual_match=False)
        draft = Path("draft")
        video = Path("video.mp4")
        step4 = next(step for step in realcut_hybrid.STEPS if step.key == "4_select_sort")
        step6 = next(step for step in realcut_hybrid.STEPS if step.key == "6_visual")

        self.assertEqual(
            realcut_hybrid.build_args(step4, video, draft, opts),
            [str(draft), "--no-open", "--no-visual-check"],
        )
        self.assertEqual(
            realcut_hybrid.build_args(step6, video, draft, opts),
            [str(draft), "--no-open", "--timeline-only"],
        )

    def test_silence_pruning_requires_explicit_opt_in(self):
        draft = Path("draft")
        video = Path("video.mp4")
        step4 = next(step for step in realcut_hybrid.STEPS if step.key == "4_select_sort")

        disabled = argparse.Namespace(visual_match=True, silence_pruning=False)
        enabled = argparse.Namespace(visual_match=True, silence_pruning=True)

        self.assertEqual(realcut_hybrid.build_args(step4, video, draft, disabled), [str(draft), "--no-open"])
        self.assertEqual(
            realcut_hybrid.build_args(step4, video, draft, enabled),
            [str(draft), "--no-open", "--silence-pruning"],
        )

    def test_empty_visual_data_uses_subtitle_source_times(self):
        audio_segments = [
            {"target_timerange": {"duration": 1_500_000}},
            {"target_timerange": {"duration": 2_000_000}},
        ]
        metadata = [
            {"src_start_ms": 1_250},
            {"src_start_ms": 6_800},
        ]

        self.assertEqual(
            assign_video_sources(audio_segments, metadata, {}, 20_000_000),
            [(1_250_000, False), (6_800_000, False)],
        )

    def test_timeline_only_does_not_load_visual_model(self):
        module = self._load_step6()

        with tempfile.TemporaryDirectory() as tmp:
            draft_path = Path(tmp)
            source_video = draft_path / "source.mp4"
            source_video.write_bytes(b"test")
            draft = {
                "duration": 0,
                "materials": {"videos": [{"id": "video-material"}]},
                "tracks": [
                    {"type": "video", "segments": []},
                    {
                        "type": "audio",
                        "segments": [
                            {"target_timerange": {"duration": 1_500_000}},
                            {"target_timerange": {"duration": 2_000_000}},
                        ],
                    },
                ],
            }
            metadata = [
                {"src_start_ms": 1_250},
                {"src_start_ms": 6_800},
            ]
            (draft_path / "draft_content.json").write_text(
                json.dumps(draft), encoding="utf-8"
            )
            (draft_path / "step4_segments.json").write_text(
                json.dumps(metadata), encoding="utf-8"
            )

            module.find_source_video = lambda _path: str(source_video)
            module.get_video_dur = lambda _path: 20
            module.import_external = lambda _name: self.fail("visual model was loaded")
            module.get_frame_actions = lambda *_args: self.fail("frames were extracted")
            written = {}
            module.write_draft = lambda _path, data: written.update(data)

            module.match_video(draft_path, auto_open=False, timeline_only=True)

            video_segments = written["tracks"][0]["segments"]
            self.assertEqual(
                [segment["source_timerange"]["start"] for segment in video_segments],
                [1_250_000, 6_800_000],
            )

    def test_step4_timestamp_does_not_invalidate_frame_cache(self):
        module = self._load_step6()
        with tempfile.TemporaryDirectory() as tmp:
            draft_path = Path(tmp)
            source_video = draft_path / "source.mp4"
            source_video.write_bytes(b"video")
            cache_path = draft_path / "_frame_full_cache_1s.json"
            actions = {"1000": "展示中"}
            module.save_frame_cache(str(cache_path), str(source_video), actions)

            step4 = draft_path / "step4_segments.json"
            step4.write_text("[]", encoding="utf-8")
            newer = cache_path.stat().st_mtime + 5
            os.utime(step4, (newer, newer))

            self.assertEqual(
                module.load_frame_cache(str(cache_path), str(source_video)),
                actions,
            )

    def test_source_signature_change_invalidates_frame_cache(self):
        module = self._load_step6()
        with tempfile.TemporaryDirectory() as tmp:
            draft_path = Path(tmp)
            source_video = draft_path / "source.mp4"
            source_video.write_bytes(b"video-v1")
            cache_path = draft_path / "_frame_full_cache_1s.json"
            module.save_frame_cache(
                str(cache_path), str(source_video), {"1000": "展示中"}
            )

            source_video.write_bytes(b"video-version-two")

            self.assertIsNone(
                module.load_frame_cache(str(cache_path), str(source_video))
            )

    def test_same_source_in_sibling_draft_reuses_frame_cache(self):
        module = self._load_step6()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "20"
            restyled = root / "20_1"
            original.mkdir()
            restyled.mkdir()
            source_a = original / "20.mp4"
            source_b = restyled / "20.mp4"
            source_a.write_bytes(b"same-video-content")
            source_b.write_bytes(source_a.read_bytes())
            source_stat = source_a.stat()
            os.utime(
                source_b,
                ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
            )
            actions = {"1000": "展示中"}
            module.save_frame_cache(
                str(original / "_frame_full_cache_1s.json"),
                str(source_a),
                actions,
            )

            self.assertEqual(
                module.find_sibling_frame_cache(str(source_b), str(restyled)),
                actions,
            )

    def test_fatal_visual_error_stops_remaining_frames_and_discards_partial_results(self):
        module = self._load_step6()
        calls = []

        def call_vl(frame):
            calls.append(frame)
            if len(calls) == 1:
                return "", "arrearage"
            self.fail("fatal account errors must stop remaining frame requests")

        actions, fatal_error = module.collect_frame_actions(
            ["f_0001.png", "f_0002.png", "f_0003.png"], call_vl
        )

        self.assertEqual(actions, {})
        self.assertEqual(fatal_error, "arrearage")
        self.assertEqual(calls, ["f_0001.png"])

    def test_all_empty_cache_is_rejected_but_partial_cache_is_kept(self):
        module = self._load_step6()
        with tempfile.TemporaryDirectory() as tmp:
            draft_path = Path(tmp)
            source_video = draft_path / "source.mp4"
            source_video.write_bytes(b"video")
            cache_path = draft_path / "_frame_full_cache_1s.json"
            module.save_frame_cache(
                str(cache_path), str(source_video), {"1000": "展示中"}
            )

            cache_path.write_text(json.dumps({"1000": "", "2000": "  "}), encoding="utf-8")
            self.assertIsNone(
                module.load_frame_cache(str(cache_path), str(source_video))
            )

            partial = {"1000": "", "2000": "展示中"}
            cache_path.write_text(json.dumps(partial, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(
                module.load_frame_cache(str(cache_path), str(source_video)), partial
            )

    def test_permission_and_billing_errors_are_fatal_but_rate_limits_are_not(self):
        module = self._load_step6()

        self.assertEqual(module._fatal_vl_error(400, "Arrearage"), "arrearage")
        self.assertEqual(module._fatal_vl_error(401, ""), "http_401")
        self.assertEqual(
            module._fatal_vl_error(400, "InvalidApiKey"), "invalidapikey"
        )
        self.assertEqual(module._fatal_vl_error(429, "Throttling"), "")


if __name__ == "__main__":
    unittest.main()
