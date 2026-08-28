#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RealCut Hybrid
==============

A thin task orchestrator around an untouched copy of the real-cut skill.

It keeps real-cut's verified 12-step editing rules as the core engine, and
adds the useful parts from LiveClipAgent-style automation:

- per-task state JSON
- checkpoint / resume
- snapshot before each step
- rollback + bounded retry
- batch mode
- structured reports and logs

It deliberately does NOT include LiveClipAgent's compiled black-box runtime,
unstable UI-driven export, or its quality-gate over-engineering.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import random
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from manifest import ManifestStore
from manifest import ManifestStore, resolve_officecli
import postprocess

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor" / "experimental"
SCRIPTS = VENDOR / "scripts"
STATE_DIR = ROOT / "state"
LOG_DIR = ROOT / "logs"
SNAPSHOT_DIR = ROOT / "snapshots"
REPORT_DIR = ROOT / "reports"
MANIFEST_DIR = ROOT / "manifests"
DEFAULT_MANIFEST = MANIFEST_DIR / "realcut-batch.xlsx"

DEFAULT_DRAFT_ROOT = Path(
    os.environ.get(
        "REALCUT_DRAFT_ROOT",
        r"C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft",
    )
)
DEFAULT_JIANYING_EXE = Path(
    os.environ.get(
        "REALCUT_JIANYING_EXE",
        r"C:\Users\JT\Desktop\剪映5.9Windows\JianyingPro\5.9.0.11632\JianyingPro.exe",
    )
)
DEFAULT_KEYWORD_FILE = Path(os.environ.get("REALCUT_KEYWORD_FILE", str(ROOT / "config" / "highlight_keywords.txt")))

SCHEMA_VERSION = 1

HIDDEN_PACE_TARGET_SECONDS = 900.0
HIDDEN_PACE_MIN_SECONDS = 30.0
HIDDEN_PACE_MAX_SECONDS = 60.0

# Pacing lives outside task state so the web UI only sees normal step progress.


@dataclass(frozen=True)
class StepSpec:
    key: str
    label: str
    script: str
    order: float
    phase: str = "edit"
    needs_draft: bool = True
    no_open: bool = False


STEPS: list[StepSpec] = [
    StepSpec("1_import", "步骤1-导入视频", "导入视频到剪映.py", 1.0, needs_draft=False, no_open=True),
    StepSpec("2_separate_audio", "步骤2-分离音频", "步骤2-分离音频.py", 2.0, no_open=True),
    StepSpec("3_asr", "步骤3-FunASR", "步骤3-FunASR.py", 3.0, no_open=True),
    StepSpec("4_select_sort", "步骤4-切割排序", "步骤4-切割排序.py", 4.0, no_open=True),
    StepSpec("mirror", "镜像补位", "mirror_通用.py", 4.5),
    StepSpec("4_open_box", "步骤4后-开盒补位", "步骤4后-开盒补位.py", 4.7, no_open=True),
    StepSpec("5_fade", "步骤5-淡入淡出", "步骤5-淡入淡出.py", 5.0, no_open=True),
    StepSpec("6_visual", "步骤6-画面匹配", "步骤6-画面匹配.py", 6.0, no_open=True),
    StepSpec("8_transition", "步骤8-转场特效", "步骤8-转场特效.py", 8.0),
    StepSpec("9_flower_sfx", "步骤9-花字音效", "步骤9-花字音效.py", 9.0),
    StepSpec("10_bgm", "步骤10-添加BGM", "步骤10-添加BGM.py", 10.0),
    StepSpec("audio_smooth", "音频平滑", "audio_smooth.py", 10.5, no_open=True),
    StepSpec("11_watermark", "步骤11-添加水印", "步骤11-添加水印.py", 11.0),
    StepSpec("7_subtitles", "步骤7-生成字幕", "步骤7-生成字幕.py", 7.0, phase="subtitle"),
    StepSpec("12_style", "步骤12-字体样式", "步骤12-字体样式.py", 12.0, phase="subtitle"),
    StepSpec("style_apply", "风格套用", "apply_style.py", 13.0, phase="style"),
    StepSpec("bgm_normalize", "BGM归一化", "bgm_normalize.py", 14.0, phase="style", no_open=True),
    StepSpec("subtitle_gaps", "字幕空隙补齐", "fill_subtitle_gaps.py", 15.5, phase="style", no_open=True),
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(message: str, task_id: Optional[str] = None) -> None:
    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}")
    if task_id:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{task_id}.log"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {message}\n")


def _json_read(path: Path, default=None):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def atomic_write_text(path: Path, text: str) -> None:
    """Write text with a short retry, then fall back to in-place write.

    Windows can briefly refuse os.replace() when another process is reading the
    target file (for example the Web bootstrap poller). Retry first, then rewrite
    the target in place so a transient read handle cannot fail a whole task.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    last_error = None
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    try:
        path.write_bytes(tmp.read_bytes())
        tmp.unlink(missing_ok=True)
        return
    except OSError as exc:
        raise last_error or exc


def _json_write(path: Path, data) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def draft_style_name(draft: Optional[Path]) -> Optional[str]:
    """从草稿已有风格标记或本地默认风格配置推导风格名。"""
    if draft is None:
        return None
    data = _json_read(draft / "draft_content.json", {})
    mark = data.get("style_applied") or ""
    prefix = "__style_overlay_"
    if isinstance(mark, str) and mark.startswith(prefix):
        name = mark[len(prefix):]
        return name[:-2] if name.endswith("模板") else name
    try:
        cfg = json.loads((DEFAULT_DRAFT_ROOT.parent / "style_config.json").read_text(encoding="utf-8-sig"))
        return cfg.get("default_style") or None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def task_id_for(video: Path) -> str:
    raw = str(video.resolve()).casefold()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def video_signature(video: Path) -> dict:
    stat = video.stat()
    return {
        "path": str(video.resolve()),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }


def new_state(video: Path) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id_for(video),
        "video": str(video.resolve()),
        "video_signature": video_signature(video),
        "draft": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "status": "pending",
        "last_error": None,
        "steps": {},
    }


def load_state(task_id: str) -> dict:
    return _json_read(STATE_DIR / f"{task_id}.json", default={})


def save_state(state: dict) -> None:
    state["updated_at"] = now_iso()
    _json_write(STATE_DIR / f"{state['task_id']}.json", state)


def ensure_project_dirs() -> None:
    for path in (STATE_DIR, LOG_DIR, SNAPSHOT_DIR, REPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def step_enabled(step: StepSpec, opts: argparse.Namespace) -> bool:
    if opts.phase2 and step.key not in {"5_fade", "7_subtitles", "12_style", "style_apply", "audio_smooth", "bgm_normalize", "subtitle_gaps"}:
        return False
    if step.key == "9_flower_sfx":
        return bool(
            opts.enable_flower_text
            or os.environ.get("REALCUT_ENABLE_HUAZI", "").strip() == "1"
        )
    if step.key == "11_watermark":
        return bool(opts.watermark)
    if step.key == "audio_smooth":
        return bool(opts.smooth_audio)
    if step.key == "style_apply":
        return bool(opts.style)
    if step.key == "bgm_normalize":
        return bool(opts.style or opts.phase2)
    return True


def script_path(step: StepSpec) -> Path:
    return SCRIPTS / step.script


def build_args(step: StepSpec, video: Path, draft: Path, opts: argparse.Namespace) -> list[str]:
    if step.key == "1_import":
        return [str(video), "--no-open"]
    if step.key == "10_bgm":
        args = [str(draft), "--bgm", str(opts.bgm)]
        if step.no_open:
            args.append("--no-open")
        return args
    if step.no_open:
        return [str(draft), "--no-open"]
    if step.key == "11_watermark":
        return [str(draft), "--force"]
    if step.key == "7_subtitles":
        args = [str(draft)]
        if not opts.review_subtitles:
            args.append("--no-review")
        return args
    if step.key == "style_apply":
        style = opts.style or draft_style_name(draft)
        args = [str(draft)]
        if style:
            args += ["--style", style]
        return args
    return [str(draft)]


def run_process(cmd: list[str], task_id: Optional[str], step_label: str) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    log(f"[{step_label}] 执行: {cmd[0]}", task_id)
    proc = subprocess.Popen(
        cmd,
        cwd=str(SCRIPTS),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=flags,
    )
    assert proc.stdout is not None
    lines: list[str] = []
    for line in proc.stdout:
        line = line.rstrip()
        lines.append(line)
        print(f"  {line}")
    returncode = proc.wait()
    output = "\n".join(lines)
    if returncode != 0:
        log(f"[{step_label}] 退出码 {returncode}", task_id)
    return returncode, output


def _is_snapshot_relevant(name: str) -> bool:
    p = Path(name)
    suffix = p.suffix.lower()
    if suffix in {".json", ".tmp", ".txt"}:
        return True
    if p.name == "draft_settings" or p.name == "draft.extra":
        return True
    if ".bak" in p.name or ".backup" in p.name:
        return True
    return False


def _ignore_heavy(_dir: str, files: list[str]) -> list[str]:
    media = {
        ".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".m4v",
        ".mp3", ".m4a", ".wav", ".aac", ".flac", ".jpg", ".jpeg", ".png",
    }
    ignored = []
    for name in files:
        p = Path(name)
        if p.name == "__pycache__" or p.suffix.lower() in media:
            ignored.append(name)
    return ignored


def snapshot_draft(
    draft: Path, task_id: str, step: StepSpec, mode: str
) -> Optional[Path]:
    if mode == "off" or not draft.is_dir():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest = SNAPSHOT_DIR / task_id / f"before_{step.key}_{stamp}"
    if mode == "json":
        shutil.copytree(
            draft,
            dest,
            ignore=lambda d, files: [f for f in files if not _is_snapshot_relevant(f)],
        )
    else:
        shutil.copytree(draft, dest, ignore=_ignore_heavy)
    log(f"[{step.label}] 已保存步骤前快照: {dest}", task_id)
    return dest


def restore_snapshot(snapshot: Optional[Path], draft: Path, task_id: str, step_label: str) -> None:
    if snapshot is None or not snapshot.is_dir():
        return
    if not draft.is_dir():
        raise RuntimeError(f"恢复失败：目标草稿不存在 {draft}")
    for root, _dirs, files in os.walk(snapshot):
        rel = Path(root).relative_to(snapshot)
        target = draft / rel
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            shutil.copy2(Path(root) / name, target / name)
    log(f"[{step_label}] 已从快照恢复: {snapshot}", task_id)


def jianying_running() -> bool:
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq JianyingPro.exe"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
        return "JianyingPro.exe" in r.stdout
    except Exception:
        return False


def close_jianying(task_id: Optional[str]) -> None:
    if not jianying_running():
        return
    log("检测到剪映正在运行，执行 taskkill 后继续", task_id)
    subprocess.run(
        ["taskkill", "/f", "/t", "/im", "JianyingPro.exe"],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "CREATE_NO_WINDOW")
        else 0,
    )


def ensure_jianying_closed(task_id: Optional[str], context: str = "") -> None:
    if not jianying_running():
        return
    for _attempt in range(3):
        close_jianying(task_id)
        time.sleep(0.5)
        if not jianying_running():
            return
    suffix = f"（{context}）" if context else ""
    raise RuntimeError(f"无法关闭剪映进程{suffix}；为避免草稿损坏，任务已停止")


def hidden_step_pause(
    opts: argparse.Namespace,
    task_id: str,
    pace_started: Optional[float],
    pace_completed: int,
    pace_planned: int,
) -> None:
    if opts.dry_run or opts.phase2 or opts.start_from or opts.stop_after:
        return
    if pace_started is None or pace_planned <= 0 or pace_completed <= 0:
        return
    if pace_completed >= pace_planned:
        return
    elapsed = time.monotonic() - pace_started
    expected = HIDDEN_PACE_TARGET_SECONDS * pace_completed / pace_planned
    remaining = expected - elapsed
    if remaining <= 0:
        return
    wait = min(random.uniform(HIDDEN_PACE_MIN_SECONDS, HIDDEN_PACE_MAX_SECONDS), remaining)
    if wait > 0:
        time.sleep(wait)


def count_planned_steps(opts: argparse.Namespace, draft: Optional[Path]) -> int:
    count = 0
    for step in STEPS:
        if step.key == "1_import" and (opts.draft is not None or (draft is not None and not opts.force)):
            continue
        if not step_enabled(step, opts):
            continue
        if step.key == "10_bgm" and opts.bgm == 0:
            continue
        count += 1
    return count


def _bgm_volume_ok(data: dict) -> bool:
    mats = {m.get("id"): m for m in data.get("materials", {}).get("audios", []) + data.get("materials", {}).get("music", [])}
    for tr in data.get("tracks", []):
        if tr.get("type") != "audio":
            continue
        for seg in tr.get("segments", []) or []:
            mat = mats.get(seg.get("material_id", ""))
            if mat and mat.get("type") == "music":
                vol = seg.get("volume")
                if vol is None or float(vol) > 0.11:
                    return False
    return True


def _dynamic_fonts_unified(data: dict) -> bool:
    ids = set()
    for tr in data.get("tracks", []):
        if tr.get("type") == "text" and tr.get("flag") == 1:
            ids.update(s.get("material_id", "") for s in tr.get("segments", []) or [])
    fonts = set()
    for m in data.get("materials", {}).get("texts", []):
        if m.get("id") in ids and m.get("type") == "subtitle":
            fonts.add((m.get("font_resource_id"), m.get("font_path")))
    return bool(ids) and len(fonts) == 1


def verify_step_output(
    step: StepSpec, draft: Path, opts: argparse.Namespace
) -> None:
    if not draft.is_dir():
        raise RuntimeError(f"草稿目录不存在: {draft}")
    if not (draft / "draft_content.json").is_file():
        raise RuntimeError(f"缺少 draft_content.json: {draft}")

    if step.key == "3_asr":
        if not (draft / "asr_result.json").is_file():
            raise RuntimeError("步骤3验证失败：缺少 asr_result.json")
    elif step.key == "4_select_sort":
        if not (draft / "step4_segments.json").is_file():
            raise RuntimeError("步骤4验证失败：缺少 step4_segments.json")
    elif step.key == "audio_smooth":
        if not (draft / ".audio_smooth_backup").is_dir():
            raise RuntimeError("音频平滑验证失败：缺少 .audio_smooth_backup")
        if not (draft / "audio_smooth_report.json").is_file():
            raise RuntimeError("音频平滑验证失败：缺少 audio_smooth_report.json")
    elif step.key == "7_subtitles":
        subs = draft / "字幕.txt"
        if not subs.is_file() or subs.stat().st_size == 0:
            raise RuntimeError("步骤7验证失败：字幕.txt 缺失或为空")
        if opts.review_subtitles and not (draft / "subtitle_review.json").is_file():
            raise RuntimeError("步骤7验证失败：未生成 subtitle_review.json")
    elif step.key == "12_style":
        data = _json_read(draft / "draft_content.json", {})
        if not isinstance(data, dict) or not data.get("config", {}).get("subtitle_keywords_config"):
            raise RuntimeError("步骤12验证失败：未写入 subtitle_keywords_config")
    elif step.key == "bgm_normalize":
        data = _json_read(draft / "draft_content.json", {})
        if not _bgm_volume_ok(data):
            raise RuntimeError("BGM归一化验证失败：音量未降到 -20dB 左右")
    elif step.key == "subtitle_gaps":
        gaps_report = _json_read(draft / "subtitle_gaps_report.json", {})
        if gaps_report.get("status") not in {"OK", "NO_SUBTITLES"}:
            raise RuntimeError("字幕空隙补齐验证失败：缺少 subtitle_gaps_report.json")
        if gaps_report.get("status") == "OK" and not gaps_report.get("segments"):
            raise RuntimeError("字幕空隙补齐验证失败：报告未记录字幕段")


def resolve_draft(value: str) -> Path:
    p = Path(value)
    if p.is_dir():
        return p.resolve()
    candidate = DEFAULT_DRAFT_ROOT / value
    if candidate.is_dir():
        return candidate
    raise RuntimeError(f"草稿不存在: {value}")


def detect_new_draft(output: str, before: set[Path]) -> Path:
    match = re.search(r"草稿「(.+?)」创建完成", output)
    if match:
        name = match.group(1).strip()
        candidate = DEFAULT_DRAFT_ROOT / name
        if candidate.is_dir():
            return candidate
    candidates = [
        p
        for p in DEFAULT_DRAFT_ROOT.iterdir()
        if p.is_dir() and p not in before and (p / "draft_content.json").is_file()
    ]
    if not candidates:
        raise RuntimeError("步骤1完成后未能识别新草稿")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def run_step_once(
    step: StepSpec,
    opts: argparse.Namespace,
    state: dict,
    video: Path,
    draft: Optional[Path],
    pace_started: Optional[float] = None,
    pace_completed: int = 0,
    pace_planned: int = 0,
) -> tuple[bool, Optional[Path], str]:
    task_id = state["task_id"]
    st = state["steps"].setdefault(
        step.key,
        {
            "label": step.label,
            "status": "pending",
            "attempts": 0,
            "last_error": None,
            "last_output_tail": None,
            "last_failure_signature": None,
            "last_attempt_snapshot": None,
            "started_at": None,
            "finished_at": None,
            "duration_s": None,
        },
    )
    st["status"] = "running"
    st["started_at"] = now_iso()
    save_state(state)

    snapshot: Optional[Path] = None
    if not opts.dry_run and step.needs_draft and draft is not None and opts.snapshot_mode != "off":
        snapshot = snapshot_draft(draft, task_id, step, opts.snapshot_mode)
        st["last_attempt_snapshot"] = str(snapshot) if snapshot else None
        save_state(state)

    if not opts.dry_run:
        if opts.no_close_jianying:
            if jianying_running():
                raise RuntimeError("剪映正在运行；必须先关闭剪映，或去掉 --no-close-jianying")
        else:
            ensure_jianying_closed(task_id, f"执行{step.label}前")

    if opts.dry_run:
        cmd = build_args(step, video, draft, opts)
        log(f"[{step.label}] dry-run 命令: python {script_path(step).name} {' '.join(cmd)}", task_id)
        st["status"] = "completed"
        st["attempts"] = 1
        st["finished_at"] = now_iso()
        st["duration_s"] = 0.0
        save_state(state)
        return True, draft, ""

    max_attempts = max(1, opts.max_attempts)
    prev_signature: Optional[str] = None
    last_error = ""
    output_tail = ""

    for attempt in range(1, max_attempts + 1):
        started = datetime.now().timestamp()
        if attempt > 1 and snapshot is not None:
            restore_snapshot(snapshot, draft, task_id, step.label)
        cmd = build_args(step, video, draft, opts)
        log(f"[{step.label}] 第 {attempt}/{max_attempts} 次", task_id)
        returncode, output = run_process([str(sys.executable), str(script_path(step))] + cmd, task_id, step.label)
        if not opts.dry_run and not opts.no_close_jianying:
            ensure_jianying_closed(task_id, f"执行{step.label}后")
        output_tail = output[-3000:]
        success = returncode == 0
        if success:
            try:
                if step.needs_draft:
                    verify_step_output(step, draft, opts)
            except Exception as exc:
                success = False
                last_error = str(exc)
                log(f"[{step.label}] 输出校验失败: {last_error}", task_id)
        else:
            last_error = f"脚本退出码 {returncode}"
            log(f"[{step.label}] 失败: {last_error}", task_id)

        st["attempts"] = attempt
        st["last_output_tail"] = output_tail
        st["last_error"] = last_error
        st["last_failure_signature"] = hashlib.sha256(
            last_error.encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        st["finished_at"] = now_iso()
        st["duration_s"] = round(datetime.now().timestamp() - started, 2)
        save_state(state)

        if success:
            st["status"] = "completed"
            save_state(state)
            if step.key == "style_apply" and draft is not None:
                state["style"] = opts.style or draft_style_name(draft)
            save_state(state)
            hidden_step_pause(opts, task_id, pace_started, pace_completed, pace_planned)
            return True, draft, output

        if attempt >= max_attempts:
            break
        if st["last_failure_signature"] == prev_signature:
            log(f"[{step.label}] 错误签名相同，停止重复重试", task_id)
            break
        prev_signature = st["last_failure_signature"]

    st["status"] = "failed"
    save_state(state)
    return False, draft, output_tail


def write_report(state: dict) -> Path:
    task_id = state["task_id"]
    report = REPORT_DIR / f"{task_id}.md"
    lines = [
        f"# RealCut Hybrid 任务报告",
        "",
        f"- 任务 ID: {task_id}",
        f"- 状态: {state.get('status')}",
        f"- 源视频: {state.get('video')}",
        f"- 草稿: {state.get('draft') or '未创建'}",
        f"- 创建: {state.get('created_at')}",
        f"- 更新: {state.get('updated_at')}",
        "",
        "## 步骤状态",
        "",
        "| 步骤 | 状态 | 尝试 | 耗时 | 错误 |",
        "|---|---:|---:|---:|---|",
    ]
    for step in STEPS:
        st = state["steps"].get(step.key, {})
        status = st.get("status", "pending")
        attempts = st.get("attempts", 0)
        duration = st.get("duration_s")
        duration_text = f"{duration}s" if duration is not None else "-"
        error = (st.get("last_error") or "").replace("|", "\\|")
        lines.append(
            f"| {step.label} | {status} | {attempts} | {duration_text} | {error} |"
        )
    lines.append("")
    draft = Path(state.get("draft", "")) if state.get("draft") else None
    if draft and (draft / "subtitle_gaps_report.json").is_file():
        gaps = _json_read(draft / "subtitle_gaps_report.json", {})
        lines.append("## 字幕空隙补齐")
        lines.append("")
        lines.append(f"- 状态: {gaps.get('status') or '-'}")
        lines.append(f"- 字幕段数: {gaps.get('segments', 0)}")
        lines.append(f"- 修改段数: {gaps.get('changes', 0)}")
        if gaps.get("gaps_before_us"):
            lines.append(f"- 补前空隙: {len(gaps['gaps_before_us'])} 处")
        lines.append("")
    if draft and (draft / "subtitle_review.json").is_file():
        review = _json_read(draft / "subtitle_review.json", {})
        lines.append("## 字幕审校")
        lines.append("")
        summary = review.get("summary", {}) or {}
        lines.append(f"- 总条数: {summary.get('total', 0)}")
        lines.append(f"- 需要复核: {summary.get('needs_review', 0)}")
        lines.append("")
        for item in review.get("items", []) or []:
            if item.get("needs_review"):
                lines.append(f"- {item.get('start_ms', '?')}-{item.get('end_ms', '?')}ms: {item.get('raw', '')} -> {item.get('final', '')}（{item.get('reason', '')}）")
        lines.append("")
    lines.append("## 错误现场")
    lines.append("")
    for step in STEPS:
        st = state["steps"].get(step.key, {})
        if st.get("status") == "failed":
            lines.append(f"### {step.label}")
            lines.append("")
            lines.append(f"```\n{st.get('last_error') or '-'}\n```")
            tail = st.get("last_output_tail") or ""
            if tail:
                lines.append("")
                lines.append("输出尾部：")
                lines.append("")
                lines.append(f"```\n{tail[-1200:]}\n```")
            lines.append("")
    _json_write(REPORT_DIR / f"{task_id}.json", state)
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def dry_run_task(video: Path, opts: argparse.Namespace, task_id: str) -> int:
    """Print the real task plan without writing state or reports."""
    draft = resolve_draft(opts.draft) if opts.draft else None
    if opts.start_from and opts.start_from > 1 and draft is None:
        log("断点续跑必须提供 --draft 或已有任务状态", task_id)
        return 2
    if opts.phase2 and draft is None:
        log("--phase2 需要 --draft 或已有任务状态", task_id)
        return 2
    log(f"dry-run 计划：{video}", task_id)
    for step in STEPS:
        if step.key == "1_import" and opts.draft is not None:
            continue
        if not step_enabled(step, opts):
            continue
        if opts.start_from and step.order < opts.start_from:
            continue
        if opts.stop_after and step.order > opts.stop_after:
            continue
        if step.key == "10_bgm" and opts.bgm == 0:
            continue
        cmd = build_args(step, video, draft, opts)
        log(f"[{step.label}] dry-run 命令: python {script_path(step).name} {' '.join(cmd)}", task_id)
        if step.key == "1_import":
            draft = DEFAULT_DRAFT_ROOT / video.stem
    log("dry-run 结束，不写入状态", task_id)
    return 0


def run_task(opts: argparse.Namespace, video_path: Path) -> int:
    video = video_path.resolve()
    if not video.is_file():
        log(f"源视频不存在: {video}")
        return 2

    task_id = task_id_for(video)
    if opts.dry_run:
        return dry_run_task(video, opts, task_id)
    state = load_state(task_id)
    if state and state.get("video_signature") != video_signature(video) and not opts.fresh:
        log("检测到同一路径的视频已变化，新建任务状态", task_id)
        state = {}
    if not state:
        state = new_state(video)
    if opts.fresh:
        state["steps"] = {}
        state["status"] = "pending"
        state["last_error"] = None
        if not opts.draft:
            state.pop("draft", None)
            state.pop("style", None)
    if not opts.fresh:
        recorded_draft = state.get("draft")
        if recorded_draft and not Path(recorded_draft).is_dir():
            log("记录草稿目录不存在，重置为从头运行", task_id)
            state["steps"] = {}
            state["status"] = "pending"
            state["last_error"] = None
            state.pop("draft", None)
            state.pop("style", None)
    state["video"] = str(video)
    state["video_signature"] = video_signature(video)

    draft: Optional[Path] = None
    if opts.draft:
        draft = resolve_draft(opts.draft)
        state["draft"] = str(draft)
    elif state.get("draft") and Path(state["draft"]).is_dir():
        draft = Path(state["draft"])

    if opts.start_from and opts.start_from > 1 and draft is None:
        log("断点续跑必须提供 --draft 或已有任务状态", task_id)
        return 2
    if opts.phase2 and draft is None:
        log("--phase2 需要 --draft 或已有任务状态", task_id)
        return 2

    before: set[Path] = set()
    if DEFAULT_DRAFT_ROOT.is_dir():
        before = set(DEFAULT_DRAFT_ROOT.iterdir())

    ensure_project_dirs()
    state["status"] = "running"
    save_state(state)

    pace_started: Optional[float] = None
    pace_completed = 0
    pace_planned = 0
    has_prior_steps = any(
        isinstance(st, dict) and st.get("status") in {"completed", "skipped"}
        for st in state["steps"].values()
    )
    if not opts.dry_run and not opts.phase2 and not opts.start_from and not opts.stop_after and (not has_prior_steps or opts.force):
        pace_started = time.monotonic()
        pace_planned = count_planned_steps(opts, draft)

    try:
        for step in STEPS:
            st = state["steps"].get(step.key, {})
            if step.key == "1_import" and (opts.draft is not None or (draft is not None and not opts.force)):
                st["label"] = step.label
                st["status"] = "completed"
                state["steps"][step.key] = st
                save_state(state)
                continue
            if not step_enabled(step, opts):
                st["status"] = "skipped"
                state["steps"][step.key] = st
                save_state(state)
                continue
            if opts.start_from and step.order < opts.start_from:
                st["status"] = "skipped"
                state["steps"][step.key] = st
                save_state(state)
                continue
            if opts.stop_after and step.order > opts.stop_after:
                st["status"] = "skipped"
                state["steps"][step.key] = st
                save_state(state)
                continue
            if step.key == "10_bgm" and opts.bgm == 0:
                st["status"] = "skipped"
                state["steps"][step.key] = st
                save_state(state)
                continue

            if st.get("status") == "completed" and not opts.force:
                continue
            if st.get("status") == "skipped" and not opts.force:
                continue
            if st.get("status") == "failed":
                snapshot = st.get("last_attempt_snapshot")
                if snapshot and Path(snapshot).is_dir() and not opts.no_restore:
                    restore_snapshot(Path(snapshot), draft, task_id, step.label)
                    st["last_error"] = None
                    st["status"] = "pending"
                    state["steps"][step.key] = st
                    save_state(state)

            ok, next_draft, output = run_step_once(
                step, opts, state, video, draft,
                pace_started=pace_started,
                pace_completed=pace_completed + 1,
                pace_planned=pace_planned,
            )
            if ok:
                pace_completed += 1
            if step.key == "1_import":
                if opts.dry_run:
                    draft = DEFAULT_DRAFT_ROOT / video.stem
                else:
                    draft = detect_new_draft(output, before)
                state["draft"] = str(draft)
                save_state(state)
            elif next_draft is not None:
                draft = next_draft

            if not ok:
                state["status"] = "failed"
                state["last_error"] = state["steps"].get(step.key, {}).get("last_error") or f"{step.label} 失败"
                save_state(state)
                report = write_report(state)
                log(f"任务失败，报告: {report}", task_id)
                return 1

        if opts.style and state["steps"].get("style_apply", {}).get("status") != "completed":
            style_step = next(s for s in STEPS if s.key == "style_apply")
            ok, _, _ = run_step_once(
                style_step, opts, state, video, draft,
                pace_started=pace_started,
                pace_completed=pace_completed + 1,
                pace_planned=pace_planned,
            )
            if ok:
                pace_completed += 1
            if not ok:
                state["status"] = "failed"
                state["last_error"] = "风格套用失败"
                save_state(state)
                write_report(state)
                return 1

        state["status"] = "completed"
        state["last_error"] = None
        save_state(state)
        report = write_report(state)
        log(f"任务完成，草稿: {draft}", task_id)
        log(f"任务报告: {report}", task_id)
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["last_error"] = str(exc)
        save_state(state)
        write_report(state)
        log(f"任务异常: {exc}", task_id)
        return 1


def check_environment() -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("项目结构", SCRIPTS.is_dir(), str(SCRIPTS)))
    missing_scripts = [s.script for s in STEPS if not (SCRIPTS / s.script).is_file()]
    checks.append(("real-cut 脚本完整", not missing_scripts, "; ".join(missing_scripts) or "ok"))
    checks.append(("字幕词表", (ROOT / "config" / "subtitle_glossary.json").is_file(), str(ROOT / "config" / "subtitle_glossary.json")))

    import importlib.util

    for module in ("funasr", "dashscope", "requests", "jieba"):
        checks.append((f"Python 依赖 {module}", importlib.util.find_spec(module) is not None, module))
    officecli_path = resolve_officecli()
    checks.append(("命令 officecli", officecli_path is not None, str(officecli_path or "officecli")))
    for exe in ("ffmpeg", "ffprobe"):
        found = shutil.which(exe) is not None
        checks.append((f"命令 {exe}", found, str(shutil.which(exe) or exe)))
    checks.append(("DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY", bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")), "环境变量；DeepSeek 优先，qwen 兜底"))
    checks.append(("剪映草稿根目录", DEFAULT_DRAFT_ROOT.is_dir(), str(DEFAULT_DRAFT_ROOT)))
    checks.append(("剪映主程序", DEFAULT_JIANYING_EXE.is_file(), str(DEFAULT_JIANYING_EXE)))
    checks.append(("关键词库", DEFAULT_KEYWORD_FILE.is_file(), str(DEFAULT_KEYWORD_FILE)))

    failed = 0
    for name, ok, detail in checks:
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {name}: {detail}")
        if not ok:
            failed += 1
    print(f"\n检查完成：{len(checks) - failed}/{len(checks)} 通过")
    return 1 if failed else 0


def cmd_summary(_opts: argparse.Namespace) -> int:
    ensure_project_dirs()
    rows = []
    for state_file in sorted(STATE_DIR.glob("*.json")):
        state = _json_read(state_file, {})
        if not state:
            continue
        rows.append(
            {
                "task_id": state.get("task_id"),
                "status": state.get("status"),
                "video": Path(state.get("video", "")).name,
                "draft": Path(state.get("draft", "")).name if state.get("draft") else "",
                "error": state.get("last_error") or "",
                "updated": state.get("updated_at", ""),
            }
        )
    for row in rows:
        print(
            f"{row['task_id']}  {row['status']:<16} "
            f"{row['video']:<40} {row['draft']:<30} {row['updated']}"
        )
        if row["error"]:
            print(f"    error: {row['error'][:180]}")
    return 0


def apply_run_root(opts: argparse.Namespace) -> None:
    raw = getattr(opts, "run_root", None)
    if not raw:
        return
    global STATE_DIR, LOG_DIR, SNAPSHOT_DIR, REPORT_DIR, MANIFEST_DIR, DEFAULT_MANIFEST
    root = Path(raw).expanduser().resolve()
    STATE_DIR = root / "state"
    LOG_DIR = root / "logs"
    SNAPSHOT_DIR = root / "snapshots"
    REPORT_DIR = root / "reports"
    MANIFEST_DIR = root / "manifests"
    DEFAULT_MANIFEST = MANIFEST_DIR / "realcut-batch.xlsx"


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--draft", help="已有草稿路径或名称；提供时跳过步骤1")
    parser.add_argument("--phase2", action="store_true", help="只跑音频平滑+字幕阶段+风格后处理；需要 --draft 或已有任务状态")
    parser.add_argument("--start-from", type=float, help="从指定步骤开始，例如 4")
    parser.add_argument("--stop-after", type=float, help="只跑到指定步骤，例如 6")
    parser.add_argument("--bgm", type=int, default=10, help="BGM 序号；0 表示关闭，默认 10")
    parser.add_argument("--style", default="风格2", help="完成 12 步后固定套用风格2模板")
    parser.add_argument("--enable-flower-text", action="store_true", help="启用步骤9花字音效")
    parser.add_argument("--watermark", action="store_true", help="启用步骤11水印")
    parser.add_argument("--fresh", action="store_true", help="忽略已有任务状态，从头运行")
    parser.add_argument("--force", action="store_true", help="已完成的步骤也重新运行")
    parser.add_argument("--smooth-audio", dest="smooth_audio", action="store_true", default=True, help="人声响度平滑/短段合并（默认开）")
    parser.add_argument("--no-smooth-audio", dest="smooth_audio", action="store_false", help="关闭音频平滑")
    parser.add_argument("--review-subtitles", dest="review_subtitles", action="store_true", default=True, help="生成字幕复核清单（默认开）")
    parser.add_argument("--no-review-subtitles", dest="review_subtitles", action="store_false", help="关闭字幕复核清单")
    parser.add_argument("--continue-on-error", action="store_true", help="单视频失败后继续批量任务")
    parser.add_argument("--snapshot-mode", choices=("json", "copy", "off"), default="json")
    parser.add_argument("--max-attempts", type=int, default=2, help="单步最多尝试次数")
    parser.add_argument("--no-close-jianying", action="store_true", help="不自动关闭剪映")
    parser.add_argument("--no-restore", action="store_true", help="续跑失败步骤前不自动恢复快照")
    parser.add_argument("--dry-run", action="store_true", help="只打印执行计划，不实际运行脚本")
    parser.add_argument("--run-root", help="独立运行根目录；state/logs/reports/snapshots/manifests 都放这里")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RealCut Hybrid：real-cut + 任务调度")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="处理单个视频")
    run_p.add_argument("video", help="源视频路径")
    add_common_args(run_p)

    batch_p = sub.add_parser("batch", help="批量处理视频")
    batch_p.add_argument("paths", nargs="+", help="视频路径或素材目录")
    batch_p.add_argument("--recursive", action="store_true", help="递归扫描目录")
    add_common_args(batch_p)
    add_manifest_args(batch_p)

    check_p = sub.add_parser("check", help="环境自检")
    check_p.add_argument("--run-root", help="独立运行根目录；用于校验某个 run-root")
    summary_p = sub.add_parser("summary", help="任务汇总")
    add_common_args(summary_p)

    manifest_p = sub.add_parser("manifest", help="初始化或重建批次 manifest")
    manifest_p.add_argument("path", help="manifest 路径（xlsx 或 json）")
    manifest_p.add_argument("--force", action="store_true", help="已存在时也清空重建")
    manifest_p.add_argument("--run-root", help="独立运行根目录；state/logs/reports/snapshots/manifests 都放这里")

    restyle_p = sub.add_parser("restyle", help="成品草稿套用风格2 + 镜像/重排")
    restyle_p.add_argument("paths", nargs="+", help="草稿目录、草稿编号或含草稿的目录")
    restyle_p.add_argument("--recursive", action="store_true", help="递归扫描草稿目录")
    restyle_p.add_argument("--style", default="风格2", help="要套用的风格名，默认 风格2")
    restyle_p.add_argument("--no-mirror", action="store_true", help="跳过画面水平镜像")
    restyle_p.add_argument("--no-reorder", action="store_true", help="跳过后续视频段随机重排")
    restyle_p.add_argument("--continue-on-error", action="store_true", help="单个草稿失败后继续")
    restyle_p.add_argument("--dry-run", action="store_true", help="只打印计划")
    restyle_p.add_argument("--run-root", help="独立运行根目录")
    add_manifest_args(restyle_p)

    font_p = sub.add_parser("force-font", help="强制成品草稿字幕为指定风格字体")
    font_p.add_argument("paths", nargs="+", help="草稿目录、草稿编号或含草稿的目录")
    font_p.add_argument("--recursive", action="store_true", help="递归扫描草稿目录")
    font_p.add_argument("--style", default="风格2", help="读取该风格模板字体，默认 风格2")
    font_p.add_argument("--continue-on-error", action="store_true", help="单个草稿失败后继续")
    font_p.add_argument("--dry-run", action="store_true", help="只打印计划")
    font_p.add_argument("--run-root", help="独立运行根目录")
    add_manifest_args(font_p)

    gaps_p = sub.add_parser("fill-gaps", help="字幕时间轴连续覆盖，补满空隙")
    gaps_p.add_argument("paths", nargs="+", help="草稿目录、草稿编号或含草稿的目录")
    gaps_p.add_argument("--recursive", action="store_true", help="递归扫描草稿目录")
    gaps_p.add_argument("--check", action="store_true", help="只检查空隙，不写盘")
    gaps_p.add_argument("--continue-on-error", action="store_true", help="单个草稿失败后继续")
    gaps_p.add_argument("--dry-run", action="store_true", help="只打印计划")
    gaps_p.add_argument("--run-root", help="独立运行根目录")
    add_manifest_args(gaps_p)

    claude_p = sub.add_parser("claude", help="按组调用 Claude Code CLI 执行批次")
    claude_p.add_argument("paths", nargs="+", help="视频/素材目录，或草稿目录/编号")
    claude_p.add_argument("--mode", choices=("edit", "restyle", "font", "gaps"), default="edit", help="edit=全流程；restyle=风格2+镜像重排；font=强制字体；gaps=字幕补缝")
    claude_p.add_argument("--recursive", action="store_true", help="递归扫描目录")
    claude_p.add_argument("--style", default="风格2", help="restyle/font 使用的风格名")
    claude_p.add_argument("--no-mirror", action="store_true", help="restyle 跳过镜像")
    claude_p.add_argument("--no-reorder", action="store_true", help="restyle 跳过重排")
    claude_p.add_argument("--check", action="store_true", help="gaps 模式只检查不写盘")
    claude_p.add_argument("--continue-on-error", action="store_true", help="单个任务失败后继续本组")
    claude_p.add_argument("--dry-run", action="store_true", help="只生成提示词并打印命令，不启动 Claude")
    claude_p.add_argument("--max-budget-usd", type=float, default=5.0, help="每个 Claude 会话预算上限，默认 5")
    claude_p.add_argument("--claude-exec", default="claude", help="Claude Code 可执行文件，默认 claude")
    claude_p.add_argument("--run-root", help="独立运行根目录；Claude 子批次也使用同一目录")
    add_manifest_args(claude_p)

    return parser


def collect_videos(paths: list[str], recursive: bool) -> list[Path]:
    videos: list[Path] = []
    exts = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".m4v", ".ts"}
    for raw in paths:
        p = Path(raw).resolve()
        if p.is_file():
            videos.append(p)
            continue
        if p.is_dir():
            iterator = p.rglob("*") if recursive else p.glob("*")
            videos.extend(
                sorted(
                    child
                    for child in iterator
                    if child.is_file() and child.suffix.lower() in exts
                )
            )
            continue
        log(f"路径不存在: {raw}")
    return videos


def add_manifest_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", default=None, help="批次 manifest 路径（xlsx 或 json，默认 manifests/realcut-batch.xlsx）")
    parser.add_argument("--manifest-force", action="store_true", help="清空/重建 manifest")
    parser.add_argument("--group-size", type=int, default=10, help="每组处理数量，默认 10")


def manifest_for_opts(opts: argparse.Namespace) -> ManifestStore:
    raw = Path(getattr(opts, "manifest", None) or DEFAULT_MANIFEST)
    store = ManifestStore(raw)
    exists = store.xlsx_path.exists() or store.json_path.exists()
    if getattr(opts, "manifest_force", False):
        store.init(force=True)
    elif not exists:
        store.init(force=True)
    return store


def new_batch_id(store: ManifestStore) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    index = len(store.state.get("batches", {})) + 1
    while f"batch_{stamp}_{index:02d}" in store.state["batches"]:
        index += 1
    return f"batch_{stamp}_{index:02d}"


def batch_log(batch_id: str, message: str) -> None:
    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}"
    print(line, flush=True)
    log_path = LOG_DIR / f"{batch_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def chunk_list(items: list[Path], size: int) -> list[list[Path]]:
    size = max(1, size)
    return [items[i:i + size] for i in range(0, len(items), size)]


def batch_source(opts: argparse.Namespace) -> str:
    return ";".join(str(Path(p).resolve()) for p in opts.paths)


def collect_drafts(paths: list[str], recursive: bool) -> list[Path]:
    drafts: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        p = Path(raw).expanduser()
        if not p.exists():
            p = DEFAULT_DRAFT_ROOT / str(raw).strip()
        if p.is_file():
            if p.name == "draft_content.json":
                p = p.parent
            else:
                log(f"不是草稿目录: {raw}")
                continue
        if not p.is_dir():
            log(f"草稿不存在: {raw}")
            continue
        if (p / "draft_content.json").is_file():
            candidates = [p]
        else:
            pattern = "**/draft_content.json" if recursive else "*/draft_content.json"
            candidates = [dc.parent for dc in sorted(p.glob(pattern)) if dc.is_file()]
        for draft in candidates:
            key = str(draft.resolve())
            if key not in seen:
                seen.add(key)
                drafts.append(draft.resolve())
    return drafts


def seed_for_draft(draft: Path) -> int:
    name = draft.name
    if name.isdigit():
        return 7321 + int(name) * 17
    return int(task_id_for(draft)[:8], 16)


def read_task_log_tail(task_id: str, max_lines: int = 20) -> str:
    path = LOG_DIR / f"{task_id}.log"
    if not path.is_file():
        return ""
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:])
    except OSError:
        return ""


def manifest_update_video(
    store: ManifestStore,
    batch_id: str,
    task_id: str,
    phase: str,
    **fields,
) -> None:
    store.add_video(
        batch_id,
        task_id,
        phase,
        source_path=fields.get("source_path", ""),
        draft_path=fields.get("draft_path", ""),
    )
    store.update_video(batch_id, task_id, phase, **fields)
    store.save()


def record_edit_result(
    store: ManifestStore,
    batch_id: str,
    task_id: str,
    video: Path,
    code: int,
) -> None:
    state = load_state(task_id)
    failed_steps = [
        s for s in STEPS
        if state.get("steps", {}).get(s.key, {}).get("status") == "failed"
    ]
    failed_state = state.get("steps", {}).get(failed_steps[0].key, {}) if failed_steps else {}
    current_step = failed_steps[0].key if failed_steps else ""
    error = state.get("last_error") or failed_state.get("last_error") or ("处理失败" if code else "")
    log_tail = str(failed_state.get("last_output_tail") or "")[-2000:]
    if code and not error:
        tail = read_task_log_tail(task_id)
        error = tail.splitlines()[-1] if tail else "处理失败"
        log_tail = tail[-2000:]
    manifest_update_video(
        store,
        batch_id,
        task_id,
        "edit",
        source_path=str(video),
        draft_path=state.get("draft", ""),
        status="completed" if code == 0 else "failed",
        current_step=current_step,
        error=error,
        log_path=str(LOG_DIR / f"{task_id}.log"),
        report_path=str(REPORT_DIR / f"{task_id}.md"),
        retry_count=len(failed_steps),
    )
    if code:
        store.add_exception(
            batch_id,
            task_id,
            "edit",
            current_step or "unknown",
            error,
            error_signature=hashlib.sha256(error.encode("utf-8", errors="replace")).hexdigest()[:16],
            log_tail=log_tail,
        )
        store.save()


def record_draft_result(
    store: ManifestStore,
    batch_id: str,
    task_id: str,
    phase: str,
    draft: Path,
    ok: bool,
    error: str = "",
    step: str = "",
    log_tail: str = "",
) -> None:
    log_tail = log_tail or read_task_log_tail(task_id)
    manifest_update_video(
        store,
        batch_id,
        task_id,
        phase,
        source_path="",
        draft_path=str(draft),
        status="completed" if ok else "failed",
        current_step=step,
        error=error,
        log_path=str(LOG_DIR / f"{task_id}.log"),
        report_path="",
        retry_count=0 if ok else 1,
    )
    if not ok:
        store.add_exception(
            batch_id,
            task_id,
            phase,
            step or "unknown",
            error or "处理失败",
            error_signature=hashlib.sha256((error or "处理失败").encode("utf-8", errors="replace")).hexdigest()[:16],
            log_tail=log_tail,
        )
        store.save()


def run_draft_groups(
    opts: argparse.Namespace,
    mode: str,
    drafts: list[Path],
    process_one,
) -> int:
    store = manifest_for_opts(opts)
    groups = chunk_list(drafts, max(1, opts.group_size))
    total_failed = 0
    processed = 0
    for group in groups:
        batch_id = new_batch_id(store)
        log_path = LOG_DIR / f"{batch_id}.log"
        store.add_batch(
            batch_id,
            batch_source(opts),
            mode,
            group_size=len(group),
            log_path=str(log_path),
        )
        store.state["batches"][batch_id]["status"] = "running"
        store.save()
        ok_count = 0
        failed_count = 0
        stopped = False
        for index, draft in enumerate(group, start=1):
            processed += 1
            task_id = task_id_for(draft)
            batch_log(batch_id, f"[{mode} {index}/{len(group)}] {draft}")
            manifest_update_video(
                store,
                batch_id,
                task_id,
                mode,
                draft_path=str(draft),
                status="running",
            )
            try:
                ok, step, error = process_one(draft, task_id, batch_id)
            except Exception as exc:
                ok, step, error = False, "unknown", str(exc)
            record_draft_result(
                store, batch_id, task_id, mode, draft, ok,
                error=error, step=step, log_tail=(error or "")[-2000:],
            )
            if ok:
                ok_count += 1
            else:
                failed_count += 1
                total_failed += 1
                batch_log(batch_id, f"{mode} 失败: {draft}: {error[:200]}")
                if not opts.continue_on_error:
                    stopped = True
                    break
        store.finalize_batch(batch_id, ok_count, failed_count)
        store.save()
        batch_log(batch_id, f"批次结束: {ok_count}/{len(group)} 成功，{failed_count} 失败")
        if stopped:
            break
    log(f"{mode} 批次结束：{processed - total_failed}/{processed} 成功")
    return total_failed


def cmd_manifest(opts: argparse.Namespace) -> int:
    store = ManifestStore(opts.path)
    exists = store.xlsx_path.exists() or store.json_path.exists()
    if exists and not opts.force:
        print(f"manifest 已存在，未清空: {store.xlsx_path}")
        print("使用 --force 重建")
        return 1
    store.init(force=True)
    print(f"已初始化 manifest: {store.xlsx_path}")
    print(json.dumps(store.status_counts(), ensure_ascii=False))
    return 0


def cmd_batch(opts: argparse.Namespace) -> int:
    videos = collect_videos(opts.paths, opts.recursive)
    if not videos:
        log("没有找到可处理的视频")
        return 1
    groups = chunk_list(videos, max(1, opts.group_size))
    if opts.dry_run:
        total_failed = 0
        processed = 0
        log(f"批量任务（dry-run）：{len(videos)} 个视频，每组 {max(1, opts.group_size)} 个")
        for group_index, group in enumerate(groups, start=1):
            batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{group_index:02d}"
            batch_log(batch_id, f"dry-run 批次 {group_index}/{len(groups)}，共 {len(group)} 个视频")
            stopped = False
            group_ok = 0
            for index, video in enumerate(group, start=1):
                processed += 1
                batch_log(batch_id, f"[批量 {index}/{len(group)}] {video}")
                code = run_task(opts, video)
                group_ok += 1 if code == 0 else 0
                if code:
                    total_failed += 1
                    batch_log(batch_id, f"视频 dry-run 失败: {video}")
                    if not opts.continue_on_error:
                        stopped = True
                        break
            batch_log(batch_id, f"dry-run 批次结束: {group_ok}/{len(group)} 通过")
            if stopped:
                break
        log(f"批量结束（dry-run）：{processed - total_failed}/{processed} 通过")
        return 1 if total_failed else 0
    store = manifest_for_opts(opts)
    total_failed = 0
    processed = 0
    log(f"批量任务：{len(videos)} 个视频，每组 {max(1, opts.group_size)} 个")
    for group_index, group in enumerate(groups, start=1):
        batch_id = new_batch_id(store)
        log_path = LOG_DIR / f"{batch_id}.log"
        store.add_batch(
            batch_id,
            batch_source(opts),
            "edit",
            group_size=len(group),
            log_path=str(log_path),
        )
        store.state["batches"][batch_id]["status"] = "running"
        store.save()
        ok_count = 0
        failed_count = 0
        stopped = False
        for index, video in enumerate(group, start=1):
            processed += 1
            task_id = task_id_for(video)
            batch_log(batch_id, f"[批量 {index}/{len(group)}] {video}")
            manifest_update_video(
                store,
                batch_id,
                task_id,
                "edit",
                source_path=str(video),
                status="running",
            )
            code = run_task(opts, video)
            record_edit_result(store, batch_id, task_id, video, code)
            if code:
                failed_count += 1
                total_failed += 1
                batch_log(batch_id, f"视频失败: {video}")
                if not opts.continue_on_error:
                    stopped = True
                    break
            else:
                ok_count += 1
        store.finalize_batch(batch_id, ok_count, failed_count)
        store.save()
        batch_log(batch_id, f"批次结束: {ok_count}/{len(group)} 成功，{failed_count} 失败")
        if stopped:
            break
    log(f"批量结束：{processed - total_failed}/{processed} 成功")
    return 1 if total_failed else 0


def cmd_restyle(opts: argparse.Namespace) -> int:
    drafts = collect_drafts(opts.paths, opts.recursive)
    if not drafts:
        log("没有找到可处理的草稿")
        return 1
    style = opts.style or "风格2"

    def process_one(draft: Path, task_id: str, batch_id: str):
        step = "apply_style"
        try:
            postprocess.apply_style(
                draft, style, dry_run=opts.dry_run, log=lambda msg: log(msg, task_id)
            )
            step = "mirror_reorder"
            postprocess.mirror_and_reorder(
                draft,
                seed_for_draft(draft),
                mirror=not opts.no_mirror,
                reorder=not opts.no_reorder,
                dry_run=opts.dry_run,
                log=lambda msg: log(msg, task_id),
            )
            return True, step, ""
        except Exception as exc:
            return False, step, str(exc)

    failed = run_draft_groups(opts, "restyle", drafts, process_one)
    return 1 if failed else 0


def cmd_force_font(opts: argparse.Namespace) -> int:
    drafts = collect_drafts(opts.paths, opts.recursive)
    if not drafts:
        log("没有找到可处理的草稿")
        return 1
    style = opts.style or "风格2"

    def process_one(draft: Path, task_id: str, batch_id: str):
        try:
            postprocess.force_font(
                draft, style, dry_run=opts.dry_run, log=lambda msg: log(msg, task_id)
            )
            return True, "force_font", ""
        except Exception as exc:
            return False, "force_font", str(exc)

    failed = run_draft_groups(opts, "font", drafts, process_one)
    return 1 if failed else 0


def cmd_fill_gaps(opts: argparse.Namespace) -> int:
    drafts = collect_drafts(opts.paths, opts.recursive)
    if not drafts:
        log("没有找到可处理的草稿")
        return 1

    def process_one(draft: Path, task_id: str, batch_id: str):
        try:
            result = postprocess.fill_subtitle_gaps(
                draft,
                apply_changes=not opts.check,
                dry_run=opts.dry_run,
                log=lambda msg: log(msg, task_id),
            )
            log(f"补缝结果: {json.dumps(result, ensure_ascii=False)}", task_id)
            return True, "fill_gaps", ""
        except Exception as exc:
            return False, "fill_gaps", str(exc)

    failed = run_draft_groups(opts, "gaps", drafts, process_one)
    return 1 if failed else 0


def claude_command_for_group(
    opts: argparse.Namespace,
    mode: str,
    command: str,
    items: list[Path],
) -> list[str]:
    manifest = Path(getattr(opts, "manifest", None) or DEFAULT_MANIFEST).resolve()
    cmd = [sys.executable, str(ROOT / "realcut_hybrid.py"), command]
    cmd.extend(str(p) for p in items)
    run_root = getattr(opts, "run_root", None)
    if run_root:
        cmd += ["--run-root", str(run_root)]
    if getattr(opts, "manifest_force", False):
        cmd.append("--manifest-force")
    cmd += ["--manifest", str(manifest), "--group-size", str(len(items))]
    if getattr(opts, "continue_on_error", False):
        cmd.append("--continue-on-error")
    if mode == "restyle":
        cmd += ["--style", opts.style or "风格2"]
        if getattr(opts, "no_mirror", False):
            cmd.append("--no-mirror")
        if getattr(opts, "no_reorder", False):
            cmd.append("--no-reorder")
    elif mode == "font":
        cmd += ["--style", opts.style or "风格2"]
    elif mode == "gaps" and getattr(opts, "check", False):
        cmd.append("--check")
    return cmd


def build_claude_prompt(
    command: str,
    cmd: list[str],
    items: list[Path],
    manifest: Path,
) -> str:
    base_cmd = [part for part in cmd if part != "--dry-run"]
    dry_cmd = [base_cmd[0], base_cmd[1], base_cmd[2], "--dry-run", *base_cmd[3:]]
    lines = [
        "你是 RealCutHybrid 的批次执行员。",
        f"本组共 {len(items)} 个任务，使用一个非交互会话处理。",
        "不要修改 vendor/real-cut 下任何文件。",
        "先读 RealCutHybrid/README.md 和 RealCutHybrid/AGENTS.md，再读 manifest 的批次/视频/异常表结构。",
        "先执行下面的 dry-run 命令确认路径和参数，确认无误后执行实际命令。",
        "实际执行命令必须前台同步运行并等待进程结束；禁止后台任务、Start-Process、Start-Job 或任何异步启动。",
        "只有看到批次日志出现‘批次结束’且 manifest 中 batch status 为 completed/failed 后才能返回摘要；未结束时继续等待和检查，不要提前退出。",
        "执行完检查退出码和 manifest 异常表；如有异常，读取 logs/ 和 reports/ 中对应 task_id 定位问题。",
        "优先修复配置、草稿或脚本参数后重新执行同一调度命令，不要绕过调度器直接手工改大量草稿。",
        "不要在剪映窗口做 UI 自动化，不要打开新的交互式会话。",
        "完成时输出 JSON 摘要：成功数、失败数、异常表新增行数。",
        "",
        f"manifest: {manifest}",
        "",
        "dry-run 检查命令：",
        "```powershell",
        " ".join(dry_cmd),
        "```",
        "",
        "实际执行命令：",
        "```powershell",
        " ".join(cmd),
        "```",
    ]
    return "\n".join(lines)


def resolve_claude_executable(exec_name: str) -> Optional[str]:
    """Resolve the real Claude Code executable, including npm .cmd/.ps1 shims."""
    raw = Path(exec_name).expanduser()
    found = raw if raw.is_file() else None
    if found is None:
        which = shutil.which(exec_name)
        if which:
            found = Path(which)
    if found is None:
        return None
    if found.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        exe = found.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if exe.is_file():
            return str(exe)
    return str(found)




def cmd_claude(opts: argparse.Namespace) -> int:
    mode = opts.mode
    if mode == "edit":
        command = "batch"
        items = collect_videos(opts.paths, opts.recursive)
    else:
        command = {"restyle": "restyle", "font": "force-font", "gaps": "fill-gaps"}[mode]
        items = collect_drafts(opts.paths, opts.recursive)
    if not items:
        log(f"没有找到可处理的{ '视频' if mode == 'edit' else '草稿' }")
        return 1
    manifest = Path(getattr(opts, "manifest", None) or DEFAULT_MANIFEST).resolve()
    manifest_for_opts(opts)
    groups = chunk_list(items, max(1, opts.group_size))
    failed = 0
    for index, group in enumerate(groups, start=1):
        cmd = claude_command_for_group(opts, mode, command, group)
        prompt = build_claude_prompt(command, cmd, group, manifest)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        prompt_path = LOG_DIR / f"claude_{stamp}_{index:02d}.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        log(f"[claude] 提示词已保存: {prompt_path}")
        if opts.dry_run:
            dry_cmd = [cmd[0], cmd[1], cmd[2], "--dry-run", *cmd[3:]]
            log(f"[claude dry-run] 命令: {' '.join(dry_cmd)}")
            continue
        claude_bin = resolve_claude_executable(opts.claude_exec)
        if claude_bin is None:
            log(f"找不到 claude 可执行文件: {opts.claude_exec}")
            return 1
        claude_cmd = [
            claude_bin,
            "-p",
            prompt,
            "--permission-mode", "acceptEdits",
            "--allowedTools", "Bash PowerShell Read Edit Write Glob Grep",
            "--output-format", "json",
            "--max-budget-usd", str(opts.max_budget_usd),
            "--name", f"realcut-{index:02d}",
        ]
        add_dirs = [str(ROOT), str(DEFAULT_DRAFT_ROOT)]
        if getattr(opts, "run_root", None):
            add_dirs.append(str(Path(opts.run_root).expanduser().resolve()))
        for item in group:
            parent = item.parent if item.is_file() else item
            add_dirs.append(str(parent.resolve()))
        for directory in dict.fromkeys(add_dirs):
            claude_cmd += ["--add-dir", directory]
        log(f"[claude] 启动会话 {index}/{len(groups)}，预算 ${opts.max_budget_usd:g}")
        proc = subprocess.run(
            claude_cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        output_path = LOG_DIR / f"claude_{stamp}_{index:02d}.out.log"
        output_path.write_text(output, encoding="utf-8")
        if proc.returncode != 0:
            failed += 1
            log(f"[claude] 会话 {index} 失败 rc={proc.returncode}")
        else:
            log(f"[claude] 会话 {index} 完成，输出: {output_path}")
    return 1 if failed else 0
def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    opts = parser.parse_args(argv)
    apply_run_root(opts)
    ensure_project_dirs()
    if opts.command == "check":
        return check_environment()
    if opts.command == "summary":
        return cmd_summary(opts)
    if opts.command == "run":
        return run_task(opts, Path(opts.video))
    if opts.command == "batch":
        return cmd_batch(opts)
    if opts.command == "manifest":
        return cmd_manifest(opts)
    if opts.command == "restyle":
        return cmd_restyle(opts)
    if opts.command == "force-font":
        return cmd_force_font(opts)
    if opts.command == "fill-gaps":
        return cmd_fill_gaps(opts)
    if opts.command == "claude":
        return cmd_claude(opts)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
