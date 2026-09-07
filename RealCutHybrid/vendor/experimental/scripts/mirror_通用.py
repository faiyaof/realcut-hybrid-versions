# -*- coding: utf-8 -*-
"""Legacy mirror compatibility step.

Duration completion now happens in step 4 with unused source speech. This
step deliberately does not create audio, insert timeline segments, or extend
the draft. Visual matching in step 6 supplies picture for every voiced unit.
"""

import json
import sys
from pathlib import Path


def main(dp_str, force=False, use_reverse=True):
    dp = Path(dp_str)
    seg_path = dp / 'step4_segments.json'
    draft_path = dp / 'draft_content.json'
    if not seg_path.exists():
        print('[skip] step4_segments.json not found')
        return False
    if not draft_path.exists():
        print('[skip] draft_content.json not found')
        return False

    with open(seg_path, 'r', encoding='utf-8') as handle:
        segments = json.load(handle)
    with open(draft_path, 'r', encoding='utf-8') as handle:
        draft = json.load(handle)

    duration_us = int(draft.get('duration', 0) or 0)
    voiced_units = sum(
        1 for segment in segments
        if segment.get('source') in ('asr', 'asr_filler')
    )
    print(
        '[skip] 静音镜像补位已禁用：步骤4只用原视频口播补足15-45秒，'
        '镜像步骤不得创建音频或延长时间线'
    )
    print(
        f'       当前 {voiced_units} 个有声单元，'
        f'草稿时长 {duration_us / 1000000:.1f}s；画面由步骤6匹配'
    )
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    force = '--force' in sys.argv
    use_reverse = '--reverse' in sys.argv
    sys.exit(0 if main(sys.argv[1], force=force, use_reverse=use_reverse) else 1)
