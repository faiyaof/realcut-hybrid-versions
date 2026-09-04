# -*- coding: utf-8 -*-
r"""
步骤3-FunASR：用 FunASR 做中文语音识别（流水线第 3 步 ASR）
==========================================================
模型：SeACo-Paraformer-zh(paraformer-zh) + FSMN-VAD + CT-Punc
特点：本地离线、结果稳定（同一音频每次一致）、逐字毫秒时间戳、按标点智能断句。
取代旧的「WhisperX large-v3 + 千问」方案，无需联网/API。

用法:
  python "步骤3-FunASR.py" <草稿路径>            # 识别后自动打开剪映验证
  python "步骤3-FunASR.py" <草稿路径> --no-open  # 只识别，不打开剪映

输出（草稿目录下）:
  - asr_result.json  {"words":[{text,start,end}...], "sentences":[{text,start,end}...], "fingerprint": 音频指纹}（毫秒；音频未变化时复用缓存）
  - asr_result.txt   每行 "句子 start end"

依赖:  pip install funasr modelscope
模型缓存:  D:\.cache\modelscope （首次自动下载 ~2.2GB，之后离线复用）
"""
import json, sys, os, subprocess, time
from pathlib import Path

# 模型缓存放 D 盘，复用已下载模型；抑制无关日志
os.environ.setdefault('MODELSCOPE_CACHE', r'D:\.cache\modelscope')
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
os.environ.setdefault('MODELSCOPE_LOG_LEVEL', '40')

# sentence_info.text 含标点，但 timestamp 只覆盖“非标点字”，用它对齐逐字时间戳
_PUNCT = set('，。？！、,.!?；;：:…—－–～~﹏「」『』（）()【】《》<>“”‘’"\'`·。 \u3000\r\n\t')
_SENT_END = set('。？！.!?')

JY_PATH = r'C:\Users\JT\Desktop\剪映5.9Windows\JianyingPro\5.9.0.11632\JianyingPro.exe'

_MODEL = None


def _load_model():
    global _MODEL
    if _MODEL is None:
        from funasr import AutoModel
        print('加载 FunASR: SeACo-Paraformer-zh + FSMN-VAD + CT-Punc ...')
        _MODEL = AutoModel(
            model='paraformer-zh',
            vad_model='fsmn-vad',
            punc_model='ct-punc',
            disable_update=True,
        )
    return _MODEL


def _find_audio(dp: Path):
    a = dp / 'audio.mp3'
    if a.exists():
        return a
    exts = ('.mp3', '.wav', '.aac', '.m4a', '.flac')
    for f in sorted(dp.iterdir()):
        if f.suffix.lower() in exts and 'audio' in f.stem.lower():
            return f
    for f in sorted(dp.iterdir()):
        if f.suffix.lower() in exts:
            return f
    return None


def _build_from_sentence_info(sentence_info):
    """首选：FunASR sentence_info 已给出带标点句子 + 起止 + 逐字时间戳。"""
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
    """回退：无 sentence_info 时，用逐字时间戳 + 标点分句。"""
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


def _audio_fingerprint(audio):
    return {
        'file': os.path.basename(str(audio)),
        'size': os.path.getsize(audio),
        'mtime': int(os.path.getmtime(audio)),
    }


def _load_cached_asr(dp, audio):
    fp = dp / 'asr_result.json'
    if not fp.exists():
        return None
    try:
        with open(fp, encoding='utf-8') as f:
            data = json.load(f)
        if (data.get('fingerprint') == _audio_fingerprint(audio)
                and data.get('words') and data.get('sentences')):
            return data
    except Exception:
        return None
    return None

def _recognize_with_engine(audio, engine):
    """按引擎识别：'volc' 走火山(云)，否则 FunASR(本地)。
    返回 (words, sentences) 或 (None, None)。"""
    if engine == 'volc':
        import _volc_asr
        return _volc_asr.recognize_audio(audio)
    # FunASR 本地
    model = _load_model()
    try:
        res = model.generate(input=str(audio), batch_size_s=300,
                             sentence_timestamp=True, disable_pbar=True)
    except TypeError:
        res = model.generate(input=str(audio), batch_size_s=300, sentence_timestamp=True)
    r = res[0] if res else {}
    full_text = (r.get('text') or '').replace(' ', '')
    sentence_info = r.get('sentence_info')
    timestamp = r.get('timestamp') or []
    if sentence_info:
        return _build_from_sentence_info(sentence_info)
    return _build_from_flat(full_text, timestamp)


def _do_asr_legacy(draft_path, auto_open=True, engine='funasr'):
    dp = Path(draft_path)
    if not dp.exists():
        print(f'草稿目录不存在: {dp}')
        return False
    audio = _find_audio(dp)
    if not audio:
        print('未找到音频文件（audio.mp3），请先执行步骤2-分离音频')
        return False
    print(f'音频: {audio.name}')

    if engine == 'volc':
        print('识别引擎: 火山 Seed-ASR 2.0（云端）')
    else:
        print('识别引擎: FunASR（本地）')
    print('识别中...')
    words, sentences = _recognize_with_engine(audio, engine)

    if not sentences:
        print('识别结果为空')
        return False

    result = {'words': words, 'sentences': sentences, 'fingerprint': _audio_fingerprint(audio)}
    with open(dp / 'asr_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(dp / 'asr_result.txt', 'w', encoding='utf-8') as f:
        for s in sentences:
            f.write(f"{s['text']} {s['start']} {s['end']}\n")

    print(f'\n完成！{len(sentences)} 句 / {len(words)} 字（逐字毫秒时间戳）')
    for s in sentences:
        print(f'  [{s["start"] / 1000:>6.2f}s-{s["end"] / 1000:>6.2f}s] {s["text"][:50]}')
    print(f'已保存: {dp / "asr_result.json"}')

    if auto_open:
        _open_draft(dp)
    return True


def do_asr(draft_path, auto_open=True, engine='funasr'):
    dp = Path(draft_path)
    if not dp.exists():
        print(f'草稿目录不存在: {dp}')
        return False
    audio = _find_audio(dp)
    if not audio:
        print('未找到音频文件（audio.mp3），请先执行步骤2-分离音频')
        return False
    cached = _load_cached_asr(dp, audio)
    if cached is None:
        return _do_asr_legacy(draft_path, auto_open=auto_open, engine=engine)

    print(f'音频: {audio.name}')
    print('复用已有 ASR 缓存（音频未变化）...')
    words = cached.get('words', [])
    sentences = cached.get('sentences', [])
    if not sentences:
        print('识别结果为空')
        return False
    result = {'words': words, 'sentences': sentences, 'fingerprint': _audio_fingerprint(audio)}
    with open(dp / 'asr_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(dp / 'asr_result.txt', 'w', encoding='utf-8') as f:
        for s in sentences:
            f.write(f"{s['text']} {s['start']} {s['end']}\n")
    print(f'\n完成！{len(sentences)} 句 / {len(words)} 字（逐字毫秒时间戳）')
    for s in sentences:
        print(f'  [{s["start"] / 1000:>6.2f}s-{s["end"] / 1000:>6.2f}s] {s["text"][:50]}')
    print(f'已保存: {dp / "asr_result.json"}')
    if auto_open:
        _open_draft(dp)
    return True


def _open_draft(dp: Path):
    draft_name = os.path.basename(str(dp))
    script_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'scripts')
    open_py = os.path.join(script_dir, 'open_draft.py')
    if not os.path.exists(JY_PATH) or not os.path.exists(open_py):
        print('（跳过自动打开剪映：未找到剪映或 open_draft.py）')
        return
    print('\n打开剪映验证...')
    subprocess.run(['taskkill', '/f', '/im', 'JianyingPro.exe'], capture_output=True, text=True)
    subprocess.Popen([JY_PATH], shell=True)
    time.sleep(20)
    subprocess.run(['python', open_py, draft_name], capture_output=True, text=True)
    print(f'已打开草稿「{draft_name}」请查看')


if __name__ == '__main__':
    args = sys.argv[1:]
    pos = [a for a in args if not a.startswith('--')]
    if not pos:
        print(__doc__)
        sys.exit(1)
    auto_open = '--no-open' not in args
    engine = 'volc'
    if '--engine' in args:
        ei = args.index('--engine')
        engine = args[ei + 1] if ei + 1 < len(args) else 'volc'
    elif '--engine volc' in ' '.join(args):   # 兼容单参数形式
        engine = 'volc'
    sys.exit(0 if do_asr(pos[0], auto_open=auto_open, engine=engine) else 1)
