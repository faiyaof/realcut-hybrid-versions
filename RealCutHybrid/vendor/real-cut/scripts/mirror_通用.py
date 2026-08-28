# -*- coding: utf-8 -*-
"""Mirror/reverse clothing fill.

When the source has fewer than 3 clothing segments, add extra video-only
segments made from the source clothing range. The added picture never uses
the original source audio; added audio comes from the sound library only.
"""

import json
import os
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from _utils import write_draft, uid

CLIP_LIB = r'C:\Users\JT\Documents\剪辑\爆点+金句 素材库\爆点素材库\素材库\_audio'
MAX_VIDEO_DURATION_MS = 30000  # 成片最长不超过30秒
FORCE_FILL_MS = 6000  # 强制补位时每条镜像/倒放片段预留的最大音轨时长


def get_duration_ms(fp):
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', fp],
            capture_output=True, text=True, timeout=10,
        )
        return int(float(r.stdout.strip()) * 1000) if r.stdout.strip() else 0
    except Exception:
        return 0


def pick_audio(exclude=None, max_dur_ms=None):
    """Pick a short library audio file, avoiding repeated sources and overruns."""
    exclude = set(exclude or [])
    candidates = [
        CLIP_LIB,
        r'C:\Users\JT\Documents\剪辑\爆点+金句 素材库\金句',
        r'C:\Users\JT\Documents\剪辑\爆点+金句 素材库\爆点',
    ]
    all_files = []
    for lib in candidates:
        if not os.path.isdir(lib):
            continue
        for f in os.listdir(lib):
            fp = os.path.join(lib, f)
            if not f.endswith('.mp3'):
                continue
            key = os.path.normcase(os.path.abspath(fp))
            if key in exclude:
                continue
            all_files.append(fp)
    if not all_files:
        return None
    short_files = sorted(all_files, key=get_duration_ms)
    if max_dur_ms is not None:
        short_files = [f for f in short_files if get_duration_ms(f) <= max_dur_ms]
        if not short_files:
            return None
    preferred = [f for f in short_files if 1500 <= get_duration_ms(f) <= 5000]
    if preferred:
        return preferred[0]
    return short_files[0]


def main(dp_str, force=False, use_reverse=True):
    dp = Path(dp_str)
    seg_path = dp / 'step4_segments.json'
    dc_path = dp / 'draft_content.json'

    if not seg_path.exists():
        print('[skip] step4_segments.json not found')
        return
    if not dc_path.exists():
        print('[skip] draft_content.json not found')
        return

    with open(seg_path, 'r', encoding='utf-8') as f:
        segs = json.load(f)
    with open(dc_path, 'r', encoding='utf-8') as f:
        draft = json.load(f)

    clothes_segs = [
        (i, s) for i, s in enumerate(segs)
        if s.get('category') == '展示衣服'
    ]
    n_clothes = len(clothes_segs)
    print(f'clothing segments: {n_clothes}')

    if n_clothes >= 3 and not force:
        print('>= 3 segments, no fill needed')
        return

    need = 3 - n_clothes
    if force:
        need = max(need, 3)
    print(f'need to add {need} segments')

    # Source ranges for mirror/reverse clips. Prefer clothing segments.
    source_segs = clothes_segs
    if not source_segs:
        source_segs = [
            (i, s) for i, s in enumerate(segs)
            if s.get('category') not in ('金句', '价格')
        ]
    if not source_segs and segs:
        source_segs = [(0, segs[0])]
    if not source_segs:
        print('[error] no usable source range for fill')
        return

    video_track = None
    audio_track = None
    for t in draft['tracks']:
        if t['type'] == 'video':
            video_track = t
        if t['type'] == 'audio':
            audio_track = t
    if not video_track or not audio_track:
        print('[error] video/audio track not found')
        return
    # 非强制模式保留30秒成片上限；强制补位时以补充足额服装画面为主。
    audio_segs = audio_track['segments']
    current_total_us = int(draft.get('duration', 0))
    if current_total_us <= 0 and audio_segs:
        last = audio_segs[-1]['target_timerange']
        current_total_us = int(last.get('start', 0)) + int(last.get('duration', 0))
    max_total_us = MAX_VIDEO_DURATION_MS * 1000
    if force:
        max_total_us = max(max_total_us, current_total_us + need * FORCE_FILL_MS * 1000)
    remaining_us = max(0, max_total_us - current_total_us)
    print(f'current duration: {current_total_us / 1e6:.1f}s, remaining budget: {remaining_us / 1e6:.1f}s')
    if remaining_us < 500000 and not force:
        print('[skip] timeline already at or near 30s, no mirror fill')
        return

    # Main video material path.
    main_vid = draft['materials']['videos'][0]
    main_vid_id = main_vid['id']
    video_path = os.path.join(str(dp), 'video_only.mp4')
    if not os.path.exists(video_path):
        for v in draft['materials']['videos']:
            p = v.get('path', '')
            if p and os.path.exists(p):
                video_path = p
                break
    print(f'main video: {video_path}')

    if clothes_segs:
        insert_audio_idx = clothes_segs[-1][0] + 1
    else:
        insert_audio_idx = next(
            (i for i, s in enumerate(segs)
             if s.get('category') in ('金句', '价格')),
            len(segs),
        )

    insert_time_us = 0
    for i in range(insert_audio_idx):
        if i < len(audio_segs):
            seg = audio_segs[i]
            insert_time_us = (
                seg['target_timerange']['start']
                + seg['target_timerange']['duration']
            )
    print(
        f'insert after segment {insert_audio_idx}, '
        f'target_time={insert_time_us / 1e6:.1f}s'
    )

    clothes_src_area = []
    for _idx, s in source_segs:
        src_s = s.get('src_start_ms', 0) * 1000
        src_e = s.get('src_end_ms', 0) * 1000
        clothes_src_area.append((src_s, src_e))

    insert_offset = 0
    new_seg_metas = []
    mirror_info = []

    used_audio = set()
    for i in range(need):
        remaining_ms = max(1, int(remaining_us // 1000))
        audio_src = pick_audio(exclude=used_audio, max_dur_ms=remaining_ms)
        if not audio_src:
            print('[warn] no audio material found, fill stopped')
            break
        used_audio.add(os.path.normcase(os.path.abspath(audio_src)))
        audio_dur_ms = get_duration_ms(audio_src)
        if audio_dur_ms <= 0:
            print('[warn] invalid audio duration, fill stopped')
            break
        audio_dur_us = min(max(audio_dur_ms * 1000, 500000), remaining_us)
        print(
            f'  audio{i + 1}: {os.path.basename(audio_src)} '
            f'({audio_dur_us / 1e6:.1f}s) [library audio only]'
        )

        audio_name = f'mirror_fill_{uuid.uuid4().hex[:8]}.mp3'
        shutil.copy2(audio_src, os.path.join(str(dp), audio_name))
        audio_mat_id = uid()
        draft['materials']['audios'].append({
            'id': audio_mat_id,
            'duration': audio_dur_us,
            'name': audio_name,
            'path': os.path.join(str(dp), audio_name),
            'type': 'sound',
        })

        src_start_us = clothes_src_area[i % len(clothes_src_area)][0]
        src_start_s = src_start_us / 1e6
        clip_name = f'mirror_fill_{uuid.uuid4().hex[:8]}.mp4'
        clip_path = os.path.join(str(dp), clip_name)

        mode = i % 3
        vf = ['hflip', 'reverse', 'hflip,reverse'][mode] if use_reverse else 'hflip'
        mode_name = ['mirror', 'reverse', 'mirror+reverse'][mode] if use_reverse else 'mirror'
        cmd = [
            'ffmpeg', '-y',
            '-ss', str(src_start_s),
            '-i', video_path,
            '-t', str(audio_dur_us / 1e6),
            '-vf', vf,
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '23',
            '-an',
            clip_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print('[warn] ffmpeg failed for fill clip')
            print(result.stderr[-500:] if result.stderr else '')

        actual_dur_us = get_duration_ms(clip_path) * 1000
        if actual_dur_us < 100000:
            actual_dur_us = audio_dur_us
        actual_dur_us = min(actual_dur_us, audio_dur_us)
        draft['materials']['audios'][-1]['duration'] = actual_dur_us
        print(
            f'  {mode_name} {i + 1}: {clip_name} '
            f'({actual_dur_us / 1e6:.1f}s) [video only]'
        )

        mirror_vid_id = uid()
        draft['materials']['videos'].append({
            'id': mirror_vid_id,
            'duration': actual_dur_us,
            'name': clip_name,
            'path': clip_path,
            'type': 'video',
        })

        insert_pos_us = insert_time_us + insert_offset
        new_audio_seg = {
            'id': uid(),
            'material_id': audio_mat_id,
            'target_timerange': {'duration': actual_dur_us, 'start': insert_pos_us},
            'source_timerange': {'duration': actual_dur_us, 'start': 0},
            'speed': 1,
            'volume': 1,
            'visible': True,
            'extra_material_refs': [],
        }
        insert_audio_idx2 = insert_audio_idx + i
        audio_segs.insert(insert_audio_idx2, new_audio_seg)

        mirror_info.append((insert_pos_us, mirror_vid_id, actual_dur_us))

        shift_us = actual_dur_us
        for j in range(insert_audio_idx2 + 1, len(audio_segs)):
            tt = audio_segs[j]['target_timerange']
            tt['start'] += shift_us

        insert_offset += shift_us

        new_seg_metas.append({
            'src_start_ms': int(src_start_us / 1000),
            'src_end_ms': int((src_start_us + actual_dur_us) / 1000),
            'src_dur_ms': int(actual_dur_us / 1000),
            'category': '展示衣服',
            'source': 'mirror',
            'text': '[镜像补位]',
        })

        remaining_us = max(0, remaining_us - actual_dur_us)
        if remaining_us < 500000 and not force:
            print('[info] 30s cap reached, stop mirror fill')
            break
    if not new_seg_metas:
        print('[skip] could not add any fill segments')
        return

    # Rebuild video track so every audio segment has a matching video segment.
    mirror_positions = {p: (vid_id, dur) for p, vid_id, dur in mirror_info}
    new_video_segs = []
    t = 0
    orig_idx = 0

    for as_ in audio_segs:
        dur = as_['target_timerange']['duration']
        start = as_['target_timerange']['start']
        if start in mirror_positions:
            vid_id, _ = mirror_positions[start]
            new_video_segs.append({
                'id': uid(),
                'material_id': vid_id,
                'target_timerange': {'duration': dur, 'start': t},
                'source_timerange': {'duration': dur, 'start': 0},
                'speed': 1,
                'volume': 1,
                'visible': True,
                'extra_material_refs': [],
            })
        else:
            src_start = 0
            if orig_idx < len(segs):
                src_start = segs[orig_idx].get('src_start_ms', 0) * 1000
            new_video_segs.append({
                'id': uid(),
                'material_id': main_vid_id,
                'target_timerange': {'duration': dur, 'start': t},
                'source_timerange': {'duration': dur, 'start': src_start},
                'speed': 1,
                'volume': 1,
                'visible': True,
                'extra_material_refs': [],
            })
            orig_idx += 1
        t += dur

    video_track['segments'] = new_video_segs
    draft['duration'] = t

    for i, meta in enumerate(new_seg_metas):
        segs.insert(insert_audio_idx + i, meta)

    with open(seg_path, 'w', encoding='utf-8') as f:
        json.dump(segs, f, ensure_ascii=False, indent=2)

    write_draft(dp, draft)

    print('\n=== mirror fill complete ===')
    print(f'added {len(new_seg_metas)} segments (video only + library audio)')
    print(f'total duration: {t / 1e6:.1f}s')
    print(
        f'clothing segments: {n_clothes} -> '
        f'{n_clothes + len(new_seg_metas)}'
    )
    print(
        f'video segments: {len(new_video_segs)} '
        f'(one-to-one with audio segments)'
    )


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    force = '--force' in sys.argv
    use_reverse = '--reverse' in sys.argv
    main(sys.argv[1], force=force, use_reverse=use_reverse)
