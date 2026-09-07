"""原版步骤4-切割排序（v3加固版）"""

import json, sys, os, uuid, subprocess, shutil, re, copy, time, base64, hashlib
from _utils import write_draft
from _llm import llm_text_with_provider
from _price_roles import detect_price_roles
from _runtime_deps import import_external
from pathlib import Path

MIN_VIDEO_DURATION_MS = 15000  # 成片至少保留15秒有声口播
MAX_VIDEO_DURATION_MS = 45000  # 成片最长不超过45秒
SPEECH_UNIT_MIN_MS = 1000
SPEECH_UNIT_MAX_SPAN_MS = 6500
SPEECH_UNIT_MAX_GAP_MS = 400
VISUAL_RECOVERY_MAX_CANDIDATES = 6
FRAME_CACHE_HASH_BYTES = 256 * 1024
CATEGORY_MAX = {'爆点': 20, '痛点': 20, '展示衣服': 60, '金句': 1, '价格': 20, '原价': 1, '上车价': 1}
BANNED_TERMS = ('南沙港', '中检仓', '仓库', '货源', '终点站', '工厂')


def is_allowed_sentence(sentence):
    text = sentence.get('text', '') if isinstance(sentence, dict) else str(sentence or '')
    return not any(term in text for term in BANNED_TERMS)


def _sentence_duration_ms(sentence):
    return max(0, int(sentence.get('end', 0) or 0) - int(sentence.get('start', 0) or 0))


def _join_sentence_text(left, right):
    left = str(left or '').strip()
    right = str(right or '').strip()
    if not left:
        return right
    if not right:
        return left
    return left + right


def build_speech_units(sentences, max_gap_ms=SPEECH_UNIT_MAX_GAP_MS,
                       min_unit_ms=SPEECH_UNIT_MIN_MS,
                       max_span_ms=SPEECH_UNIT_MAX_SPAN_MS):
    """Merge adjacent ASR fragments without discarding spoken content.

    Natural pauses up to ``max_gap_ms`` stay inside the resulting source range.
    Banned and allowed text are never merged together, so an unsafe fragment
    cannot make a neighbouring safe sentence disappear with it.
    """
    normalized = []
    for original_idx, raw in enumerate(sentences or []):
        if not isinstance(raw, dict):
            continue
        start = int(raw.get('start', 0) or 0)
        end = int(raw.get('end', 0) or 0)
        text = str(raw.get('text', '') or '').strip()
        if end <= start or not text:
            continue
        item = dict(raw)
        item.update({
            'start': start,
            'end': end,
            'text': text,
            'sentence_ids': [original_idx],
            'speech_ms': end - start,
        })
        normalized.append(item)
    normalized.sort(key=lambda item: (item['start'], item['end']))
    if not normalized:
        return []

    units = []
    current = normalized[0]
    for item in normalized[1:]:
        gap_ms = item['start'] - current['end']
        combined_span_ms = item['end'] - current['start']
        can_merge = (
            0 <= gap_ms <= max_gap_ms
            and combined_span_ms <= max_span_ms
            and is_allowed_sentence(current) == is_allowed_sentence(item)
        )
        if can_merge:
            current['end'] = item['end']
            current['text'] = _join_sentence_text(current.get('text'), item.get('text'))
            current['sentence_ids'].extend(item['sentence_ids'])
            current['speech_ms'] += item['speech_ms']
        else:
            units.append(current)
            current = item
    units.append(current)

    if len(units) >= 2 and _sentence_duration_ms(units[-1]) < min_unit_ms:
        previous, tail = units[-2], units[-1]
        gap_ms = tail['start'] - previous['end']
        combined_span_ms = tail['end'] - previous['start']
        if (
            0 <= gap_ms <= max_gap_ms
            and combined_span_ms <= max_span_ms
            and is_allowed_sentence(previous) == is_allowed_sentence(tail)
        ):
            previous['end'] = tail['end']
            previous['text'] = _join_sentence_text(previous.get('text'), tail.get('text'))
            previous['sentence_ids'].extend(tail['sentence_ids'])
            previous['speech_ms'] += tail['speech_ms']
            units.pop()
    return units


def find_source_video(draft_path):
    for fname in os.listdir(str(draft_path)):
        fpl = fname.lower()
        if any(fpl.endswith(ext) for ext in ['.mp4', '.mkv', '.mov', '.avi', '.flv']):
            fp = os.path.join(str(draft_path), fname)
            if os.path.isfile(fp) and os.path.getsize(fp) > 1024:
                if not fpl.endswith('video_only.mp4'):
                    return fp
    for fname in os.listdir(str(draft_path)):
        if fname.lower().endswith(('.mp4', '.mkv')):
            return os.path.join(str(draft_path), fname)
    return None


def _quick_source_hash(src_video):
    size = os.path.getsize(src_video)
    digest = hashlib.sha256()
    with open(src_video, 'rb') as source:
        digest.update(source.read(FRAME_CACHE_HASH_BYTES))
        if size > FRAME_CACHE_HASH_BYTES:
            source.seek(max(0, size - FRAME_CACHE_HASH_BYTES))
            digest.update(source.read(FRAME_CACHE_HASH_BYTES))
    return digest.hexdigest()


def _frame_cache_meta_matches(meta, src_video, allow_different_path=False):
    if not isinstance(meta, dict):
        return False
    stat = os.stat(src_video)
    if meta.get('source_size') != stat.st_size:
        return False
    if meta.get('interval_seconds', 1) != 1:
        return False
    if meta.get('model', 'qwen-vl-plus') != 'qwen-vl-plus':
        return False
    expected_hash = meta.get('source_quick_hash')
    if expected_hash and expected_hash != _quick_source_hash(src_video):
        return False
    if not allow_different_path:
        expected_path = os.path.normcase(os.path.abspath(src_video))
        cached_path = os.path.normcase(os.path.abspath(meta.get('source_path', '')))
        if cached_path and cached_path != expected_path:
            return False
        cached_mtime = meta.get('source_mtime_ns')
        if cached_mtime is not None and cached_mtime != stat.st_mtime_ns:
            return False
    return True


def _read_frame_cache(cache_path):
    try:
        actions = json.loads(Path(cache_path).read_text(encoding='utf-8'))
        return actions if isinstance(actions, dict) else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def load_step6_frame_cache(draft_path, src_video):
    """Load current or same-source sibling 1s labels without importing step6."""
    draft = Path(draft_path)
    source = Path(src_video)
    current_cache = draft / '_frame_full_cache_1s.json'
    if current_cache.is_file():
        meta_path = Path(str(current_cache) + '.meta.json')
        try:
            compatible = (
                _frame_cache_meta_matches(
                    json.loads(meta_path.read_text(encoding='utf-8')), src_video
                )
                if meta_path.is_file()
                else current_cache.stat().st_mtime_ns >= source.stat().st_mtime_ns
            )
            if compatible:
                actions = _read_frame_cache(current_cache)
                if actions is not None:
                    print('  [VL] 复用当前草稿1秒画面缓存')
                    return actions
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    source_hash = None
    for cache_path in draft.parent.glob('*/_frame_full_cache_1s.json'):
        if cache_path.parent == draft:
            continue
        try:
            meta_path = Path(str(cache_path) + '.meta.json')
            if meta_path.is_file():
                meta = json.loads(meta_path.read_text(encoding='utf-8'))
                compatible = _frame_cache_meta_matches(
                    meta, src_video, allow_different_path=True
                )
            else:
                sibling_source = cache_path.parent / source.name
                if not sibling_source.is_file():
                    continue
                if sibling_source.stat().st_size != source.stat().st_size:
                    continue
                source_hash = source_hash or _quick_source_hash(src_video)
                compatible = (
                    cache_path.stat().st_mtime_ns >= sibling_source.stat().st_mtime_ns
                    and _quick_source_hash(str(sibling_source)) == source_hash
                )
            if not compatible:
                continue
            actions = _read_frame_cache(cache_path)
            if actions is not None:
                print(f'  [VL] 复用同源草稿1秒画面缓存: {cache_path.parent.name}')
                return actions
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return None


def _cached_frame_action(actions, midpoint_ms, max_distance_ms=1000):
    if not isinstance(actions, dict):
        return None
    numeric_actions = []
    for key, value in actions.items():
        try:
            numeric_actions.append((abs(int(key) - midpoint_ms), int(key), value))
        except (TypeError, ValueError):
            continue
    if not numeric_actions:
        return None
    distance_ms, _timestamp_ms, value = min(numeric_actions)
    if distance_ms > max_distance_ms:
        return None
    first_line = next(
        (line.strip() for line in str(value or '').splitlines() if line.strip()),
        '',
    )
    if first_line.startswith('展示中'):
        return '展示中'
    for label in ('丢掉', '其他商品', '开盒', '空手'):
        if first_line.startswith(label):
            return label
    return None

def visual_check_clothing_display(draft_path, sentences, discarded_indices, src_video):
    if not discarded_indices or not src_video or not os.path.exists(src_video):
        return []
    cached_actions = load_step6_frame_cache(draft_path, src_video)
    recls = []
    cloud_indices = []
    for idx in discarded_indices:
        sentence = sentences[idx]
        midpoint_ms = int((sentence['start'] + sentence['end']) / 2)
        cached_action = _cached_frame_action(cached_actions, midpoint_ms)
        if cached_action == '展示中':
            recls.append(idx)
            print(f'  [VL缓存] seg{idx}: 展示中 -> 改判展示衣服')
        elif cached_action is not None:
            print(f'  [VL缓存] seg{idx}: {cached_action} -> 仍抛弃')
        else:
            cloud_indices.append(idx)
    if not cloud_indices:
        return recls
    try:
        MultiModalConversation = import_external('dashscope').MultiModalConversation
    except ImportError:
        print('  [VL] dashscope not installed, skip visual check')
        return recls
    key = os.environ.get('DASHSCOPE_API_KEY', '')
    if not key:
        print('  [VL] DASHSCOPE_API_KEY not set, skip visual check')
        return recls
    print(f'  [VL] Checking {len(cloud_indices)} discarded segments for clothing display visually...')
    tmpdir = os.path.join(str(draft_path), '_vl_check_step4')
    os.makedirs(tmpdir, exist_ok=True)
    for idx in cloud_indices:
        s = sentences[idx]
        start_ms = s['start']
        end_ms = s['end']
        mid_s = (start_ms + end_ms) / 2000.0
        fp = os.path.join(tmpdir, f'seg{idx}.png')
        subprocess.run(['ffmpeg', '-y', '-ss', f'{mid_s:.3f}', '-i', src_video,
                       '-vframes', '1', '-q:v', '2', '-hide_banner', '-loglevel', 'error', fp],
                      capture_output=True, timeout=30)
        if not os.path.exists(fp) or os.path.getsize(fp) < 100:
            continue
        try:
            with open(fp, 'rb') as f:
                img_b64 = base64.b64encode(f.read()).decode('utf-8')
            resp = MultiModalConversation.call(
                model='qwen-vl-plus',
                messages=[{'role': 'user', 'content': [
                    {'image': 'data:image/png;base64,' + img_b64},
                    {'text': '主播有没有在展示、举起、拿着衣服展示细节？只回答其中一种：展示中(手举着/拿着展示衣服), 空手/其他(没拿衣服/空手比划/其他商品/丢掉)'}
                ]}],
                result_format='message'
            )
            if hasattr(resp, 'status_code') and resp.status_code == 200:
                c = resp.output.choices[0].message.content
                txt = c[0]['text'] if isinstance(c, list) and len(c) > 0 and isinstance(c[0], dict) else str(c)
                if '展示中' in txt or 'display' in txt.lower():
                    recls.append(idx)
                    print(f'  [VL] seg{idx} [{start_ms/1000:.1f}s-{end_ms/1000:.1f}s]: {txt[:20]} -> 改判展示衣服')
                else:
                    print(f'  [VL] seg{idx} [{start_ms/1000:.1f}s-{end_ms/1000:.1f}s]: {txt[:20]} -> 仍抛弃')
        except Exception as e:
            print(f'  [VL] seg{idx} error: {e}')
        try:
            os.remove(fp)
        except:
            pass
    try:
        shutil.rmtree(tmpdir)
    except:
        pass
    return recls


def _grouped_sentence_indices(grouped, sentences):
    selected = []
    seen = set()
    for indices in (grouped or {}).values():
        for idx in indices or []:
            if idx in seen or not 0 <= idx < len(sentences):
                continue
            if not is_allowed_sentence(sentences[idx]):
                continue
            selected.append(idx)
            seen.add(idx)
    return selected


def should_run_visual_recovery(grouped, sentences, min_ms=MIN_VIDEO_DURATION_MS):
    selected = _grouped_sentence_indices(grouped, sentences)
    selected_ms = sum(_sentence_duration_ms(sentences[idx]) for idx in selected)
    has_clothing_display = bool(grouped.get('展示衣服'))
    return selected_ms < min_ms or not has_clothing_display


def select_visual_recovery_candidates(grouped, discarded, sentences,
                                      allowed_indices=None,
                                      min_ms=MIN_VIDEO_DURATION_MS,
                                      limit=VISUAL_RECOVERY_MAX_CANDIDATES):
    """Bound expensive VL checks to useful, nearby, compliant speech units."""
    if limit <= 0:
        return []
    allowed = set(allowed_indices) if allowed_indices is not None else {
        idx for idx, sentence in enumerate(sentences) if is_allowed_sentence(sentence)
    }
    selected = _grouped_sentence_indices(grouped, sentences)
    selected_ranges = [
        {'start': int(sentences[idx]['start']), 'end': int(sentences[idx]['end'])}
        for idx in selected
    ]
    selected_ms = sum(_sentence_duration_ms(sentences[idx]) for idx in selected)
    deficit_ms = max(0, min_ms - selected_ms)
    candidates = []
    seen = set()
    for idx in discarded or []:
        if idx in seen or idx not in allowed or not 0 <= idx < len(sentences):
            continue
        seen.add(idx)
        sentence = sentences[idx]
        if not is_allowed_sentence(sentence):
            continue
        duration_ms = _sentence_duration_ms(sentence)
        if duration_ms <= 0:
            continue
        sentence_range = {
            'start': int(sentence.get('start', 0) or 0),
            'end': int(sentence.get('end', 0) or 0),
        }
        source_gap_ms = min(
            (_source_gap_ms(sentence_range, selected_range)
             for selected_range in selected_ranges),
            default=10 ** 12,
        )
        fills_deficit = deficit_ms > 0 and duration_ms >= deficit_ms
        near_selected = source_gap_ms <= SPEECH_UNIT_MAX_GAP_MS
        useful_ms = min(duration_ms, deficit_ms) if deficit_ms else duration_ms
        candidates.append((
            0 if fills_deficit else 1,
            0 if near_selected else 1,
            -useful_ms,
            source_gap_ms,
            idx,
        ))
    candidates.sort()
    return [
        idx for _fills, _near, _useful, _gap, idx in candidates[:limit]
    ]


def maybe_recover_visual_clothing(grouped, discarded, sentences, allowed_indices,
                                  draft_path, key, visual_check=True,
                                  src_video=None, visual_checker=None):
    if not visual_check or not key or not discarded:
        return []
    if not should_run_visual_recovery(grouped, sentences):
        print('  [VL] 已有≥15秒合规核心口播且包含服装展示，跳过废弃段视觉复核')
        return []
    visual_candidates = select_visual_recovery_candidates(
        grouped, discarded, sentences, allowed_indices=allowed_indices
    )
    if not visual_candidates:
        return []
    src_video = src_video or find_source_video(draft_path)
    if not src_video:
        return []
    visual_checker = visual_checker or visual_check_clothing_display
    recls = visual_checker(
        draft_path, sentences, visual_candidates, src_video
    )
    recovered = []
    for idx in recls:
        if idx not in discarded:
            continue
        text = sentences[idx]['text'] if idx < len(sentences) else ''
        if not is_allowed_sentence(text):
            print(f'  [合规] VL捞回段含违禁词，仍判废话丢弃: {text[:24]}')
            continue
        discarded.remove(idx)
        if idx not in grouped['展示衣服']:
            grouped['展示衣服'].append(idx)
        recovered.append(idx)
    return recovered

def uid(): return str(uuid.uuid4()).upper()

def classify_sentences(sentences, dashscope_key, max_retries=2):
    numbered = [f"{i} | {s['text']}" for i, s in enumerate(sentences)]
    prompt = f"""请将以下每句话分类到以下范畴之一：

【范畴定义 — 按视频顺序排列】
- 爆点（第1段，最多1条）：品质背书、稀缺感、原版供应链、复刻工艺、品牌历史、做了多少年。注意：普通的"质量好"不属于爆点，归展示衣服
- 痛点（第2段，最多1条）：价格落差、稀缺焦虑、品质对比、限量版太贵、买不起
- 展示衣服（第3段，尽量多）：面料、制衣工艺、版型、细节、材质描述、刺绣、做工、质量描述、衣服本身、推荐理由、搭配建议。凡是提到衣服/质量/面料/做工/版型/好看的，优先归此类
- 金句（第4段，最多1条）：名人名言、价值观输出、认同感、品质金句、人生道理（仅保留原视频本身出现的金句，不从素材库补充）
- 价格（第5段，最多1条）：当前推荐商品的真实上车价、具体价格数字，最好以"上链接"或"上车"结尾。注意：提到价格的句子优先保留，不要丢弃
- 废话：不属于以上任何范畴，丢弃

【重要说明 — 严格遵守！】
- "原版工艺/复刻工艺/做了X年/供应链"属于"爆点"；普通"质量好/面料好/做工好"属于"展示衣服"
- "版型/做工/面料/刺绣/冰丝/材质/细节/质量/好看/衣服/西装/裙子/套装"统一归"展示衣服"
- ⚡ "亚麻/桑蚕丝/天丝/莱赛尔/真丝/羊绒/棉麻/雪纺/蕾丝/纯棉/羊毛"等面料词 → 必须归展示衣服！
- ⚡ 一句话同时提到面料和价格（如"桑蚕丝七百九十九"）→ 优先归展示衣服（面料信息比价格数字更有价值）
- 只有明确提到具体价格金额（如xxx元/xxx块钱/开个xxx）才是"价格"
- 价格类优先选带"上链接""上车""开个"的句子
- 尽量把提到衣服相关内容的句子归到展示衣服，宁多勿少！展示衣服要尽可能多！
- 这次分类只用于决定“保留哪些句子”，不再用于重排：除了“废话”之外，其余句子都会按原视频顺序保留。
- 不确定是否属于废话时，保留到最接近的范畴，不要为了凑结构或减少段落随意丢弃。

【句子列表】
{chr(10).join(numbered)}

请严格按以下格式输出，每行一条，不要添加任何解释：
句子ID|范畴"""

    for attempt in range(max_retries + 1):
        try:
            content, provider = llm_text_with_provider(
                prompt,
                temperature=0.1,
                deepseek_timeout=30,
                deepseek_max_retries=0,
            )
            if not content:
                print(f' 分类API失败 (尝试 {attempt+1})')
                if attempt < max_retries: continue
                return None
            print(f' 分类模型: {provider}')
            text = content.strip()
            classifications = []
            for line in text.split('\n'):
                line = line.strip()
                if not line: continue
                m = re.match(r'^(\d+)\s*[|:\u3000]\s*(.+?)\s*[\u2713\u2714]*\s*$', line)
                if m:
                    idx, cat_raw = int(m.group(1)), m.group(2).strip()
                    for vc in ['爆点', '痛点', '展示衣服', '金句', '价格', '废话']:
                        if vc in cat_raw: classifications.append((idx, vc)); break
                    else:
                        if '爆' in cat_raw and '点' in cat_raw: classifications.append((idx, '爆点'))
                        elif '痛' in cat_raw: classifications.append((idx, '痛点'))
                        elif '展示' in cat_raw or '衣服' in cat_raw or '服装' in cat_raw: classifications.append((idx, '展示衣服'))
                        elif '金句' in cat_raw or '金' in cat_raw: classifications.append((idx, '金句'))
                        elif '价格' in cat_raw or '价' in cat_raw: classifications.append((idx, '价格'))
                        else: classifications.append((idx, '废话'))
            unique_valid = {
                idx for idx, _cat in classifications
                if 0 <= idx < len(sentences)
            }
            if len(unique_valid) >= len(sentences) * 0.7:
                completed = complete_classifications(sentences, classifications)
                missing_count = len(sentences) - len(unique_valid)
                suffix = f'，本地补全 {missing_count} 条' if missing_count else ''
                print(f' AI分类成功: {len(unique_valid)}/{len(sentences)} 条{suffix}')
                return completed
            else:
                print(f' 分类不完整 ({len(unique_valid)}/{len(sentences)}), 重试...')
                if attempt < max_retries: continue
        except Exception as e:
            print(f' 分类异常 (尝试 {attempt+1}): {e}')
            if attempt < max_retries: continue
    return None

def fallback_classify(sentences):
    cls = []
    for i, s in enumerate(sentences):
        t = s['text']; cat = '废话'
        # 展示衣服优先 — 凡提到衣服/面料/质量/好看的都算（面料关键词优先级最高）
        if any(k in t for k in ['面料','冰丝','刺绣','版型','材质','细节','工艺','做工','走线','剪裁',
                               '设计','手感','质感','柔软','透气','质量','好看','衣服','西装','裙子',
                               '套装','这一件','这件','一件','裤子','上衣','马甲','衬衫','西服',
                               '漂亮','百搭','经典','简约','高级','时髦','亚麻','桑蚕丝','天丝',
                               '莱赛尔','真丝','羊绒','棉麻','雪纺','蕾丝','针织','纯棉','羊毛',
                               '碎花','一整','一整套','一套','拿一套','去拿']): cat = '展示衣服'
        if any(k in t for k in ['复购','真本事','品质不错','相当不错','才是','才是真']): cat = '金句'
        elif any(k in t for k in ['开个','块钱','就行','上车','上链接','只要','只需','元','块','百多','百块']): cat = '价格'
        elif any(k in t for k in ['限量','三万多','买不起','太贵','几千','几万','差距','不值']): cat = '痛点'
        elif any(k in t for k in ['原版','供应链','复刻','定制','独有','大师']): cat = '爆点'
        # 太美改为爆点
        if '太美' in t or '太漂亮' in t:
            if cat == '废话' or cat == '价格':
                cat = '爆点'
        # 南沙港/中检仓/仓库/货源类 -> 废话
        if not is_allowed_sentence(t):
            cat = '废话'
        cls.append((i, cat))
    return cls


def complete_classifications(sentences, classifications):
    """Return exactly one safe classification for every sentence index."""
    fallback = dict(fallback_classify(sentences))
    parsed = {}
    valid_categories = {'爆点', '痛点', '展示衣服', '金句', '价格', '废话'}
    for idx, category in classifications or []:
        if not isinstance(idx, int) or not 0 <= idx < len(sentences):
            continue
        if idx in parsed:
            continue
        parsed[idx] = category if category in valid_categories else fallback[idx]

    completed = []
    detail_keywords = [
        '面料','冰丝','刺绣','版型','材质','细节','工艺','做工','走线',
        '剪裁','设计','手感','质感','柔软','透气','西服','套装','大版',
        'boyfriend','男朋友','衣服','上衣','裙子','裤子','T恤','马甲','衬衫',
    ]
    for idx, sentence in enumerate(sentences):
        category = parsed.get(idx, fallback[idx])
        text = sentence.get('text', '')
        if not is_allowed_sentence(sentence):
            category = '废话'
        elif category == '爆点' and any(keyword in text for keyword in detail_keywords):
            category = '展示衣服'
        elif category == '废话' and ('太美' in text or '太漂亮' in text):
            category = '爆点'
        completed.append((idx, category))
    return completed


def categorize_price_sentences(grouped, sentences):
    price_idxs = grouped.get('价格', [])
    if not price_idxs: return
    best = [idx for idx in price_idxs if idx < len(sentences) and sentences[idx]['text'].rstrip('。！？.!?， ').endswith(('上链接','上车'))]
    other = [idx for idx in price_idxs if idx < len(sentences) and idx not in best]
    chosen = best[:1] if best else other[:1]
    grouped['价格'] = chosen
    if best: print(f' 价格: 优先选 "{sentences[chosen[0]]["text"][:30]}"')
    if best and other: print(f' 价格: 丢弃 {len(other)} 条非"上链接/上车"')



FALLBACK_BAODIAN_KW = ['做了','多年','品质','保证','正品','原创','独家','源头','实力','专业','口碑','信任','老牌','历史','背书','十几年','几十年','一直','坚持','专注']
FALLBACK_JINJU_KW = ['人生','道理','认同','生活','选择','值得','相信','坚持','努力','喜欢','态度','价值观','感悟','体会','品味','格调','优雅','自信','气质','高级','好看','时尚','品质','需要','实用','耐穿','经典','百搭','舒服','自在','大方','魅力','动人','好搭']

def smart_fallback_from_discarded(discarded, sentences, category):
    """从被丢弃的废话句子中按内容匹配最佳候选"""
    keywords = FALLBACK_BAODIAN_KW if category == '爆点' else FALLBACK_JINJU_KW
    scored = []
    for idx in discarded:
        if idx >= len(sentences): continue
        t = sentences[idx]['text']
        if not is_allowed_sentence(t):
            continue
        score = sum(1 for k in keywords if k in t)
        if score > 0:
            scored.append((score, idx))
    scored.sort(key=lambda x: -x[0])
    if scored:
        best_idx = scored[0][1]
        print(f' {category}: 从原视频内容匹配到 "{sentences[best_idx]["text"][:40]}" (匹配{scored[0][0]}个关键词)')
        return best_idx
    return None


def enforce_limits_and_fallback(grouped, sentences, asr_source_audio, pre_duration_ms=0, discarded=None):
    for cat in ['爆点','展示衣服','金句','价格','原价','上车价']:
        mx = CATEGORY_MAX.get(cat, 99)
        cur = grouped[cat]
        if len(cur) > mx:
            grouped[cat] = cur[:mx]
            print(f' {cat}: 超出上限 {mx}，丢弃 {len(cur)-mx} 条 -> 保留 {len(grouped[cat])} 条')
        if cat == '爆点' and len(grouped[cat]) == 0:
            if discarded is not None:
                best_idx = smart_fallback_from_discarded(discarded, sentences, '爆点')
                if best_idx is not None:
                    grouped[cat] = [best_idx]
                    try: discarded.remove(best_idx)
                    except: pass
                    continue
    # 金句不自动补充：仅保留原视频 ASR 分类出的金句
    return grouped


def rebucket_price_roles(grouped, original_idx, current_idx):
    """Move detected price roles into dedicated buckets without deleting them."""
    price_ids = {original_idx, current_idx} - {None}
    for category in ('爆点', '痛点', '展示衣服', '金句', '价格'):
        grouped[category] = [idx for idx in grouped.get(category, []) if idx not in price_ids]
    grouped['原价'] = (
        [original_idx]
        if original_idx is not None and original_idx != current_idx
        else []
    )
    grouped['上车价'] = [current_idx] if current_idx is not None else []
    return grouped, price_ids


def _seg_start_ms(seg):
    return int(seg.get('src_start_ms', 0) or 0)


def _refill_dropped(segs, dropped, grouped, sentences, audio_src, _ts, analysis):
    """净化丢弃近全静音段后，若某分类结构位因此空缺，从 grouped 同分类的
    剩余候补句子补一条，保住叙事结构。候补复用全音频分析，不再运行 ffmpeg。
    返回补位后的 segs（保持原相对顺序；补入段加在同类位置附近）。"""
    if not dropped or not grouped:
        return segs
    dropped_cats = {}
    for d in dropped:
        cat = d.get('category')
        if cat and cat in ('爆点', '痛点', '金句', '价格'):
            dropped_cats[cat] = d
    if not dropped_cats:
        return segs
    used_starts = {_seg_start_ms(s) for s in segs}
    for cat, dseg in dropped_cats.items():
        # 该分类是否还空缺（当前 segs 无此分类）
        if any(s.get('category') == cat for s in segs):
            continue
        # 从 grouped 该分类候选里找：未被用过、且不是近全静音的
        for idx in grouped.get(cat, []):
            if idx >= len(sentences):
                continue
            st = int(sentences[idx].get('start', 0))
            if st in used_starts:
                continue
            s = sentences[idx]
            new_seg = {'category': cat, 'text': s['text'],
                       'src_start_ms': s['start'], 'src_end_ms': s['end'],
                       'src_dur_ms': s['end'] - s['start'], 'source': 'asr', 'file': None}
            candidate, rejected = _ts.clean_ordered_segments(
                [new_seg], audio_src, analysis=analysis
            )
            if rejected:
                continue
            new_seg = candidate[0]
            # 插到 segs 中与 dropped 原位置接近处（按 src_start 排序插入）
            insert_pos = len(segs)
            for i, x in enumerate(segs):
                if _seg_start_ms(x) > _seg_start_ms(dseg):
                    insert_pos = i
                    break
            segs.insert(insert_pos, new_seg)
            used_starts.add(st)
            print(f'  [补位] {cat} 从候补补入: "{s["text"][:30]}" ({s["start"]/1000:.1f}-{s["end"]/1000:.1f}s)')
            break
    return segs


def _sentence_segment(sentence_idx, category, sentences, source='asr'):
    sentence = sentences[sentence_idx]
    return {
        'category': category,
        'text': sentence['text'],
        'src_start_ms': sentence['start'],
        'src_end_ms': sentence['end'],
        'src_dur_ms': sentence['end'] - sentence['start'],
        'source': source,
        'file': None,
        'sentence_index': sentence_idx,
        'sentence_ids': list(sentence.get('sentence_ids', [sentence_idx])),
    }


def _ordered_segment_layout(segments):
    leading = [s for s in segments if s.get('category') in ('原价', '上车价')]
    tail = [s for s in segments if s.get('category') == '金句']
    body = [
        s for s in segments
        if s.get('category') not in ('原价', '上车价', '金句')
    ]
    body.sort(key=lambda item: (_seg_start_ms(item), int(item.get('src_dur_ms', 0) or 0)))
    return leading + body + tail


def build_ordered_segments(grouped, sentences):
    ordered = []
    for cat in ('原价', '上车价'):
        for idx in grouped.get(cat, []):
            if idx >= len(sentences): continue
            ordered.append(_sentence_segment(idx, cat, sentences))
    rest = []
    for cat in ('爆点', '痛点', '展示衣服', '价格'):
        for idx in grouped.get(cat, []):
            if idx >= len(sentences): continue
            rest.append(_sentence_segment(idx, cat, sentences))
    rest.sort(key=lambda x: (x['src_start_ms'], x['src_dur_ms']))
    tail = []
    for idx in grouped.get('金句', []):
        if idx >= len(sentences): continue
        tail.append(_sentence_segment(idx, '金句', sentences))
    return ordered + rest + tail

def _segment_duration_ms(segment):
    return max(1, int(segment.get('src_dur_ms', 0) or 0))


def _source_gap_ms(left, right):
    if left['end'] <= right['start']:
        return right['start'] - left['end']
    if right['end'] <= left['start']:
        return left['start'] - right['end']
    return 0


def fill_segments_to_min_duration(segs, sentences, classifications,
                                  min_ms=MIN_VIDEO_DURATION_MS,
                                  max_ms=MAX_VIDEO_DURATION_MS,
                                  candidate_cleaner=None):
    """Refill a short edit with unused source speech, using chatter last."""
    result = list(segs)
    total_ms = sum(_segment_duration_ms(segment) for segment in result)
    if total_ms >= min_ms:
        return _ordered_segment_layout(result), []

    categories = dict(classifications or [])
    used_indices = {
        int(segment['sentence_index']) for segment in result
        if segment.get('sentence_index') is not None
    }
    used_ranges = [
        {'start': int(segment.get('src_start_ms', 0)),
         'end': int(segment.get('src_end_ms', 0))}
        for segment in result
    ]
    has_price_anchor = any(
        segment.get('category') in ('原价', '上车价', '价格')
        for segment in result
    )
    candidates = []
    for idx, sentence in enumerate(sentences):
        if idx in used_indices or not is_allowed_sentence(sentence):
            continue
        start = int(sentence.get('start', 0) or 0)
        end = int(sentence.get('end', 0) or 0)
        if end <= start:
            continue
        if any(start < used['end'] and end > used['start'] for used in used_ranges):
            continue
        category = categories.get(idx, '废话')
        candidates.append((idx, category))

    added = []
    rejected = set()
    while total_ms < min_ms:
        available = [item for item in candidates if item[0] not in rejected and item[0] not in used_indices]
        if not available:
            break

        selected_ranges = [
            {'start': int(sentences[idx]['start']), 'end': int(sentences[idx]['end'])}
            for idx in used_indices if 0 <= idx < len(sentences)
        ]
        min_used = min(used_indices) if used_indices else None
        max_used = max(used_indices) if used_indices else None

        def priority(item):
            idx, category = item
            sentence_range = {
                'start': int(sentences[idx]['start']),
                'end': int(sentences[idx]['end']),
            }
            near_context = bool(selected_ranges) and min(
                _source_gap_ms(sentence_range, selected) for selected in selected_ranges
            ) <= SPEECH_UNIT_MAX_GAP_MS
            bridges_context = (
                min_used is not None and max_used is not None
                and min_used < idx < max_used
            )
            meaningful = category != '废话'
            duplicate_price = has_price_anchor and category == '价格'
            if duplicate_price:
                tier = 4
            elif meaningful and (near_context or bridges_context):
                tier = 0
            elif meaningful:
                tier = 1
            elif near_context or bridges_context:
                tier = 2
            else:
                tier = 3
            distance = min((abs(idx - used) for used in used_indices), default=idx)
            return tier, distance, idx

        idx, category = min(available, key=priority)
        output_category = (
            '闲聊补位'
            if category == '废话' or (has_price_anchor and category == '价格')
            else category
        )
        candidate = _sentence_segment(idx, output_category, sentences, source='asr_filler')
        if candidate_cleaner is not None:
            candidate = candidate_cleaner(candidate)
            if candidate is None:
                rejected.add(idx)
                continue
        duration_ms = _segment_duration_ms(candidate)
        if total_ms + duration_ms > max_ms:
            rejected.add(idx)
            continue
        result.append(candidate)
        added.append(candidate)
        used_indices.add(idx)
        used_ranges.append({
            'start': int(candidate['src_start_ms']),
            'end': int(candidate['src_end_ms']),
        })
        total_ms += duration_ms

    return _ordered_segment_layout(result), added


def limit_segments_to_max_duration(segs, max_ms=MAX_VIDEO_DURATION_MS,
                                   min_ms=MIN_VIDEO_DURATION_MS):
    """Drop whole speech units until the edit fits; never cut a sentence mid-unit."""
    result = list(segs)
    total_ms = sum(_segment_duration_ms(segment) for segment in result)
    while total_ms > max_ms:
        removable = []
        for idx, segment in enumerate(result):
            duration_ms = _segment_duration_ms(segment)
            if total_ms - duration_ms < min_ms:
                continue
            is_anchor = segment.get('category') in ('原价', '上车价', '金句')
            is_filler = segment.get('source') == 'asr_filler'
            removal_tier = 0 if is_filler else (2 if is_anchor else 1)
            removable.append((removal_tier, -idx, idx, duration_ms))
        if not removable:
            raise ValueError('完整口播单元无法同时满足15-45秒时长限制')
        _tier, _neg_idx, remove_idx, duration_ms = min(removable)
        result.pop(remove_idx)
        total_ms -= duration_ms
    return _ordered_segment_layout(result)


def restore_trimmed_boundaries_for_duration(segs, min_ms=MIN_VIDEO_DURATION_MS):
    """Restore only trimmed sentence edges when they are needed for 15 seconds."""
    if sum(_segment_duration_ms(segment) for segment in segs) >= min_ms:
        return 0
    restored = 0
    for segment in segs:
        original_start = segment.get('original_src_start_ms')
        original_end = segment.get('original_src_end_ms')
        if original_start is None or original_end is None:
            continue
        segment['src_start_ms'] = int(original_start)
        segment['src_end_ms'] = int(original_end)
        segment['src_dur_ms'] = int(original_end) - int(original_start)
        segment['silence_trim_reverted_for_duration'] = True
        segment.pop('silence_trimmed', None)
        restored += 1
    return restored


def main(dp_str, auto_open=True, visual_check=True, silence_pruning=False):
    dp = Path(dp_str)
    dc_path = dp / 'draft_content.json'
    asr_path = dp / 'asr_result.json'
    audio_src = dp / 'audio.mp3'
    pruning_report_path = dp / 'silence_pruning_report.json'
    if not dc_path.exists() or not asr_path.exists() or not audio_src.exists():
        print('缺少必要文件'); return False
    if not silence_pruning and pruning_report_path.exists():
        try:
            pruning_report_path.unlink()
        except OSError:
            pass

    with open(dc_path, encoding='utf-8') as f: draft = json.load(f)
    with open(asr_path, encoding='utf-8') as f: asr = json.load(f)
    raw_sentences = asr.get('sentences', [])
    if not raw_sentences: print('ASR 空'); return False

    sentences = build_speech_units(raw_sentences)
    if not sentences: print('ASR 无有效口播'); return False
    merged_count = len(raw_sentences) - len(sentences)
    print(
        f'口播单元: {len(raw_sentences)} 条 ASR -> {len(sentences)} 个单元'
        f'（合并 {max(0, merged_count)} 条短句，不丢弃 <1s 口播）'
    )

    key = os.environ.get('DASHSCOPE_API_KEY', '') or os.environ.get('DEEPSEEK_API_KEY', '')
    cls = classify_sentences(sentences, key) if key else fallback_classify(sentences)
    if not cls: cls = fallback_classify(sentences)

    cat_order = ['爆点','痛点','展示衣服','金句','价格']
    grouped = {c: [] for c in cat_order}
    discarded = []
    allowed_indices = {i for i, sentence in enumerate(sentences) if is_allowed_sentence(sentence)}
    for idx, cat in cls:
        if idx >= len(sentences): continue
        if idx not in allowed_indices:
            discarded.append(idx)
            continue
        (grouped[cat] if cat in grouped else discarded).append(idx)

    print('\n分类结果:')
    for cat in cat_order:
        print(f' 【{cat}】: {len(grouped[cat])}')
        for idx in grouped[cat]:
            s = sentences[idx]
            print(f'   {idx}: {s["text"][:40]} ({s["end"]-s["start"]:.0f}ms)')

    # Only spend VL calls when duration or clothing-display structure still needs help.
    maybe_recover_visual_clothing(
        grouped, discarded, sentences, allowed_indices,
        dp, key, visual_check=visual_check,
    )
    print()
    orig_idx, curr_idx, price_source = detect_price_roles(
        sentences, allowed_indices=allowed_indices
    )
    if curr_idx is None and grouped.get('价格'):
        curr_idx = grouped['价格'][0]
    grouped, price_ids = rebucket_price_roles(grouped, orig_idx, curr_idx)
    discarded = [i for i in discarded if i not in price_ids]
    try:
        (dp / 'price_roles.json').write_text(json.dumps({
            'original_idx': orig_idx, 'current_idx': curr_idx, 'source': price_source,
            'original_text': sentences[orig_idx].get('text', '') if orig_idx is not None else '',
            'current_text': sentences[curr_idx].get('text', '') if curr_idx is not None else '',
        }, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as exc:
        print(f'  [价格角色] 写出失败: {exc}')
    grouped = enforce_limits_and_fallback(grouped, sentences, str(audio_src), discarded=discarded)
    segs = build_ordered_segments(grouped, sentences)

    candidate_cleaner = None
    # 该功能成本较高且可能误删轻声口播，默认关闭，需显式灰度启用。
    if silence_pruning:
        pruning_report = {
            'status': 'ERROR',
            'noise_db': None,
            'silence_min_s': None,
            'min_speech_ratio': None,
            'source_mean_volume_db': None,
            'silence_interval_count': 0,
            'trimmed': [],
            'dropped': [],
        }
        try:
            import _trim_segments as _ts
            analysis = _ts.analyze_audio(str(audio_src))
            base_vol = analysis.get('vol_db')
            pruning_report.update({
                'status': 'OK',
                'noise_db': _ts.NOISE_DB,
                'silence_min_s': _ts.SILENCE_MIN_S,
                'min_speech_ratio': _ts.MIN_SPEECH_RATIO,
                'source_mean_volume_db': base_vol,
                'silence_interval_count': len(analysis.get('silences', [])),
            })
            if base_vol is not None:
                print(f'源音频整体音量: {base_vol:.1f}dB')
            print(f'静音净化: 一次扫描发现 {len(analysis.get("silences", []))} 个长静音区间')
            before_n = len(segs)
            segs, dropped = _ts.clean_ordered_segments(
                segs, str(audio_src), analysis=analysis
            )
            trimmed_n = sum(bool(seg.get('silence_trimmed')) for seg in segs)
            if trimmed_n:
                print(f'语音净化: 裁短 {trimmed_n} 段句首/句尾静音')
            if len(segs) < before_n:
                print(f'语音净化: 丢弃 {before_n - len(segs)} 段近全静音语音')
            if dropped:
                segs = _refill_dropped(
                    segs, dropped, grouped, sentences, str(audio_src), _ts, analysis
                )
            def candidate_cleaner(segment):
                cleaned, rejected = _ts.clean_ordered_segments(
                    [copy.deepcopy(segment)], str(audio_src), analysis=analysis
                )
                return None if rejected else cleaned[0]
            pruning_report['trimmed'] = [
                {
                    'category': segment.get('category'), 'text': segment.get('text', ''),
                    'original_src_start_ms': segment.get('original_src_start_ms'),
                    'original_src_end_ms': segment.get('original_src_end_ms'),
                    'src_start_ms': segment.get('src_start_ms'),
                    'src_end_ms': segment.get('src_end_ms'),
                }
                for segment in segs if segment.get('silence_trimmed')
            ]
            pruning_report['dropped'] = [
                {
                    'category': segment.get('category'), 'text': segment.get('text', ''),
                    'src_start_ms': segment.get('src_start_ms'),
                    'src_end_ms': segment.get('src_end_ms'),
                    'speech_ratio': (segment.get('silence_analysis') or {}).get('ratio'),
                }
                for segment in dropped
            ]
        except Exception as e:
            pruning_report['error'] = str(e)
            print(f'  (语音净化跳过: {e})')
        try:
            pruning_report_path.write_text(
                json.dumps(pruning_report, ensure_ascii=False, indent=2), encoding='utf-8'
            )
        except OSError as e:
            print(f'  (静音净化报告写入失败: {e})')

    segs, filler_segments = fill_segments_to_min_duration(
        segs,
        sentences,
        cls,
        candidate_cleaner=candidate_cleaner,
    )
    restored_trims = (
        restore_trimmed_boundaries_for_duration(segs)
        if silence_pruning else 0
    )
    if restored_trims:
        print(
            f'时长门禁优先：恢复 {restored_trims} 个口播单元的句首/句尾自然停顿，'
            '不恢复已判定为近全静音的段'
        )
        pruning_report['duration_guard_reverted_trims'] = restored_trims
        try:
            pruning_report_path.write_text(
                json.dumps(pruning_report, ensure_ascii=False, indent=2), encoding='utf-8'
            )
        except OSError as exc:
            print(f'  (静音净化报告更新失败: {exc})')
    if filler_segments:
        print(f'语音补位: 从原视频回捞 {len(filler_segments)} 个口播单元')
        for segment in filler_segments:
            print(
                f'  [{segment["category"]}] {segment["text"][:35]} '
                f'({segment["src_dur_ms"]/1000:.1f}s)'
            )

    try:
        segs = limit_segments_to_max_duration(segs)
    except ValueError as exc:
        print(f'[时长门禁] {exc}')
        return False
    if not segs: print('无可用段落'); return False

    planned_duration_ms = sum(_segment_duration_ms(segment) for segment in segs)
    available_voiced_ms = sum(
        _sentence_duration_ms(sentence)
        for sentence in sentences if is_allowed_sentence(sentence)
    )
    duration_report = {
        'status': 'OK' if planned_duration_ms >= MIN_VIDEO_DURATION_MS else 'INSUFFICIENT_VOICED_CONTENT',
        'min_duration_ms': MIN_VIDEO_DURATION_MS,
        'max_duration_ms': MAX_VIDEO_DURATION_MS,
        'planned_duration_ms': planned_duration_ms,
        'available_allowed_source_ms': available_voiced_ms,
        'selected_units': len(segs),
        'filler_units': len(filler_segments),
        'silent_fill_allowed': False,
    }
    try:
        (dp / 'duration_policy_report.json').write_text(
            json.dumps(duration_report, ensure_ascii=False, indent=2), encoding='utf-8'
        )
    except OSError as exc:
        print(f'  (时长报告写入失败: {exc})')
    if planned_duration_ms < MIN_VIDEO_DURATION_MS:
        print(
            f'[时长门禁] 合规原声全部用完仍只有 {planned_duration_ms/1000:.1f}s，'
            '拒绝使用静音、重复人声或外部主播音频补位'
        )
        return False
    print(f'\n排序结果 ({len(segs)} 段, {sum(s["src_dur_ms"] for s in segs)/1000:.1f}s):')
    for i, seg in enumerate(segs):
        print(f'  {i}: [{seg["category"]}] {seg["text"][:35]} ({seg["src_dur_ms"]/1000:.1f}s)')

    # ffmpeg 切割；重跑时清理旧的语音切片和已废弃的静音镜像资产。
    for old in dp.iterdir():
        is_old_clip = old.suffix == '.mp3' and old.name.startswith('clip_')
        is_legacy_mirror = old.name.startswith('mirror_fill_') and old.suffix.lower() in ('.wav', '.mp4')
        if is_old_clip or is_legacy_mirror:
            old.unlink()

    draft_placeholder = ''
    for v in draft.get('materials', {}).get('videos', []):
        p = v.get('path', '')
        if '##_draftpath_placeholder' in p:
            draft_placeholder = p[:p.index('##/') + 3]
            break

    # ===== [坑3] 备份非视频轨道 (防止步骤5-12数据丢失) =====
    _non_video = [t for t in draft['tracks'] if t['type'] != 'video']
    if _non_video:
        _bak = dp / 'draft_content.pre_step4.json'
        shutil.copy2(str(dc_path), str(_bak))
        _types = {}
        for _t in _non_video:
            _types[_t['type']] = _types.get(_t['type'], 0) + 1
        _summary = ', '.join(f'{k}\u00d7{v}' for k, v in _types.items())
        print(f'\n!!! [Keng3] Step4 will clear ALL non-video tracks: {_summary}')
        print(f'    Auto-backup -> {_bak.name}')
        print(f'    Restore with: --recover flag')
        print(f'    WARNING: Step5-12 changes (subtitles/BGM/transitions) will be LOST!')
        print(f'    Must re-run step5-12 after step4.\n')

    new_tracks = [t for t in draft['tracks'] if t['type'] == 'video']
    new_audio_mats = [
        audio for audio in draft.get('materials', {}).get('audios', [])
        if audio.get('name') != 'audio.mp3'
        and not str(audio.get('name', '')).startswith(('clip_', 'mirror_fill_'))
    ]
    draft['materials']['videos'] = [
        video for video in draft.get('materials', {}).get('videos', [])
        if not str(video.get('name', '')).startswith('mirror_fill_')
    ]
    audio_track = {"type": "audio", "flag": 0, "is_main_track": False, "attribute": 0, "id": uid(), "segments": []}
    tl_us = 0

    actual_durations = []
    for si, seg in enumerate(segs):
        clip_name = f"clip_{si:02d}_{seg['category']}.mp3"
        clip_file = dp / clip_name

        if seg.get('source') == 'file' and seg.get('file'):
            shutil.copy2(seg['file'], clip_file)
            actual_dur_us = seg['src_dur_ms'] * 1000
        else:
            src_s = seg['src_start_ms'] / 1000.0
            dur_s = seg['src_dur_ms'] / 1000.0
            # 始终重编码 libmp3lame，避免 -c copy 的 MP3 帧对齐误差（每帧 ~26ms 累积偏移）
            subprocess.run(
                ['ffmpeg', '-y', '-ss', f'{src_s:.3f}', '-i', str(audio_src),
                 '-t', f'{dur_s:.3f}', '-acodec', 'libmp3lame', '-q:a', '2', str(clip_file)],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
            )
            r = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                 '-of', 'csv=p=0', str(clip_file)],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
            )
            actual_dur_s = float(r.stdout.strip()) if r.stdout.strip() else dur_s
            actual_dur_us = int(actual_dur_s * 1000000)

        remaining_timeline_us = MAX_VIDEO_DURATION_MS * 1000 - tl_us
        timeline_dur_us = min(actual_dur_us, remaining_timeline_us)
        if timeline_dur_us <= 0:
            print('[时长门禁] MP3 编码后时间线已达到45秒，停止追加')
            break
        actual_durations.append(timeline_dur_us)
        mat_id = uid()
        new_audio_mats.append({
            "id": mat_id, "duration": actual_dur_us, "name": clip_name,
            "path": f"{draft_placeholder}{clip_name}" if draft_placeholder else str(clip_file),
            "type": "sound"
        })
        audio_track['segments'].append({
            "id": uid(), "material_id": mat_id,
            "target_timerange": {"duration": timeline_dur_us, "start": tl_us},
            "source_timerange": {"duration": timeline_dur_us, "start": 0},
            "speed": 1, "volume": 1, "visible": True,
            "extra_material_refs": []
        })
        print(f'  [{tl_us/1000000:.1f}s] [{seg["source"]}] {seg["category"]} ({timeline_dur_us/1000000:.1f}s)')
        tl_us += timeline_dur_us

    new_tracks.append(audio_track)
    draft['tracks'] = new_tracks
    draft['materials']['audios'] = new_audio_mats
    draft['duration'] = tl_us
    for v in draft.get('materials', {}).get('videos', []): v['duration'] = tl_us

    write_draft(dp, draft)

    seg_meta = []
    written_segments = segs[:len(actual_durations)]
    for i, segment in enumerate(written_segments):
        item = {
            'index': i, 'category': segment['category'],
            'src_start_ms': segment['src_start_ms'], 'src_end_ms': segment['src_end_ms'],
            'src_dur_ms': int(actual_durations[i] / 1000) if i < len(actual_durations) else segment['src_dur_ms'],
            'source': segment.get('source', 'asr'), 'text': segment['text'],
            'file': segment.get('file'),
        }
        if segment.get('sentence_index') is not None:
            item['sentence_index'] = int(segment['sentence_index'])
        if segment.get('sentence_ids'):
            item['sentence_ids'] = list(segment['sentence_ids'])
        if segment.get('silence_trimmed'):
            item.update({
                'silence_trimmed': True,
                'original_src_start_ms': segment['original_src_start_ms'],
                'original_src_end_ms': segment['original_src_end_ms'],
            })
        if segment.get('silence_trim_reverted_for_duration'):
            item['silence_trim_reverted_for_duration'] = True
        seg_meta.append(item)

    with open(dp / 'step4_segments.json', 'w', encoding='utf-8') as f: json.dump(seg_meta, f, ensure_ascii=False, indent=2)

    if not MIN_VIDEO_DURATION_MS * 1000 <= tl_us <= MAX_VIDEO_DURATION_MS * 1000:
        print(f'[时长门禁] 实际时间线 {tl_us/1000000:.2f}s 不在15-45秒范围')
        return False

    print(f'\n切割排序完成！总长: {tl_us/1000000:.1f}s')

    if not auto_open:
        print('(Skipping CapCut auto-open, --no-open)')
        return True

    draft_name = os.path.basename(str(Path(sys.argv[1])))
    jy_path = os.environ.get('REALCUT_JIANYING_EXE', r'C:\Users\JT\Desktop\剪映5.9Windows\JianyingPro\5.9.0.11632\JianyingPro.exe')
    script_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'scripts')
    open_py = os.path.join(script_dir, 'open_draft.py')
    print('\n打开剪映验证...')
    subprocess.run(['taskkill', '/f', '/im', 'JianyingPro.exe'], capture_output=True, text=True)
    subprocess.Popen([jy_path], shell=True)
    time.sleep(20)
    subprocess.run(['python', open_py, draft_name], capture_output=True, text=True)
    print('草稿已打开')
    return True

if __name__ == '__main__':
    if len(sys.argv) < 2: print(__doc__); sys.exit(1)
    pos = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not pos: print(__doc__); sys.exit(1)
    dp_arg = pos[0]

    if '--recover' in sys.argv:
        dp = Path(dp_arg)
        bak = dp / 'draft_content.pre_step4.json'
        if not bak.exists():
            print(f'Error: backup not found: {bak}')
            sys.exit(1)
        with open(bak, 'r', encoding='utf-8') as f:
            data = json.load(f)
        write_draft(dp, data)
        print(f'Recovered all tracks from {bak.name}')
        sys.exit(0)

    auto_open = '--no-open' not in sys.argv
    visual_check = '--no-visual-check' not in sys.argv
    silence_pruning = '--silence-pruning' in sys.argv
    if not visual_check:
        print('已关闭 AI 画面复核，步骤4仅按字幕内容分类')
    success = main(
        dp_arg,
        auto_open=auto_open,
        visual_check=visual_check,
        silence_pruning=silence_pruning,
    )
    sys.exit(0 if success else 1)
