# -*- coding: utf-8 -*-
"""
_video_assign.py - F1 画面分配公共逻辑

规则：
1. 只从纯展示区间取画面，开盒/剪标签/其他商品画面不进成片
2. 相邻两个视频段不能使用重叠的源区间（防止同一画面紧挨着露出破绽）
3. 同一源区间最多使用 2 次，第 2 次自动水平镜像
4. 优先保留原位置，原位置不可用时自动重定向
"""

import json
import os
from pathlib import Path

from _utils import write_draft


def classify_action(action):
    if not action:
        return 'other'
    if ('开盒' in action or '打盒' in action or '拿衣服' in action):
        return 'opening'
    if ('剪标签' in action or '剪吊牌' in action or '撕标签' in action):
        return 'tagcut'
    if ('展示' in action or '举' in action or 'display' in action.lower()):
        return 'display'
    if ('丢掉' in action or '放下' in action or '丢' in action or '空手' in action):
        return 'closing'
    return 'other'


def build_display_blocks(frame_actions, video_file_dur_us):
    """从 1s 帧缓存构建连续纯展示区间（微秒）。"""
    keys = sorted([
        int(k) for k, v in frame_actions.items()
        if classify_action(v) == 'display' and (int(k) + 1000) * 1000 <= video_file_dur_us
    ])
    if not keys:
        return []
    blocks = []
    start = keys[0]
    end = start + 1000
    for k in keys[1:]:
        if k == end:
            end = k + 1000
        else:
            blocks.append([start * 1000, end * 1000])
            start = k
            end = k + 1000
    blocks.append([start * 1000, end * 1000])
    return blocks


def _overlaps(a, b):
    return a[0] < b[0] + b[1] and b[0] < a[0] + a[1]


def assign_video_sources(asegs, seg_meta, frame_actions, video_file_dur_us):
    """
    返回与音频段一一对应的 [(src_start_us, flip_h), ...]

    分配顺序按段时长从大到小，优先占满大块展示区，避免长金句段无处安放。
    """
    n = len(asegs)
    blocks = build_display_blocks(frame_actions, video_file_dur_us)
    if not blocks:
        print('  [WARN] 未找到纯展示区间，回退原位置')
        return [(int(seg_meta[i].get('src_start_ms', 0)) * 1000, False) for i in range(n)]

    layers = {bi: [[], []] for bi in range(len(blocks))}
    placements = [None] * n
    order = sorted(range(n), key=lambda i: -asegs[i]['target_timerange']['duration'])

    for idx in order:
        dur = asegs[idx]['target_timerange']['duration']
        orig = int(seg_meta[idx].get('src_start_ms', 0)) * 1000 if idx < len(seg_meta) else 0
        candidates = []

        # 原位置优先
        for bi, block in enumerate(blocks):
            if block[0] <= orig and orig + dur <= block[1]:
                for layer in (0, 1):
                    if all(not _overlaps((orig, dur), iv) for iv in layers[bi][layer]):
                        if not _conflicts_with_neighbors(idx, n, placements, orig, dur):
                            candidates.append((0, 0, bi, layer, orig))

        # 扫描可用起点（100ms 粒度）
        for bi, block in enumerate(blocks):
            if dur > block[1] - block[0]:
                continue
            max_start = block[1] - dur
            for layer in (0, 1):
                for st in range(block[0], max_start + 1, 100000):
                    if all(not _overlaps((st, dur), iv) for iv in layers[bi][layer]):
                        if _conflicts_with_neighbors(idx, n, placements, st, dur):
                            continue
                        score = layer * 1000000 + abs(st - orig) // 1000 + bi * 10000
                        candidates.append((score, bi, layer, st))

        if not candidates:
            # 放宽相邻段不重叠约束，仍只从纯展示区取画面。
            for bi, block in enumerate(blocks):
                if dur > block[1] - block[0]:
                    continue
                max_start = block[1] - dur
                for layer in (0, 1):
                    for st in range(block[0], max_start + 1, 100000):
                        if all(not _overlaps((st, dur), iv) for iv in layers[bi][layer]):
                            score = 1000000000 + layer * 1000000 + abs(st - orig) // 1000 + bi * 10000
                            candidates.append((score, bi, layer, st))
        if not candidates:
            # 最后兜底：允许使用原时间位置，保证步骤6不中断。
            if orig + dur <= video_file_dur_us:
                candidates.append((2000000000, 0, 0, orig))
            else:
                st = max(0, video_file_dur_us - dur)
                candidates.append((2000000000, 0, 0, st))

        first = candidates[0]
        if len(first) == 5:
            _, _, bi, layer, st = first
        else:
            _, bi, layer, st = min(candidates)

        flip = any(_overlaps((st, dur), iv) for b_layers in layers.values()
                   for iv in b_layers[0] + b_layers[1])
        placements[idx] = (st, dur, bi, layer, flip)
        layers[bi][layer].append((st, dur))

    return [(p[0], p[4]) for p in placements]


def _conflicts_with_neighbors(idx, n, placements, st, dur):
    for nj in (idx - 1, idx + 1):
        if 0 <= nj < n and placements[nj] is not None:
            if _overlaps((st, dur), (placements[nj][0], placements[nj][1])):
                return True
    return False


def reassign_draft_sources(draft_path):
    """对已生成步骤4/6的草稿直接执行画面分配修复。"""
    dp = Path(draft_path)
    dc_path = dp / 'draft_content.json'
    meta_path = dp / 'step4_segments.json'
    cache_path = dp / '_frame_full_cache_1s.json'
    if not cache_path.exists():
        old_cache = dp / '_frame_full_cache.json'
        if old_cache.exists():
            raise RuntimeError('检测到旧0.5s缓存，请先重跑步骤6生成1s缓存')
        raise FileNotFoundError('未找到1s画面缓存 _frame_full_cache_1s.json')

    with open(dc_path, encoding='utf-8') as f:
        draft = json.load(f)
    with open(meta_path, encoding='utf-8') as f:
        seg_meta = json.load(f)
    with open(cache_path, encoding='utf-8') as f:
        frame_actions = json.load(f)

    src_video = None
    for fname in os.listdir(dp):
        fpl = fname.lower()
        if fpl.endswith(('.mp4', '.mkv', '.mov')) and fpl != 'video_only.mp4':
            fp = os.path.join(dp, fname)
            if os.path.isfile(fp) and os.path.getsize(fp) > 1024:
                src_video = fp
                break
    if not src_video:
        raise RuntimeError('未找到源视频')

    import subprocess
    r = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'csv=p=0', src_video],
        capture_output=True, text=True
    )
    try:
        video_file_dur_us = int(float(r.stdout.strip()) * 1e6)
    except Exception:
        video_file_dur_us = (max(int(k) for k in frame_actions) + 1000) * 1000

    audio_track = next(t for t in draft['tracks'] if t['type'] == 'audio')
    asegs = audio_track['segments']
    sources = assign_video_sources(asegs, seg_meta, frame_actions, video_file_dur_us)

    video_id = draft['materials']['videos'][0]['id']
    video_segs = []
    target_start = 0
    for i, seg in enumerate(asegs):
        audio_dur = seg['target_timerange']['duration']
        src_start, flip_h = sources[i]
        video_segs.append({
            "caption_info": None, "cartoon": None,
            "clip": {"alpha": 1, "flip": {"horizontal": flip_h, "vertical": False},
                     "rotation": 0, "scale": {"x": 1, "y": 1}, "transform": {"x": 0, "y": 0}},
            "common_keyframes": [], "enable_adjust": False,
            "enable_color_correct_adjust": False, "enable_color_curves": False,
            "enable_color_match_adjust": False, "enable_color_wheels": False,
            "enable_lut": False, "enable_smart_color_adjust": False,
            "extra_material_refs": [], "group_id": "", "hdr_settings": "",
            "id": str(__import__('uuid').uuid4()).upper(),
            "intensifies_audio": None, "is_placeholder": False,
            "is_tone_modify": False, "keyframe_refs": [],
            "last_nonzero_volume": 1, "material_id": video_id,
            "render_index": 0, "responsive_layout": 0, "reverse": False,
            "source_timerange": {"duration": audio_dur, "start": src_start},
            "speed": 1.0,
            "target_timerange": {"duration": audio_dur, "start": target_start},
            "template_id": "", "template_scene": "",
            "track_attribute": 1, "track_render_index": 0,
            "uniform_scale": 1, "visible": True, "volume": 1
        })
        target_start += audio_dur

    draft['tracks'][0]['segments'] = video_segs
    draft['duration'] = target_start
    write_draft(dp, draft)
    return len(video_segs)
