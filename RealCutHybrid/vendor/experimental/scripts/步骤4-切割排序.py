"""原版步骤4-切割排序（v3加固版）"""

import json, sys, os, uuid, subprocess, shutil, re, copy, time, base64
from _utils import write_draft
from _llm import llm_text_with_provider
from _price_roles import detect_price_roles
from _runtime_deps import import_external
from pathlib import Path

MAX_VIDEO_DURATION_MS = 30000  # 成片最长不超过30秒
CATEGORY_MAX = {'爆点': 20, '痛点': 20, '展示衣服': 60, '金句': 1, '价格': 20, '原价': 1, '上车价': 1}


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

def visual_check_clothing_display(draft_path, sentences, discarded_indices, src_video):
    if not discarded_indices or not src_video or not os.path.exists(src_video):
        return []
    try:
        MultiModalConversation = import_external('dashscope').MultiModalConversation
    except ImportError:
        print('  [VL] dashscope not installed, skip visual check')
        return []
    key = os.environ.get('DASHSCOPE_API_KEY', '')
    if not key:
        print('  [VL] DASHSCOPE_API_KEY not set, skip visual check')
        return []
    print(f'  [VL] Checking {len(discarded_indices)} discarded segments for clothing display visually...')
    recls = []
    tmpdir = os.path.join(str(draft_path), '_vl_check_step4')
    os.makedirs(tmpdir, exist_ok=True)
    for idx in discarded_indices:
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
            content, provider = llm_text_with_provider(prompt, temperature=0.1)
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
            if len(classifications) >= len(sentences) * 0.7:
                # 修正：爆点中带衣服细节改判展示衣服
                corrected = []
                for idx, cat in classifications:
                    if cat == '爆点':
                        t = sentences[idx]['text']
                        dkw = ['面料','冰丝','刺绣','版型','材质','细节','工艺','做工','走线',
                               '剪裁','设计','手感','质感','柔软','透气','西服','套装','大版',
                               'boyfriend','男朋友','衣服','上衣','裙子','裤子','T恤','马甲','衬衫']
                        if any(k in t for k in dkw):
                            corrected.append((idx, '展示衣服'))
                            continue
                    if cat == '废话':
                        t = sentences[idx]['text']
                        if '太美' in t or '太漂亮' in t:
                            corrected.append((idx, '爆点'))
                            continue
                    if cat == '爆点':
                        t = sentences[idx]['text']
                        if any(k in t for k in ['南沙港','中检仓','仓库','货源','终点站','工厂']):
                            corrected.append((idx, '废话'))
                            continue
                    corrected.append((idx, cat))
                classifications = corrected
                print(f' AI分类成功: {len(classifications)}/{len(sentences)} 条')
                return classifications
            else:
                print(f' 分类不完整 ({len(classifications)}/{len(sentences)}), 重试...')
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
        if any(k in t for k in ['南沙港','中检仓','仓库','货源','终点站','工厂']):
            cat = '废话'
        cls.append((i, cat))
    return cls


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

def build_ordered_segments(grouped, sentences):
    ordered = []
    for cat in ('原价', '上车价'):
        for idx in grouped.get(cat, []):
            if idx >= len(sentences): continue
            s = sentences[idx]
            ordered.append({'category': cat, 'text': s['text'], 'src_start_ms': s['start'], 'src_end_ms': s['end'], 'src_dur_ms': s['end'] - s['start'], 'source': 'asr', 'file': None})
    rest = []
    for cat in ('爆点', '痛点', '展示衣服', '价格'):
        for idx in grouped.get(cat, []):
            if idx >= len(sentences): continue
            s = sentences[idx]
            rest.append({'category': cat, 'text': s['text'], 'src_start_ms': s['start'], 'src_end_ms': s['end'], 'src_dur_ms': s['end'] - s['start'], 'source': 'asr', 'file': None})
    rest.sort(key=lambda x: (x['src_start_ms'], x['src_dur_ms']))
    tail = []
    for idx in grouped.get('金句', []):
        if idx >= len(sentences): continue
        s = sentences[idx]
        tail.append({'category': '金句', 'text': s['text'], 'src_start_ms': s['start'], 'src_end_ms': s['end'], 'src_dur_ms': s['end'] - s['start'], 'source': 'asr', 'file': None})
    return ordered + rest + tail

def limit_segments_to_max_duration(segs, max_ms=MAX_VIDEO_DURATION_MS):
    """把成片总时长压到30秒内，同时保持价格开头、原文顺序、金句结尾。"""
    if not segs:
        return segs

    def _dur(s):
        return max(1, int(s.get('src_dur_ms', 0) or 0))

    def _set_dur(s, dur):
        s['src_dur_ms'] = max(1, dur)
        s['src_end_ms'] = int(s.get('src_start_ms', 0)) + s['src_dur_ms']

    total = sum(_dur(s) for s in segs)
    if total <= max_ms:
        return segs

    golden_start = len(segs)
    for i, s in enumerate(segs):
        if s.get('category') == '金句':
            golden_start = i
            break
    head = segs[:golden_start]
    tail = segs[golden_start:]
    head_budget = max(0, max_ms - sum(_dur(s) for s in tail))

    keep = []
    for s in head:
        dur = _dur(s)
        if dur <= head_budget:
            keep.append(s)
            head_budget -= dur
        elif head_budget > 0:
            _set_dur(s, head_budget)
            keep.append(s)
            head_budget = 0
        else:
            break
    result = keep + tail

    while sum(_dur(s) for s in result) > max_ms and result:
        over = sum(_dur(s) for s in result) - max_ms
        last = result[-1]
        if _dur(last) > over:
            _set_dur(last, _dur(last) - over)
            break
        result.pop()
    return result


def main(dp_str, auto_open=True, visual_check=True):
    dp = Path(dp_str)
    dc_path = dp / 'draft_content.json'
    asr_path = dp / 'asr_result.json'
    audio_src = dp / 'audio.mp3'
    if not dc_path.exists() or not asr_path.exists() or not audio_src.exists():
        print('缺少必要文件'); return False

    with open(dc_path, encoding='utf-8') as f: draft = json.load(f)
    with open(asr_path, encoding='utf-8') as f: asr = json.load(f)
    sentences = asr.get('sentences', [])
    if not sentences: print('ASR 空'); return False

    # 铁律15：过滤 <1s 的段
    before = len(sentences)
    sentences = [s for s in sentences if (s['end'] - s['start']) >= 1000]
    after = len(sentences)
    if before != after:
        print(f'过滤 <1s 段: {before} -> {after}（丢弃 {before-after} 条）')
    if not sentences: print('ASR 过滤后为空'); return False

    key = os.environ.get('DASHSCOPE_API_KEY', '') or os.environ.get('DEEPSEEK_API_KEY', '')
    cls = classify_sentences(sentences, key) if key else fallback_classify(sentences)
    if not cls: cls = fallback_classify(sentences)

    cat_order = ['爆点','痛点','展示衣服','金句','价格']
    grouped = {c: [] for c in cat_order}
    discarded = []
    for idx, cat in cls:
        if idx >= len(sentences): continue
        (grouped[cat] if cat in grouped else discarded).append(idx)

    print('\n分类结果:')
    for cat in cat_order:
        print(f' 【{cat}】: {len(grouped[cat])}')
        for idx in grouped[cat]:
            s = sentences[idx]
            print(f'   {idx}: {s["text"][:40]} ({s["end"]-s["start"]:.0f}ms)')

    # [VL visual check] Reclassify discarded segments that show clothing display on video
    if visual_check and key and discarded:
        src_video = find_source_video(dp)
        if src_video:
            recls = visual_check_clothing_display(dp, sentences, discarded, src_video)
            for idx in recls:
                if idx in discarded:
                    discarded.remove(idx)
                    if idx not in grouped['展示衣服']:
                        grouped['展示衣服'].append(idx)
    print()
    orig_idx, curr_idx, price_source = detect_price_roles(sentences)
    if curr_idx is None and grouped.get('价格'):
        curr_idx = grouped['价格'][0]
    grouped.setdefault('原价', [])
    grouped.setdefault('上车价', [])
    if orig_idx is not None:
        grouped['原价'].append(orig_idx)
    if curr_idx is not None:
        grouped['上车价'].append(curr_idx)
    price_ids = {orig_idx, curr_idx} - {None}
    for cat in list(grouped.keys()):
        grouped[cat] = [i for i in grouped[cat] if i not in price_ids]
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


    # 全部自动补位完成后，统一把成片压到30秒内
    segs = limit_segments_to_max_duration(segs)
    if not segs: print('无可用段落'); return False
    print(f'\n排序结果 ({len(segs)} 段, {sum(s["src_dur_ms"] for s in segs)/1000:.1f}s):')
    for i, seg in enumerate(segs):
        print(f'  {i}: [{seg["category"]}] {seg["text"][:35]} ({seg["src_dur_ms"]/1000:.1f}s)')

    # ffmpeg 切割
    for old in dp.iterdir():
        if old.suffix == '.mp3' and old.name.startswith('clip_'): old.unlink()

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
    new_audio_mats = [a for a in draft.get('materials', {}).get('audios', []) if a.get('name') != 'audio.mp3']
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
            subprocess.run(['ffmpeg', '-y', '-ss', f'{src_s:.3f}', '-i', str(audio_src), '-t', f'{dur_s:.3f}', '-acodec', 'libmp3lame', '-q:a', '2', str(clip_file)], capture_output=True, text=True)
            r = subprocess.run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(clip_file)], capture_output=True, text=True)
            actual_dur_s = float(r.stdout.strip()) if r.stdout.strip() else dur_s
            actual_dur_us = int(actual_dur_s * 1000000)

        actual_durations.append(actual_dur_us)
        mat_id = uid()
        new_audio_mats.append({
            "id": mat_id, "duration": actual_dur_us, "name": clip_name,
            "path": f"{draft_placeholder}{clip_name}" if draft_placeholder else str(clip_file),
            "type": "sound"
        })
        audio_track['segments'].append({
            "id": uid(), "material_id": mat_id,
            "target_timerange": {"duration": actual_dur_us, "start": tl_us},
            "source_timerange": {"duration": actual_dur_us, "start": 0},
            "speed": 1, "volume": 1, "visible": True,
            "extra_material_refs": []
        })
        print(f'  [{tl_us/1000000:.1f}s] [{seg["source"]}] {seg["category"]} ({actual_dur_us/1000000:.1f}s)')
        tl_us += actual_dur_us

    new_tracks.append(audio_track)
    draft['tracks'] = new_tracks
    draft['materials']['audios'] = new_audio_mats
    draft['duration'] = tl_us
    for v in draft.get('materials', {}).get('videos', []): v['duration'] = tl_us

    write_draft(dp, draft)

    seg_meta = [{'index': i, 'category': s['category'], 'src_start_ms': s['src_start_ms'], 'src_end_ms': s['src_end_ms'], 'src_dur_ms': int(actual_durations[i] / 1000) if i < len(actual_durations) else s['src_dur_ms'], 'source': s.get('source','asr'), 'text': s['text'], 'file': s.get('file')} for i, s in enumerate(segs)]

    with open(dp / 'step4_segments.json', 'w', encoding='utf-8') as f: json.dump(seg_meta, f, ensure_ascii=False, indent=2)

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
    if not visual_check:
        print('已关闭 AI 画面复核，步骤4仅按字幕内容分类')
    success = main(dp_arg, auto_open=auto_open, visual_check=visual_check)
    sys.exit(0 if success else 1)
