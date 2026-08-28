# -*- coding: utf-8 -*-
"""画面降重：对成品草稿的部分视频段做镜像/倒放，降低作品重复率。
用法: python de_dup.py <草稿路径> [--ratio 0.5] [--seed 42]
- 随机选 ratio 比例的视频段做水平镜像（flip.horizontal=true）
- 再随机选部分段做倒放（reverse=true）
- 默认不动第一段（保留开场稳定）
"""
import json, sys, os, random, io
from pathlib import Path
from _utils import write_draft, ensure_utf8_stdout

ensure_utf8_stdout()


def apply(dp_str, ratio=0.5, seed=42):
    dp = Path(dp_str)
    dc = dp / 'draft_content.json'
    if not dc.exists():
        print(f'草稿不存在: {dc}')
        return False

    draft = json.load(open(dc, encoding='utf-8'))
    rng = random.Random(seed)

    n_flip = 0
    n_reverse = 0
    total = 0
    for t in draft.get('tracks', []):
        if t['type'] != 'video':
            continue
        segs = t.get('segments', [])
        for i, s in enumerate(segs):
            total += 1
            if i == 0:
                continue  # 第一段保留稳定
            clip = s.get('clip', {})
            if rng.random() < ratio:
                clip.setdefault('flip', {})['horizontal'] = True
                n_flip += 1
            if rng.random() < ratio * 0.5:  # 倒放比例减半
                s['reverse'] = True
                n_reverse += 1

    # 三文件原子同步（写前关剪映 + 备份 + 原子写，由 write_draft 保证）
    write_draft(dp, draft)

    print(f'已降重: {total}个视频段中 {n_flip}段镜像 + {n_reverse}段倒放')
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    ratio = 0.5
    seed = 42
    if '--ratio' in sys.argv:
        ratio = float(sys.argv[sys.argv.index('--ratio') + 1])
    if '--seed' in sys.argv:
        seed = int(sys.argv[sys.argv.index('--seed') + 1])
    sys.exit(0 if apply(sys.argv[1], ratio, seed) else 1)
