# -*- coding: utf-8 -*-
"""实验版字幕空隙补齐：让动态字幕从 0 到草稿结尾连续覆盖。

只处理动态字幕轨 flag=1 的 subtitle 素材，不修改 flag=0 的风格固定文字/贴纸。
用法: python fill_subtitle_gaps.py <草稿路径> [--no-open]
"""
import argparse
import json
import sys
from pathlib import Path

from _utils import ensure_utf8_stdout, read_draft, write_draft

ensure_utf8_stdout()


def dynamic_subtitle_ids(draft):
    ids = set()
    for tr in draft.get('tracks', []) or []:
        if tr.get('type') != 'text' or tr.get('flag') != 1:
            continue
        for seg in tr.get('segments', []) or []:
            if seg.get('material_id'):
                ids.add(seg['material_id'])
    mats = {
        m.get('id')
        for m in draft.get('materials', {}).get('texts', []) or []
        if isinstance(m, dict) and m.get('type') == 'subtitle' and m.get('id')
    }
    return ids & mats


def collect_segments(draft, sub_ids):
    items = []
    for ti, track in enumerate(draft.get('tracks', []) or []):
        if track.get('type') != 'text' or track.get('flag') != 1:
            continue
        for si, seg in enumerate(track.get('segments', []) or []):
            if not isinstance(seg, dict) or seg.get('material_id') not in sub_ids:
                continue
            trange = seg.get('target_timerange', {}) or {}
            start = int(trange.get('start', 0) or 0)
            duration = max(1, int(trange.get('duration', 0) or 1))
            items.append({
                'track_idx': ti,
                'seg_idx': si,
                'segment': seg,
                'start': start,
                'duration': duration,
                'end': start + duration,
            })
    return items


def flatten_timeline(items, total_duration):
    ordered = sorted(items, key=lambda x: (x['start'], x['track_idx'], x['seg_idx']))
    new_starts = []
    new_durations = []
    for idx, item in enumerate(ordered):
        if idx == 0:
            start = 0
        else:
            start = max(item['start'], new_starts[-1] + new_durations[-1])
        new_starts.append(start)
        new_durations.append(item['duration'])
        if idx > 0:
            new_durations[idx - 1] = start - new_starts[idx - 1]
    new_durations[-1] = max(1, total_duration - new_starts[-1])
    return ordered, new_starts, new_durations


def before_gaps(ordered):
    gaps = []
    if len(ordered) < 2:
        return gaps
    prev = ordered[0]
    if prev['start'] > 0:
        gaps.append({'start': 0, 'end': prev['start']})
    for item in ordered[1:]:
        gap_start = prev['end']
        if item['start'] > gap_start:
            gaps.append({'start': gap_start, 'end': item['start']})
        prev = item
    return gaps


def fill_subtitle_gaps(dp_str):
    dp = Path(dp_str).resolve()
    draft = read_draft(dp)
    total_duration = int(draft.get('duration', 0) or 0)
    if total_duration <= 0:
        raise RuntimeError(f'草稿 duration 无效: {dp}')

    sub_ids = dynamic_subtitle_ids(draft)
    items = collect_segments(draft, sub_ids)
    if not items:
        report = {
            'status': 'NO_SUBTITLES',
            'changes': 0,
            'segments': 0,
            'total_duration_us': total_duration,
            'message': '未找到动态字幕素材，跳过补缝',
        }
        (dp / 'subtitle_gaps_report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        print('未找到动态字幕素材，跳过补缝')
        return True

    gaps = before_gaps(items)
    ordered, new_starts, new_durations = flatten_timeline(items, total_duration)

    changes = []
    for item, start, duration in zip(ordered, new_starts, new_durations):
        trange = item['segment'].setdefault('target_timerange', {})
        old_start = int(trange.get('start', 0) or 0)
        old_duration = int(trange.get('duration', 0) or 1)
        if old_start != start or old_duration != duration:
            trange['start'] = start
            trange['duration'] = duration
            changes.append({
                'material_id': item['segment'].get('material_id'),
                'track_idx': item['track_idx'],
                'seg_idx': item['seg_idx'],
                'old_start_us': old_start,
                'old_duration_us': old_duration,
                'new_start_us': start,
                'new_duration_us': duration,
            })

    if changes:
        write_draft(dp, draft)

    report = {
        'status': 'OK',
        'changes': len(changes),
        'segments': len(ordered),
        'total_duration_us': total_duration,
        'gaps_before_us': gaps,
        'changed_segments': changes,
    }
    (dp / 'subtitle_gaps_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'字幕空隙补齐完成：{len(ordered)} 段，修改 {len(changes)} 段，覆盖 0 -> {total_duration / 1000000:.3f}s')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='实验版动态字幕空隙补齐')
    parser.add_argument('draft', help='草稿路径')
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    sys.exit(0 if fill_subtitle_gaps(args.draft) else 1)
