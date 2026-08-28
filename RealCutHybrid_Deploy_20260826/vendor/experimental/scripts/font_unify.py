# -*- coding: utf-8 -*-
"""实验版字体统一：只把动态字幕（flag=1 subtitle）刷成风格模板字体。

不修改 flag=0 的风格固定文字/贴纸元素。
用法: python font_unify.py <草稿路径>
"""
import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path

from _utils import (
    DRAFT_ROOT,
    STYLE_CONFIG_FILE,
    STYLE_LIB,
    ensure_utf8_stdout,
    read_draft,
    resolve_template_dir as utils_resolve_template_dir,
    write_draft,
)

ensure_utf8_stdout()

FONT_FIELDS = ['font_resource_id', 'font_path', 'font_title', 'fonts', 'font_size']


def style_name_for_draft(draft):
    mark = draft.get('style_applied') or ''
    prefix = '__style_overlay_'
    if isinstance(mark, str) and mark.startswith(prefix):
        return mark[len(prefix):]
    try:
        cfg = json.loads(STYLE_CONFIG_FILE.read_text(encoding='utf-8-sig'))
        return cfg.get('default_style')
    except Exception:
        return None


def resolve_style_template_dir():
    name = None
    try:
        cfg = json.loads(STYLE_CONFIG_FILE.read_text(encoding='utf-8-sig'))
        name = cfg.get('default_style')
    except Exception:
        pass
    if name:
        cand = STYLE_LIB / f'{name}模板'
        if (cand / 'draft_content.json').exists():
            return cand
        cand = DRAFT_ROOT / name
        if (cand / 'draft_content.json').exists():
            return cand
    resolved, _ = utils_resolve_template_dir()
    return resolved


def read_plain_or_draft(tmpl_dir):
    dc = tmpl_dir / 'draft_content.json'
    if not dc.exists():
        return None
    try:
        raw = dc.read_bytes()
        if raw.lstrip(b'\xef\xbb\xbf').lstrip().startswith(b'{'):
            return json.loads(raw.decode('utf-8-sig'))
        return read_draft(tmpl_dir)
    except Exception:
        return None


def dynamic_subtitle_materials(draft):
    ids = set()
    for tr in draft.get('tracks', []):
        if tr.get('type') == 'text' and tr.get('flag') == 1:
            for seg in tr.get('segments', []) or []:
                ids.add(seg.get('material_id', ''))
    mats = []
    by_id = {m['id']: m for m in draft.get('materials', {}).get('texts', [])}
    for mid in ids:
        mat = by_id.get(mid)
        if mat and mat.get('type') == 'subtitle':
            mats.append(mat)
    return mats


def _majority_font(mats):
    counts = Counter((m.get('font_resource_id'), m.get('font_path')) for m in mats)
    if not counts:
        return None
    target_key, _ = counts.most_common(1)[0]
    for m in mats:
        if (m.get('font_resource_id'), m.get('font_path')) == target_key:
            return m
    return None


def template_font(draft):
    mats = dynamic_subtitle_materials(draft)
    if mats:
        return _majority_font(mats)
    tmpl_dir = resolve_style_template_dir()
    if tmpl_dir is not None:
        tmpl = read_plain_or_draft(tmpl_dir)
        if tmpl is not None:
            mats = dynamic_subtitle_materials(tmpl)
            if mats:
                return _majority_font(mats)
    return None


def font_snapshot(mat):
    return {
        'font_resource_id': mat.get('font_resource_id'),
        'font_path': mat.get('font_path'),
        'font_title': mat.get('font_title'),
        'fonts': mat.get('fonts'),
    }


def apply_font(mat, target):
    for key in FONT_FIELDS:
        if key in target:
            mat[key] = copy.deepcopy(target[key])
    content = mat.get('content')
    try:
        parsed = json.loads(content) if isinstance(content, str) else content
    except Exception:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get('styles'), list):
        for style in parsed['styles']:
            if not isinstance(style, dict):
                continue
            font = style.setdefault('font', {})
            if isinstance(font, dict):
                if target.get('font_resource_id'):
                    font['id'] = target['font_resource_id']
                if target.get('font_path'):
                    font['path'] = target['font_path']
        mat['content'] = json.dumps(parsed, ensure_ascii=False)


def verify_fonts(mats, target):
    for mat in mats:
        snap = font_snapshot(mat)
        if snap['font_resource_id'] != target.get('font_resource_id'):
            return False, mat.get('id')
        if snap['font_path'] != target.get('font_path'):
            return False, mat.get('id')
        content = mat.get('content')
        try:
            parsed = json.loads(content) if isinstance(content, str) else content
        except Exception:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get('styles'), list):
            for style in parsed['styles']:
                font = style.get('font', {}) if isinstance(style, dict) else {}
                if isinstance(font, dict) and (font.get('id') != target.get('font_resource_id') or font.get('path') != target.get('font_path')):
                    return False, mat.get('id')
    return True, ''


def unify_font(dp_str):
    dp = Path(dp_str)
    draft = read_draft(dp)
    mats = dynamic_subtitle_materials(draft)
    if not mats:
        print('未找到动态字幕素材')
        return True
    target = template_font(draft)
    if target is None:
        print('无法确定目标字体')
        return False
    for mat in mats:
        apply_font(mat, target)
    ok, bad_id = verify_fonts(mats, target)
    if not ok:
        print(f'字体校验失败，素材仍有旧字体: {bad_id}')
        return False
    write_draft(dp, draft)
    print(f'字体统一完成：{len(mats)} 条动态字幕 -> {target.get("font_path")}')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='实验版动态字幕字体统一')
    parser.add_argument('draft', help='草稿路径')
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    sys.exit(0 if unify_font(args.draft) else 1)
