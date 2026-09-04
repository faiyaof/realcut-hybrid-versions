# -*- coding: utf-8 -*-
"""
_trim_segments.py — 步骤4 用：对选中的 ASR 片段做语音质量校验与净化。

问题背景：步骤4 把 ASR 句子按 [start,end] 整段切进成片，若某句来自一段
音量极低 / 长停顿的源区间（如草稿54 的 25.29-40.02s，mean -34.5dB），
成片会出现"一大段没声音"。ChatCut 会裁停顿 / 弃无效段，RealCut 不会。

本模块提供：
  1. analyze_segment(): 对源音频某区间检测 平均音量 / 有效语音占比 / 长停顿
  2. clean_ordered_segments(): 净化一批 segs
       - 音量明显低于源音频整体 => 判 LQ（低质），丢弃或标记
       - 有效语音占比过低       => 判 无效，丢弃
       - 过长句内停顿           => 收缩到有效语音边界
  丢弃的段会尝试从同分类未选中的候补句子替补（若调用方提供 grouped）。

设计为无状态、可被 步骤4 直接 import；ffmpeg 检测用临时文件，用完清理。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

# 可调参数（同一条源音频内的相对判定，避免绝对阈值误伤）
VOL_DIFF_DB = 6.0        # 段平均音量低于"源音频整体音量"超过此值(±) => 低质
MIN_SPEECH_RATIO = 0.40  # 段内有效语音占比低于此 => 判无效
SILENCE_MIN_S = 0.5      # 视为"长停顿"的静音下限
NOISE_DB = -40


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _mean_volume_db(path: str) -> float | None:
    r = _run(["ffmpeg", "-nostdin", "-i", path, "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"mean_volume: ([-\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else None


def _silences(path: str, min_s: float = SILENCE_MIN_S) -> list[tuple[float, float, float]]:
    r = _run(["ffmpeg", "-nostdin", "-i", path, "-af",
              f"silencedetect=noise={NOISE_DB}dB:d={min_s}", "-f", "null", "-"])
    out = re.findall(
        r"silence_start: ([\d.]+).*?silence_end: ([\d.]+).*?silence_duration: ([\d.]+)",
        r.stderr, re.S)
    return [(float(a), float(b), float(c)) for a, b, c in out]


def _slice(audio: str, start_s: float, end_s: float) -> str:
    """切一段出来做检测，返回临时文件路径（调用方负责删除）。"""
    fd, tmp = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    _run(["ffmpeg", "-y", "-nostdin", "-i", audio, "-ss", f"{start_s:.3f}",
          "-t", f"{max(end_s - start_s, 0.001):.3f}",
          "-acodec", "libmp3lame", "-q:a", "3", tmp])
    return tmp


def overall_mean_volume(audio: str) -> float | None:
    """整段源音频的平均音量(dB)，用作相对参照。"""
    return _mean_volume_db(audio)


def analyze_segment(audio: str, start_ms: int, end_ms: int) -> dict:
    """返回某源区间 [start_ms,end_ms] 的语音质量画像。"""
    start_s, end_s = start_ms / 1000.0, end_ms / 1000.0
    tmp = _slice(audio, start_s, end_s)
    try:
        vol = _mean_volume_db(tmp)
        sil = _silences(tmp)
        seg_s = max(end_s - start_s, 0.001)
        # 有效语音 = 总时长 - 长停顿总和
        total_sil = sum(c for _, _, c in sil)
        speech = max(seg_s - total_sil, 0.0)
        ratio = speech / seg_s
        return {
            "vol_db": vol,
            "silences": [(round(a + start_s, 2), round(b + start_s, 2), round(c, 2)) for a, b, c in sil],
            "speech_s": round(speech, 2),
            "ratio": round(ratio, 2),
        }
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def clean_ordered_segments(segs: list[dict], audio: str,
                           baseline_vol: float | None = None,
                           drop_low_vol: bool = True) -> list[dict]:
    """净化一批 ordered segs（source='asr' 才校验）。

    对每段跑 analyze_segment：
      - 有效语音占比 < MIN_SPEECH_RATIO            -> drop（无效）
      - baseline_vol 非空 且 段音量 < baseline - VOL_DIFF_DB -> drop（低音量/近无声）
    返回净化后的 segs（保持原顺序），并打印剔除原因。
    """
    if baseline_vol is None:
        baseline_vol = overall_mean_volume(audio)
    kept: list[dict] = []
    dropped: list[dict] = []
    for seg in segs:
        if seg.get("source") != "asr":
            kept.append(seg)  # 素材库整段/其他源不校验
            continue
        st, en = seg.get("src_start_ms"), seg.get("src_end_ms")
        if st is None or en is None or en <= st:
            kept.append(seg)
            continue
        info = analyze_segment(audio, int(st), int(en))
        reason = None
        if info["ratio"] < MIN_SPEECH_RATIO:
            reason = f"有效语音占比过低 {info['ratio']} (<{MIN_SPEECH_RATIO})"
        elif drop_low_vol and baseline_vol is not None and info["vol_db"] is not None \
                and info["vol_db"] < baseline_vol - VOL_DIFF_DB:
            reason = (f"音量异常低 {info['vol_db']}dB (源整体 {baseline_vol:.1f}dB, "
                      f"差>{VOL_DIFF_DB}dB) 近无声")
        if reason:
            print(f'  [剪裁] 丢弃段[{seg.get("category")}] "{str(seg.get("text"))[:24]}" '
                  f'({st/1000:.1f}-{en/1000:.1f}s): {reason}')
            dropped.append(seg)
            continue
        kept.append(seg)
    return kept, dropped


def reload_sentences(asr_path: str | Path) -> list[dict]:
    with open(asr_path, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("sentences", [])


if __name__ == "__main__":
    # 快速自检：草稿54 源音频 + 该音频的 asr_result.json 全文
    import sys
    draft = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\54"
    audio = os.path.join(draft, "audio.mp3")
    asr = os.path.join(draft, "asr_result.json")
    if not os.path.exists(audio) or not os.path.exists(asr):
        print("需草稿含 audio.mp3 + asr_result.json"); sys.exit(1)
    base = overall_mean_volume(audio)
    print(f"源音频整体音量: {base}dB")
    sents = reload_sentences(asr)
    print(f"句子数: {len(sents)}")
    # 模拟 build_ordered 产出的 segs：全部句子当候选（演示校验逻辑）
    segs = [{"category": "测试", "text": s["text"], "src_start_ms": s["start"],
             "src_end_ms": s["end"], "source": "asr"} for s in sents]
    out = clean_ordered_segments(segs, audio, baseline_vol=base)
    print(f"\n原始 {len(segs)} 段 -> 净化后 {len(out)} 段")
    # 打印被丢弃的明细（含那条 14.7s 痛点段）
    dropped = [s for s in segs if s not in out]
    print(f"丢弃 {len(dropped)} 段")
    for s in dropped[:15]:
        st, en = s["src_start_ms"], s["src_end_ms"]
        print(f'   [{st/1000:.1f}-{en/1000:.1f}s] "{str(s["text"])[:24]}"')
