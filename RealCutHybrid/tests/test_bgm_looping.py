import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "vendor" / "experimental" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))


def load_step10_module():
    path = SCRIPT_ROOT / "步骤10-添加BGM.py"
    spec = importlib.util.spec_from_file_location("realcut_step10_bgm_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


step10 = load_step10_module()


class BgmLoopingTests(unittest.TestCase):
    def test_short_bgm_repeats_and_trims_last_segment(self):
        segments, covered = step10.create_bgm_segments(
            "bgm-material", 30_000_000, 45_000_000
        )

        self.assertEqual(covered, 45_000_000)
        self.assertEqual(
            [segment["target_timerange"] for segment in segments],
            [
                {"duration": 30_000_000, "start": 0},
                {"duration": 15_000_000, "start": 30_000_000},
            ],
        )
        self.assertEqual(
            [segment["source_timerange"] for segment in segments],
            [
                {"duration": 30_000_000, "start": 0},
                {"duration": 15_000_000, "start": 0},
            ],
        )
        self.assertEqual(len({segment["id"] for segment in segments}), 2)

    def test_exact_repeats_are_contiguous_without_overrun(self):
        segments, covered = step10.create_bgm_segments(
            "bgm-material", 15_000_000, 45_000_000
        )

        self.assertEqual(covered, 45_000_000)
        self.assertEqual(
            [segment["target_timerange"]["start"] for segment in segments],
            [0, 15_000_000, 30_000_000],
        )
        self.assertTrue(all(
            segment["target_timerange"]["start"]
            + segment["target_timerange"]["duration"]
            <= 45_000_000
            for segment in segments
        ))

    def test_add_bgm_writes_looped_track_for_short_custom_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            draft_path = Path(tmp)
            bgm_path = draft_path / "short.mp3"
            bgm_path.write_bytes(b"test")
            draft = {
                "duration": 45_000_000,
                "materials": {"audios": [], "videos": []},
                "tracks": [{
                    "type": "video",
                    "segments": [{
                        "target_timerange": {"duration": 45_000_000, "start": 0}
                    }],
                }],
            }
            (draft_path / "draft_content.json").write_text(
                json.dumps(draft), encoding="utf-8"
            )
            written = {}

            with mock.patch.object(
                step10,
                "LOCAL_BGM_FILES",
                {11: {"path": str(bgm_path), "name": "短BGM"}},
            ), mock.patch.object(
                step10, "get_audio_duration", return_value=30_000_000
            ), mock.patch.object(
                step10,
                "write_draft",
                side_effect=lambda _path, data: written.update(copy.deepcopy(data)),
            ):
                self.assertTrue(step10.add_bgm(draft_path, 11))

            bgm_track = written["tracks"][-1]
            self.assertEqual(
                [segment["target_timerange"] for segment in bgm_track["segments"]],
                [
                    {"duration": 30_000_000, "start": 0},
                    {"duration": 15_000_000, "start": 30_000_000},
                ],
            )
            self.assertEqual(written["duration"], 45_000_000)

    def test_add_bgm_loops_short_template_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_path = root / "draft"
            template_path = root / "template"
            draft_path.mkdir()
            template_path.mkdir()

            draft = {
                "duration": 45_000_000,
                "materials": {"audios": [], "videos": []},
                "tracks": [{
                    "type": "video",
                    "segments": [{
                        "target_timerange": {"duration": 45_000_000, "start": 0}
                    }],
                }],
            }
            template_tracks = [
                {"type": "text", "segments": []}
                for _ in range(7)
            ]
            template_tracks.append({
                "type": "audio",
                "segments": [{"material_id": "template-bgm"}],
            })
            template = {
                "materials": {"audios": [{
                    "id": "template-bgm",
                    "duration": 30_000_000,
                    "name": "30秒模板BGM",
                    "type": "music",
                }]},
                "tracks": template_tracks,
            }
            (draft_path / "draft_content.json").write_text(
                json.dumps(draft), encoding="utf-8"
            )
            (template_path / "draft_content.json").write_text(
                json.dumps(template), encoding="utf-8"
            )
            written = {}

            with mock.patch.object(
                step10, "TEMPLATE", template_path
            ), mock.patch.object(
                step10, "LOCAL_BGM_FILES", {}
            ), mock.patch.object(
                step10, "rewrite_pkg_asset_paths", side_effect=lambda data: data
            ), mock.patch.object(
                step10,
                "write_draft",
                side_effect=lambda _path, data: written.update(copy.deepcopy(data)),
            ):
                self.assertTrue(step10.add_bgm(draft_path, 7))

            bgm_track = written["tracks"][-1]
            self.assertEqual(
                [segment["target_timerange"] for segment in bgm_track["segments"]],
                [
                    {"duration": 30_000_000, "start": 0},
                    {"duration": 15_000_000, "start": 30_000_000},
                ],
            )
            self.assertTrue(all(
                segment["material_id"] == written["materials"]["audios"][-1]["id"]
                for segment in bgm_track["segments"]
            ))


if __name__ == "__main__":
    unittest.main()
