# -*- coding: utf-8 -*-
"""
_volc_asr.py — 火山引擎 Seed-ASR 2.0 (豆包录音文件识别) 后端。

供 real-cut 流水线替换 FunASR 使用。识别音频文件，并把火山返回归一化成
与 _funasr.recognize_audio 相同的契约：
    recognize_audio(path) -> (words, sentences)
    words:     [{text, start(ms), end(ms)}, ...]   单字级，无标点
    sentences: [{text(带标点短句), start(ms), end(ms)}, ...]  按逗号/句末标点断句

凭证：从本脚本同目录/项目根的 asr_volc.env 读取（或环境变量）。勿硬编码。
  VOLCENGINE_API_KEY=         语音技术控制台签发 API Key
  VOLCENGINE_ACCESS_KEY_ID=   IAM AK
  VOLCENGINE_SECRET_ACCESS_KEY=  IAM SK
  VOLCENGINE_TOS_BUCKET=      TOS 桶名
  VOLCENGINE_TOS_REGION=      默认 cn-beijing

依赖：requests（项目 requirements.txt 已有）。
"""
import os, sys, time, uuid, hashlib, hmac, re
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

try:
    import requests
except ImportError:
    requests = None

# ---------- 凭证加载：asr_volc.env（同目录向上找） ----------
_ENV_VARS = (
    "VOLCENGINE_API_KEY", "VOLCENGINE_ACCESS_KEY_ID",
    "VOLCENGINE_SECRET_ACCESS_KEY", "VOLCENGINE_TOS_BUCKET", "VOLCENGINE_TOS_REGION",
)


def _find_env_file():
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (here, os.path.dirname(here), os.getcwd()):
        p = os.path.join(d, "asr_volc.env")
        if os.path.isfile(p):
            return p
    return None


def _load_env():
    """轻量 .env 解析（无第三方依赖）。已存在的环境变量优先。"""
    fp = _find_env_file()
    if fp:
        with open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k in _ENV_VARS and k not in os.environ:
                    os.environ.setdefault(k, v)


def _creds():
    _load_env()
    return {
        "api_key": os.environ.get("VOLCENGINE_API_KEY", ""),
        "ak": os.environ.get("VOLCENGINE_ACCESS_KEY_ID", ""),
        "sk": os.environ.get("VOLCENGINE_SECRET_ACCESS_KEY", ""),
        "bucket": os.environ.get("VOLCENGINE_TOS_BUCKET", ""),
        "region": os.environ.get("VOLCENGINE_TOS_REGION", "cn-beijing"),
    }


# ---------- TOS 预签名上传 ----------
def _tos_sign_v4(method, url, ak, sk, region, expires=3600):
    parsed = urlparse(url)
    now = datetime.now(timezone.utc)
    date_stamp = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    scope = f"{date_stamp}/{region}/tos/request"
    q = {
        "X-Tos-Algorithm": "TOS4-HMAC-SHA256",
        "X-Tos-Credential": f"{ak}/{scope}",
        "X-Tos-Date": amz_date,
        "X-Tos-Expires": str(expires),
        "X-Tos-SignedHeaders": "host",
    }
    cqs = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(q.items()))
    can_req = "\n".join([
        method, quote(parsed.path, safe="/"), cqs,
        f"host:{parsed.hostname}\n", "host", "UNSIGNED-PAYLOAD",
    ])
    sts = "\n".join([
        "TOS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(can_req.encode()).hexdigest(),
    ])

    def _sign(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    skey = _sign(_sign(_sign(_sign(sk.encode("utf-8"), date_stamp), region), "tos"), "request")
    sig = hmac.new(skey, sts.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{parsed.scheme}://{parsed.hostname}{parsed.path}?{cqs}&X-Tos-Signature={sig}"


def _upload_to_tos(filepath, fmt, creds):
    ak, sk, bucket, region = creds["ak"], creds["sk"], creds["bucket"], creds["region"]
    if not (ak and sk and bucket):
        raise RuntimeError("火山凭证不全：需 VOLCENGINE_ACCESS_KEY_ID / SECRET_ACCESS_KEY / TOS_BUCKET（见 asr_volc.env）")
    obj = f"realcut-asr/{uuid.uuid4()}.{fmt}"
    url_raw = f"https://{bucket}.tos-{region}.volces.com/{obj}"
    put_url = _tos_sign_v4("PUT", url_raw, ak, sk, region, expires=300)
    content_type = "audio/wav" if fmt == "wav" else "audio/mpeg"
    with open(filepath, "rb") as f:
        resp = requests.put(put_url, data=f, headers={"Content-Type": content_type}, timeout=180)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"TOS 上传失败 ({resp.status_code}): {resp.text[:200]}")
    return _tos_sign_v4("GET", url_raw, ak, sk, region, expires=3600)


def _fmt_of(path):
    ext = os.path.splitext(str(path))[1].lower().lstrip(".")
    m = {"mp3": "mp3", "wav": "wav", "m4a": "m4a", "aac": "aac", "mp4": "mp4", "flac": "flac"}
    if ext not in m:
        raise RuntimeError(f"火山不支持音频格式: {ext}")
    return m[ext]


# ---------- 火山 API ----------
_API_BASE = "https://openspeech.bytedance.com/api/v3/auc/bigmodel"
_RES_MAP = {
    "standard": "volc.seedasr.auc",
    "express": "volc.bigasr.auc_turbo",
}


def _headers(api_key, resource_id, rid, sequence=None):
    h = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": rid,
    }
    if sequence is not None:
        h["X-Api-Sequence"] = str(sequence)
    return h


def _body(audio_url, fmt, speakers=True):
    return {
        "user": {"uid": "realcut-hybrid"},
        "audio": {"url": audio_url, "format": fmt},
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,        # 数字归一化 169/499
            "enable_punc": True,       # 标点
            "enable_ddc": True,        # 顺滑/语气词
            "show_utterances": True,
            "enable_speaker_info": speakers,
        },
    }


def _recognize_express(audio_url, fmt, api_key, timeout=300):
    rid = str(uuid.uuid4())
    h = _headers(api_key, _RES_MAP["express"], rid, sequence=None)
    resp = requests.post(f"{_API_BASE}/recognize/flash", headers=h,
                         json=_body(audio_url, fmt), timeout=timeout)
    st = resp.headers.get("X-Api-Status-Code", "")
    if st == "20000003":
        return {"result": {"text": "", "utterances": []}}
    if st != "20000000":
        raise RuntimeError(f"火山极速识别失败: {st} {resp.headers.get('X-Api-Message','')}")
    return resp.json()


def _recognize_standard(audio_url, fmt, api_key, timeout=600):
    rid = str(uuid.uuid4())
    h = _headers(api_key, _RES_MAP["standard"], rid, sequence=-1)
    resp = requests.post(f"{_API_BASE}/submit", headers=h, json=_body(audio_url, fmt), timeout=30)
    st = resp.headers.get("X-Api-Status-Code", "")
    if st != "20000000":
        raise RuntimeError(f"火山提交失败: {st} {resp.headers.get('X-Api-Message','')}")
    qh = _headers(api_key, _RES_MAP["standard"], rid, sequence=None)
    elapsed = 0
    while elapsed < timeout:
        r = requests.post(f"{_API_BASE}/query", headers=qh, json={}, timeout=30)
        s = r.headers.get("X-Api-Status-Code", "")
        if s == "20000000":
            return r.json()
        if s in ("20000001", "20000002"):
            time.sleep(3)
            elapsed += 3
            continue
        if s == "20000003":
            return {"result": {"text": "", "utterances": []}}
        raise RuntimeError(f"火山查询失败: {s} {r.headers.get('X-Api-Message','')}")
    raise RuntimeError(f"火山识别超时({timeout}s)")


# ---------- 归一化：火山 utterances -> 契约(words, sentences) ----------
_PUNCT = set('，。？！、,.!?；;：:…—－–～~﹏「」『』（）()【】《》<>“”‘’"\'`·。 　\r\n\t')
_SENT_END = set('，。？！、,.!?；;')  # 含逗号，短句粒度贴近 FunASR sentence_info


def _split_utterance(text, utt_start, utt_end, utt_words):
    """把一个 utterance 切成短句；字符标点就地插入，逐字对回 words 毫秒。"""
    chars = []
    wi = 0
    for c in text:
        if c in _PUNCT:
            chars.append((c, None, None))
        else:
            if wi < len(utt_words):
                w = utt_words[wi]
                chars.append((c, w["start"], w["end"]))
                wi += 1
            else:
                chars.append((c, None, None))
    sentences, cur, has_c, c_start, c_end = [], [], False, None, None

    def flush():
        nonlocal cur, has_c, c_start, c_end
        if has_c:
            txt = "".join(cur).strip()
            if txt:
                sentences.append({
                    "text": txt,
                    "start": c_start if c_start is not None else utt_start,
                    "end": c_end if c_end is not None else utt_end,
                })
        cur, has_c, c_start, c_end = [], False, None, None

    for c, ws, we in chars:
        cur.append(c)
        if c not in _PUNCT:
            has_c = True
            if ws is not None:
                if c_start is None:
                    c_start = ws
                c_end = we
        if c in _SENT_END and has_c:
            flush()
    flush()
    return sentences


def normalize_volc(payload):
    """火山完整 JSON -> (words, sentences)。无语音返回 (None, None)。"""
    res = payload.get("result") or payload
    utts = res.get("utterances") or []
    words, sentences = [], []
    for u in utts:
        txt = (u.get("text") or "").strip()
        st = int(u.get("start_time", 0) or 0)
        en = int(u.get("end_time", st) or st)
        uw = []
        for w in u.get("words") or []:
            wt = (w.get("text") or "").strip()
            if wt:
                uw.append({
                    "text": wt,
                    "start": int(w.get("start_time", 0) or 0),
                    "end": int(w.get("end_time", 0) or 0),
                })
        if not uw and txt and en > st:
            chars = [c for c in txt if c not in _PUNCT]
            if chars:
                n = len(chars)
                dur = (en - st) // n
                uw = [{"text": c, "start": st + i * dur, "end": st + (i + 1) * dur}
                      for i, c in enumerate(chars)]
        words.extend(uw)
        if txt:
            sentences.extend(_split_utterance(txt, st, en, uw))
    if not sentences:
        return None, None
    return words, sentences


# ---------- 对外主入口 ----------
def recognize_audio(audio_path, tier="express", timeout=600):
    """识别一个音频文件，返回 (words, sentences)；失败抛异常或 (None,None)。
    tier: 'express'(极速, 快) 默认；'standard'(标准)。
    火山极速档若未开通会抛错，可改 standard（已在实测中走通）。"""
    if requests is None:
        raise RuntimeError("缺少 requests，请先 pip install requests")
    creds = _creds()
    if not creds["api_key"]:
        raise RuntimeError("缺少 VOLCENGINE_API_KEY（见 asr_volc.env，参考 _volc_asr.py 顶部说明）")
    fmt = _fmt_of(audio_path)
    url = _upload_to_tos(str(audio_path), fmt, creds)
    if tier == "standard":
        payload = _recognize_standard(url, fmt, creds["api_key"], timeout=timeout)
    else:
        try:
            payload = _recognize_express(url, fmt, creds["api_key"], timeout=timeout)
        except RuntimeError as e:
            if "not granted" in str(e) or "45000030" in str(e):
                print("  [volc] 极速档未开通，回退标准档...", file=sys.stderr)
                payload = _recognize_standard(url, fmt, creds["api_key"], timeout=timeout)
            else:
                raise
    return normalize_volc(payload)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python _volc_asr.py <音频文件> [--tier express|standard]")
        sys.exit(1)
    tier = "express"
    if "--tier" in sys.argv:
        tier = sys.argv[sys.argv.index("--tier") + 1]
    words, sentences = recognize_audio(sys.argv[1], tier=tier)
    if not sentences:
        print("识别为空")
        sys.exit(1)
    print(f"火山 Seed-ASR: {len(sentences)} 句 / {len(words)} 词")
    for s in sentences:
        print(f'  [{s["start"] / 1000:6.2f}-{s["end"] / 1000:6.2f}] {s["text"]}')
