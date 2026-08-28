# -*- coding: utf-8 -*-
"""
步骤12：修改文字样式 — 江湖体+白字黑描边+关键词外挂库标黄
用法: python "步骤12-字体样式.py" <草稿路径>

流程：
  1. 读取 C:/Users/JT/Documents/剪辑/highlight_keywords.txt 外挂关键词库
  2. 对每条字幕，匹配关键词并标记 subtitle_keywords.range
  3. 字号改为 10，字幕 Y 位置 = -0.4167
"""
import json, sys, re, copy, os
from pathlib import Path
from _utils import write_draft

FONT_PATH = os.environ.get('REALCUT_FONT_PATH', 'C:/Users/JT/AppData/Local/JianyingPro/User Data/Cache/effect/1654203/50957d5102cb4f2ea1459e140826eb0c/HelloFont ID JiangHuTi.ttf')
FONT_ID = '7080097079397192228'
FONT_LIST = [{'category_id':'favoured','category_name':'我的收藏','effect_id':FONT_ID,'file_uri':'','id':'9342442C-5214-4f90-87C0-FE6B41367998','path':'','request_id':'','resource_id':'','team_id':'','title':'江湖体'}]

# ── 关键词高亮渲染 ──
# 剪映认可的富文本字幕格式（草稿104/150验证）：
#   · content 为 rich JSON 字符串 {"styles":[...],"text":"..."}，is_rich_text=False 时剪映会解析渲染
#   · 普通段：白 fill [1,1,1] + 黑描边 width 0.08，字号 10
#   · 关键字段：黄 fill [1,0.8705882430076599,0] + 黑描边 width 0.06，字号 10.4
#   · 同时写 material 级 subtitle_keywords.range + 顶层 config.subtitle_keywords_config
# 注意：所有字幕必须统一 rich JSON 格式；若纯文本与 JSON 混合，纯文本字幕会被
#       subtitle_keywords_config 的 placeholder 样式整条染黄。


def build_rich_content(text, yellow_ranges, font_id, font_path, size):
    """重建 rich text content：普通白字黑描边，关键字黄字细描边（对齐模板精简格式）。"""
    n = len(text)
    is_yellow = [False] * n
    for r in yellow_ranges:
        loc = r['location']
        ln = r['length']
        for i in range(loc, min(loc + ln, n)):
            is_yellow[i] = True

    def _make_style(seg_text, color, stroke_width, seg_size, start_pos):
        return {
            'fill': {'content': {'solid': {'color': color}}},
            'font': {'path': font_path, 'id': font_id},
            'range': [start_pos, start_pos + len(seg_text)],
            'size': seg_size,
            'strokes': [{'content': {'solid': {'color': [0, 0, 0]}}, 'width': stroke_width}],
            'useLetterColor': True,
        }

    styles = []
    i = 0
    while i < n:
        if is_yellow[i]:
            j = i
            while j < n and is_yellow[j]:
                j += 1
            styles.append(_make_style(text[i:j], [1, 0.87058824300766, 0], 0.06, 10.4, start_pos=i))
            i = j
        else:
            j = i
            while j < n and not is_yellow[j]:
                j += 1
            styles.append(_make_style(text[i:j], [1, 1, 1], 0.07999999821186066, size, start_pos=i))
            i = j

    return json.dumps({'text': text, 'styles': styles}, ensure_ascii=False)


def build_base_content(text, font_id, font_path, size):
    """重建 base_content：单段白字+黑描边（不含关键字标黄）。"""
    return json.dumps({
        'styles': [{
            'fill': {'alpha': 1.0,
                     'content': {'render_type': 'solid',
                                 'solid': {'alpha': 1.0, 'color': [1.0, 1.0, 1.0]}}},
            'font': {'id': font_id, 'path': font_path},
            'range': [0, len(text)],
            'size': size,
            'strokes': [{'alpha': 1.0,
                         'content': {'render_type': 'solid',
                                     'solid': {'alpha': 1.0, 'color': [0.0, 0.0, 0.0]}},
                         'width': 0.08}],
            'useLetterColor': True,
        }],
        'text': text,
    }, ensure_ascii=False)


# ── 外挂关键词库路径 ──
KEYWORD_FILE = Path(os.environ.get('REALCUT_KEYWORD_FILE', r'C:/Users/JT/Documents/剪辑/highlight_keywords.txt'))


def load_keywords():
    """从外挂关键词文件加载关键词列表（跳过注释和空行）"""
    if not KEYWORD_FILE.exists():
        print(f'[跳过] 关键词库不存在: {KEYWORD_FILE}')
        return []
    kws = []
    with open(KEYWORD_FILE, 'r', encoding='utf-8-sig') as f:  # utf-8-sig 自动去 BOM
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('//'):
                continue
            if line.startswith('==='):
                continue
            kws.append(line)
    # 去重（保留首次出现顺序），避免重复词导致标黄逻辑重复
    seen = set()
    unique = []
    for kw in kws:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    print(f'关键词库: {len(unique)} 个关键词')
    return unique


def get_yellow_ranges(text, keywords):
    """
    返回需要标黄的字符区间列表 [{"length": N, "location": start}, ...]
    剪映5.9使用 length+location 格式，不是起止区间
    包含：阿拉伯数字 + 中文数字 + 关键词库匹配
    """
    n = len(text)
    if n == 0:
        return []

    is_yellow = [False] * n

    # 匹配阿拉伯数字连续序列
    for m in re.finditer(r'\d+', text):
        for i in range(m.start(), m.end()):
            if i < n:
                is_yellow[i] = True

    # 匹配中文数字（价格"三百""六千九"等标黄），单个数字词不强标避免误伤
    cn_num_pat = re.compile(r'(?:零|一|二|两|三|四|五|六|七|八|九)(?:十|百|千|万)?(?:零|一|二|两|三|四|五|六|七|八|九)?(?:十|百|千|万)?')
    cn_num_units = set('十百千万')
    for m in cn_num_pat.finditer(text):
        seg = m.group()
        # 至少含一个"十百千万"单位才算中文数字（"三"单独不强标）
        if any(u in seg for u in cn_num_units):
            for i in range(m.start(), m.end()):
                if i < n:
                    is_yellow[i] = True

    # 匹配关键词库中的每个词（按长度降序，避免短词先命中覆盖长词边界）
    for kw in sorted(keywords, key=len, reverse=True):
        if kw in '0123456789' or any(u in kw for u in '十百千万'):
            continue  # 纯数字/中文单位词由上面数字规则处理，避免重复
        idx = 0
        while True:
            pos = text.find(kw, idx)
            if pos == -1:
                break
            for i in range(pos, pos + len(kw)):
                if i < n:
                    is_yellow[i] = True
            idx = pos + 1

    # 合并连续区间翻译为 length+location 格式
    items = []
    i = 0
    while i < n:
        if is_yellow[i]:
            start = i
            while i < n and is_yellow[i]:
                i += 1
            items.append({"length": i - start, "location": start})
        else:
            i += 1

    return items


def _extract_plain_text(txt):
    """递归解包：若 txt 本身是 JSON 字符串（双重嵌套），继续解析直到拿到纯文本。"""
    if not isinstance(txt, str):
        return txt
    s = txt.strip().lstrip('﻿')
    if s.startswith('{'):
        try:
            inner = json.loads(s)
            if isinstance(inner, dict) and 'text' in inner:
                return _extract_plain_text(inner['text'])
        except Exception:
            pass
    return txt


def get_text(content):
    """提取字幕实际文本（支持 JSON rich text、dict、纯文本、双重嵌套）"""
    if isinstance(content, str) and content.startswith('{'):
        try:
            j = json.loads(content)
            return _extract_plain_text(j.get('text', ''))
        except:
            pass
    elif isinstance(content, dict):
        return _extract_plain_text(content.get('text', ''))
    elif isinstance(content, str):
        return content.replace('﻿', '')
    return ''


def _build_words(text, asr_words):
    """从 ASR 逐字数据生成剪映 words 字段 {start_time, end_time, text}。"""
    if not text or not asr_words:
        return None
    # 从 asr_words 提取覆盖该字幕文本的逐字数据
    chars = [w['text'] for w in asr_words if w.get('text')]
    starts = [int(w['start']) for w in asr_words if w.get('text')]
    ends = [int(w['end']) for w in asr_words if w.get('text')]
    if not chars:
        return None
    # 对齐文本：asr_words 的字可能带标点，过滤
    plain = ''.join(ch for ch in text if ch.strip())
    # 尝试在 chars 拼接里找 plain 的起始位置
    joined = ''.join(chars)
    try:
        start_idx = joined.index(plain)
        end_idx = start_idx + len(plain)
    except ValueError:
        # 找不到精确匹配，用全部（比例不精确但结构正确）
        return {
            'start_time': starts,
            'end_time': ends,
            'text': chars,
        }
    # 截取对应区间
    sel_starts, sel_ends, sel_text = [], [], []
    cur = 0
    for w, st, en in zip(chars, starts, ends):
        wlen = len(w)
        w_end = cur + wlen
        if w_end > start_idx and cur < end_idx:
            sel_text.append(w)
            sel_starts.append(st)
            sel_ends.append(en)
        cur = w_end
    if sel_text:
        return {'start_time': sel_starts, 'end_time': sel_ends, 'text': sel_text}
    return None


def _fill_native_fields(tx, font_id, font_path, font_list):
    """补全剪映原生字幕素材字段（对齐剪映自建字幕模板）。

    剪映打开草稿时，若字幕素材缺少原生字段（background/shadow/typesetting等），
    会判定为"外部导入的不完整富文本"，重新解析 content 并二次序列化，
    导致字幕显示 JSON 代码。补全这些字段后剪映识别为自建字幕，不再重写。
    """
    defaults = {
        'alignment': 1,
        'background_alpha': 1.0,
        'background_color': '#000000',
        'background_height': 0.14,
        'background_horizontal_offset': 0.0,
        'background_round_radius': 0.0,
        'background_style': 0,
        'background_vertical_offset': 0.0,
        'background_width': 0.14,
        'bold_width': 0.0,
        'border_alpha': 1.0,
        'border_color': '#000000',
        'border_width': 0.08,
        'check_flag': 15,
        'fixed_height': -1.0,
        'fixed_width': -1.0,
        'font_category_id': '',
        'font_category_name': '',
        'font_id': '',
        'font_name': '',
        'font_path': font_path,
        'font_resource_id': font_id,
        'font_size': 10.0,
        'font_source_platform': 0,
        'font_team_id': '',
        'font_title': 'none',
        'font_url': '',
        'force_apply_line_max_width': False,
        'global_alpha': 1.0,
        'has_shadow': False,
        'initial_scale': 1.0,
        'inner_padding': -1.0,
        'is_rich_text': False,
        'italic_degree': 0,
        'ktv_color': '',
        'language': '',
        'layer_weight': 1,
        'letter_spacing': 0.0,
        'line_feed': 1,
        'line_max_width': 0.82,
        'line_spacing': 0.02,
        'multi_language_current': 'none',
        'name': '',
        'original_size': [],
        'preset_category': '',
        'preset_category_id': '',
        'preset_has_set_alignment': False,
        'preset_id': '',
        'preset_index': 0,
        'preset_name': '',
        'recognize_type': 0,
        'relevance_segment': [],
        'shadow_alpha': 0.9,
        'shadow_angle': -45.0,
        'shadow_color': '',
        'shadow_distance': 5.0,
        'shadow_point': {'x': 0.6363961030678928, 'y': -0.6363961030678928},
        'shadow_smoothing': 0.45,
        'shape_clip_x': False,
        'shape_clip_y': False,
        'source_from': '',
        'style_name': '',
        'sub_type': 0,
        'subtitle_template_original_fontsize': 0.0,
        'text_alpha': 1.0,
        'text_color': '#ffffff',
        'text_preset_resource_id': '',
        'text_size': 30,
        'text_to_audio_ids': [],
        'tts_auto_update': False,
        'type': 'subtitle',
        'typesetting': 0,
        'underline': False,
        'underline_offset': 0.22,
        'underline_width': 0.05,
        'use_effect_default_color': True,
    }
    defaults['fonts'] = font_list
    for k, v in defaults.items():
        if tx.get(k) in (None, ''):
            tx[k] = v
    # 动态字段单独处理
    tx['add_type'] = 1
    tx['combo_info'] = {'text_templates': []}
    if not tx.get('caption_template_info'):
        tx['caption_template_info'] = {
            'category_id': '', 'category_name': '', 'effect_id': '',
            'is_new': False, 'path': '', 'request_id': '',
            'resource_id': '', 'resource_name': '', 'source_platform': 0,
        }


_TEMPLATE_SHELL = None
_TEMPLATE_CONFIG = None
_STYLE_TEMPLATE_DIR = None


def _resolve_style_template():
    """解析当前激活的风格模板目录（模板隔离）。

    优先级：
      1. 环境变量 REALCUT_STYLE（临时指定风格名）
      2. style_config.json 的 default_style（默认风格）
      3. 回退 com.lveditor.draft/模板（旧版行为）

    风格名 → 模板目录：styles_dir/<风格名>模板（如 风格2 → 风格2模板）。
    若指定风格模板不存在，回退到 com.lveditor.draft/模板。
    """
    global _STYLE_TEMPLATE_DIR
    if _STYLE_TEMPLATE_DIR is not None:
        return _STYLE_TEMPLATE_DIR

    import os as _os
    # 1. 环境变量
    style = _os.environ.get('REALCUT_STYLE', '')
    # 2. style_config.json
    if not style:
        cfg_file = Path(os.environ.get('REALCUT_DRAFT_ROOT', r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft')).parent / 'style_config.json'
        if cfg_file.exists():
            try:
                with open(cfg_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                style = cfg.get('default_style', '')
            except Exception:
                pass
    # 3. 解析模板目录
    if style:
        if style == '\u6a21\u677f1':
            tmpl = Path(os.environ.get('REALCUT_DRAFT_ROOT', r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft')) / '\u6a21\u677f1'
            if tmpl.exists() and (tmpl / 'draft_content.json').exists():
                _STYLE_TEMPLATE_DIR = tmpl
                print(f'[模板] 使用风格模板: {tmpl.name}')
                return tmpl
        styles_dir = Path(os.environ.get('REALCUT_STYLE_LIB', r'D:/10  jianyin/JianyingPro Drafts'))
        tmpl = styles_dir / f'{style}模板'
        if tmpl.exists() and (tmpl / 'draft_content.json').exists():
            _STYLE_TEMPLATE_DIR = tmpl
            print(f'[模板] 使用风格模板: {tmpl.name}')
            return tmpl
    # 回退
    _STYLE_TEMPLATE_DIR = Path(os.environ.get('REALCUT_DRAFT_ROOT', r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft')) / '模板'
    return _STYLE_TEMPLATE_DIR


def _load_template_json(tmpl_dir):
    """读取模板草稿内容，支持加密格式自动降级。

    优先读 draft_content.json（明文）；若加密（非 { 开头），
    依次尝试 template.json.bak、draft_info.json（10.0/剪映可能把完整数据存这里）。
    """
    dc = tmpl_dir / 'draft_content.json'
    if not dc.exists():
        return None
    raw = dc.read_bytes()[:10]
    if raw.startswith(b'{'):
        from _utils import rewrite_pkg_asset_paths
        return rewrite_pkg_asset_paths(json.load(open(dc, encoding='utf-8')))
    # 加密 → 依次尝试明文兜底
    for fn in ['template.json.bak', 'draft_info.json']:
        p = tmpl_dir / fn
        if p.exists():
            try:
                r = p.read_bytes()[:10]
                if r.startswith(b'{'):
                    return json.load(open(p, encoding='utf-8'))
            except Exception:
                continue
    return None


def _load_template_shell():
    """读取剪映原生模板草稿的外壳字段（剪映能正常识别/打开的关键）。

    外部生成的草稿若外壳字段不完整（new_version/platform/canvas_config等），
    剪映首次打开会重新解析并二次序列化 content，导致字幕显示 JSON 代码。
    用原生模板外壳覆盖后，剪映识别为正常草稿，不再重写 content。
    """
    global _TEMPLATE_SHELL, _TEMPLATE_CONFIG
    if _TEMPLATE_SHELL is not None:
        return True
    tmpl = _resolve_style_template()
    dc = tmpl / 'draft_content.json'
    if not dc.exists():
        print('[外壳] 未找到模板草稿，跳过外壳修复')
        return False
    try:
        t = _load_template_json(tmpl)
        if t is None:
            print('[外壳] 模板读取失败（明文与template.json.bak均不可用）')
            return False
        SHELL_FIELDS = [
            'new_version', 'platform', 'canvas_config', 'color_space',
            'source', 'render_index_track_mode_on', 'last_modified_platform',
            'free_render_index_mode_on', 'keyframe_graph_list', 'relationships',
            'mutable_config', 'group_container', 'time_marks', 'cover',
            'static_cover_image_path', 'create_time', 'update_time',
        ]
        _TEMPLATE_SHELL = {k: t[k] for k in SHELL_FIELDS if k in t}
        _TEMPLATE_CONFIG = t.get('config')
        return True
    except Exception as e:
        print(f'[外壳] 模板读取失败: {e}')
        return False


def _apply_template_shell(draft):
    """把模板外壳字段套用到草稿（保留轨道/素材）。"""
    if not _load_template_shell():
        return
    for k, v in _TEMPLATE_SHELL.items():
        if k in draft:
            draft[k] = v
    if _TEMPLATE_CONFIG:
        draft['config'] = _TEMPLATE_CONFIG
    print('[外壳] 已套用模板外壳字段')


_TEMPLATE_FONT = None


def _load_template_font():
    """从模板草稿读取字幕字体（字语圆体等），替换硬编码江湖体。
    返回 dict: {font_id, font_path, font_list, font_size} 或 None。
    """
    global _TEMPLATE_FONT
    if _TEMPLATE_FONT is not None:
        return _TEMPLATE_FONT
    tmpl = _resolve_style_template()
    dc = tmpl / 'draft_content.json'
    if not dc.exists():
        print('[字体] 未找到模板草稿，用默认江湖体')
        return None
    try:
        t = _load_template_json(tmpl)
        if t is None:
            print('[字体] 模板读取失败，用默认江湖体')
            return None
        # 找 flag=1 字幕轨引用的 subtitle 素材
        sub_ids = set()
        for tr in t.get('tracks', []):
            if tr['type'] == 'text' and tr.get('flag') == 1:
                for s in tr.get('segments', []):
                    sub_ids.add(s.get('material_id', ''))
        for mat in t.get('materials', {}).get('texts', []):
            if mat['id'] in sub_ids and mat.get('type') == 'subtitle':
                _TEMPLATE_FONT = {
                    'font_id': mat.get('font_resource_id') or '7495689259223880202',
                    'font_path': mat.get('font_path') or '',
                    'font_list': mat.get('fonts') or [],
                    'font_size': mat.get('font_size') or 10.0,
                }
                print(f"[字体] 已加载模板字体: {_TEMPLATE_FONT['font_id'][:12]}...")
                return _TEMPLATE_FONT
    except Exception as e:
        print(f'[字体] 模板字体读取失败: {e}')
    return None


def _check_jianying_closed():
    """检测剪映是否正在运行。运行中写草稿会被后台覆盖，必须先关闭。"""
    try:
        import subprocess
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq JianyingPro.exe'],
                             capture_output=True, text=True, timeout=10).stdout
        if 'JianyingPro.exe' in out and 'INFO: No tasks' not in out:
            print('[警告] 检测到剪映正在运行！写草稿会被后台覆盖。')
            print('  请先执行: taskkill /f /im JianyingPro.exe')
            return False
    except Exception as e:
        print(f'[警告] 无法检测剪映进程: {e}，继续执行（风险：后台可能覆盖）')
    return True


def apply_style(draft_path):
    global FONT_ID, FONT_PATH, FONT_LIST
    if not _check_jianying_closed():
        print('已终止。关闭剪映后重跑步骤12。')
        sys.exit(1)

    # 从模板草稿加载字幕字体（字语圆体等），替换硬编码江湖体
    _tf = _load_template_font()
    if _tf:
        FONT_ID = _tf['font_id']
        FONT_PATH = _tf['font_path']
        FONT_LIST = _tf['font_list'] or FONT_LIST
        print(f'[字体] 步骤12使用模板字体: {FONT_ID[:12]}...')

    dp = Path(draft_path)
    with open(dp / 'draft_content.json', 'r', encoding='utf-8') as f:
        draft = json.load(f)

    # 加载 ASR 逐字数据（用于补全 words 字段，让剪映识别为原生富文本，避免二次序列化）
    asr_words = []
    asr_file = dp / 'asr_result.json'
    if asr_file.exists():
        try:
            with open(asr_file, 'r', encoding='utf-8') as f:
                asr_words = json.load(f).get('words', [])
        except Exception:
            asr_words = []

    # 加载关键词
    keywords = load_keywords()

    # 字幕 Y 归一化坐标 -0.4167（屏幕上方，对齐草稿104手动精调黄金值）
    POS_Y_NORMALIZED = -0.4166666666666667

    texts = draft['materials']['texts']
    HZ_NAMES = {'种草', '推荐指数', '爆款', '简洁又百搭', '日常穿搭', '福利来袭', '立即下单', '强推'}

    # 收集字幕轨 (flag=1) 的素材 ID
    subtitle_track_mat_ids = set()
    for t in draft['tracks']:
        if t['type'] == 'text' and t.get('flag') == 1:
            for s in t.get('segments', []):
                subtitle_track_mat_ids.add(s.get('material_id', ''))

    subtitle_texts = []
    for tx in texts:
        if tx.get('id') not in subtitle_track_mat_ids:
            continue
        txt = get_text(tx.get('content', ''))
        clean_txt = txt.strip().replace(chr(10), '').replace(chr(13), '')
        # 排除花字素材名（花字轨已被 subtitle_track_mat_ids 过滤，这里只防误入）
        if clean_txt not in HZ_NAMES:
            subtitle_texts.append(tx)

    applied = 0
    for tx in subtitle_texts:
        txt = get_text(tx.get('content', ''))
        if not txt:
            continue

        # 计算关键词标黄区间
        yellow_ranges = get_yellow_ranges(txt, keywords)

        # content 统一为 rich JSON（对齐模板精简格式，剪映正确渲染字体/字号/颜色）
        tx['content'] = build_rich_content(txt, yellow_ranges, FONT_ID, FONT_PATH, 10)
        tx['base_content'] = build_base_content(txt, FONT_ID, FONT_PATH, 10)

        # 样式属性
        tx['font_path'] = FONT_PATH
        tx['font_resource_id'] = FONT_ID
        tx['font_title'] = '江湖体'
        tx['fonts'] = copy.deepcopy(FONT_LIST)
        tx['font_size'] = 10.0
        tx['text_size'] = 30
        tx['text_color'] = '#ffffff'
        tx['text_alpha'] = 1.0
        # 对齐102手动格式：material 级描边保留 0.08（普通段描边），关键词段靠 style 级 strokes
        tx['border_color'] = '#000000'
        tx['border_width'] = 0.08
        tx['border_alpha'] = 1.0
        tx['is_rich_text'] = False
        tx['check_flag'] = 15
        tx['global_alpha'] = 1.0
        tx['alignment'] = 1

        # 预设样式
        tx['type'] = 'subtitle'
        tx['preset_index'] = 0
        tx['preset_id'] = ''
        tx['preset_name'] = ''
        tx['preset_category'] = ''
        tx['preset_category_id'] = ''
        tx['preset_has_set_alignment'] = False
        tx['sub_type'] = 0
        # 使用效果默认颜色（必须 True，False 会导致字幕不显示）
        tx['use_effect_default_color'] = True
        tx['font_title'] = 'none'
        tx['line_max_width'] = 0.82
        tx['line_spacing'] = 0.02
        tx['caption_template_info'] = {
            "category_id": "",
            "category_name": "",
            "effect_id": "",
            "is_new": False,
            "path": "",
            "request_id": "",
            "resource_id": "",
            "resource_name": "",
            "source_platform": 0
        }
        # ── 关键词高亮：写入 subtitle_keywords.range ──
        tx['subtitle_keywords'] = {"range": yellow_ranges}
        tx['subtitle_template_original_fontsize'] = 0.0

        # ── 补全剪映原生字幕字段（关键：避免剪映二次序列化 content）──
        # 剪映原生字幕都带 words 逐字时间戳 + add_type=1 + recognize_task_id。
        # 缺失这些字段时，剪映打开会判定为"外部导入的不完整富文本"，重新解析 content
        # 导致 content 被二次序列化成 {"text":"{\"text\":...}"}，字幕显示 JSON 代码。
        import uuid as _uuid
        tx['add_type'] = 1
        if not tx.get('recognize_task_id'):
            tx['recognize_task_id'] = str(_uuid.uuid4())
        if not tx.get('group_id'):
            tx['group_id'] = f'Auto_{int(_uuid.uuid1().time)}'
        tx['layer_weight'] = 1
        tx['initial_scale'] = 1.0
        # words：尝试从 ASR 逐字数据生成（找不到就用 content 文本按比例分）
        if not (tx.get('words', {}) or {}).get('text'):
            _wt = _build_words(txt, asr_words)
            if _wt:
                tx['words'] = _wt

        # 打印高亮信息
        preview = txt[:25].strip('\ufeff')
        yellow_texts = [txt[r['location']:r['location']+r['length']] for r in yellow_ranges]
        print(f'  [{preview}...] -> yellow: {yellow_texts}')
        applied += 1

    # 强制字幕轨道段 Y=-0.4167（只改 flag=1 字幕轨，花字/风格文字轨保持原样）
    for t in draft['tracks']:
        if t['type'] != 'text':
            continue
        if t.get('flag') != 1:
            continue  # 花字/风格文字轨（flag=0）不动
        segs = t.get('segments', [])
        if not segs:
            continue
        for s in segs:
            clip = s.get('clip', {})
            if clip:
                clip['transform']['y'] = POS_Y_NORMALIZED
                clip['transform']['x'] = 0.0

    # ── 关键字预设样式：写入顶层 config.subtitle_keywords_config ──
    # 剪映用 subtitle_keywords.range 定义关键字，用此 config 定义关键字样式。
    # 颜色不对齐草稿104黄金格式：黄 [1.0,0.8705882430076599,0.0] + 细黑描边 + 字号10.4
    _kw_styles_json = json.dumps({
        'styles': [{
            'fill': {'alpha': 1.0,
                     'content': {'render_type': 'solid',
                                 'solid': {'alpha': 1.0, 'color': [1.0, 0.8705882430076599, 0.0]}}},
            'range': [0, 11],
            'size': 10.4,
            'strokes': [{'alpha': 1.0,
                         'content': {'render_type': 'solid',
                                     'solid': {'alpha': 1.0, 'color': [0.0, 0.0, 0.0]}},
                         'width': 0.06}],
            'useLetterColor': True,
        }],
        'text': 'placeholder',
    }, ensure_ascii=False)
    draft.setdefault('config', {})['subtitle_keywords_config'] = {
        'font_size_ratio': 1.3,
        'styles': _kw_styles_json,
        'subtitle_template_keywords_original_font_size': 0.0,
        'subtitle_template_original_font_size': 0.0,
    }

    # ── 套用剪映原生模板外壳（根治剪映首次打开二次序列化 content）──
    _apply_template_shell(draft)

    write_draft(dp, draft)

    print(f'\n已处理 {applied} 条字幕 (font_size=10, y={POS_Y_NORMALIZED}, 关键词高亮已应用)')
    print(f'subtitle_keywords.range 已写入手稿（剪映原生高亮）')
    print(f'subtitle_keywords_config 黄色样式已写入 config')
    print(f'归一化Y: {POS_Y_NORMALIZED}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    apply_style(sys.argv[1])
