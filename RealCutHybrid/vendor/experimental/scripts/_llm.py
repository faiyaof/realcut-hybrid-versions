# -*- coding: utf-8 -*-
"""OpenAI-compatible-first LLM helper for experimental real-cut scripts.

Uses a configurable OpenAI-compatible endpoint when OPENAI_API_KEY and
OPENAI_LLM_ENABLED are set, then falls back to DeepSeek and DashScope qwen-plus.
"""
from __future__ import annotations

import os
from typing import Optional

from _runtime_deps import import_external

OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-5.5')
DEEPSEEK_BASE_URL = os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')
DEEPSEEK_MODEL = os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')
QWEN_FALLBACK_MODEL = os.environ.get('QWEN_FALLBACK_MODEL', 'qwen-plus')


def _openai_text(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.1,
    json_mode: bool = False,
    max_retries: int = 2,
    timeout: int = 60,
) -> Optional[str]:
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key or os.environ.get('OPENAI_LLM_ENABLED', '').strip() not in {'1', 'true', 'yes'}:
        return None
    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': prompt})
    payload = {'model': OPENAI_MODEL, 'messages': messages, 'temperature': temperature}
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
    url = f'{OPENAI_BASE_URL}/chat/completions'
    for attempt in range(max_retries + 1):
        try:
            requests = import_external('requests')
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code == 400 and json_mode:
                payload.pop('response_format', None)
                r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code == 400 and 'temperature' in payload:
                payload.pop('temperature', None)
                r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code != 200:
                print(f'  [LLM] OpenAI-compatible API {r.status_code}: {r.text[:300]}')
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    return None
                continue
            content = r.json()['choices'][0]['message']['content']
            if content and content.strip():
                return content.strip()
        except Exception as exc:
            print(f'  [LLM] OpenAI-compatible 调用异常({exc})')
            if attempt >= max_retries:
                return None
    return None


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
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    return None
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
    deepseek_timeout: int = 60,
    deepseek_max_retries: int = 2,
) -> tuple[Optional[str], str]:
    content = _openai_text(
        prompt,
        system=system,
        temperature=temperature,
        json_mode=json_mode,
        timeout=deepseek_timeout,
        max_retries=deepseek_max_retries,
    )
    if content is not None:
        return content, f'openai:{OPENAI_MODEL}'
    content = _deepseek_text(
        prompt,
        system=system,
        temperature=temperature,
        json_mode=json_mode,
        timeout=deepseek_timeout,
        max_retries=deepseek_max_retries,
    )
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
