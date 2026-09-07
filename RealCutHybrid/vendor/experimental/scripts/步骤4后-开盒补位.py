# -*- coding: utf-8 -*-
"""Legacy open-box compatibility step.

Open-box video must never extend a timeline without matching source speech.
Step 4 now refills short edits from all allowed ASR units, including useful
open-box chatter when selected. Step 6 then assigns picture to that audio.
"""

import json
import sys
from pathlib import Path


def main(dp_str, auto_open=True):
    dp = Path(dp_str)
    seg_path = dp / 'step4_segments.json'
    draft_path = dp / 'draft_content.json'
    if not seg_path.exists():
        print('[跳过] step4_segments.json 不存在，请先执行步骤4')
        return False
    if not draft_path.exists():
        print('[跳过] draft_content.json 不存在')
        return False

    with open(seg_path, 'r', encoding='utf-8') as handle:
        segments = json.load(handle)
    with open(draft_path, 'r', encoding='utf-8') as handle:
        draft = json.load(handle)

    duration_us = int(draft.get('duration', 0) or 0)
    print(
        '[跳过] 无声开盒补位已禁用：没有配套原声的画面不得插入或延长时间线'
    )
    print(
        f'       保持 {len(segments)} 个有声单元和 '
        f'{duration_us / 1000000:.1f}s 草稿时长不变'
    )
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    auto_open = '--no-open' not in sys.argv
    sys.exit(0 if main(sys.argv[1], auto_open=auto_open) else 1)
