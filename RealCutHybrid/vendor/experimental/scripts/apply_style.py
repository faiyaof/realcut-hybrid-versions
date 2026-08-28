# -*- coding: utf-8 -*-
"""风格套用器（独立于 real-cut 原版）：把选中的风格模板应用到成品草稿。
用法: python apply_style.py <成品草稿路径> [--style 风格名] [--template <模板路径>]
默认风格: 从 style_config.json 读，或 fallback 到 com.lveditor.draft/模板

功能：
  1. 读取风格模板（5.9格式），若是10.0加密格式则自动转5.9
  2. 套用模板外壳字段（剪映首次打开不再二次序列化）
  3. 套用模板字幕字体（字语圆体等）
  4. 叠加固定元素（风格文字/贴纸/音频）铺满全程
"""
import json, sys, os, uuid, shutil, argparse, copy, io, random, re
from pathlib import Path
from _utils import write_draft, read_draft, ensure_jianying_closed, ensure_utf8_stdout

DRAFT_ROOT = Path(r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft')
CONFIG_FILE = Path(r'C:\Users\JT\AppData\Local\JianyingPro\User Data\style_config.json')
# 模板库：10.0风格模板放这里
STYLE_LIB = Path(r'D:/10  jianyin/JianyingPro Drafts')

ensure_utf8_stdout()


def load_config():
    cfg = {'default_style': '模板'}
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.load(open(CONFIG_FILE, encoding='utf-8')))
        except Exception:
            pass
    return cfg


def uid():
    return str(uuid.uuid4()).upper()


def _style_lib_path():
    cfg = load_config()
    raw = cfg.get('style_lib') or ''
    return Path(raw) if raw else STYLE_LIB


def resolve_style_template_dir(style_name):
    """兼容 风格1、风格1模板 两种写法，并回退 5.9 草稿目录。"""
    style = (style_name or '').strip()
    base = style[:-2] if style.endswith('模板') and style != '模板' else style
    candidates = []
    if base:
        candidates.append(_style_lib_path() / f'{base}模板')
        candidates.append(DRAFT_ROOT / base)
        candidates.append(DRAFT_ROOT / f'{base}模板')
    candidates.append(DRAFT_ROOT / '模板')
    for cand in candidates:
        if (cand / 'draft_content.json').is_file():
            return cand
    return candidates[0]

def get_text_plain(content):
    """从 content 提取纯文本（支持 JSON / 纯文本 / 双重嵌套）。"""
    if isinstance(content, str) and content.startswith('{'):
        try:
            j = json.loads(content)
            txt = j.get('text', '')
            while isinstance(txt, str) and txt.strip().startswith('{'):
                j2 = json.loads(txt)
                txt = j2.get('text', '')
            return txt
        except Exception:
            return content
    return content if isinstance(content, str) else ''


def _decrypt_draft_content(tmpl_dir):
    """尝试用 videoeditor.dll 解密 draft_content.json，返回 dict 或 None。

    这是模板的「真实内容」：含视频素材、字幕（字语圆体）等。
    剪映的 draft_info.json 只是索引（无视频素材、字幕字体可能被旧版覆盖），
    不能当模板内容用。
    """
    try:
        from jy_crypt import JyCrypt
        dc = tmpl_dir / 'draft_content.json'
        if not dc.exists():
            return None
        raw = dc.read_bytes()
        if raw.startswith(b'{'):
            return json.loads(raw.decode('utf-8'))
        c = JyCrypt()
        return json.loads(c.decrypt(raw.decode('latin-1')))
    except Exception:
        return None


def convert_10_to_59(tmpl_dir):
    """若模板是10.0加密格式，解密 draft_content.json 并转成5.9格式。
    优先解密真实内容（含视频素材+字幕字体），失败才回退明文备用文件。
    返回转换后的 draft dict，或 None 表示已是5.9。
    """
    dc = tmpl_dir / 'draft_content.json'
    raw = dc.read_bytes()[:10] if dc.exists() else b''
    if raw.startswith(b'{'):
        return None  # 已是明文5.9
    # 1) 优先：解密 draft_content.json（真实内容，含视频素材+字语圆体）
    d = _decrypt_draft_content(tmpl_dir)
    if d is None:
        # 2) 回退：明文备用文件（template.json.bak / draft_info.json）
        for fn in ['template.json.bak', 'draft_info.json']:
            p = tmpl_dir / fn
            if p.exists():
                try:
                    r = p.read_bytes()[:10]
                    if r.startswith(b'{'):
                        d = json.load(open(p, encoding='utf-8'))
                        break
                except Exception:
                    continue
    if d is None:
        return None
    # 转5.9格式
    for f in ['is_drop_frame_timecode', 'function_assistant_info', 'smart_ads_info',
              'lyrics_effects', 'path', 'draft_type', 'mixed_track_mode_on',
              'uneven_animation_template_info', 'keyframes']:
        d.pop(f, None)
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
    for k in ['group_container', 'extra_info', 'time_marks', 'mutable_config', 'cover', 'retouch_cover']:
        d.setdefault(k, None)
    d.setdefault('static_cover_image_path', '')
    d.setdefault('render_index_track_mode_on', True)
    return d


def apply_style(dp_str, style_name=None, tmpl_path=None):
    dp = Path(dp_str)
    dc = dp / 'draft_content.json'
    if not dc.exists():
        print(f'成品草稿不存在: {dc}')
        return False

    # 确定模板
    cfg = load_config()
    if tmpl_path:
        tmpl_dir = Path(tmpl_path)
    elif style_name:
        tmpl_dir = resolve_style_template_dir(style_name)
    else:
        style_name = cfg.get('default_style', '模板')
        tmpl_dir = resolve_style_template_dir(style_name)
    print(f'使用风格: {tmpl_dir}')

    # 读模板
    tdc = tmpl_dir / 'draft_content.json'
    if not tdc.exists():
        print(f'模板不存在: {tdc}')
        return False
    raw = tdc.read_bytes()[:10]
    if raw.startswith(b'{'):
        tmpl = json.load(open(tdc, encoding='utf-8'))
    else:
        # 10.0加密：转换
        tmpl = convert_10_to_59(tmpl_dir)
        if tmpl is None:
            print('模板无法读取（非明文且无template.json.bak）')
            return False
        print('已从10.0模板转换')

    # 读取成品草稿（明文/加密统一入口，写坏即成品损坏，异常直接抛出不让调用方误判成功）
    try:
        draft = read_draft(dp)
    except Exception as e:
        print(f'成品草稿读取失败（明文/加密均支持）: {e}')
        return False
    total_dur = draft.get('duration', 0)

    # 套用前确保剪映关闭（防止内存副本覆盖成品）
    ensure_jianying_closed()

    # 1. 套用模板外壳
    SHELL_FIELDS = ['new_version', 'platform', 'canvas_config', 'color_space',
                    'source', 'render_index_track_mode_on', 'last_modified_platform',
                    'free_render_index_mode_on', 'keyframe_graph_list', 'relationships',
                    'mutable_config', 'group_container', 'time_marks', 'cover',
                    'static_cover_image_path', 'create_time', 'update_time']
    for f in SHELL_FIELDS:
        if f in tmpl:
            draft[f] = tmpl[f]
    # 1.5 config 逐 key 合并：保留成品已有的 subtitle_keywords_config（步骤12 写入的标黄样式）
    #     模板 config 的键逐一合并进成品 config；成品有且模板没有的键全部保留。
    tmpl_cfg = tmpl.get('config', {})
    draft_cfg = draft.setdefault('config', {})
    for k, v in tmpl_cfg.items():
        if k == 'subtitle_keywords_config' and draft_cfg.get('subtitle_keywords_config'):
            # 成品已有标黄 config（步骤12 刚写），用成品的，不被模板覆盖
            print('[1/4] 保留成品 subtitle_keywords_config（模板同键不覆盖）')
            continue
        draft_cfg[k] = copy.deepcopy(v)
    print('[1/4] 已套用模板外壳')

    # 2. 套用模板字幕字体
    tmpl_mats = tmpl.get('materials', {})
    tmpl_tracks = tmpl.get('tracks', [])
    tmpl_texts = {t['id']: t for t in tmpl_mats.get('texts', [])}
    tmpl_sub_font = None
    for tr in tmpl_tracks:
        if tr['type'] == 'text' and tr.get('flag') == 1:
            for s in tr.get('segments', []):
                m = tmpl_texts.get(s.get('material_id', ''))
                if m and m.get('type') == 'subtitle':
                    tmpl_sub_font = m
                    break
            if tmpl_sub_font:
                break
    if tmpl_sub_font:
        n_applied = 0
        draft_sub_ids = set()
        for tr in draft.get('tracks', []):
            if tr['type'] == 'text' and tr.get('flag') == 1:
                for s in tr.get('segments', []):
                    draft_sub_ids.add(s.get('material_id', ''))
        for mat in draft.get('materials', {}).get('texts', []):
            if mat['id'] not in draft_sub_ids:
                continue
            old_content = mat.get('content', '')
            old_text = get_text_plain(old_content)
            old_ranges = mat.get('subtitle_keywords', {}).get('range', [])
            # 重建 content（保留文字+关键词标黄，用模板字体）
            try:
                tc = json.loads(tmpl_sub_font.get('content', '{}'))
                base_styles = tc.get('styles', [])
                base_style = base_styles[0] if base_styles else {}
            except Exception:
                base_style = {}
            new_content = _build_styled(old_text, old_ranges, base_style)
            mat['content'] = new_content
            for f in ['font_resource_id', 'font_path', 'font_size', 'font_title',
                      'fonts', 'is_rich_text', 'use_effect_default_color',
                      'border_color', 'border_width', 'text_color']:
                if f in tmpl_sub_font:
                    mat[f] = json.loads(json.dumps(tmpl_sub_font[f]))
            n_applied += 1
        print(f'[2/4] 已套用模板字幕字体到 {n_applied} 条')
    else:
        print('[2/4] 模板无字幕样式，跳过字体套用')

    # ── 幂等标记 + 旧叠加清理 ──
    STYLE_MARK = '__style_overlay_v2_'
    applied_mark = draft.get('style_applied')
    current_mark = STYLE_MARK + str(style_name or tmpl_dir.name)
    already_applied = (applied_mark == current_mark)

    # 3. 叠加固定元素（风格文字/贴纸/BGM）
    if already_applied:
        print(f'[3/4] 风格「{style_name or tmpl_dir.name}」已套用，跳过文字/贴纸叠加（仅刷新字体/外壳）')
    else:
        # 换风格（或首次）：识别历史叠加的轨道/素材并移除，防止重复叠加
        overlay_mark_ids = set()
        overlay_key_ids = {}
        for key, mats in draft.get('materials', {}).items():
            if not isinstance(mats, list):
                continue
            for mat in mats:
                if isinstance(mat, dict) and isinstance(mat.get('style_overlay_mark'), str):
                    overlay_mark_ids.add(mat['id'])
                    overlay_key_ids.setdefault(key, set()).add(mat['id'])
        if overlay_mark_ids:
            # 移除被标记的素材（文字/贴纸/图片水印及色度抠图引用等）
            for key, ids in overlay_key_ids.items():
                draft['materials'][key] = [
                    m for m in draft.get('materials', {}).get(key, [])
                    if m['id'] not in ids
                ]
            # 移除引用了被标记素材的轨道段及其轨道
            draft['tracks'] = [t for t in draft.get('tracks', []) if not (
                t.get('segments') and any(
                    s.get('material_id', '') in overlay_mark_ids for s in t['segments']
                )
            )]
            print(f'[3/4] 已移除旧风格叠加: {len(overlay_mark_ids)} 条素材/轨道段')
            # 移除引用了被标记素材的轨道段及其轨道
            draft['tracks'] = [t for t in draft.get('tracks', []) if not (
                t.get('segments') and any(
                    s.get('material_id', '') in overlay_mark_ids for s in t['segments']
                )
            )]
            print(f'[3/4] 已移除旧风格叠加: {len(overlay_mark_ids)} 条素材/轨道段')
        _apply_overlay(draft, tmpl, total_dur, current_mark, tmpl_dir=tmpl_dir, draft_dir=dp)
    # BGM 替换：无论是否已套用，都用模板 BGM 替换成品旧 BGM（避免「慵懒」残留）
    _replace_bgm(draft, tmpl, total_dur, current_mark)

    # 4. 写盘（三文件原子同步 + 写前备份 + 写前关剪映）
    write_draft(dp, draft)
    print('[4/4] 写盘完成（三文件原子同步）')
    return True


def _replace_bgm(draft, tmpl, total_dur, mark):
    """用模板 BGM 替换成品草稿里的 BGM（music 轨）。

    1) 移除成品已有的 music 素材及引用它的音频轨（配音 sound 不受影响）
    2) 从模板 music 轨叠加 BGM，铺满成品时长
    """
    mats = draft.get('materials', {})
    # 1. 移除成品旧 BGM
    music_ids = set(m['id'] for m in mats.get('audios', []) + mats.get('music', [])
                    if m.get('type') == 'music')
    if music_ids:
        draft['tracks'] = [t for t in draft.get('tracks', []) if not (
            t['type'] == 'audio' and any(
                s.get('material_id', '') in music_ids for s in t.get('segments', [])
            )
        )]
        for key in ['audios', 'music']:
            mats[key] = [m for m in mats.get(key, []) if m.get('type') != 'music']
        print(f'[3/4] 已移除成品旧BGM（{len(music_ids)} 条 music 素材/轨）')

    # 2. 叠加模板 BGM
    tmpl_mats = tmpl.get('materials', {})
    tmpl_audios = {m['id']: m for m in tmpl_mats.get('audios', []) + tmpl_mats.get('music', [])}
    tmpl_bgm_segs = []
    for tr in tmpl.get('tracks', []):
        if tr['type'] != 'audio':
            continue
        for seg in tr.get('segments', []):
            m = tmpl_audios.get(seg.get('material_id', ''))
            if m and m.get('type') == 'music':
                tmpl_bgm_segs.append((seg, m))
    if not tmpl_bgm_segs:
        return
    seg, mat = random.choice(tmpl_bgm_segs)
    new_mat = copy.deepcopy(mat)
    new_mat['id'] = uid()
    new_mat['style_overlay_mark'] = mark
    new_mat['duration'] = total_dur
    mats.setdefault('audios', []).append(new_mat)
    mats.setdefault('music', []).append(new_mat)
    new_tr = {'type': 'audio', 'flag': 0, 'id': uid(), 'segments': [{
        **copy.deepcopy(seg),
        'id': uid(),
        'material_id': new_mat['id'],
        'target_timerange': {'duration': total_dur, 'start': 0},
        'source_timerange': {'duration': total_dur, 'start': 0},
    }]}
    draft.setdefault('tracks', []).append(new_tr)
    print(f"[3/4] 已叠加模板BGM: {(mat.get('name') or '?')[:40]}")


def _index_template_materials(tmpl_mats):
    """返回素材 ID -> (素材列表名, 素材) 的索引，用于复制水印引用。"""
    index = {}
    for key, mats in (tmpl_mats or {}).items():
        if not isinstance(mats, list):
            continue
        for mat in mats:
            if isinstance(mat, dict) and mat.get('id'):
                index[mat['id']] = (key, mat)
    return index


def _clone_material_refs(refs, tmpl_mat_index, draft_mats, id_map, mark):
    """复制轨道段引用的 chroma/speed/canvas/animation 等素材。"""
    mapped = []
    for ref in refs:
        if ref in id_map:
            mapped.append(id_map[ref])
            continue
        entry = tmpl_mat_index.get(ref)
        if entry is None:
            continue
        key, mat = entry
        new_mat = copy.deepcopy(mat)
        new_mat['id'] = uid()
        new_mat['style_overlay_mark'] = mark
        draft_mats.setdefault(key, []).append(new_mat)
        id_map[ref] = new_mat['id']
        mapped.append(new_mat['id'])
    return mapped


def _copy_photo_matting(tmpl_dir, draft_dir, matting_path):
    """把模板草稿的抠图素材复制到成品草稿，并重写 draftpath 占位符。"""
    if not matting_path or not tmpl_dir or not draft_dir:
        return matting_path
    m = re.search(r'##_draftpath_placeholder_[^#]+_##', matting_path)
    if not m:
        return matting_path
    rel_m = re.search(r'matting[/\\]([^/\\]+)', matting_path)
    if not rel_m:
        return matting_path
    rel = rel_m.group(1)
    src = Path(tmpl_dir) / 'matting' / rel
    dst = Path(draft_dir) / 'matting' / rel
    if not src.is_dir():
        return matting_path
    try:
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(src), str(dst))
    except Exception as e:
        print(f'[水印] 复制抠图素材失败: {e}')
        return matting_path
    return matting_path.replace(m.group(0), f'##_draftpath_placeholder_{uid()}_##')


def _apply_overlay(draft, tmpl, total_dur, mark, tmpl_dir=None, draft_dir=None):
    """叠加模板固定元素（风格文字/贴纸/图片水印/BGM），给素材/轨道写入唯一 mark 便于幂等清理。"""
    tmpl_mats = tmpl.get('materials', {})
    tmpl_tracks = tmpl.get('tracks', [])
    tmpl_mat_index = _index_template_materials(tmpl_mats)
    tmpl_texts = {t['id']: t for t in tmpl_mats.get('texts', [])}
    tmpl_stickers = {t['id']: t for t in tmpl_mats.get('stickers', [])}
    overlay_mats = {'texts': [], 'stickers': [], 'videos': []}
    overlay_tracks = []
    ref_id_map = {}
    draft_mats = draft.setdefault('materials', {})
    for tr in tmpl_tracks:
        if tr['type'] == 'text' and tr.get('flag') == 1:
            continue  # 字幕样例不叠加
        if tr['type'] == 'audio':
            continue  # BGM 由 _replace_bgm 单独处理，这里不叠加音频
        new_tr = {'type': tr['type'], 'flag': tr.get('flag', 0), 'id': uid(), 'segments': []}
        for seg in tr.get('segments', []):
            mid = seg.get('material_id', '')
            mat = None
            new_mat = None
            if tr['type'] == 'text':
                mat = tmpl_texts.get(mid)
                if mat:
                    new_mat = copy.deepcopy(mat)
                    new_mat['id'] = uid()
                    new_mat['style_overlay_mark'] = mark
                    overlay_mats['texts'].append(new_mat)
            elif tr['type'] == 'sticker':
                mat = tmpl_stickers.get(mid)
                if mat:
                    new_mat = copy.deepcopy(mat)
                    new_mat['id'] = uid()
                    new_mat['style_overlay_mark'] = mark
                    overlay_mats['stickers'].append(new_mat)
            elif tr['type'] == 'video':
                entry = tmpl_mat_index.get(mid)
                if entry and entry[1].get('type') == 'photo':
                    key, mat = entry
                    new_mat = copy.deepcopy(mat)
                    new_mat['id'] = uid()
                    new_mat['style_overlay_mark'] = mark
                    if isinstance(new_mat.get('matting'), dict):
                        mp = new_mat['matting'].get('path')
                        if mp:
                            new_mat['matting']['path'] = _copy_photo_matting(tmpl_dir, draft_dir, mp)
                    overlay_mats.setdefault(key, []).append(new_mat)
            if mat is None or new_mat is None:
                continue
            new_seg = copy.deepcopy(seg)
            new_seg['id'] = uid()
            new_seg['material_id'] = new_mat['id']
            new_seg['target_timerange'] = {'duration': total_dur, 'start': 0}
            new_seg['source_timerange'] = {'duration': total_dur, 'start': 0}
            if 'extra_material_refs' in new_seg:
                new_seg['extra_material_refs'] = _clone_material_refs(
                    new_seg.get('extra_material_refs') or [],
                    tmpl_mat_index, draft_mats, ref_id_map, mark,
                )
            if 'keyframe_refs' in new_seg:
                new_seg['keyframe_refs'] = _clone_material_refs(
                    new_seg.get('keyframe_refs') or [],
                    tmpl_mat_index, draft_mats, ref_id_map, mark,
                )
            new_tr['segments'].append(new_seg)
        if new_tr['segments']:
            overlay_tracks.append(new_tr)
    for key in overlay_mats:
        if overlay_mats[key]:
            draft_mats.setdefault(key, []).extend(overlay_mats[key])
    draft.setdefault('tracks', []).extend(overlay_tracks)
    for key, mats in overlay_mats.items():
        for mat in mats:
            mat['duration'] = total_dur
    # 写幂等标记：下次同风格直接跳过叠加
    draft['style_applied'] = mark
    n_text = len(overlay_mats['texts'])
    n_stk = len(overlay_mats['stickers'])
    n_photo = len(overlay_mats['videos'])
    print(f"[3/4] 已叠加 {n_text}风格文字 + {n_stk}贴纸 + {n_photo}图片水印")


def _build_styled(text, yellow_ranges, base_style):
    """用模板 style 重建 content，保留文字 + 关键词标黄。"""
    n = len(text)
    is_yellow = [False] * n
    for r in yellow_ranges:
        loc = r.get('location', 0)
        ln = r.get('length', 0)
        for i in range(loc, min(loc + ln, n)):
            is_yellow[i] = True
    base = json.loads(json.dumps(base_style)) if base_style else {}
    base_size = base.get('size', 10)
    yellow_fill = {'content': {'solid': {'color': [1.0, 0.8705882430076599, 0.0]}}}
    white_fill = base.get('fill', {'content': {'solid': {'color': [1.0, 1.0, 1.0]}}})

    def _mk(fill, start, end, yellow):
        st = json.loads(json.dumps(base))
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
            styles.append(_mk(json.loads(json.dumps(yellow_fill)), i, j, True))
            i = j
        else:
            j = i
            while j < n and not is_yellow[j]:
                j += 1
            styles.append(_mk(json.loads(json.dumps(white_fill)), i, j, False))
            i = j
    return json.dumps({'text': text, 'styles': styles}, ensure_ascii=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='风格套用器')
    parser.add_argument('draft', help='成品草稿路径')
    parser.add_argument('--style', help='风格名（对应 STYLE_LIB 下的 XX模板）')
    parser.add_argument('--template', help='模板草稿路径')
    args = parser.parse_args()
    sys.exit(0 if apply_style(args.draft, args.style, args.template) else 1)
