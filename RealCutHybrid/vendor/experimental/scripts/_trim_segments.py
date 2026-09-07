# -*- coding: utf-8 -*-
"""步骤4的实验性静音裁边。

整段音频只调用一次 ffmpeg，同时收集整体音量和长静音区间。后续所有候选句子
都在内存中计算静音占比：句首、句尾的长静音会被裁掉，只有近乎整句无声时才
删除整句。这样不会因局部轻声而误删，也不会为每个候选反复启动 ffmpeg。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


MIN_SPEECH_RATIO = 0.10
SILENCE_MIN_S = 0.5
NOISE_DB = -40


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _parse_silences(stderr: str) -> list[tuple[float, float]]:
    """Parse ffmpeg silencedetect events without pairing unrelated log lines."""
    intervals: list[tuple[float, float]] = []
    active_start: float | None = None
    event_re = re.compile(
        r"silence_(start|end):\s*([-\d.]+)(?:\s*\|\s*silence_duration:\s*([\d.]+))?"
    )
    for match in event_re.finditer(stderr):
        kind, raw_time, raw_duration = match.groups()
        event_time = float(raw_time)
        if kind == "start":
            active_start = event_time
            continue
        if active_start is None and raw_duration is not None:
            active_start = event_time - float(raw_duration)
        if active_start is not None and event_time > active_start:
            intervals.append((max(0.0, active_start), event_time))
        active_start = None
    return _merge_intervals(intervals)


def analyze_audio(audio: str) -> dict[str, Any]:
    """Analyze the complete source once and return reusable silence metadata."""
    result = _run([
        "ffmpeg", "-nostdin", "-i", audio,
        "-af", f"silencedetect=noise={NOISE_DB}dB:d={SILENCE_MIN_S},volumedetect",
        "-f", "null", "-",
    ])
    if result.returncode != 0:
        raise RuntimeError("ffmpeg 静音分析失败")
    volume_match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", result.stderr)
    return {
        "vol_db": float(volume_match.group(1)) if volume_match else None,
        "silences": _parse_silences(result.stderr),
    }


def overall_mean_volume(audio: str) -> float | None:
    """Compatibility helper for callers that only need the global volume."""
    return analyze_audio(audio)["vol_db"]


def _clipped_silences(
    analysis: dict[str, Any], start_s: float, end_s: float
) -> list[tuple[float, float]]:
    clipped = []
    for silence_start, silence_end in analysis.get("silences", []):
        start = max(start_s, float(silence_start))
        end = min(end_s, float(silence_end))
        if end > start:
            clipped.append((start, end))
    return _merge_intervals(clipped)


def analyze_segment(
    analysis: dict[str, Any], start_ms: int, end_ms: int
) -> dict[str, Any]:
    """Calculate one sentence's speech coverage from a shared full-audio analysis."""
    start_s, end_s = start_ms / 1000.0, end_ms / 1000.0
    segment_s = max(end_s - start_s, 0.001)
    silences = _clipped_silences(analysis, start_s, end_s)
    silent_s = sum(end - start for start, end in silences)
    speech_s = max(segment_s - silent_s, 0.0)

    trimmed_start_s = start_s
    trimmed_end_s = end_s
    if silences and silences[0][0] <= start_s + 0.001:
        trimmed_start_s = min(end_s, silences[0][1])
    if silences and silences[-1][1] >= end_s - 0.001:
        trimmed_end_s = max(start_s, silences[-1][0])

    return {
        "vol_db": analysis.get("vol_db"),
        "silences": [
            (round(start, 3), round(end, 3), round(end - start, 3))
            for start, end in silences
        ],
        "speech_s": round(speech_s, 3),
        "ratio": round(speech_s / segment_s, 4),
        "trimmed_start_ms": round(trimmed_start_s * 1000),
        "trimmed_end_ms": round(trimmed_end_s * 1000),
    }


def clean_ordered_segments(
    segs: list[dict],
    audio: str,
    analysis: dict[str, Any] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Trim ASR segment edges and drop only sentences that are almost all silent."""
    shared_analysis = analysis if analysis is not None else analyze_audio(audio)
    kept: list[dict] = []
    dropped: list[dict] = []
    for seg in segs:
        if seg.get("source") != "asr":
            kept.append(seg)
            continue
        start_ms, end_ms = seg.get("src_start_ms"), seg.get("src_end_ms")
        if start_ms is None or end_ms is None or end_ms <= start_ms:
            kept.append(seg)
            continue

        info = analyze_segment(shared_analysis, int(start_ms), int(end_ms))
        if info["ratio"] < MIN_SPEECH_RATIO:
            rejected = dict(seg)
            rejected["silence_analysis"] = info
            dropped.append(rejected)
            print(
                f'  [剪裁] 丢弃近全静音段[{seg.get("category")}] '
                f'"{str(seg.get("text"))[:24]}" ({start_ms/1000:.1f}-{end_ms/1000:.1f}s): '
                f'有效语音占比 {info["ratio"]:.2f} (<{MIN_SPEECH_RATIO})'
            )
            continue

        trimmed_start = int(info["trimmed_start_ms"])
        trimmed_end = int(info["trimmed_end_ms"])
        if trimmed_end > trimmed_start and (
            trimmed_start != int(start_ms) or trimmed_end != int(end_ms)
        ):
            updated = dict(seg)
            updated["original_src_start_ms"] = int(start_ms)
            updated["original_src_end_ms"] = int(end_ms)
            updated["src_start_ms"] = trimmed_start
            updated["src_end_ms"] = trimmed_end
            updated["src_dur_ms"] = trimmed_end - trimmed_start
            updated["silence_trimmed"] = True
            kept.append(updated)
            print(
                f'  [剪裁] 收缩段[{seg.get("category")}] '
                f'"{str(seg.get("text"))[:24]}"：'
                f'{start_ms/1000:.2f}-{end_ms/1000:.2f}s -> '
                f'{trimmed_start/1000:.2f}-{trimmed_end/1000:.2f}s'
            )
        else:
            kept.append(seg)
    return kept, dropped


def reload_sentences(asr_path: str | Path) -> list[dict]:
    with open(asr_path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("sentences", [])


if __name__ == "__main__":
    import sys

    draft = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\54"
    audio = os.path.join(draft, "audio.mp3")
    asr = os.path.join(draft, "asr_result.json")
    if not os.path.exists(audio) or not os.path.exists(asr):
        print("需草稿含 audio.mp3 + asr_result.json")
        raise SystemExit(1)
    full_analysis = analyze_audio(audio)
    print(f'源音频整体音量: {full_analysis["vol_db"]}dB')
    sentences = reload_sentences(asr)
    segs = [
        {
            "category": "测试", "text": sentence["text"],
            "src_start_ms": sentence["start"], "src_end_ms": sentence["end"],
            "src_dur_ms": sentence["end"] - sentence["start"],
            "source": "asr",
        }
        for sentence in sentences
    ]
    output, dropped = clean_ordered_segments(segs, audio, analysis=full_analysis)
    trimmed = sum(bool(seg.get("silence_trimmed")) for seg in output)
    print(f"\n原始 {len(segs)} 段 -> 保留 {len(output)} 段，裁边 {trimmed} 段，丢弃 {len(dropped)} 段")
