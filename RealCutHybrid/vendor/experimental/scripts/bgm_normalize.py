# -*- coding: utf-8 -*-
"""实验版 BGM 平滑：模板 BGM 固定为 -20dB，加 300ms 首尾淡入淡出。

用法: python bgm_normalize.py <草稿路径>
"""
import argparse
import sys
from pathlib import Path

from _utils import ensure_utf8_stdout, read_draft, uid, write_draft

ensure_utf8_stdout()

TARGET_DB = -20.0
TARGET_VOLUME = 10 ** (TARGET_DB / 20.0)  # 0.1
FADE_MS = 300


def find_bgm_segments(draft):
    mats = {m['id']: m for m in draft.get('materials', {}).get('audios', []) + draft.get('materials', {}).get('music', [])}
    hits = []
    for tr in draft.get('tracks', []):
        if tr.get('type') != 'audio':
            continue
        for seg in tr.get('segments', []) or []:
            mat = mats.get(seg.get('material_id', ''))
            if mat and mat.get('type') == 'music':
                hits.append((tr, seg, mat))
    return hits


def normalize_bgm(dp_str):
    dp = Path(dp_str)
    draft = read_draft(dp)
    hits = find_bgm_segments(draft)
    if not hits:
        print('未找到 BGM，跳过')
        return True
    fade_id = uid()
    fade = {
        'fade_in_duration': FADE_MS * 1000,
        'fade_out_duration': FADE_MS * 1000,
        'fade_type': 0,
        'id': fade_id,
        'type': 'audio_fade',
    }
    fades = draft.setdefault('materials', {}).setdefault('audio_fades', [])
    fades.append(fade)
    for tr, seg, mat in hits:
        seg['volume'] = TARGET_VOLUME
        seg['last_nonzero_volume'] = TARGET_VOLUME
        mat['volume'] = TARGET_VOLUME
        refs = [r for r in seg.get('extra_material_refs', []) or [] if not _is_audio_fade_ref(draft, r)]
        refs.append(fade_id)
        seg['extra_material_refs'] = refs
    write_draft(dp, draft)
    print(f'BGM 已归一化：{TARGET_DB}dB（{TARGET_VOLUME:.4f}），淡入淡出 {FADE_MS}ms')
    return True


def _is_audio_fade_ref(draft, ref_id):
    for m in draft.get('materials', {}).get('audio_fades', []):
        if m.get('id') == ref_id:
            return True
    return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='实验版 BGM 音量与淡入淡出')
    parser.add_argument('draft', help='草稿路径')
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    sys.exit(0 if normalize_bgm(args.draft) else 1)
