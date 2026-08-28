# -*- coding: utf-8 -*-
"""DeepSeek-first LLM helper for experimental real-cut scripts.

Uses the OpenAI-compatible DeepSeek API when DEEPSEEK_API_KEY is set.
Falls back to DashScope qwen-plus so existing projects keep working.
"""
from __future__ import annotations

import os
from typing import Optional

from _runtime_deps import import_external

DEEPSEEK_BASE_URL = os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')
DEEPSEEK_MODEL = os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')
QWEN_FALLBACK_MODEL = os.environ.get('QWEN_FALLBACK_MODEL', 'qwen-plus')


def _deepseek_text(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.1,
    json_mode: bool = False,
    max_retries: int = 2,
    timeout: int = 60,
) -> Optional[str]:
    key = os.environ.get('DEEPSEEK_API_KEY', '').strip()
    if not key:
        return None

    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': prompt})

    payload = {
        'model': DEEPSEEK_MODEL,
        'messages': messages,
        'temperature': temperature,
    }
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}

    headers = {
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    }
    url = f'{DEEPSEEK_BASE_URL}/chat/completions'

    for attempt in range(max_retries + 1):
        try:
            requests = import_external('requests')
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code == 400 and json_mode:
                payload.pop('response_format', None)
                r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code != 200:
                body = r.text[:300]
                print(f'  [LLM] DeepSeek API {r.status_code}: {body}')
                if attempt < max_retries:
                    continue
                return None
            data = r.json()
            content = data['choices'][0]['message']['content']
            if content and content.strip():
                return content.strip()
        except Exception as exc:
            print(f'  [LLM] DeepSeek 调用异常({exc})')
            if attempt < max_retries:
                continue
    return None


def _qwen_text(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.1,
    max_retries: int = 2,
) -> Optional[str]:
    key = os.environ.get('DASHSCOPE_API_KEY', '').strip()
    if not key:
        return None
    try:
        dashscope = import_external('dashscope')
        Generation = dashscope.Generation
    except ImportError:
        print('  [LLM] dashscope 未安装，无法回退')
        return None

    dashscope.api_key = key
    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': prompt})

    for attempt in range(max_retries + 1):
        try:
            resp = Generation.call(
                model=QWEN_FALLBACK_MODEL,
                messages=messages,
                result_format='message',
                temperature=temperature,
            )
            if getattr(resp, 'status_code', 0) != 200:
                print(f'  [LLM] qwen API {getattr(resp, "status_code", 0)}')
                if attempt < max_retries:
                    continue
                return None
            content = resp.output.choices[0].message.content
            if content and content.strip():
                return content.strip()
        except Exception as exc:
            print(f'  [LLM] qwen 调用异常({exc})')
            if attempt < max_retries:
                continue
    return None


def llm_text_with_provider(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.1,
    json_mode: bool = False,
) -> tuple[Optional[str], str]:
    content = _deepseek_text(prompt, system=system, temperature=temperature, json_mode=json_mode)
    if content is not None:
        return content, f'deepseek:{DEEPSEEK_MODEL}'
    content = _qwen_text(prompt, system=system, temperature=temperature)
    if content is not None:
        return content, f'qwen:{QWEN_FALLBACK_MODEL}'
    return None, 'none'


def llm_text(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.1,
    json_mode: bool = False,
) -> Optional[str]:
    return llm_text_with_provider(prompt, system=system, temperature=temperature, json_mode=json_mode)[0]
