# -*- coding: utf-8 -*-
"""风格应用器：把模板草稿的固定元素（风格字幕/贴纸/音频）叠加到成品草稿。
用法: python apply_style_template.py <成品草稿路径> [模板草稿路径]
默认模板: com.lveditor.draft/模板
"""
import json, sys, os, uuid, shutil, io
from pathlib import Path
from _utils import write_draft, ensure_utf8_stdout, rewrite_pkg_asset_paths

ensure_utf8_stdout()

DEFAULT_TEMPLATE = Path(os.environ.get('REALCUT_DRAFT_ROOT', r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft')) / '模板'


def uid():
    return str(uuid.uuid4()).upper()


def _build_styled_content(text, yellow_ranges, tmpl_style):
    """用模板字幕样式重建 content，保留文字 + 关键词标黄区间。
    基于模板 subtitle 的 content 结构（font id/path + 白字/黄字样式）。
    """
    # 从模板 style 提取基础样式
    try:
        tmpl_content = json.loads(tmpl_style.get('content', '{}'))
        tmpl_styles = tmpl_content.get('styles', [])
    except Exception:
        tmpl_styles = []
    # 模板第一条 style 作为普通段基准
    base_style = {}
    if tmpl_styles:
        s = tmpl_styles[0]
        base_style['fill'] = s.get('fill')
        base_style['font'] = s.get('font')
        base_style['size'] = s.get('size')
        base_style['strokes'] = s.get('strokes')
    # 黄色重点样式（如果没有则用 fill 黄）
    yellow_fill = {'content': {'solid': {'color': [1.0, 0.8705882430076599, 0.0]}}}
    base_size = base_style.get('size', 10)

    n = len(text)
    is_yellow = [False] * n
    for r in yellow_ranges:
        loc = r.get('location', 0)
        ln = r.get('length', 0)
        for i in range(loc, min(loc + ln, n)):
            is_yellow[i] = True

    def _mk_style(fill, start, end, yellow):
        st = json.loads(json.dumps(base_style)) if base_style else {}
        st['fill'] = fill
        st['range'] = [start, end]
        st['size'] = 10.4 if yellow else base_size
        st['useLetterColor'] = True
        return st

    styles = []
    i = 0
    while i < n:
        if is_yellow[i]:
            j = i
            while j < n and is_yellow[j]:
                j += 1
            styles.append(_mk_style(json.loads(json.dumps(yellow_fill)), i, j, True))
            i = j
        else:
            j = i
            while j < n and not is_yellow[j]:
                j += 1
            styles.append(_mk_style(json.loads(json.dumps(base_style.get('fill', {'content': {'solid': {'color': [1.0, 1.0, 1.0]}}}))), i, j, False))
            i = j

    return json.dumps({'text': text, 'styles': styles}, ensure_ascii=False)


def apply(dp_str, tmpl_str=None):
    dp = Path(dp_str)
    tmpl_dir = Path(tmpl_str) if tmpl_str else DEFAULT_TEMPLATE
    dc = dp / 'draft_content.json'
    tdc = tmpl_dir / 'draft_content.json'
    if not dc.exists():
        print(f'成品草稿不存在: {dc}')
        return False
    if not tdc.exists():
        print(f'模板草稿不存在: {tdc}')
        return False

    draft = json.load(open(dc, encoding='utf-8'))
    tmpl = json.load(open(tdc, encoding='utf-8'))
    tmpl = rewrite_pkg_asset_paths(tmpl)
    total_dur = draft.get('duration', 0)
    print(f'成品时长: {total_dur}us, 模板时长: {tmpl.get("duration")}us')

    # 提取模板的固定元素：text/sticker/audio 素材 + 它们的轨道段（flag=0的）
    tmpl_mats = tmpl.get('materials', {})
    tmpl_tracks = tmpl.get('tracks', [])

    # 模板素材 ID -> 素材
    tmpl_texts = {t['id']: t for t in tmpl_mats.get('texts', [])}
    tmpl_stickers = {t['id']: t for t in tmpl_mats.get('stickers', [])}
    tmpl_audios = {t['id']: t for t in tmpl_mats.get('audios', [])}

    # 收集要叠加的素材类型和轨道段（跳过视频轨 和 flag=1字幕轨——那是模板字幕样例）
    overlay_mats = {'texts': [], 'stickers': [], 'audios': []}
    overlay_tracks = []
    for tr in tmpl_tracks:
        if tr['type'] == 'video':
            continue
        if tr['type'] == 'text' and tr.get('flag') == 1:
            continue  # 模板的动态字幕样例不叠加，只用于提取样式
        new_tr = {'type': tr['type'], 'flag': 0, 'id': uid(), 'segments': []}
        for seg in tr.get('segments', []):
            mid = seg.get('material_id', '')
            mat = None
            if tr['type'] == 'text':
                mat = tmpl_texts.get(mid)
                if mat:
                    # 深拷贝素材，替换ID
                    new_mat = json.loads(json.dumps(mat))
                    new_mat['id'] = uid()
                    overlay_mats['texts'].append(new_mat)
            elif tr['type'] == 'sticker':
                mat = tmpl_stickers.get(mid)
                if mat:
                    new_mat = json.loads(json.dumps(mat))
                    new_mat['id'] = uid()
                    overlay_mats['stickers'].append(new_mat)
            elif tr['type'] == 'audio':
                mat = tmpl_audios.get(mid)
                if mat:
                    new_mat = json.loads(json.dumps(mat))
                    new_mat['id'] = uid()
                    overlay_mats['audios'].append(new_mat)
            if mat is None:
                continue
            # 新轨道段：引用新素材ID，铺满成品时长
            new_seg = json.loads(json.dumps(seg))
            new_seg['id'] = uid()
            new_seg['material_id'] = new_mat['id']
            new_seg['target_timerange'] = {'duration': total_dur, 'start': 0}
            new_seg['source_timerange'] = {'duration': total_dur, 'start': 0}
            new_tr['segments'].append(new_seg)
        if new_tr['segments']:
            overlay_tracks.append(new_tr)

    # ── 套用模板字幕样式到成品动态字幕 ──
    # 从模板 flag=1 字幕轨取第一条 subtitle 的样式（字体/字号/content格式），
    # 套用到成品草稿的 flag=1 动态字幕，保留成品的字幕文字 + 关键词标黄区间。
    tmpl_style = None
    for tr in tmpl_tracks:
        if tr['type'] == 'text' and tr.get('flag') == 1:
            for seg in tr.get('segments', []):
                mid = seg.get('material_id', '')
                m = tmpl_texts.get(mid)
                if m and m.get('type') == 'subtitle':
                    tmpl_style = m
                    break
            if tmpl_style:
                break
    if tmpl_style:
        n_applied = 0
        # 成品动态字幕 = flag=1 字幕轨引用的 subtitle 素材
        draft_sub_ids = set()
        for tr in draft.get('tracks', []):
            if tr['type'] == 'text' and tr.get('flag') == 1:
                for s in tr.get('segments', []):
                    draft_sub_ids.add(s.get('material_id', ''))
        draft_mats_all = draft.setdefault('materials', {})
        for mat in draft_mats_all.get('texts', []):
            if mat['id'] not in draft_sub_ids:
                continue
            # 提取成品字幕文字 + 关键词区间
            old_content = mat.get('content', '')
            old_text = old_content
            old_ranges = mat.get('subtitle_keywords', {}).get('range', [])
            if isinstance(old_content, str) and old_content.startswith('{'):
                try:
                    j = json.loads(old_content)
                    old_text = j.get('text', old_text)
                except Exception:
                    pass
            # 用模板样式重建 content（保留文字 + 关键词标黄）
            new_content = _build_styled_content(old_text, old_ranges, tmpl_style)
            mat['content'] = new_content
            # 套用模板字体字段
            mat['font_resource_id'] = tmpl_style.get('font_resource_id', mat.get('font_resource_id'))
            mat['font_path'] = tmpl_style.get('font_path', mat.get('font_path'))
            mat['font_size'] = tmpl_style.get('font_size', mat.get('font_size'))
            mat['font_title'] = tmpl_style.get('font_title', mat.get('font_title'))
            mat['fonts'] = json.loads(json.dumps(tmpl_style.get('fonts', mat.get('fonts'))))
            mat['is_rich_text'] = tmpl_style.get('is_rich_text', mat.get('is_rich_text'))
            mat['use_effect_default_color'] = tmpl_style.get('use_effect_default_color', mat.get('use_effect_default_color'))
            mat['border_color'] = tmpl_style.get('border_color', mat.get('border_color'))
            mat['border_width'] = tmpl_style.get('border_width', mat.get('border_width'))
            mat['text_color'] = tmpl_style.get('text_color', mat.get('text_color'))
            n_applied += 1
        print(f'已套用模板字幕样式到 {n_applied} 条动态字幕（字语圆体）')

    # 合并到成品草稿
    draft_mats = draft.setdefault('materials', {})
    for key in overlay_mats:
        draft_mats.setdefault(key, []).extend(overlay_mats[key])
    draft.setdefault('tracks', []).extend(overlay_tracks)

    # 素材时长同步
    for mat in overlay_mats['texts'] + overlay_mats['stickers'] + overlay_mats['audios']:
        mat['duration'] = total_dur

    # 写盘（三文件原子同步 + 写前备份 + 写前关剪映，由 write_draft 保证）
    write_draft(dp, draft)

    n_text = len(overlay_mats['texts'])
    n_stk = len(overlay_mats['stickers'])
    n_aud = len(overlay_mats['audios'])
    print(f'已叠加: {n_text}条风格字幕 + {n_stk}个贴纸 + {n_aud}条音频, 铺满{total_dur/1000000:.1f}s')
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    t = sys.argv[2] if len(sys.argv) > 2 else None
    sys.exit(0 if apply(sys.argv[1], t) else 1)
