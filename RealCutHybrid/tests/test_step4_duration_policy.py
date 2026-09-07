import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "vendor" / "experimental" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

import realcut_hybrid
import _price_roles as PRICE_ROLES


def load_script(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STEP4 = load_script("realcut_step4_duration_test", "步骤4-切割排序.py")
MIRROR = load_script("realcut_mirror_policy_test", "mirror_通用.py")
OPEN_BOX = load_script("realcut_open_box_policy_test", "步骤4后-开盒补位.py")


class Step4DurationPolicyTests(unittest.TestCase):
    def _visual_groups(self, clothing=None, pain=None):
        return {
            "爆点": [], "痛点": list(pain or []),
            "展示衣服": list(clothing or []),
            "金句": [], "价格": [],
        }

    def test_step4_classification_uses_fast_deepseek_fallback_controls(self):
        sentences = [
            {"start": 0, "end": 1_500, "text": "这件衣服版型很好"},
        ]
        calls = []
        original_llm = STEP4.llm_text_with_provider
        STEP4.llm_text_with_provider = lambda prompt, **kwargs: (
            calls.append(kwargs) or ("0|展示衣服", "qwen")
        )
        try:
            result = STEP4.classify_sentences(sentences, "key", max_retries=0)
        finally:
            STEP4.llm_text_with_provider = original_llm

        self.assertEqual(result, [(0, "展示衣服")])
        self.assertEqual(calls[0]["deepseek_timeout"], 30)
        self.assertEqual(calls[0]["deepseek_max_retries"], 0)

    def test_price_role_detection_uses_fast_deepseek_fallback_controls(self):
        sentences = [
            {"text": "原价五百二"},
            {"text": "今天一百二上车"},
        ]
        calls = []
        original_llm = PRICE_ROLES.llm_text_with_provider
        PRICE_ROLES.llm_text_with_provider = lambda prompt, **kwargs: (
            calls.append(kwargs) or (
                '{"original_price":[0],"current_price":[1]}', "qwen"
            )
        )
        try:
            PRICE_ROLES.detect_price_roles(sentences)
        finally:
            PRICE_ROLES.llm_text_with_provider = original_llm

        self.assertEqual(calls[0]["deepseek_timeout"], 30)
        self.assertEqual(calls[0]["deepseek_max_retries"], 0)

    def test_visual_recovery_skips_vl_when_core_is_long_enough_and_has_display(self):
        sentences = [
            {"start": 0, "end": 8_000, "text": "这件衣服版型很好"},
            {"start": 8_100, "end": 15_100, "text": "穿起来不挑身材"},
            {"start": 15_200, "end": 18_200, "text": "随便聊两句"},
        ]
        calls = []

        STEP4.maybe_recover_visual_clothing(
            self._visual_groups(clothing=[0], pain=[1]), [2], sentences,
            {0, 1, 2}, Path("."), "key", src_video="source.mp4",
            visual_checker=lambda *args: calls.append(args) or [],
        )

        self.assertEqual(calls, [])

    def test_visual_recovery_calls_vl_when_duration_is_short(self):
        sentences = [
            {"start": 0, "end": 8_000, "text": "这件衣服版型很好"},
            {"start": 8_100, "end": 12_100, "text": "今天先聊到这里"},
        ]
        calls = []

        STEP4.maybe_recover_visual_clothing(
            self._visual_groups(clothing=[0]), [1], sentences, {0, 1},
            Path("."), "key", src_video="source.mp4",
            visual_checker=lambda *args: calls.append(args) or [],
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], [1])

    def test_visual_recovery_calls_vl_when_display_is_missing(self):
        sentences = [
            {"start": 0, "end": 16_000, "text": "上身效果很利落"},
            {"start": 16_100, "end": 19_100, "text": "再给你们看一眼"},
        ]
        calls = []

        STEP4.maybe_recover_visual_clothing(
            self._visual_groups(pain=[0]), [1], sentences, {0, 1},
            Path("."), "key", src_video="source.mp4",
            visual_checker=lambda *args: calls.append(args) or [],
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], [1])

    def test_visual_recovery_candidates_are_capped_and_favor_duration_then_proximity(self):
        sentences = [
            {"start": 10_000, "end": 12_000, "text": "已选口播"},
            {"start": 12_050, "end": 13_050, "text": "近处短句"},
            {"start": 30_000, "end": 43_000, "text": "远处但可补足时长"},
        ]
        sentences.extend(
            {"start": 44_000 + idx * 2_000, "end": 45_000 + idx * 2_000,
             "text": f"候选{idx}"}
            for idx in range(8)
        )
        discarded = list(range(1, len(sentences)))
        calls = []

        STEP4.maybe_recover_visual_clothing(
            self._visual_groups(clothing=[0]), discarded, sentences,
            set(range(len(sentences))), Path("."), "key",
            src_video="source.mp4",
            visual_checker=lambda *args: calls.append(args) or [],
        )

        candidates = calls[0][2]
        self.assertEqual(len(candidates), STEP4.VISUAL_RECOVERY_MAX_CANDIDATES)
        self.assertEqual(candidates[0], 2)
        self.assertIn(1, candidates)

    def test_visual_check_uses_frame_cache_without_loading_cloud_client(self):
        sentences = [
            {"start": 500, "end": 1_500, "text": "拿起来展示"},
            {"start": 1_500, "end": 2_500, "text": "随便聊两句"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            draft_path = Path(tmp)
            source_video = draft_path / "source.mp4"
            source_video.write_bytes(b"video")
            cache_path = draft_path / "_frame_full_cache_1s.json"
            cache_path.write_text(
                json.dumps({"1000": "展示中", "2000": "空手"}, ensure_ascii=False),
                encoding="utf-8",
            )
            original_import = STEP4.import_external
            STEP4.import_external = lambda _name: self.fail("cloud client was loaded")
            try:
                recovered = STEP4.visual_check_clothing_display(
                    draft_path, sentences, [0, 1], str(source_video)
                )
            finally:
                STEP4.import_external = original_import

        self.assertEqual(recovered, [0])

    def test_short_adjacent_sentences_merge_without_being_dropped(self):
        sentences = [
            {"start": 11_560, "end": 12_200, "text": "看成分，"},
            {"start": 12_240, "end": 12_760, "text": "看面料，"},
            {"start": 12_760, "end": 13_600, "text": "看做工啊，"},
        ]

        units = STEP4.build_speech_units(sentences)

        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]["start"], 11_560)
        self.assertEqual(units[0]["end"], 13_600)
        self.assertEqual(units[0]["sentence_ids"], [0, 1, 2])
        self.assertIn("看成分", units[0]["text"])
        self.assertIn("看面料", units[0]["text"])
        self.assertIn("看做工", units[0]["text"])

    def test_short_merge_stops_at_large_gap_and_banned_boundary(self):
        sentences = [
            {"start": 0, "end": 500, "text": "这件很好，"},
            {"start": 1_000, "end": 1_500, "text": "间隔太远，"},
            {"start": 1_520, "end": 2_000, "text": "仓库拿货，"},
            {"start": 2_020, "end": 2_500, "text": "继续介绍。"},
        ]

        units = STEP4.build_speech_units(sentences)

        self.assertEqual(len(units), 4)
        self.assertTrue(STEP4.is_allowed_sentence(units[1]))
        self.assertFalse(STEP4.is_allowed_sentence(units[2]))
        self.assertTrue(STEP4.is_allowed_sentence(units[3]))

    def test_incomplete_and_duplicate_llm_output_is_completed_once(self):
        sentences = [
            {"start": 0, "end": 1_100, "text": "这件衣服很好看"},
            {"start": 1_200, "end": 2_300, "text": "随便聊两句"},
            {"start": 2_400, "end": 3_500, "text": "九十九块钱上链接"},
        ]

        completed = STEP4.complete_classifications(
            sentences,
            [(0, "爆点"), (0, "废话")],
        )

        self.assertEqual([idx for idx, _category in completed], [0, 1, 2])
        self.assertEqual(dict(completed)[0], "展示衣服")
        self.assertEqual(dict(completed)[2], "价格")

    def test_price_roles_survive_rebucket_and_same_sentence_is_not_duplicated(self):
        grouped = {
            "爆点": [0], "痛点": [], "展示衣服": [1],
            "金句": [], "价格": [2],
        }

        rebucketed, price_ids = STEP4.rebucket_price_roles(grouped, 2, 3)

        self.assertEqual(price_ids, {2, 3})
        self.assertEqual(rebucketed["原价"], [2])
        self.assertEqual(rebucketed["上车价"], [3])

        same, _ = STEP4.rebucket_price_roles(grouped, 2, 2)
        self.assertEqual(same["原价"], [])
        self.assertEqual(same["上车价"], [2])

    def test_short_edit_refills_with_allowed_source_speech_and_never_banned_text(self):
        sentences = [
            {"start": 0, "end": 4_000, "text": "这件衣服版型很好"},
            {"start": 4_100, "end": 8_100, "text": "今天准备得有点匆忙"},
            {"start": 8_200, "end": 12_200, "text": "姐妹们点一下关注"},
            {"start": 12_300, "end": 16_300, "text": "下一场再准备充分"},
            {"start": 16_400, "end": 30_400, "text": "仓库货源不能播"},
        ]
        classifications = [
            (0, "展示衣服"), (1, "废话"), (2, "废话"),
            (3, "废话"), (4, "废话"),
        ]
        core = [STEP4._sentence_segment(0, "展示衣服", sentences)]

        result, added = STEP4.fill_segments_to_min_duration(
            core, sentences, classifications
        )

        duration = sum(segment["src_dur_ms"] for segment in result)
        self.assertGreaterEqual(duration, STEP4.MIN_VIDEO_DURATION_MS)
        self.assertLessEqual(duration, STEP4.MAX_VIDEO_DURATION_MS)
        self.assertTrue(added)
        self.assertTrue(all(segment["source"] == "asr_filler" for segment in added))
        self.assertFalse(any("仓库" in segment["text"] for segment in result))

    def test_max_duration_drops_whole_units_without_truncating_source_ranges(self):
        segments = [
            {
                "category": "展示衣服",
                "source": "asr" if idx < 4 else "asr_filler",
                "src_start_ms": idx * 10_000,
                "src_end_ms": (idx + 1) * 10_000,
                "src_dur_ms": 10_000,
                "text": str(idx),
            }
            for idx in range(5)
        ]
        original_ranges = {
            (segment["src_start_ms"], segment["src_end_ms"])
            for segment in segments
        }

        limited = STEP4.limit_segments_to_max_duration(segments)

        self.assertEqual(sum(segment["src_dur_ms"] for segment in limited), 40_000)
        self.assertTrue(all(
            (segment["src_start_ms"], segment["src_end_ms"]) in original_ranges
            for segment in limited
        ))

    def test_duration_guard_restores_trimmed_edges_but_not_dropped_segments(self):
        segments = [
            {
                "src_start_ms": 100,
                "src_end_ms": 14_900,
                "src_dur_ms": 14_800,
                "original_src_start_ms": 0,
                "original_src_end_ms": 15_100,
                "silence_trimmed": True,
            }
        ]

        restored = STEP4.restore_trimmed_boundaries_for_duration(segments)

        self.assertEqual(restored, 1)
        self.assertEqual(segments[0]["src_start_ms"], 0)
        self.assertEqual(segments[0]["src_end_ms"], 15_100)
        self.assertNotIn("silence_trimmed", segments[0])
        self.assertTrue(segments[0]["silence_trim_reverted_for_duration"])

    def test_realistic_short_fragment_fixtures_reach_voiced_duration(self):
        fixtures = {
            "20": [
                (80, 520, "上的，"), (560, 2480, "200 320可以吗？"),
                (2640, 3040, "行不行。"), (3960, 4880, "30羊毛。"),
                (5080, 5760, "及时改了啊。"), (5920, 6920, "220上链接，"),
                (7360, 8080, "220块钱。"), (8520, 8760, "来，"),
                (8760, 9640, "今天就这样子吧，"), (9760, 10320, "来不及了，"),
                (10360, 10640, "姐们，"), (10760, 11520, "没有整理好，"),
                (11640, 12040, "可以吗？"), (12040, 12920, "今天就这么地了，"),
                (13280, 14200, "裙子在二号链接。"), (14400, 15200, "审核太慢了啊，"),
                (15400, 16120, "审核太慢了，"), (16120, 16760, "完全太慢了，"),
                (16800, 17720, "没有临时准备的，"), (17720, 18320, "没有准备好。"),
                (19220, 20700, "没点关注点下关注啊，"), (21340, 22740, "我们呢没有准备好，"),
                (23020, 24180, "下场给你们准备充足。"), (26180, 27020, "裙子二号链接，"),
                (27100, 28020, "325块钱，"), (28060, 30020, "我们家今天破价破的狠狠的啊。"),
            ],
            "27": [
                (2480, 3120, "来这个，"), (3320, 5840, "这个款号是2771170K，"),
                (6200, 7000, "159，"), (7120, 8280, "100 259的，"),
                (8360, 9480, "99块钱上链接。"), (9800, 10360, "九十九啊。"),
                (10600, 11160, "99啊，"), (11560, 12200, "看成分，"),
                (12240, 12760, "看面料，"), (12760, 13600, "看做工啊，"),
                (13800, 14520, "99块钱。"), (15570, 16370, "改成功了吗？"),
                (16970, 17450, "改成功了，"), (17530, 17770, "99。"),
                (17890, 18610, "六十件库存，"), (18650, 19530, "多一件都没有，"),
                (19850, 20450, "六十件库存。"),
            ],
            "39": [
                (120, 440, "块钱。"), (1280, 2760, "这个衣服是羊毛的，"),
                (2840, 4200, "这个以前是520的，"), (4440, 6160, "款号是90560G，"),
                (6320, 7400, "来120给大家，"), (8000, 9680, "120 120上链接。"),
                (9760, 10160, "一号链接，"), (10320, 11120, "120块钱。"),
                (11580, 12900, "骗你们是假的，"), (12980, 13820, "我真的改价格。"),
                (14260, 16660, "没有改价成功的姐们就算了，"),
                (16660, 17060, "可以吗？"), (17140, 17500, "因为我"),
            ],
        }

        for name, raw in fixtures.items():
            with self.subTest(name=name):
                sentences = [
                    {"start": start, "end": end, "text": text}
                    for start, end, text in raw
                ]
                units = STEP4.build_speech_units(sentences)
                classifications = STEP4.fallback_classify(units)
                core_idx = next(
                    (idx for idx, category in classifications if category != "废话"),
                    0,
                )
                core_category = dict(classifications)[core_idx]
                core = [STEP4._sentence_segment(core_idx, core_category, units)]
                result, _added = STEP4.fill_segments_to_min_duration(
                    core, units, classifications
                )
                duration = sum(segment["src_dur_ms"] for segment in result)
                self.assertGreaterEqual(duration, STEP4.MIN_VIDEO_DURATION_MS)
                self.assertLessEqual(duration, STEP4.MAX_VIDEO_DURATION_MS)
                self.assertFalse(any(segment["source"] == "mirror" for segment in result))
                if name == "27":
                    combined = "".join(unit["text"] for unit in units)
                    self.assertIn("看成分", combined)
                    self.assertIn("看面料", combined)
                    self.assertIn("看做工", combined)


class SilentFillGuardTests(unittest.TestCase):
    def test_orchestrator_accepts_continuous_voice_and_rejects_mirror_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            draft = {
                "duration": 15_000_000,
                "materials": {"audios": [{"id": "voice", "name": "clip_00_闲聊补位.mp3"}]},
                "tracks": [{
                    "type": "audio",
                    "segments": [{
                        "material_id": "voice",
                        "target_timerange": {"start": 0, "duration": 15_000_000},
                    }],
                }],
            }
            metadata = [{"source": "asr_filler", "src_dur_ms": 15_000}]
            policy = {"status": "OK", "silent_fill_allowed": False}
            (path / "draft_content.json").write_text(json.dumps(draft), encoding="utf-8")
            (path / "step4_segments.json").write_text(json.dumps(metadata), encoding="utf-8")
            (path / "duration_policy_report.json").write_text(json.dumps(policy), encoding="utf-8")

            realcut_hybrid._verify_voiced_duration_policy(path)

            metadata[0]["source"] = "mirror"
            (path / "step4_segments.json").write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "mirror"):
                realcut_hybrid._verify_voiced_duration_policy(path)

    def test_mirror_and_open_box_steps_do_not_mutate_the_draft(self):
        draft = {
            "duration": 16_000_000,
            "materials": {
                "audios": [{"id": "voice", "name": "clip_00.mp3"}],
                "videos": [{"id": "video", "name": "video_only.mp4"}],
            },
            "tracks": [
                {
                    "type": "audio",
                    "segments": [{
                        "material_id": "voice",
                        "target_timerange": {"start": 0, "duration": 16_000_000},
                    }],
                },
                {"type": "video", "segments": []},
            ],
        }
        metadata = [{
            "category": "闲聊补位",
            "source": "asr_filler",
            "src_start_ms": 0,
            "src_end_ms": 16_000,
            "src_dur_ms": 16_000,
            "text": "有声内容",
        }]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            draft_path = path / "draft_content.json"
            segment_path = path / "step4_segments.json"
            draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
            segment_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            before_draft = draft_path.read_bytes()
            before_segments = segment_path.read_bytes()
            before_files = sorted(item.name for item in path.iterdir())

            self.assertTrue(MIRROR.main(path))
            self.assertTrue(OPEN_BOX.main(path, auto_open=False))

            self.assertEqual(draft_path.read_bytes(), before_draft)
            self.assertEqual(segment_path.read_bytes(), before_segments)
            self.assertEqual(sorted(item.name for item in path.iterdir()), before_files)
            self.assertFalse(any(path.glob("mirror_fill_*.wav")))


if __name__ == "__main__":
    unittest.main()
