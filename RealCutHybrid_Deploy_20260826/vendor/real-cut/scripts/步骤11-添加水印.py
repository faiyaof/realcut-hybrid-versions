from _utils import write_draft, resolve_template_dir, ensure_utf8_stdout
"""
步骤11：添加水印 — 从字体特效草稿复制两个水印文字
用法: python "步骤11-添加水印.py" "<草稿路径>"

效果:
  - 添加两个水印：
    - boss姐 / 165 / 110 / S码（左下）
    - BOSS姐奢品 / VAZSLVE（右下）
  - 水印时长 = 切割后的音频/画面时长（不是原视频全长）
  - 从模板草稿复制水印文字素材和轨道样式
前提: 需已完成步骤10
"""

import json, sys, uuid, shutil, copy, io
from pathlib import Path

ensure_utf8_stdout()

# 水印功能已暂时关闭，如需启用请注释掉下面这行
print("步骤11 水印已关闭，跳过")
if len(sys.argv) < 2 or "--force" not in sys.argv:
    sys.exit(0)

# 模板草稿：优先用当前风格模板，找不到回退 com.lveditor.draft/草稿
TEMPLATE, _tmpl_name = resolve_template_dir()
if TEMPLATE is None:
    TEMPLATE = Path(r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\草稿')
print(f'水印 使用模板: {TEMPLATE}')

# 模板中水印所在的轨道索引（草稿模板的 track[2] 和 track[3]）
WATERMARK_TRACK_INDICES = [2, 3]


def uid():
    return str(uuid.uuid4()).upper()


def get_timeline_duration(draft):
    """计算实际时间线总长（仅视频/主音频轨道，不含BGM/音效）"""
    max_end = 0
    for t in draft.get('tracks', []):
        # 跳过BGM轨道（单段长音频且非音效）
        if t['type'] == 'audio' and len(t.get('segments', [])) == 1 and t.get('name', '') != '__sfx__':
            continue
        if t.get('name', '') == '__sfx__':
            continue
        for seg in t.get('segments', []):
            tr = seg.get('target_timerange', {})
            end = tr.get('start', 0) + tr.get('duration', 0)
            if end > max_end:
                max_end = end
    return max_end


def add_watermark(draft_path):
    dp = Path(draft_path)
    if not (dp / 'draft_content.json').exists():
        print(f'错误: 草稿目录不存在 {dp}')
        return False

    # 读取目标草稿
    with open(dp / 'draft_content.json', 'r', encoding='utf-8') as f:
        draft = json.load(f)

    # 读取模板草稿
    with open(TEMPLATE / 'draft_content.json', 'r', encoding='utf-8') as f:
        tmpl = json.load(f)

    # ── 计算有效时长 ──
    total_dur = get_timeline_duration(draft)
    print(f'有效时间线总长: {total_dur / 1000000:.1f}s')

    # ── 清理旧水印轨道（attr=2 的 text 轨道） ──
    removed_count = 0
    removed_mat_ids = set()
    new_tracks = []
    for t in draft['tracks']:
        if t['type'] == 'text' and t.get('attribute', 0) == 2:
            for seg in t.get('segments', []):
                removed_mat_ids.add(seg.get('material_id', ''))
            removed_count += 1
        else:
            new_tracks.append(t)
    draft['tracks'] = new_tracks
    if removed_count:
        print(f'已清理 {removed_count} 条旧水印轨道')

    # ── 从模板复制水印素材和轨道 ──
    new_mat_ids = {}
    for ti in WATERMARK_TRACK_INDICES:
        tmpl_track = tmpl['tracks'][ti]
        tmpl_seg = tmpl_track['segments'][0]
        tmpl_mat_id = tmpl_seg['material_id']

        # 查找模板中的水印文字素材
        tmpl_mat = None
        for tx in tmpl['materials']['texts']:
            if tx['id'] == tmpl_mat_id:
                tmpl_mat = copy.deepcopy(tx)
                break
        if tmpl_mat is None:
            print(f'错误: 模板中未找到水印素材 {tmpl_mat_id}')
            continue

        # 生成新UUID
        new_mat_id = uid()
        new_track_id = uid()
        new_seg_id = uid()
        new_mat_ids[tmpl_mat_id] = new_mat_id

        # 更新素材ID
        tmpl_mat['id'] = new_mat_id
        tmpl_mat['local_material_id'] = new_mat_id
        draft['materials']['texts'].append(tmpl_mat)

        # 创建新的水印轨道段
        new_seg = copy.deepcopy(tmpl_seg)
        new_seg['id'] = new_seg_id
        new_seg['material_id'] = new_mat_id
        new_seg['target_timerange'] = {
            'duration': total_dur,
            'start': 0
        }
        new_seg['source_timerange'] = None
        # 清空extra_material_refs（模板中的引用在目标中无效）
        new_seg['extra_material_refs'] = []

        # 创建新轨道
        new_track = {
            'attribute': tmpl_track.get('attribute', 2),
            'flag': 0,
            'id': new_track_id,
            'is_default_name': True,
            'name': '',
            'segments': [new_seg],
            'type': 'text'
        }
        draft['tracks'].append(new_track)

        # 打印水印内容
        content_raw = tmpl_mat.get('content', '')
        if isinstance(content_raw, str) and content_raw.startswith('{'):
            content_text = json.loads(content_raw).get('text', content_raw)
        else:
            content_text = content_raw
        print(f'  添加水印: {repr(content_text.replace(chr(10), " / "))}')

    print(f'水印时长: {total_dur / 1000000:.1f}s (与实际画面/音频一致)')

    # ── 写回 ──
    write_draft(dp, draft)

    print(f'\n水印添加完成')
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    success = add_watermark(sys.argv[1])
    sys.exit(0 if success else 1)
