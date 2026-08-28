# -*- coding: utf-8 -*-
"""把剪映10.0风格模板转成5.9兼容的"模板"草稿。
读取 D:/10 jianyin/JianyingPro Drafts/风格2模板/template.json.bak（明文），
转成 5.9 能打开的草稿，保存到 com.lveditor.draft/模板。
"""
import json, os, sys, uuid, shutil
from pathlib import Path

DEFAULT_DRAFT_ROOT = Path(os.environ.get('REALCUT_DRAFT_ROOT', r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft'))
STYLE_LIB = Path(os.environ.get('REALCUT_STYLE_LIB', r'D:/10  jianyin/JianyingPro Drafts'))
SRC = STYLE_LIB / '风格2模板' / 'template.json.bak'
DST_DIR = DEFAULT_DRAFT_ROOT / '模板'

# 10.0独有字段，5.9不需要
DROP_FIELDS = ['is_drop_frame_timecode', 'function_assistant_info', 'smart_ads_info',
               'lyrics_effects', 'path', 'draft_type', 'mixed_track_mode_on',
               'uneven_animation_template_info', 'keyframes']


def convert():
    d = json.load(open(SRC, encoding='utf-8'))

    # 1. 去掉10.0独有字段
    for f in DROP_FIELDS:
        d.pop(f, None)

    # 2. 外壳修正为5.9可识别的"模板"格式（对齐已验证的模板草稿）
    d['new_version'] = '110.0.0'
    d['name'] = ''
    d['version'] = 360000
    d['source'] = 'default'
    d['platform'] = {
        'app_id': 3704, 'app_source': 'lv', 'app_version': '5.9.0',
        'device_id': 'b01238e1fc97414f875e2ee6ba075927',
        'hard_disk_id': '50cecedb853a64668e01e31bfe54f1b8',
        'mac_address': 'caccf53d4db2884dd5fa2bcd7f6cd120',
        'os': 'Windows', 'os_version': '10.0.19045',
    }
    d['last_modified_platform'] = dict(d['platform'])
    d['canvas_config'] = {'height': 1920, 'ratio': 'original', 'width': 1080}
    d['color_space'] = 0
    d['fps'] = 30.0
    # 5.9需要但10.0可能缺的
    d.setdefault('group_container', None)
    d.setdefault('extra_info', None)
    d.setdefault('time_marks', None)
    d.setdefault('mutable_config', None)
    d.setdefault('cover', None)
    d.setdefault('retouch_cover', None)
    d.setdefault('static_cover_image_path', '')
    d.setdefault('render_index_track_mode_on', True)
    d.setdefault('free_render_index_mode_on', False)

    # 3. config 补 subtitle_keywords_config（剪映标黄需要）
    cfg = d.setdefault('config', {})
    if not cfg.get('subtitle_keywords_config'):
        cfg['subtitle_keywords_config'] = {
            'font_size_ratio': 1.3,
            'styles': '{"styles":[{"fill":{"alpha":1.0,"content":{"render_type":"solid","solid":{"alpha":1.0,"color":[1.0,0.8705882430076599,0.0]}}},"range":[0,11],"size":13.0,"strokes":[{"alpha":1.0,"content":{"render_type":"solid","solid":{"alpha":1.0,"color":[0.0,0.0,0.0]}},"width":0.06}],"useLetterColor":true}],"text":"placeholder"}',
            'subtitle_template_keywords_original_font_size': 0.0,
            'subtitle_template_original_font_size': 0.0,
        }

    # 4. 写入5.9草稿库（三文件同步）
    DST_DIR.mkdir(parents=True, exist_ok=True)
    for fn in ['draft_content.json', 'draft_info.json', 'template-2.tmp']:
        with open(DST_DIR / fn, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=4)

    # 5. draft_meta_info.json
    meta = {
        'draft_name': '模板',
        'draft_root_path': str(DST_DIR.parent),
        'draft_fold_path': str(DST_DIR),
        'draft_json_file': str(DST_DIR / 'draft_content.json'),
        'draft_cover': str(DST_DIR / 'draft_cover.jpg'),
        'draft_id': str(uuid.uuid4()).upper(),
        'draft_type': 'normal',
        'draft_cloud_last_action_download': False,
        'draft_cloud_purchase_info': '',
        'draft_cloud_template_id': '',
        'draft_new_version': '110.0.0',
    }
    with open(DST_DIR / 'draft_meta_info.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=4)

    # 6. draft_settings
    import time
    now = int(time.time())
    with open(DST_DIR / 'draft_settings', 'w', encoding='utf-8') as f:
        f.write(f'[General]\ncloud_last_modify_platform=windows\ndraft_create_time={now}\ndraft_last_edit_time={now}\nreal_edit_seconds=10\nreal_edit_keys=1\n')

    print('已生成5.9模板草稿:')
    print(f'  texts: {len(d.get("materials",{}).get("texts",[]))}')
    print(f'  stickers: {len(d.get("materials",{}).get("stickers",[]))}')
    print(f'  new_version: {d.get("new_version")}')
    print(f'  tracks: {[(t["type"],t.get("flag"),len(t.get("segments",[]))) for t in d.get("tracks",[])]}')


if __name__ == '__main__':
    convert()
