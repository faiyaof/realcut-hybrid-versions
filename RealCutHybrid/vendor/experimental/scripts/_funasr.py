# -*- coding: utf-8 -*-
"""Shared FunASR recognition helpers for real-cut scripts."""
import os

from _runtime_deps import import_external

os.environ.setdefault('MODELSCOPE_CACHE', os.environ.get('REALCUT_MODELSCOPE_CACHE', r'D:\.cache\modelscope'))
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
os.environ.setdefault('MODELSCOPE_LOG_LEVEL', '40')

_PUNCT = set('，。？！、,.!?；;：:…—－–～~﹏「」『』（）()【】《》<>“”‘’"\'`·。 \u3000\r\n\t')
_SENT_END = set('。？！.!?')

_MODEL = None


def load_model():
    global _MODEL
    if _MODEL is None:
        AutoModel = import_external('funasr').AutoModel
        print('加载 FunASR: SeACo-Paraformer-zh + FSMN-VAD + CT-Punc ...')
        _MODEL = AutoModel(
            model='paraformer-zh',
            vad_model='fsmn-vad',
            punc_model='ct-punc',
            disable_update=True,
        )
    return _MODEL


def _build_from_sentence_info(sentence_info):
    sentences, words = [], []
    for s in sentence_info:
        txt = (s.get('text') or '').strip()
        st = int(s.get('start', 0))
        en = int(s.get('end', st))
        if txt:
            sentences.append({'text': txt, 'start': st, 'end': en})
        stamps = s.get('timestamp') or []
        chars = [c for c in txt if c not in _PUNCT]
        for c, ts in zip(chars, stamps):
            try:
                words.append({'text': c, 'start': int(ts[0]), 'end': int(ts[1])})
            except Exception:
                pass
    return words, sentences


def _build_from_flat(full_text, timestamp):
    chars_all = list(full_text or '')
    nz = [c for c in chars_all if c not in _PUNCT]
    words = []
    for c, ts in zip(nz, timestamp):
        try:
            words.append({'text': c, 'start': int(ts[0]), 'end': int(ts[1])})
        except Exception:
            pass
    sentences = []
    cur, cur_start, wi = '', None, 0
    for c in chars_all:
        if c in _PUNCT:
            if c in _SENT_END and cur.strip() and wi > 0:
                sentences.append({'text': cur.strip(), 'start': cur_start, 'end': words[wi - 1]['end']})
                cur, cur_start = '', None
            continue
        if wi < len(words):
            if cur_start is None:
                cur_start = words[wi]['start']
            cur += c
            wi += 1
    if cur.strip() and words:
        sentences.append({'text': cur.strip(), 'start': cur_start if cur_start is not None else words[0]['start'],
                          'end': words[min(wi, len(words)) - 1]['end']})
    if not sentences and words:
        sentences = [{'text': ''.join(w['text'] for w in words), 'start': words[0]['start'], 'end': words[-1]['end']}]
    return words, sentences


def recognize_audio(audio_path):
    """Return (words, sentences) for a single audio file, or (None, None) on failure."""
    model = load_model()
    try:
        res = model.generate(input=str(audio_path), batch_size_s=300,
                             sentence_timestamp=True, disable_pbar=True)
    except TypeError:
        res = model.generate(input=str(audio_path), batch_size_s=300, sentence_timestamp=True)

    r = res[0] if res else {}
    full_text = (r.get('text') or '').replace(' ', '')
    sentence_info = r.get('sentence_info')
    timestamp = r.get('timestamp') or []

    if sentence_info:
        words, sentences = _build_from_sentence_info(sentence_info)
    else:
        words, sentences = _build_from_flat(full_text, timestamp)

    if not sentences:
        return None, None
    return words, sentences
