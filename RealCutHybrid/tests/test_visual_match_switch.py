import argparse
import importlib.util
import json
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


class VisualMatchSwitchTests(unittest.TestCase):
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
        script_path = SCRIPT_ROOT / "步骤6-画面匹配.py"
        spec = importlib.util.spec_from_file_location("realcut_step6_test", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

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


if __name__ == "__main__":
    unittest.main()
