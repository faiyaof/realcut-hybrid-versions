# -*- coding: utf-8 -*-
"""步骤7：生成字幕（v4 - 最终完整语音轨 ASR + AI 整段审核）
用法: python "步骤7-生成字幕.py" <草稿路径>
"""
import json, sys, subprocess, re, os, shutil, io
from datetime import datetime
from pathlib import Path
from _funasr import recognize_audio
from _runtime_deps import import_external

# 保证 stdout 以 UTF-8 输出中文（父进程按 UTF-8 读取）
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

enable_review = '--no-review' not in sys.argv[1:]
dp = Path(next((a for a in sys.argv[1:] if not a.startswith('--')), '.'))
draft_path = dp / 'draft_content.json'
asr_path = dp / 'asr_result.json'
seg_meta_path = dp / 'step4_segments.json'

# ── 加载数据 ──
with open(draft_path, encoding='utf-8') as f:
    draft = json.load(f)

# 防御：无音频轨直接明确报错退出，不 IndexError
_audio_tracks = [t['segments'] for t in draft['tracks'] if t['type'] == 'audio']
if not _audio_tracks or not _audio_tracks[0]:
    print(f'错误: 草稿无音频轨道（{draft_path}），无法生成字幕。请先运行 步骤2-分离音频。')
    sys.exit(1)
audio_segs = _audio_tracks[0]
audio_mats = {m['id']: m for m in draft['materials']['audios']}

with open(asr_path, 'r', encoding='utf-8') as f:
    asr = json.load(f)
words = asr.get('words', [])

seg_meta = []
if seg_meta_path.exists():
    with open(seg_meta_path, 'r', encoding='utf-8') as f:
        seg_meta = json.load(f)

seg_meta_by_clip = {}
for sm in seg_meta:
    idx = sm.get('index')
    cat = sm.get('category')
    if idx is not None and cat:
        seg_meta_by_clip.setdefault(f'clip_{idx:02d}_{cat}.mp3', sm)


def get_words_in_range(start_ms, end_ms):
    result = []
    for w in words:
        if w['end'] > start_ms and w['start'] < end_ms:
            result.append(w)
    return result


def split_text_only(text):
    """jieba 词边界断句：断点尽量落在词边界，保护数字/价格不拆开。"""
    if not text:
        return []
    MAX_CHARS = 10  # 每段字幕≤10字，更美观
    # 中文数字转阿拉伯后可能带 '/'（如 3000/4000），这类组合整体保留
    sentences = re.split(r'[。？！.!?]', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    parts = []
    for s in sentences:
        if len(s) <= MAX_CHARS:
            parts.append(s)
            continue
        subs = re.split(r'[，、；,;]', s)
        for sub in subs:
            sub = sub.strip()
            if not sub:
                continue
            if len(sub) <= MAX_CHARS:
                parts.append(sub)
                continue
            parts.extend(_split_long_sub(sub, MAX_CHARS))
    if not parts:
        return []
    return _merge_and_clean(parts, MAX_CHARS)


def ai_segment_text(text, max_chars=10, max_retries=2):
    """
    用千问 AI 断句 + 定关键词 + 修错别字，返回 (segments, keywords)。
    segments: 断好的字幕段落列表（每段<=max_chars字，语义通顺）
    keywords: 推荐标黄的关键词列表
    AI 不可用时返回 (None, None)，调用方回退 jieba 断句。
    """

    prompt = (
        '你是一位拥有多年电商直播话术编辑经验的字幕编辑，精通直播带货表达、平台合规和短句节奏。把下面的口播文本处理成适合字幕展示的短句。\n'
        f'要求：\n'
        f'1. 断句：把文本切成若干短句，每句不超过{max_chars}个字。\n'
        '   若整段本身<=10字，直接输出为1句，不要拆分；\n'
        f'   若超过{max_chars}字，断在意思完整处，每句都尽可能接近{max_chars}字但不超过；\n'
        '2. 必须保留原文所有文字和顺序，只允许修正明显错别字（如"伤残"到"桑蚕丝"、"双抽"到"上车"）'
        '和口语数字转阿拉伯（"二百"到"200"），不得增删改写原文；\n'
        '3. 合规过滤：不得出现“南沙港”“中检仓”“泰国”等违禁词，也不得出现“最”“第一”“绝对”“必买”“秒杀”等过于绝对的词；\n'
        '4. 标记关键词：挑出1-4个最能吸引观众的重点词（价格、面料、卖点、互动词），'
        '必须是原文出现的词或数字，用于字幕标黄。不要输出单字虚词，也不要输出违禁词或过于绝对的词；\n'
        '只输出 JSON，不要任何其他文字。格式：\n'
        '{"segments": ["句1", "句2", ...], "keywords": ["词1", "词2", ...]}\n'
        f'待处理文本：{text}'
    )
    from _llm import llm_text_with_provider
    content, provider = llm_text_with_provider(prompt, temperature=0.1, json_mode=True)
    if not content:
        print('  [AI] LLM 不可用，回退本地断句')
        return None, None
    print(f'  [AI] 断句模型: {provider}')
    try:
        content = content.strip()
        if content.startswith('```'):
            content = re.sub(r'^```\w*\n?|\n?```$', '', content)
        j = json.loads(content)
        segs = [s.strip() for s in j.get('segments', []) if s.strip()]
        kws = [k.strip() for k in j.get('keywords', []) if k.strip()]
        _joined = ''.join(segs)
        _orig_chars = set(text)
        _fidelity = sum(1 for ch in _joined if ch in _orig_chars) / max(len(_joined), 1)
        if _fidelity < 0.85:
            print(f'  [AI] 文本保真度低({_fidelity:.0%})，回退本地')
            return None, None
        final_segs = []
        for s in segs:
            if len(s) <= max_chars:
                final_segs.append(s)
            else:
                final_segs.extend(split_text_only(s))
        if final_segs:
            return final_segs, kws
    except Exception as e:
        print(f'  [AI] 断句失败({e})，回退本地')
    return None, None


def _split_long_sub(sub, max_chars):
    """超长子句按 jieba 词边界拆段。返回拆分后的片段列表。"""
    jieba = import_external('jieba')
    # 预分词，得到 (词, 起点, 终点) 列表；标点/空白作为独立边界符处理
    tokens = []
    pos = 0
    for w in jieba.cut(sub, HMM=True):
        if not w:
            continue
        w = w.strip()
        if not w:
            continue
        idx = sub.find(w, pos)
        if idx == -1:
            idx = pos
        tokens.append((w, idx, idx + len(w)))
        pos = idx + len(w)

    if not tokens:
        return [sub]

    # 词边界集合：每个词的起点（词尾可断）。单字虚词优先吸收到前段
    word_starts = {t[1] for t in tokens}
    word_ends = {t[2] for t in tokens}
    n = len(sub)

    def _num_unit(pos_):
        """pos 前面紧贴数字或数量词时不断开（避免拆散 3000/4000、20个）。"""
        if pos_ < 1:
            return True
        if sub[pos_ - 1].isdigit():
            return True
        if sub[pos_:pos_ + 1] == '/' and pos_ + 1 < n and sub[pos_ + 1].isdigit():
            return True
        return False

    def _good_cut(pos_):
        """pos_ 是否为优质断点：落在词边界 + 不在数字/斜杠内。"""
        if pos_ >= n or pos_ < 1:
            return True
        if sub[pos_ - 1].isdigit() or (pos_ < n and sub[pos_].isdigit()):
            return False
        if sub[pos_] == '/':
            return False
        if _num_unit(pos_):
            return False
        return pos_ in word_starts

    result = []
    cur = 0
    # 虚词开头的段应吸回前段（避免 '的衣服'、'的限量版' 开头）
    FUNC_HEAD = '的了着过在和与是有那就才也还把被地得而或者因为所以如果但是虽然可很'
    # 量词/单位开头的段也应吸回（避免 '块的衣服'、'件的衣服' 开头）
    QUANT_HEAD = '块元个件斤克天号条双件套张匹顶枚颗'

    while len(sub) - cur > max_chars:
        hi = cur + max_chars
        # 在 [cur+1, hi] 内找最右的优质断点；找不到则退到任意词边界，再不行就硬切
        cut = -1
        for p in range(hi, cur, -1):
            if _good_cut(p):
                cut = p
                break
        if cut == -1:
            for p in range(hi, cur, -1):
                if p in word_ends or p in word_starts:
                    cut = p
                    break
        if cut == -1 or cut <= cur:
            cut = hi
        # 断点后若紧贴虚词开头，尝试把虚词之前的词边界作为断点（保持语义完整）
        if cut < n and sub[cut] in FUNC_HEAD:
            for p in range(cut - 1, cur, -1):
                if p in word_ends:
                    cut = p
                    break
        # 切割点后只剩 ≤2 字：先正常落当前段，再把剩余小尾巴并入前段（合并后不超限才并）
        if len(sub) - cut <= 2 and cut - cur >= 2:
            result.append(sub[cur:cut])
            tail_remain = sub[cut:]
            if len(result[-1]) + len(tail_remain) <= max_chars:
                result[-1] += tail_remain
            else:
                result.append(tail_remain)
            cur = len(sub)
            continue
        result.append(sub[cur:cut])
        cur = cut
    if cur < len(sub):
        # 尾段过短（≤2字）且前段非空：并入前段，避免孤立字尾（如"赶紧来"+"抢"）
        tail = sub[cur:]
        if len(tail) <= 2 and result and len(result[-1]) + len(tail) <= max_chars + 3:
            result[-1] += tail
        elif tail[0] in FUNC_HEAD or tail[0] in QUANT_HEAD:
            if result and len(result[-1]) + len(tail) <= max_chars + 3:
                result[-1] += tail
                return [r for r in result if r.strip()]
            result.append(tail)
        else:
            result.append(tail)
    return [r for r in result if r.strip()]


def _merge_and_clean(parts, max_chars):
    """清理 + 小片段合并 + 数字粘连。"""
    final_parts = []
    cn_num_chars = set('零一二三四五六七八九两')
    cn_unit_chars = set('十百千万')
    merged_parts = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if (merged_parts and (merged_parts[-1][-1] in cn_num_chars or merged_parts[-1][-1] in cn_unit_chars)
                and (p[0] in cn_num_chars or p[0] in cn_unit_chars)):
            merged_parts[-1] += p
        else:
            merged_parts.append(p)
    for p in merged_parts:
        if final_parts and len(p) <= 3 and len(final_parts[-1]) + len(p) <= max_chars:
            final_parts[-1] = final_parts[-1] + p
        else:
            final_parts.append(p)
    return [p for p in final_parts if p.strip()]


def assign_timing_from_words(text_pieces, seg_words, src_start_ms, target_start_ms):
    if not seg_words:
        return None
    full_text = ''.join(text_pieces)
    # Build character timing from ASR words
    char_timing = []  # [(char, start_ms, end_ms)]
    for w in seg_words:
        wt = w['text'].strip()
        if wt in '，。？！、；：""''「」（）,.;:!?':
            continue
        for ch in wt:
            ch_dur = (w['end'] - w['start']) / max(len(wt), 1)
            ch_start = w['start'] + (wt.index(ch) if ch in wt else 0) * ch_dur
            char_timing.append((ch, int(ch_start), int(ch_start + ch_dur)))
    if not char_timing:
        return None
    # 中文数字转阿拉伯后字符数会变化，逐字对齐不可靠，交给比例分时
    if any(c.isdigit() for c in full_text) and len(full_text) != len(char_timing):
        return None
    result = []
    char_idx = 0
    for piece in text_pieces:
        piece_start = None
        piece_end = None
        for ch in piece:
            if ch.strip() and char_idx < len(char_timing):
                if piece_start is None:
                    piece_start = char_timing[char_idx][1]
                piece_end = char_timing[char_idx][2]
                char_idx += 1
            elif not ch.strip():
                char_idx += 1
        if piece_start is not None and piece_end is not None:
            offset = target_start_ms - src_start_ms
            result.append((piece, piece_start + offset, piece_end + offset))
    return result if result else None


def split_subtitle_proportional(text, total_dur_ms):
    if not text:
        return []
    pieces = split_text_only(text)
    if not pieces:
        return []
    total_chars = sum(len(p) for p in pieces)
    if total_chars == 0:
        return []
    result = []
    start = 0
    for p in pieces:
        ratio = len(p) / total_chars
        dur = int(total_dur_ms * ratio)
        result.append((p, start, start + dur))
        start += dur
    return result


def distribute_pieces_proportional(pieces, total_dur_ms):
    """保留已断好的字幕短句，仅按短句长度比例分配整段时间。"""
    if not pieces or total_dur_ms <= 0:
        return []
    total_chars = sum(len(p) for p in pieces)
    if total_chars == 0:
        return []
    result = []
    start = 0
    for p in pieces:
        ratio = len(p) / total_chars
        dur = int(total_dur_ms * ratio)
        result.append((p, start, start + dur))
        start += dur
    return result


# ── 违禁词 ──
BANNED_WORDS = ['南沙港','中检仓','泰国',
                '最便宜','最低价','最先进','最后一件','最后一波','最后一轮','绝无仅有',
                '第一','唯一','第一个','全网第一','销量第一','排名第一','独一无二','首个','首选',
                '极品','极致','顶级','顶极','极佳','终极','国家级','世界级',
                '绝对','史上','全网最','全国最','全球最','秒杀','必买','必入',
                '稳赚','保本','保底','稳盈','躺赚','日赚','月入过万','翻倍','一夜暴富','财富自由',
                '丰胸','减肥','瘦脸','瘦身','增高','长高','防癌','抗癌','生发']

# ── 错别字修正映射表（ASR 误识 → 正确） ──
# 按长度降序匹配，避免短词误替换长词的一部分。
# 例: '桑蚕丝' 必须先于 '蚕丝'，'老板娘' 必须先于 '老板'。
# 用户可按需追加：每次跑步骤7自动生效。
TYPO_MAP = {
    # ── 已确立（2026-06-04 参考文档） ──
    '一线纯': '一线成衣',
    '盒子纱': '盒子衫',
    '伤残': '桑蚕丝',
    '最好的回忆': '最好的回应',
    '最好的礼物': '最好的回应',
    # ── 带货/直播常见误识（2026-08-06 补充） ──
    '风骨意': '缝工艺',
    '双抽': '上车',
    '使百九像': '使百九像',   # 占位：此条按实际内容另修，勿删
}


def fix_typos(text):
    """修正 ASR 错别字，返回修正后的文本。"""
    if not text:
        return text
    # 长映射优先（按长度降序），避免短词误伤长词
    for wrong, right in sorted(TYPO_MAP.items(), key=lambda x: -len(x[0])):
        if wrong and wrong != right:
            text = text.replace(wrong, right)
    return text


HYBRID_ROOT = Path(os.environ.get('REALCUT_ROOT', Path(__file__).resolve().parents[3]))
GLOSSARY_FILE = HYBRID_ROOT / 'config' / 'subtitle_glossary.json'
OVERRIDE_FILE = HYBRID_ROOT / 'config' / 'subtitle_overrides.json'


def _read_json_file(path, default):
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception as exc:
        print(f'  [词表] 读取失败 {path}: {exc}')
    return default


def load_glossary():
    """加载领域保护词、硬替换和疑似词表。"""
    return _read_json_file(GLOSSARY_FILE, {'preserve': [], 'replace': [], 'suspicious': []})


def load_overrides():
    """加载人工 from->to 字幕覆盖项，可在不重跑 ASR 时修正个别句。"""
    data = _read_json_file(OVERRIDE_FILE, [])
    return data if isinstance(data, list) else []


def apply_glossary(text, glossary, changes=None):
    """按词表做长词优先的硬替换，并记录实际替换项。"""
    if not text or not isinstance(text, str):
        return text, (changes or [])
    entries = [e for e in glossary.get('replace', []) if isinstance(e, dict)]
    for entry in sorted(entries, key=lambda e: -len(str(e.get('wrong', '')))):
        wrong = str(entry.get('wrong', '') or '')
        right = str(entry.get('right', '') or '')
        if wrong and wrong != right and wrong in text:
            text = text.replace(wrong, right)
            if changes is not None:
                changes.append({'wrong': wrong, 'right': right, 'category': entry.get('category', '')})
    return text, (changes or [])


def apply_overrides(text, overrides):
    """按 subtitle_overrides.json 做人工 from->to 覆盖。"""
    if not text or not overrides:
        return text
    for item in overrides:
        if not isinstance(item, dict):
            continue
        from_text = str(item.get('from', '') or '')
        to_text = str(item.get('to', '') or '')
        if from_text and to_text and from_text in text:
            text = text.replace(from_text, to_text)
            print(f'  [人工覆盖] "{from_text}" -> "{to_text}"')
    return text


def _digit_tokens(text):
    return sorted(re.findall(r'\d+(?:\.\d+)?', text or ''))


def validate_review_candidate(original, candidate, glossary):
    """校验 AI 候选，返回 (是否接受, 可疑原因)。"""
    if not candidate:
        return False, 'AI输出为空'
    if _digit_tokens(original) != _digit_tokens(candidate):
        return False, 'AI改动价格或数字'
    if any(bw in candidate for bw in BANNED_WORDS):
        return False, 'AI候选含违禁词'
    for term in glossary.get('preserve', []):
        if term in original and term not in candidate:
            return False, f'AI删除了保护词:{term}'
    orig_chars = set(original)
    fidelity = sum(1 for ch in candidate if ch in orig_chars) / max(len(candidate), 1)
    if fidelity < 0.85:
        return False, f'AI保真度低于85%({fidelity:.0%})'
    if fidelity < 0.95 or abs(len(candidate) - len(original)) > 3:
        return True, f'AI修改幅度较大，建议人工确认({fidelity:.0%})'
    return True, ''


def write_subtitle_review(dp, items, ai_available=True, ai_provider=''):
    """写出字幕审校 JSON + Markdown，供 Web/CLI 人工复核。"""
    needs_review = [i for i in items if i.get('needs_review')]
    payload = {
        'schema_version': 1,
        'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'ai_available': ai_available,
        'ai_provider': ai_provider,
        'summary': {'total': len(items), 'needs_review': len(needs_review)},
        'items': items,
    }
    try:
        json_path = dp / 'subtitle_review.json'
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        md_lines = ['# 字幕审校清单', '', f'- 总条数: {len(items)}', f'- 需要复核: {len(needs_review)}', '']
        if needs_review:
            md_lines.append('## 需要复核')
            md_lines.append('')
            for item in needs_review:
                md_lines.append(f'- {item.get("start_ms", "?")}-{item.get("end_ms", "?")}ms: {item.get("raw", "")} -> {item.get("final", "")}（{item.get("reason", "")}）')
        (dp / 'subtitle_review.md').write_text('\n'.join(md_lines), encoding='utf-8')
        print(f'  [审校] 已生成 subtitle_review.json（总{len(items)}条，需复核{len(needs_review)}条）')
    except Exception as exc:
        print(f'  [审校] 写出失败: {exc}')


def fix_known_golden_quote(text):
    """修正已收录金句的 ASR 误识。目前内置金句36；后续新金句可在此追加。"""
    if not text:
        return text
    text = text.replace('我有勇气把这个奢裙裙就干到到厉害的人', '我有勇气把这个奢侈品全部干到几十块钱')
    text = text.replace('我有勇气把这个奢裙就干到到厉害的人', '我有勇气把这个奢侈品全部干到几十块钱')
    text = text.replace('我有勇气把这个奢裙就干到厉害的人', '我有勇气把这个奢侈品全部干到几十块钱')
    text = text.replace('把这个奢裙裙就干到到厉害的人', '把这个奢侈品全部干到几十块钱')
    text = text.replace('把这个奢裙就干到到厉害的人', '把这个奢侈品全部干到几十块钱')
    text = text.replace('把这个奢裙就干到厉害的人', '把这个奢侈品全部干到几十块钱')
    text = text.replace('把这个奢裙裙全部', '把这个奢侈品全部')
    text = text.replace('把这个奢裙全部', '把这个奢侈品全部')
    text = text.replace('把这个奢裙', '把这个奢侈品')
    text = text.replace('这个奢侈全部', '这个奢侈品全部')
    text = re.sub(r'勇气[，,、\s]+是给我们这个时代', '勇气是给我们这个时代', text)
    if '是给我们这个时代最好的回应' in text and '勇气是给我们这个时代' not in text:
        text = text.replace('是给我们这个时代最好的回应', '勇气是给我们这个时代最好的回应')
    elif '时代最好的回应' in text and '勇气是给我们这个时代' not in text:
        text = text.replace('时代最好的回应', '勇气是给我们这个时代最好的回应')
    return text


# 已收录金句36的固定断句，避免 AI 把已知金句切成病句
GOLDEN_QUOTE36_PIECES = [
    '勇气是给我们这个时代', '最好的回应', '我不是一个', '很厉害的人',
    '但是我告诉你们', '我有勇气把', '这个奢侈品', '全部干到几十块钱',
]

def split_with_known_golden_quote(text):
    """若句子命中金句36片段，按已知断句输出，前面/后面的杂音仍走 jieba。"""
    if not text:
        return []
    for start_piece in GOLDEN_QUOTE36_PIECES:
        idx = text.find(start_piece)
        if idx < 0:
            continue
        prefix = text[:idx].strip('，。！？、；：,.!?;: ')
        parts = split_text_only(prefix) if prefix else []
        remaining = text[idx:]
        matched = []
        for piece in GOLDEN_QUOTE36_PIECES:
            if remaining.startswith(piece):
                matched.append(piece)
                remaining = remaining[len(piece):]
        if matched:
            parts.extend(matched)
            rest = remaining.strip('，。！？、；：,.!?;: ')
            if rest:
                parts.extend(split_text_only(rest))
            return parts
    return []



def chinese_num_to_arabic(text):
    """Replace Chinese numerals with Arabic. 三百二十五 -> 325, 六千九 -> 6900"""
    if not text: return text
    cn_d = {"零":0,"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"两":2}
    skip = {"百分百","一部分","一定","一起","一直","一般","一下","一点"}
    special = {"六千九":"6900","九千二":"9200","四千六":"4600","十几万":"10几万","几十万":"几十万","几万":"几万","几百万":"几百万","几千万":"几千万","几亿":"几亿","几百":"几百","几千":"几千"}
    special["几十"] = "几十"
    special["\u4e09\u56db\u5343"] = "3000/4000"
    cn_pat = re.compile(r"[零一二三四五六七八九两几十百千万]+")
    def _parse_num(s):
        if s and all(ch in cn_d for ch in s) and any(ch != '\u96f6' for ch in s):
            return ''.join(str(cn_d[ch]) for ch in s)
        val = 0; cur = 0; last_unit = 0
        for ch in s:
            if ch in cn_d:
                cur = cn_d[ch]
                continue
            if ch == '\u96f6':
                last_unit = 0
                continue
            unit = {'\u5341': 10, '\u767e': 100, '\u5343': 1000, '\u4e07': 10000}[ch]
            if cur == 0: cur = 1
            cur *= unit; val += cur; cur = 0; last_unit = unit
        if cur:
            if last_unit >= 100:
                val += cur * (last_unit // 10)
            else:
                val += cur
        return str(val) if val > 0 else s
    def _parse_phrase(s):
        if s in special: return special[s]
        if s in ("十","百","千","万"): return s  # single unit stays Chinese
        parts = s.split("几")
        result = ""
        for i, p in enumerate(parts):
            if p: result += _parse_num(p)
            if i < len(parts) - 1: result += "几"
        return result
    result = text; offset = 0
    for m in cn_pat.finditer(text):
        orig = m.group()
        is_skip = any(sw in orig or orig in sw for sw in skip)
        if is_skip: continue
        conv = _parse_phrase(orig)
        if conv != orig:
            s = m.start() + offset; e = m.end() + offset
            result = result[:s] + conv + result[e:]
            offset += len(conv) - len(orig)
    return result


# ══════════════════════════════════════════════════════════════
# v4：最终完整语音轨 ASR
# 音频排序、金句爆点加入完成后再跑整段 ASR，字幕时间天然对齐最终时间线。
# ══════════════════════════════════════════════════════════════

def get_speech_audio_segments(draft, dp):
    """从音频轨道中找出口播轨：优先选择含 clip_*.mp3 素材最多的 audio 轨道。"""
    audio_tracks = [t for t in draft.get('tracks', []) if t.get('type') == 'audio']
    if not audio_tracks:
        return []
    mats = {m['id']: m for m in draft.get('materials', {}).get('audios', [])}
    best, best_score = None, (-1, -1)
    for t in audio_tracks:
        segs = t.get('segments', []) or []
        clip_count = 0
        for s in segs:
            path = (mats.get(s.get('material_id', ''), {}).get('path', '') or '')
            base = os.path.basename(path.replace('\\', '/'))
            if base.startswith('clip_') or str(dp).lower() in str(path).lower():
                clip_count += 1
        score = (clip_count, len(segs))
        if score > best_score:
            best, best_score = t, score
    if best is None:
        best = audio_tracks[0]
    return best.get('segments', []) or []


def build_full_voice_audio(dp, draft):
    """把口播轨所有 clip 按 target 时间轴合成为一条完整语音轨，返回 (wav_path, fingerprint)。"""
    segs = get_speech_audio_segments(draft, dp)
    if not segs:
        return None, []
    mats = {m['id']: m for m in draft.get('materials', {}).get('audios', [])}
    sorted_segs = sorted(
        segs,
        key=lambda s: (s.get('target_timerange', {}).get('start', 0),
                       s.get('target_timerange', {}).get('duration', 0)),
    )
    inputs, filters, fingerprint = [], [], []
    for i, seg in enumerate(sorted_segs):
        tgt = seg.get('target_timerange', {}) or {}
        src = seg.get('source_timerange', {}) or {}
        mat = mats.get(seg.get('material_id', ''), {})
        path = mat.get('path', '') or ''
        if not path or not os.path.exists(path):
            print(f'  [FULL] 跳过缺失音频: {path}')
            continue
        src_start = int(src.get('start', 0) or 0)
        tgt_start = int(tgt.get('start', 0) or 0)
        dur = int(tgt.get('duration', 0) or 0)
        if dur <= 0:
            continue
        inputs += ['-ss', f'{src_start / 1000.0:.3f}', '-t', f'{dur / 1000.0:.3f}', '-i', path]
        filters.append(
            f'[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,'
            f'adelay={tgt_start // 1000}|{tgt_start // 1000}[a{i}]'
        )
        fingerprint.append({
            'mat': mat.get('id'),
            'src_start': src_start,
            'delay_ms': tgt_start // 1000,
            'tgt_start': tgt_start,
            'dur': dur,
            'mtime': int(os.path.getmtime(path)),
            'size': os.path.getsize(path),
        })
    if not filters:
        return None, []
    out_path = dp / '_full_voice.wav'
    ffmpeg = shutil.which('ffmpeg') or r'C:\ffmpeg\bin\ffmpeg.exe'
    if not os.path.exists(ffmpeg):
        print('  [FULL] 找不到 ffmpeg')
        return None, []

    def _build_cmd(mix_expr):
        return [ffmpeg, '-y', '-nostdin', '-loglevel', 'error'] + inputs + [
            '-filter_complex', ';'.join(filters + [mix_expr]),
            '-map', '[out]', '-ac', '1', '-ar', '16000', str(out_path),
        ]

    mix = ''.join(f'[a{i}]' for i in range(len(filters))) + \
          f'amix=inputs={len(filters)}:duration=longest:normalize=0[out]'
    r = subprocess.run(_build_cmd(mix), capture_output=True, text=True, timeout=900)
    if r.returncode != 0 and 'normalize' in (r.stderr or ''):
        mix = ''.join(f'[a{i}]' for i in range(len(filters))) + \
              f'amix=inputs={len(filters)}:duration=longest[out]'
        r = subprocess.run(_build_cmd(mix), capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not out_path.exists() or os.path.getsize(out_path) == 0:
        print('  [FULL] ffmpeg 合成完整语音轨失败: ' + (r.stderr or '')[-400:])
        return None, []
    print(f'  [FULL] 完整语音轨已生成: {out_path.name} ({len(filters)} 段)')
    return str(out_path), fingerprint


def load_full_asr(dp, fingerprint):
    cache_path = dp / '_full_voice_asr.json'
    if not cache_path.exists() or not fingerprint:
        return None, None
    try:
        with open(cache_path, encoding='utf-8') as f:
            cache = json.load(f)
        if (cache.get('fingerprint') == fingerprint
                and cache.get('words') and cache.get('sentences')):
            print('  [FULL] 复用整段 ASR 缓存')
            return cache['words'], cache['sentences']
    except Exception:
        pass
    return None, None


def save_full_asr(dp, fingerprint, words, sentences):
    try:
        with open(dp / '_full_voice_asr.json', 'w', encoding='utf-8') as f:
            json.dump({'fingerprint': fingerprint, 'words': words, 'sentences': sentences},
                      f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'  [FULL] ASR 缓存写入失败: {e}')


def ai_review_transcript(sentences, glossary=None):
    """对整段 ASR 结果做受限 AI 审核，带领域保护词和固定替换约束。"""
    glossary = glossary or {}
    if not sentences:
        return None
    preserve = [str(x) for x in glossary.get('preserve', []) if x]
    replace_entries = [e for e in glossary.get('replace', []) if isinstance(e, dict) and e.get('wrong') and e.get('right')]
    replace_desc = '、'.join(f'{e["wrong"]}→{e["right"]}' for e in replace_entries)
    numbered = '\n'.join(f'{i + 1}. {s.get("text", "")}' for i, s in enumerate(sentences))
    prompt = (
        '你是一位拥有多年电商直播话术编辑经验的字幕编辑，精通直播带货表达和平台合规审核。下面是一段由语音识别得到的字幕文本，已经按顺序编号。\n'
        '任务：只修正明显错别字、把口语数字转成阿拉伯数字、调整明显不通顺的词序；'
        '不得增删句子数量、不得合并或拆分句子、不得改变句子顺序、不得改写原意。\n'
        '合规要求：不得保留“南沙港”“中检仓”“泰国”等违禁词，也不得保留“最”“第一”“绝对”“必买”“秒杀”等过于绝对的词；\n'
        '只输出 JSON 数组，数组长度必须与输入相同，每个元素是对应编号修正后的句子文本。\n'
        f'待审核文本：\n{numbered}'
    )
    if preserve:
        prompt += '领域保护词必须原样保留，不得删除、不得改写：' + '、'.join(preserve) + '\n'
    if replace_desc:
        prompt += '以下固定替换必须执行：' + replace_desc + '\n'
    from _llm import llm_text_with_provider
    content, provider = llm_text_with_provider(prompt, temperature=0.1, json_mode=True)
    if not content:
        print('  [AI] 整段审核 LLM 不可用，回退本地修正')
        return None
    print(f'  [AI] 整段审核模型: {provider}')
    try:
        content = content.strip()
        if content.startswith('```'):
            content = re.sub(r'^```\w*\n?|\n?```$', '', content)
        j = json.loads(content)
        if isinstance(j, dict):
            j = j.get('sentences') or j.get('texts') or []
        if not isinstance(j, list):
            return None
        out = []
        review_reasons = {}
        for i, item in enumerate(j):
            if isinstance(item, dict):
                item = item.get('text') or item.get('sentence') or ''
            item = str(item).strip()
            if not item:
                continue
            original = sentences[i].get('text', '') if i < len(sentences) else ''
            accepted, reason = validate_review_candidate(original, item, glossary)
            if not accepted:
                print(f'  [AI] 句子{i + 1} 被拒收（{reason}），保留本地文本: {item!r}')
                item = original
            elif reason:
                review_reasons[i] = reason
            out.append(item)
        if len(out) != len(sentences):
            print(f'  [AI] 整段审核数量不匹配({len(out)}/{len(sentences)})，回退本地修正')
            return None
        return out, review_reasons, provider
    except Exception as e:
        print(f'  [AI] 整段审核失败({e})，回退本地修正')
        return None


def generate_subs_from_full_audio(dp, draft, review_enabled=True):
    """v4 主路径：完整语音轨 ASR → 整段审核 → 按最终时间轴断句生成字幕。"""
    full_path, fingerprint = build_full_voice_audio(dp, draft)
    if not full_path:
        print(' [FULL] 无法合成完整语音轨，回退逐段模式')
        return None, None

    full_words, full_sentences = load_full_asr(dp, fingerprint)
    if not full_sentences:
        print(' [FULL] 开始整段 FunASR ...')
        full_words, full_sentences = recognize_audio(full_path)
        if not full_sentences:
            print(' [FULL] 整段 ASR 失败，回退逐段模式')
            return None, None
        save_full_asr(dp, fingerprint, full_words, full_sentences)

    glossary = load_glossary()
    overrides = load_overrides()
    print(f' [FULL] ASR 句子 {len(full_sentences)} 条')
    for sent in full_sentences:
        raw_text = sent.get('text', '')
        sent['_raw'] = raw_text
        sent['text'] = fix_typos(raw_text)
        sent['text'] = fix_known_golden_quote(sent['text'])
        sent['text'] = apply_overrides(sent['text'], overrides)
        sent['text'], _glossary_changes = apply_glossary(sent['text'], glossary)
        sent['text'] = chinese_num_to_arabic(sent['text'])
        sent['_after_glossary'] = sent['text']
    ai_result = ai_review_transcript(full_sentences, glossary) if review_enabled else None
    reviewed = None
    review_reasons = {}
    review_provider = ''
    if ai_result is not None:
        reviewed, review_reasons, review_provider = ai_result
    subs = []
    ai_keywords_all = []
    review_items = []

    for idx, sent in enumerate(full_sentences):
        s_start = int(sent.get('start', 0))
        s_end = int(sent.get('end', s_start))
        if s_end <= s_start:
            continue
        s_text = sent.get('text', '').strip()
        if reviewed and idx < len(reviewed) and reviewed[idx]:
            fixed_text = reviewed[idx].strip()
            if fixed_text and fixed_text != s_text:
                print(f'  [AI] 句子{idx + 1}: "{s_text}" -> "{fixed_text}"')
                s_text = fixed_text
        if not s_text:
            continue

        text = fix_typos(s_text)
        if text != s_text:
            print(f'  [修正] "{s_text}" -> "{text}"')
        fixed2 = fix_known_golden_quote(text)
        if fixed2 != text:
            print(f'  [金句修正] "{text}" -> "{fixed2}"')
        text = fixed2
        text = apply_overrides(text, overrides)
        text, _glossary_changes = apply_glossary(text, glossary)
        text = chinese_num_to_arabic(text)
        final_text = text
        needs_review = False
        reason = review_reasons.get(idx, '')
        if reason:
            needs_review = True
        suspicious_hits = [s for s in glossary.get('suspicious', []) if s and (s in final_text or s in sent.get('_after_glossary', ''))]
        if suspicious_hits:
            needs_review = True
            reason = (reason + ('；' if reason else '') + '含疑似词:' + '、'.join(suspicious_hits))
        review_items.append({
            'index': idx + 1,
            'start_ms': s_start,
            'end_ms': s_end,
            'raw': sent.get('_raw', ''),
            'after_glossary': sent.get('_after_glossary', ''),
            'final': final_text,
            'needs_review': needs_review,
            'reason': reason,
        })

        sent_words = [w for w in full_words if w['end'] > s_start and w['start'] < s_end]
        known_pieces = split_with_known_golden_quote(text)
        ai_kws = []
        if known_pieces:
            pieces = known_pieces
        else:
            ai_pieces, ai_kws = ai_segment_text(text)
            pieces = ai_pieces if ai_pieces else split_text_only(text)
        if ai_kws:
            ai_keywords_all.extend(ai_kws)
        if not pieces:
            continue

        timed = assign_timing_from_words(pieces, sent_words, 0, 0)
        if timed is None or len(timed) < len(pieces):
            timed = distribute_pieces_proportional(pieces, s_end - s_start)
            timed = [(pt, s_start + ps, s_start + pe) for pt, ps, pe in timed]
            print(f'  [WARN] 句子{idx + 1} 无可靠逐字数据，按句内比例分时')
        else:
            print(f'  [OK] 句子{idx + 1} 逐字定位 ({len(sent_words)} 词)')

        for pt, abs_s, abs_e in timed:
            pt_clean = re.sub(r"[，。？！、；：“”‘’「」（）‘’，.!?;:()\[\]]", '', pt).strip()
            for bw in BANNED_WORDS:
                pt_clean = pt_clean.replace(bw, '')
            pt_clean = pt_clean.strip()
            if len(pt_clean) <= 1:
                continue
            if pt_clean in '嗯啊哦喔呢吗嘛哈嘿':
                continue
            if abs_e > s_end:
                abs_e = s_end
            if abs_s >= abs_e:
                continue
            subs.append((pt_clean, abs_s, abs_e))
            print(f'  字幕: {pt_clean} ({abs_s / 1000:.1f}s-{abs_e / 1000:.1f}s)')

    if review_enabled:
        write_subtitle_review(dp, review_items, ai_available=reviewed is not None, ai_provider=review_provider)
    return subs, ai_keywords_all


def generate_subs_legacy(dp, draft):
    """旧逐段模式兜底：原视频 ASR + 外部素材单独 ASR。"""
    subs = []
    ai_keywords_all = []
    glossary = load_glossary()
    overrides = load_overrides()
    for i, seg in enumerate(audio_segs):
        tgt = seg['target_timerange']
        target_start_ms = tgt['start'] // 1000
        target_dur_ms = tgt['duration'] // 1000

        meta = seg_meta[i] if i < len(seg_meta) else {}
        _mat = audio_mats.get(seg.get('material_id', ''), {})
        _fname = os.path.basename((_mat.get('path', '') or _mat.get('name', '')).replace('\\', '/'))
        meta = seg_meta_by_clip.get(_fname) or (seg_meta[i] if i < len(seg_meta) else {})
        src_start_ms = meta.get('src_start_ms', 0)
        src_end_ms = meta.get('src_end_ms', src_start_ms + target_dur_ms)
        src_dur_ms = src_end_ms - src_start_ms
        source_type = meta.get('source', 'asr')

        # ── 获取文本 ──
        text = ''
        if source_type == 'asr' and meta.get('text'):
            text = meta['text']

        file_asr_words = None
        file_asr_sentences = None
        if source_type == 'file':
            clip_mat = audio_mats.get(seg.get('material_id', ''), {})
            clip_path = clip_mat.get('path', '') or ''
            if not clip_path or not Path(clip_path).exists():
                cand = dp / f'clip_{i:02d}_{meta.get("category", "金句")}.mp3'
                if cand.exists():
                    clip_path = str(cand)
            if clip_path and Path(clip_path).exists():
                try:
                    file_asr_words, file_asr_sentences = recognize_audio(clip_path)
                except Exception as e:
                    print(f'  [ASR] 外部素材识别失败: {e}')
            if file_asr_sentences:
                review_input = []
                for sent in file_asr_sentences:
                    _review_text = re.sub(r'[，。？！、；：“”‘’「」（）(),.!?;:]', '', sent.get('text', '')).strip()
                    review_input.append({'text': chinese_num_to_arabic(_review_text)})
                file_reviewed = None
                _file_review = ai_review_transcript(review_input, glossary)
                if _file_review is not None:
                    file_reviewed, _, _ = _file_review
                joined = ''.join(w['text'] for w in file_asr_words) if file_asr_words else ''
                print(f'  [ASR] 外部素材实际音频: {joined[:60]}')
                for sent_idx, sent in enumerate(file_asr_sentences):
                    stext = re.sub(r'[，。？！、；：“”‘’「」（）(),.!?;:]', '', sent.get('text', '')).strip()
                    s_start = int(sent.get('start', 0))
                    s_end = int(sent.get('end', s_start))
                    if not stext:
                        continue
                    stext = chinese_num_to_arabic(stext)
                    if file_reviewed and sent_idx < len(file_reviewed) and file_reviewed[sent_idx]:
                        stext = file_reviewed[sent_idx].strip() or stext
                    fixed = fix_typos(stext)
                    if fixed != stext:
                        print(f'  [修正] "{stext}" -> "{fixed}"')
                    stext = fixed
                    fixed2 = fix_known_golden_quote(stext)
                    if fixed2 != stext:
                        print(f'  [金句修正] "{stext}" -> "{fixed2}"')
                    stext = fixed2
                    stext = apply_overrides(stext, overrides)
                    stext, _glossary_changes = apply_glossary(stext, glossary)
                    pieces = split_text_only(stext)
                    if not pieces:
                        continue
                    sent_words = [w for w in file_asr_words if w['end'] > s_start and w['start'] < s_end]
                    timed = assign_timing_from_words(pieces, sent_words, 0, target_start_ms)
                    if timed is None:
                        timed = split_subtitle_proportional(stext, s_end - s_start)
                        timed = [(pt, target_start_ms + ps, target_start_ms + pe) for pt, ps, pe in timed]
                        print('  [WARN] 句子无逐字数据，回退到比例分时')
                    else:
                        print(f'  [OK] 外部素材句子逐字定位 ({len(sent_words)} 词)')
                    seg_end_ms = target_start_ms + target_dur_ms
                    for pt, abs_s, abs_e in timed:
                        pt_clean = re.sub(r"[，。？！、；：“”‘’「」（）‘’，.!?;:()\[\]]", '', pt).strip()
                        for bw in BANNED_WORDS:
                            pt_clean = pt_clean.replace(bw, '')
                        pt_clean = pt_clean.strip()
                        if len(pt_clean) <= 1:
                            continue
                        if pt_clean in '嗯啊哦喔呢吗嘛哈嘿':
                            continue
                        if abs_e > seg_end_ms:
                            abs_e = seg_end_ms
                        if abs_s >= abs_e:
                            continue
                        subs.append((pt_clean, abs_s, abs_e))
                        print(f'  字幕: {pt_clean} ({abs_s/1000:.1f}s-{abs_e/1000:.1f}s)')
                continue
            else:
                text = meta.get('text', '')
                if text:
                    text = text.replace('[素材库] ', '').replace('[素材库]', '').strip()
                    text = re.sub(r'^(金句|爆点)\s*\d+\s*', '', text).strip()
        elif source_type == 'mirror':
            text = ''
        else:
            seg_words = get_words_in_range(src_start_ms, src_end_ms)
            text = ''.join(w['text'].strip() for w in seg_words) if seg_words else ''

        print(f'段{i} (src {src_start_ms/1000:.1f}s-{src_end_ms/1000:.1f}s, '
              f'tgt {target_start_ms/1000:.1f}s-{(target_start_ms+target_dur_ms)/1000:.1f}s): {text[:40] if text else "(无文本)"}')

        if not text:
            continue

        # 先转阿拉伯数字再断句，避免 3000/4000 这类转换把字幕撑超长
        text = chinese_num_to_arabic(text)

        # 错别字修正（ASR 误识 → 正确）
        fixed = fix_typos(text)
        if fixed != text:
            print(f'  [修正] "{text}" -> "{fixed}"')
        text = fixed
        fixed2 = fix_known_golden_quote(text)
        if fixed2 != text:
            print(f'  [金句修正] "{text}" -> "{fixed2}"')
        text = fixed2
        text = apply_overrides(text, overrides)
        text, _glossary_changes = apply_glossary(text, glossary)

        # ── 拆分字幕文本（优先 AI 断句，失败回退 jieba）──
        ai_keywords = []
        pieces = None
        if source_type != 'mirror':
            _ai_segs, _ai_kws = ai_segment_text(text)
            if _ai_segs:
                pieces = _ai_segs
                ai_keywords = _ai_kws or []
                print(f'  [AI] 断句成功 ({len(pieces)}段), 关键词: {ai_keywords}')
        if pieces is None:
            pieces = split_text_only(text)
        if ai_keywords:
            ai_keywords_all.extend(ai_keywords)
        if not pieces:
            continue

        # ── 分配时间戳 ──
        use_asr_timing = source_type == 'asr' or (source_type == 'file' and file_asr_sentences)
        if use_asr_timing:
            if source_type == 'file':
                seg_words = file_asr_words or []
                timed_pieces = assign_timing_from_words(pieces, seg_words, 0, target_start_ms)
            else:
                seg_words = get_words_in_range(src_start_ms, src_end_ms)
                timed_pieces = assign_timing_from_words(pieces, seg_words, src_start_ms, target_start_ms)
            if timed_pieces is None:
                timed_pieces = distribute_pieces_proportional(pieces, target_dur_ms)
                timed_pieces = [(pt, target_start_ms + ps, target_start_ms + pe) for pt, ps, pe in timed_pieces]
                print('  [WARN] 无逐字数据，回退到比例分时')
            else:
                print(f'  [OK] FunASR 逐字精确定位 ({len(seg_words)} 词)')
        else:
            timed_pieces = distribute_pieces_proportional(pieces, target_dur_ms)
            timed_pieces = [(pt, target_start_ms + ps, target_start_ms + pe) for pt, ps, pe in timed_pieces]
            print(f'  (外部素材，比例分时)')

        # ── 清理 & 输出 ──
        for pt, abs_s, abs_e in timed_pieces:
            pt_clean = re.sub(r"[，。？！、；：“”‘’「」（）‘’，.!?;:()\[\]]", '', pt).strip()
            for bw in BANNED_WORDS:
                pt_clean = pt_clean.replace(bw, '')
            pt_clean = pt_clean.strip()
            if len(pt_clean) <= 1:
                continue
            if pt_clean in '嗯啊哦喔呢吗嘛哈嘿':
                continue
            seg_end = target_start_ms + target_dur_ms
            if abs_e > seg_end:
                abs_e = seg_end
            if abs_s >= abs_e:
                continue
            subs.append((pt_clean, abs_s, abs_e))
            print(f'  字幕: {pt_clean} ({abs_s/1000:.1f}s-{abs_e/1000:.1f}s)')

    return subs, ai_keywords_all


# ── 主流程：优先完整语音轨 ASR，失败才逐段兜底 ──
subs, ai_keywords_all = generate_subs_from_full_audio(dp, draft, review_enabled=enable_review)
if subs is None:
    subs, ai_keywords_all = generate_subs_legacy(dp, draft)

print(f'\n共{len(subs)}条字幕')

# ── AI 关键词回写关键词库（供步骤12标黄）──
if ai_keywords_all:
    kw_file = Path(os.environ.get('REALCUT_KEYWORD_FILE', r'C:/Users/JT/Documents/剪辑/highlight_keywords.txt'))
    try:
        # 过滤噪声关键词：单字、虚词、无意义互动词
        noise = set('的了着过在和与是就把被地得而或有那就才也很啊哦嗯吧吗呢么上下中间')
        noise_words = {'搭','票','我家','秘密','看到吗','拿命','最后一场','真亚麻','整套搭配',
                       '不好拆','20天','300多','67元','超值'}
        clean_kws = []
        seen_kws = set()
        for kw in ai_keywords_all:
            kw = kw.strip()
            if not kw or len(kw) < 2 or len(kw) > 6:
                continue
            if kw in noise_words or any(ch in noise for ch in kw) or any(bw in kw for bw in BANNED_WORDS):
                continue
            if kw in seen_kws:
                continue
            seen_kws.add(kw)
            clean_kws.append(kw)
        if not clean_kws:
            print('  [AI] 关键词均被过滤（无有效新词）')
        else:
            if kw_file.exists():
                existing = kw_file.read_text(encoding='utf-8-sig').splitlines()
            else:
                existing = []
            existing_set = set()
            for l in existing:
                s = l.strip().lstrip('﻿')
                if s and not s.startswith('#') and not s.startswith('==='):
                    existing_set.add(s)
            added = [kw for kw in clean_kws if kw not in existing_set]
            if added:
                with open(kw_file, 'a', encoding='utf-8') as f:
                    if existing and existing[-1].strip():
                        f.write('\n')
                    f.write('\n# === AI 自动识别关键词 ===\n')
                    for kw in added:
                        f.write(kw + '\n')
                print(f'  [AI] 已追加 {len(added)} 个关键词到关键词库: {added}')
            else:
                print('  [AI] 关键词已存在，跳过追加')
    except Exception as e:
        print(f'  [AI] 关键词写入失败: {e}')

# ── 保存 ──
with open(dp / '字幕.txt', 'w', encoding='utf-8-sig') as f:
    for text, s, e in subs:
        text = chinese_num_to_arabic(text)
        f.write(f'{text} {s} {e}\n')

# ── 导入到剪映草稿 ──
import os as _os
_local_import = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '导入字幕.py')
_bin_dir = Path(_os.environ.get('REALCUT_BIN_DIR', HYBRID_ROOT / 'bin'))
_subtitle_binary = _bin_dir / 'import_subtitles.exe'
if _subtitle_binary.is_file():
    _subtitle_cmd = [str(_subtitle_binary), str(dp)]
else:
    _subtitle_import = _local_import if _os.path.exists(_local_import) else _os.environ.get('REALCUT_IMPORT_SUBTITLE_SCRIPT', _local_import)
    _subtitle_cmd = [sys.executable, _subtitle_import, str(dp)]
_r = subprocess.run(_subtitle_cmd, capture_output=True, text=True, encoding='utf-8')
if _r.returncode != 0:
    print('导入字幕失败（退出码 %s）:' % _r.returncode)
    print((_r.stdout or '')[-500:])
    print((_r.stderr or '')[-500:])
    print('字幕未导入草稿，请勿继续后续步骤；可重跑本步骤。')
    sys.exit(1)

print('导入完成！')
