# -*- coding: utf-8 -*-
"""Price-role detection for experimental step 4.

Reads all ASR sentences, asks the LLM (DeepSeek first, qwen fallback) to label
the original price sentence and the lowest/on-vehicle price sentence, then
falls back to deterministic numeric heuristics when the LLM is unavailable.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from _llm import llm_text_with_provider

PRICE_MARK_KW = ['元', '块钱', '块', '万', '千', '价格', '价位', '原价', '吊牌', '专柜',
                 '上车', '上链接', '开个', '只要', '只需', '到手', '多少钱', '便宜', '贵']
ORIGINAL_PRICE_KW = ['原价', '吊牌', '专柜', '官方', '牌价', '上万', '几万', '一万', '两万',
                     '三万', '几千', '高价', '太贵', '买不起']
CURRENT_PRICE_KW = ['上车', '上链接', '开个', '只要', '只需', '到手', '最低', '低价',
                    '便宜', '几十', '几百', '几十块', '百来', '几块', '多少钱']


def _price_value(text: str) -> Optional[float]:
    values = []
    for m in re.finditer(r'(?<!\d)(\d+(?:[.,，]\d+)?)\s*(万|w|W|千|k|K|元|块钱|块)?', text or ''):
        try:
            n = float(m.group(1).replace(',', '').replace('，', ''))
            unit = (m.group(2) or '').lower()
            if unit in ('万', 'w'):
                n *= 10000
            elif unit in ('千', 'k'):
                n *= 1000
            values.append(n)
        except Exception:
            pass
    for phrase, value in [('上万', 10000), ('几万', 50000), ('两万', 20000), ('一万', 10000),
                          ('三万', 30000), ('几千', 5000), ('一千', 1000), ('几百', 500), ('几十', 50)]:
        if phrase in (text or ''):
            values.append(value)
    return max(values) if values else None


def _has_price(text: str) -> bool:
    if not text:
        return False
    return _price_value(text) is not None or any(k in text for k in PRICE_MARK_KW)


def _clean_role_ids(raw_ids, sentences, max_len):
    out = []
    if isinstance(raw_ids, (str, int)):
        raw_ids = [raw_ids]
    if isinstance(raw_ids, list):
        for x in raw_ids:
            try:
                i = int(x)
            except Exception:
                continue
            if 0 <= i < max_len and i not in out and _has_price(sentences[i].get('text', '')):
                out.append(i)
    return out


def _extract_json_object(content):
    text = (content or '').strip()
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.I)
    text = re.sub(r'\s*```$', '', text, flags=re.I)
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return None
    return text[start:end + 1]


def detect_price_roles(sentences):
    """Return (original_idx, current_idx, source)."""
    candidates = [i for i, s in enumerate(sentences) if _has_price(s.get('text', ''))]
    if not candidates:
        return None, None, 'none'

    numbered = '\n'.join(f'{i}. {s.get("text", "")}' for i, s in enumerate(sentences))
    prompt = (
        '你是直播带货口播审片员。下面是视频全部 ASR 字幕，按编号排列。\n'
        '任务：找出原价句（吊牌/专柜/原价，可能是几千或上万）和上车价句（主播最终给的最低价/上车价）。\n'
        '如果某句同时包含两个价格，优先把它标成上车价，再尽量找另一句作为原价。\n'
        '只输出 JSON，不要解释：{"original_price": [句子ID], "current_price": [句子ID], "reason": "简短判断"}'
        f'\n字幕：\n{numbered}'
    )
    content, provider = llm_text_with_provider(prompt, temperature=0.1, json_mode=True)
    orig_id = curr_id = None
    source = 'fallback'
    if content:
        try:
            j = json.loads(_extract_json_object(content) or content.strip().strip('`'))
            origs = _clean_role_ids(j.get('original_price') or j.get('original'), sentences, len(sentences))
            currs = _clean_role_ids(j.get('current_price') or j.get('current'), sentences, len(sentences))
            if origs and currs:
                orig_id, curr_id = origs[0], currs[0]
                source = provider
                print(f'  [价格角色] LLM({provider}): 原价={orig_id} 上车价={curr_id}')
        except Exception as exc:
            print(f'  [价格角色] LLM 解析失败: {exc}')

    def _by_value(reverse):
        scored = []
        for i in candidates:
            v = _price_value(sentences[i].get('text', ''))
            if v is not None:
                scored.append((v, i))
        scored.sort(key=lambda x: x[0], reverse=reverse)
        return [i for _, i in scored]

    if orig_id is None:
        for i in candidates:
            if any(k in sentences[i].get('text', '') for k in ORIGINAL_PRICE_KW):
                orig_id = i
                break
    if orig_id is None and _by_value(True):
        orig_id = _by_value(True)[0]
    if curr_id is None:
        for i in candidates:
            if any(k in sentences[i].get('text', '') for k in CURRENT_PRICE_KW):
                curr_id = i
                break
    if curr_id is None and _by_value(False):
        curr_id = _by_value(False)[0]

    if orig_id is not None and orig_id == curr_id:
        others = [i for i in candidates if i != curr_id]
        if others:
            if any(k in sentences[curr_id].get('text', '') for k in CURRENT_PRICE_KW):
                high = _by_value(True)
                orig_id = next((i for i in high if i != curr_id), None)
            else:
                low = _by_value(False)
                curr_id = next((i for i in low if i != orig_id), None)

    print(f'  [价格角色] 原价句={orig_id} 上车价句={curr_id} (来源: {source})')
    return orig_id, curr_id, source
