# -*- coding: utf-8 -*-
"""Post-processing helpers used by the RealCutHybrid CLI.

These functions mirror the verified workflows that used to live in one-off
scripts under D:\\ai-edit-studio. They operate on finished JianYing drafts and
write through the same three-file sync helper as the experimental engine.
"""

from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "vendor" / "experimental" / "scripts"
DEFAULT_DRAFT_ROOT = Path(
    os.environ.get(
        "REALCUT_DRAFT_ROOT",
        r"C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft",
    )
)
STYLE_LIB = Path(
    os.environ.get("REALCUT_STYLE_LIB", r"D:\10  jianyin\JianyingPro Drafts")
)

LogFn = Callable[[str], None]


def _log_default(message: str) -> None:
    print(message, flush=True)


def _ensure_utils():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    from _utils import read_draft, write_draft

    return read_draft, write_draft


def _create_no_window_flag() -> int:
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def run_script(
    script_name: str,
    args: list[str],
    log: LogFn = _log_default,
) -> str:
    """Run an experimental engine script and return its combined output."""
    script = SCRIPTS / script_name
    cmd = [sys.executable, str(script), *args]
    log(f"[postprocess] 执行: {script_name} {' '.join(args)}")
    proc = subprocess.run(
        cmd,
        cwd=str(SCRIPTS),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_create_no_window_flag(),
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if output.strip():
        log(output.strip())
    if proc.returncode != 0:
        raise RuntimeError(
            f"{script_name} 退出码 {proc.returncode}: {output[-1200:]}"
        )
    return output


def resolve_style_template(style: str, log: LogFn = _log_default) -> Path:
    """Resolve a style template dir, preferring the 10.0 template library."""
    if style:
        base = style[:-2] if style.endswith('模板') and style != '模板' else style
        for cand in (
            STYLE_LIB / f"{base}模板",
            DEFAULT_DRAFT_ROOT / f"{base}模板",
            DEFAULT_DRAFT_ROOT / base,
        ):
            if (cand / "draft_content.json").is_file():
                return cand
    log(f"[postprocess] 未找到风格模板: {style}")
    raise RuntimeError(f"风格模板不存在: {style}")


def apply_style(
    draft: Path,
    style: str,
    dry_run: bool = False,
    log: LogFn = _log_default,
) -> bool:
    if dry_run:
        log(f"[dry-run] 套用风格 {style}: {draft}")
        return True
    run_script("apply_style.py", [str(draft), "--style", style], log=log)
    return True


def mirror_and_reorder(
    draft: Path,
    seed: int,
    mirror: bool = True,
    reorder: bool = True,
    dry_run: bool = False,
    log: LogFn = _log_default,
) -> bool:
    """Mirror every video segment and optionally shuffle the tail segments.

    The first video segment is always kept in place; later segments are shuffled
    with a deterministic seed so reruns produce the same arrangement.
    """
    if dry_run:
        log(f"[dry-run] 镜像/重排视频轨: {draft}")
        return True
    read_draft, write_draft = _ensure_utils()
    data = read_draft(draft)
    rng = random.Random(seed)

    video_durations: list[int] = []
    changed = False
    for tr in data.get("tracks", []):
        if tr.get("type") != "video":
            continue
        segs = tr.get("segments", []) or []
        if not segs:
            continue

        if mirror:
            for seg in segs:
                flip = seg.setdefault("clip", {}).setdefault("flip", {})
                flip["horizontal"] = True
                flip["vertical"] = False
                changed = True

        if reorder and len(segs) >= 3:
            tail = segs[1:]
            rng.shuffle(tail)
            tr["segments"] = [segs[0], *tail]
            changed = True

        t = 0
        for seg in tr["segments"]:
            trange = seg.setdefault("target_timerange", {})
            dur = int(trange.get("duration", 0) or 0)
            trange["start"] = t
            t += dur
        video_durations.append(t)

    if not changed:
        log(f"[postprocess] 未找到可处理的视频轨: {draft}")
        return True

    if video_durations:
        data["duration"] = max(video_durations)
    write_draft(draft, data)
    count = sum(
        len(t.get("segments", []) or [])
        for t in data.get("tracks", [])
        if t.get("type") == "video"
    )
    log(f"[postprocess] 视频轨已镜像并重排，段数={count}")
    return True


def _template_subtitle_font(template: dict) -> Optional[dict]:
    sub_ids = set()
    for tr in template.get("tracks", []):
        if tr.get("type") == "text" and tr.get("flag") == 1:
            for seg in tr.get("segments", []) or []:
                sub_ids.add(seg.get("material_id", ""))
    texts = template.get("materials", {}).get("texts", []) or []
    for mat in texts:
        if mat.get("id") in sub_ids and mat.get("type") == "subtitle":
            return mat
    for mat in texts:
        if mat.get("type") == "subtitle":
            return mat
    return None


def _set_json_font(value, font_id: str, font_path: str):
    obj = value
    if isinstance(obj, str) and obj.lstrip().startswith("{"):
        try:
            obj = json.loads(obj)
        except Exception:
            return value
    if not isinstance(obj, dict):
        return value
    for st in obj.get("styles", []) or []:
        if isinstance(st, dict):
            st["font"] = {"id": font_id, "path": font_path}
    return json.dumps(obj, ensure_ascii=False) if isinstance(value, str) else obj


def force_font(
    draft: Path,
    style: str,
    dry_run: bool = False,
    log: LogFn = _log_default,
) -> int:
    """Force every subtitle material in a draft to the style template's font."""
    if dry_run:
        log(f"[dry-run] 强制字幕字体 {style}: {draft}")
        return 0
    read_draft, write_draft = _ensure_utils()
    template_dir = resolve_style_template(style, log=log)
    template = read_draft(template_dir)
    target = _template_subtitle_font(template)
    if target is None:
        raise RuntimeError(f"模板中未找到字幕字体: {template_dir}")

    data = read_draft(draft)
    count = 0
    for mat in data.get("materials", {}).get("texts", []) or []:
        if mat.get("type") != "subtitle":
            continue
        for key in (
            "font_resource_id",
            "font_path",
            "font_title",
            "fonts",
            "font_size",
        ):
            if key in target:
                mat[key] = copy.deepcopy(target[key])
        mat["content"] = _set_json_font(
            mat.get("content", ""), target.get("font_resource_id", ""), target.get("font_path", "")
        )
        mat["base_content"] = _set_json_font(
            mat.get("base_content", ""), target.get("font_resource_id", ""), target.get("font_path", "")
        )
        count += 1

    if count == 0:
        log(f"[postprocess] 无字幕素材，跳过: {draft}")
        return 0

    write_draft(draft, data)
    log(
        f"[postprocess] 已强制刷新 {count} 条字幕字体: "
        f"{target.get('font_path')}"
    )
    return count


def fill_subtitle_gaps(
    draft: Path,
    apply_changes: bool = True,
    dry_run: bool = False,
    log: LogFn = _log_default,
) -> dict:
    """Flatten subtitle segments so global subtitle coverage is continuous."""
    if dry_run:
        log(f"[dry-run] 字幕补缝: {draft}")
        return {"status": "DRY_RUN", "changes": 0}

    read_draft, write_draft = _ensure_utils()
    data = read_draft(draft)
    total_duration = int(data.get("duration", 0) or 0)
    items: list[dict] = []
    sub_ids = {
        seg.get("material_id")
        for tr in data.get("tracks", []) or []
        if tr.get("type") == "text" and tr.get("flag") == 1
        for seg in tr.get("segments", []) or []
        if seg.get("material_id")
    }
    sub_ids &= {
        m.get("id")
        for m in data.get("materials", {}).get("texts", []) or []
        if isinstance(m, dict) and m.get("type") == "subtitle" and m.get("id")
    }

    for ti, track in enumerate(data.get("tracks", []) or []):
        if track.get("type") != "text":
            continue
        if track.get("flag") != 1:
            continue
        segments = track.get("segments", []) or []
        for si, seg in enumerate(segments):
            if not isinstance(seg, dict) or seg.get("material_id") not in sub_ids:
                continue
            trange = seg.get("target_timerange", {}) or {}
            start = int(trange.get("start", 0) or 0)
            duration = max(1, int(trange.get("duration", 0) or 1))
            items.append(
                {
                    "track_idx": ti,
                    "seg_idx": si,
                    "segment": seg,
                    "start": start,
                    "duration": duration,
                    "end": start + duration,
                }
            )

    if not items:
        return {"status": "NO_SUBTITLES", "changes": 0}

    if total_duration <= 0:
        raise RuntimeError(f"草稿 duration 无效: {draft}")

    ordered = sorted(items, key=lambda x: (x["start"], x["track_idx"], x["seg_idx"]))
    new_starts: list[int] = []
    new_durations: list[int] = []
    for idx, item in enumerate(ordered):
        if idx == 0:
            start = 0
        else:
            start = max(item["start"], new_starts[-1] + new_durations[-1])
        new_starts.append(start)
        new_durations.append(item["duration"])
        if idx > 0:
            new_durations[idx - 1] = start - new_starts[idx - 1]
    new_durations[-1] = max(1, total_duration - new_starts[-1])

    changes = 0
    for item, start, duration in zip(ordered, new_starts, new_durations):
        trange = item["segment"].setdefault("target_timerange", {})
        old_start = int(trange.get("start", 0) or 0)
        old_duration = int(trange.get("duration", 0) or 1)
        if old_start != start or old_duration != duration:
            trange["start"] = start
            trange["duration"] = duration
            changes += 1

    if apply_changes and changes:
        write_draft(draft, data)
    log(
        f"[postprocess] 字幕补缝: {draft} 段数={len(ordered)} "
        f"changes={changes} apply={apply_changes}"
    )
    return {"status": "OK", "changes": changes}
