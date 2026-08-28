"""Import subtitles as 'texts' materials (subtitle type) so step12 can style them"""
import json, sys, uuid, shutil, io
from pathlib import Path
from _utils import write_draft, ensure_utf8_stdout

ensure_utf8_stdout()

def uid():
    return str(uuid.uuid4()).upper()

dp = Path(sys.argv[1])
sub_file = dp / '字幕.txt'
dc_file = dp / 'draft_content.json'

with open(sub_file, 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()

subs = []
for line in lines:
    parts = line.strip().rsplit(' ', 2)
    if len(parts) != 3:
        continue
    text, start_s, end_s = parts
    start_us = int(start_s) * 1000
    end_us = int(end_s) * 1000
    dur_us = end_us - start_us
    subs.append((text, start_us, dur_us))

print(f'Parsed {len(subs)} subtitles')

with open(dc_file, 'r', encoding='utf-8') as f:
    draft = json.load(f)

# Get canvas height for coordinate normalization
canvas_height = draft.get('canvas_config', {}).get('height', 0) or 1920
# User wants y = -800px  →  normalized = -800 / canvas_height
POS_Y_NORMALIZED = 0.2  # reference draft value

# ── 清理旧字幕 ──
# 找出所有 type=subtitle 的素材 ID，移除对应轨道段和素材
old_subtitle_mat_ids = set()
for mat in draft['materials'].get('texts', []):
    if mat.get('type') == 'subtitle':
        old_subtitle_mat_ids.add(mat['id'])

if old_subtitle_mat_ids:
    draft['materials']['texts'] = [
        m for m in draft['materials']['texts']
        if m['id'] not in old_subtitle_mat_ids
    ]
    # 移除引用了这些素材的轨道段
    for t in draft['tracks']:
        if t['type'] == 'text':
            t['segments'] = [
                s for s in t.get('segments', [])
                if s.get('material_id', '') not in old_subtitle_mat_ids
            ]
    # 移除空轨道
    draft['tracks'] = [
        t for t in draft['tracks']
        if not (t['type'] == 'text' and len(t.get('segments', [])) == 0)
    ]
    print(f'Removed {len(old_subtitle_mat_ids)} old subtitle materials')

# 额外清理：移除 text_templates 中旧的 字幕 分类
draft['materials']['text_templates'] = [
    t for t in draft['materials'].get('text_templates', [])
    if t.get('category_name') != '字幕'
]

# Also clean old text_templates subtitle category
templates = draft['materials'].get('text_templates', [])
draft['materials']['text_templates'] = [t for t in templates if t.get('category_name') != '字幕']

# ── 创建新字幕 ──
texts_mats = draft['materials'].get('texts', [])
new_text_track = {
    "type": "text",
    "flag": 1,
    "is_main_track": False,
    "attribute": 0,
    "id": uid(),
    "segments": []
}

for text, start_us, dur_us in subs:
    mat_id = uid()
    text_mat = {
        "id": mat_id,
        "type": "subtitle",
        "content": text,
        "duration": dur_us,
        "font_color": "#ffffff",
        "font_size": 8,
        "text_size": 30,
        "alignment": 1,
        "bold": False,
        "use_msg_card": False,
        "is_rich_text": False,
        "text_color": "#ffffff",
        "text_alpha": 1.0,
        "border_color": "#000000",
        "border_width": 0.08,
        "border_alpha": 1.0,
        "check_flag": 15,
        "global_alpha": 1.0,
        "preset_index": 0,
        "preset_id": "",
        "preset_name": "",
        "preset_category": "",
        "preset_category_id": "",
        "preset_has_set_alignment": False,
        "sub_type": 0,
        "use_effect_default_color": False,
        "line_max_width": 0.82,
        "line_spacing": 0.02,
        "recognize_type": 0,
        "font_path": "",
        "font_resource_id": "",
        "font_title": "江湖体",
        "fonts": [{"category_id": "favoured", "category_name": "我的收藏", "effect_id": "7080097079397192228", "file_uri": "", "id": "", "path": "", "request_id": "", "resource_id": "7080097079397192228", "source_platform": 0, "team_id": "", "title": "江湖体"}],
        "caption_template_info": {
            "category_id": "",
            "category_name": "",
            "effect_id": "",
            "is_new": False,
            "path": "",
            "request_id": "",
            "resource_id": "",
            "resource_name": "",
            "source_platform": 0
        },
        "subtitle_keywords": {"range": []},
        "subtitle_template_original_fontsize": 0.0,
        "width": 0,
        "height": 0,
        "x": 0,
        "y": 0
    }
    texts_mats.append(text_mat)

    seg = {
        "id": uid(),
        "material_id": mat_id,
        "target_timerange": {
            "duration": dur_us,
            "start": start_us
        },
        "source_timerange": {
            "duration": dur_us,
            "start": 0
        },
        "speed": 1,
        "volume": 1,
        "visible": True,
        "extra_material_refs": [],
        "clip": {
            "alpha": 1.0,
            "flip": {"horizontal": False, "vertical": False},
            "rotation": 0.0,
            "scale": {"x": 1.0, "y": 1.0},
            "transform": {"x": 0.0, "y": POS_Y_NORMALIZED}
        }
    }
    new_text_track['segments'].append(seg)

draft['materials']['texts'] = texts_mats
draft['tracks'].append(new_text_track)

# 三文件原子同步（写前关剪映 + 备份 + 原子写）
write_draft(dp, draft)

print(f'Imported {len(subs)} subtitles as subtitle-type materials')
print(f'Canvas height: {canvas_height}, normalized Y: {POS_Y_NORMALIZED:.4f}')
print(f'Total texts: {len(texts_mats)}')
