from _utils import write_draft, rewrite_pkg_asset_paths
"""
步骤8：转场特效
- 保留草稿已有转场素材（用户添加的不覆盖）
- 按源跳变选2处添加转场
- 转场时长直接从素材的duration复制

用法: python "步骤8-转场特效.py" <草稿路径>
"""
import json, os, sys, uuid, shutil, random
from pathlib import Path

SCRIPT_DIR = Path(os.environ.get('REALCUT_SCRIPT_DATA_DIR', Path(__file__).parent))

def add_transitions(draft_path):
    dp = Path(draft_path)
    with open(dp / 'draft_content.json', 'r', encoding='utf-8') as f:
        draft = json.load(f)

    # ---------- 读取转场素材 ----------
    # 优先用草稿已有的转场（用户可能已添加其他效果）
    # 不够再从模板文件补充
    existing = draft['materials'].get('transitions', [])
    
    tmpl_path = SCRIPT_DIR / 'transitions_template.json'
    if tmpl_path.exists():
        with open(tmpl_path, 'r', encoding='utf-8') as f:
            tmpl = json.load(f)
    else:
        tmpl = {'transitions': []}
    
    # 强制用模板文件（用户最新添加的转场效果）
    if tmpl.get('transitions'):
        trans_mats = rewrite_pkg_asset_paths([dict(t) for t in tmpl['transitions']])
        for t in trans_mats:
            t['id'] = str(uuid.uuid4()).upper()
    else:
        trans_mats = [dict(t) for t in existing]
    
    draft['materials']['transitions'] = trans_mats
    
    if not trans_mats:
        print('无转场素材可用')
        return

    transition_duration_us = trans_mats[0]['duration']
    print(f'转场素材: {len(trans_mats)} 个, 时长: {transition_duration_us}us ({transition_duration_us/1000000:.2f}s)')

    # ---------- 选位：按源跳变选2处 ----------
    segs = [t['segments'] for t in draft['tracks'] if t['type'] == 'video'][0]
    if len(segs) < 2:
        print('视频段不足2个')
        return

    MIN_JUMP_US = 1000000        # 跳变 < 1s 不算不连续
    MIN_SEG_GAP = 0              # 至少隔1段才能加另一个转场
    MAX_TRANSITIONS = 2

    jumps = []
    for i in range(1, len(segs)):
        prev = segs[i - 1]['source_timerange']
        curr = segs[i]['source_timerange']
        prev_end = prev['start'] + prev['duration']
        jump = abs(curr['start'] - prev_end)
        target_pos = (segs[i - 1].get('target_timerange', {}) or {}).get('start', 0) + \
                     (segs[i - 1].get('target_timerange', {}) or {}).get('duration', 0)
        jumps.append({'seg_idx': i, 'jump_us': jump, 'target_pos_us': target_pos})

    # 筛掉 < 1s 的连续段，按跳幅降序
    valid = [j for j in jumps if j['jump_us'] >= MIN_JUMP_US]
    valid.sort(key=lambda j: j['jump_us'], reverse=True)

    selected = []
    for j in valid:
        if len(selected) >= MAX_TRANSITIONS:
            break
        # 检查是否与已选转场在连续段上（不能一和二加了二和三也加）
        too_close = any(abs(j['seg_idx'] - s['seg_idx']) <= MIN_SEG_GAP for s in selected)
        if not too_close:
            selected.append(j)

    # ---------- 加转场 ----------
    added = 0
    for j in selected:
        ti = random.randint(0, len(trans_mats) - 1)
        tm = trans_mats[ti]
        i = j['seg_idx']

        # 转场挂在 extra_material_refs 上（剪映实际机制，不用 transition 字段）
        refs = segs[i - 1].get('extra_material_refs', [])
        if not isinstance(refs, list):
            refs = []
        if tm['id'] not in refs:
            refs.append(tm['id'])
        segs[i - 1]['extra_material_refs'] = refs

        print(f'  seg[{i-1}]->seg[{i}]: +{tm.get("name","?" )} (跳幅{j["jump_us"]/1000000:.1f}s)')
        added += 1

    # ---------- 保存 ----------
    write_draft(dp, draft)

    print(f'\n添加了 {added} 处转场 (最多{MAX_TRANSITIONS}处)')

if __name__ == '__main__':
    add_transitions(sys.argv[1])
