#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RealCutHybrid local web server.

Serves a small LiveClipAgent-inspired frontend and runs the existing
realcut_hybrid CLI in a persistent background queue. The queue stores
submitted/running items on disk so a Web restart does not lose pending work,
and can run up to three tasks in parallel from the Web toggle.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import mimetypes
import os
import re
import socket
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlsplit
from runtime_layout import application_root, entrypoint_command
from runtime_settings import (
    apply_runtime_settings,
    masked_settings_payload,
    update_runtime_settings,
)
import postprocess

from realcut_hybrid import (
    LOG_DIR,
    DEFAULT_DRAFT_ROOT,
    REPORT_DIR,
    STATE_DIR,
    STEPS,
    now_iso,
    task_id_for,
    atomic_write_text,
)

ROOT = application_root(__file__)
WEB_DIR = ROOT / "web"
ORCHESTRATOR = ROOT / "realcut_hybrid.py"
DEFAULT_PORT = 8765
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".m4v", ".ts"}

QUEUE_FILE = ROOT / "web_queue.json"
QUEUE_SCHEMA_VERSION = 1
MAX_WORKER_THREADS = 3
DEFAULT_MAX_CONCURRENCY = 1


MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


@dataclass
class QueueItem:
    task_id: str
    video: str
    options: dict
    queued_at: str
    status: str = "pending"
    pid: Optional[int] = None
    started_at: Optional[str] = None


class TaskQueue:
    def __init__(
        self,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        queue_file: Optional[Path] = None,
    ) -> None:
        self._cond = threading.Condition()
        self._items: list[QueueItem] = []
        self._running: dict[str, QueueItem] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._max_concurrency = self._clamp_max(max_concurrency)
        self._queue_file = queue_file or QUEUE_FILE
        self._stop = False
        self._load_persisted()
        for _ in range(MAX_WORKER_THREADS):
            threading.Thread(
                target=self._worker,
                name="realcut-web-queue",
                daemon=True,
            ).start()

    @staticmethod
    def _clamp_max(value: Any) -> int:
        try:
            return min(MAX_WORKER_THREADS, max(1, int(value)))
        except (TypeError, ValueError):
            return DEFAULT_MAX_CONCURRENCY
    def _save_queue_locked(self) -> None:
        payload = {
            "schema_version": QUEUE_SCHEMA_VERSION,
            "updated_at": now_iso(),
            "max_concurrency": self._max_concurrency,
            "pending": [self._item_payload(item) for item in self._items],
            "running": [self._item_payload(item) for item in self._running.values()],
        }
        try:
            atomic_write_text(self._queue_file, json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception as exc:
            append_log("web_queue", f"队列持久化失败: {exc}")

    def _load_persisted(self) -> None:
        if not self._queue_file.is_file():
            return
        try:
            data = json.loads(self._queue_file.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            append_log("web_queue", f"队列文件读取失败，已按空队列启动: {exc}")
            return
        if not isinstance(data, dict):
            return
        self._max_concurrency = self._clamp_max(
            data.get("max_concurrency", DEFAULT_MAX_CONCURRENCY)
        )
        records = list(data.get("pending", []) or []) + list(data.get("running", []) or [])
        records.sort(key=lambda record: str(record.get("queued_at") or ""))
        seen: set[str] = set()
        recovered: list[QueueItem] = []
        for raw in records:
            if not isinstance(raw, dict):
                continue
            task_id = str(raw.get("task_id") or "")
            if not task_id or task_id in seen:
                continue
            state = _load_state(task_id)
            if state.get("status") in {"completed", "failed"}:
                seen.add(task_id)
                continue
            seen.add(task_id)
            item = QueueItem(
                task_id=task_id,
                video=str(raw.get("video") or ""),
                options=dict(raw.get("options") or {}),
                queued_at=str(raw.get("queued_at") or now_iso()),
                status="pending",
            )
            recovered.append(item)
        if recovered:
            append_log("web_queue", f"Web 启动恢复队列：{len(recovered)} 个任务")
        self._items = recovered
        self._save_queue_locked()
    def submit(self, video: Path, options: dict) -> tuple[bool, str]:
        video = video.resolve()
        task_id = task_id_for(video)
        with self._cond:
            if task_id in self._running:
                return False, "该任务正在运行"
            if any(item.task_id == task_id for item in self._items):
                return False, "该任务已在队列中"
            item = QueueItem(
                task_id=task_id,
                video=str(video),
                options=dict(options or {}),
                queued_at=now_iso(),
            )
            self._items.append(item)
            self._save_queue_locked()
            self._cond.notify()
        append_log(task_id, "Web 已提交任务到后台队列")
        return True, task_id

    def snapshot(self) -> dict:
        with self._cond:
            pending = [self._item_payload(item) for item in self._items]
            running = [self._item_payload(item) for item in self._running.values()]
            current = running[0] if running else None
        return {
            "pending": pending,
            "running": running,
            "current": current,
            "single_concurrency": self._max_concurrency <= 1,
            "max_concurrency": self._max_concurrency,
            "parallel_enabled": self._max_concurrency > 1,
        }

    def set_concurrency(
        self,
        enabled: Optional[bool] = None,
        max_concurrency: Optional[int] = None,
    ) -> dict:
        with self._cond:
            if enabled is False:
                self._max_concurrency = 1
            elif enabled is True:
                requested = self._clamp_max(max_concurrency if max_concurrency is not None else 3)
                self._max_concurrency = 3 if requested < 2 else requested
            elif max_concurrency is not None:
                self._max_concurrency = self._clamp_max(max_concurrency)
            self._save_queue_locked()
            self._cond.notify_all()
        return self.snapshot()
    def cancel(self, task_id: str) -> bool:
        with self._cond:
            before = len(self._items)
            self._items = [item for item in self._items if item.task_id != task_id]
            proc = self._processes.get(task_id)
            was_running = task_id in self._running
            self._running.pop(task_id, None)
            removed = len(self._items) != before or was_running
            self._save_queue_locked()
        if proc and proc.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0,
                )
            except Exception as exc:
                append_log(task_id, f"停止任务时遇到异常: {exc}")
            append_log(task_id, "已请求停止任务")
            return True
        if removed:
            append_log(task_id, "已从等待队列移除")
            return True
        return False

    def shutdown(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()

    def _item_payload(self, item: QueueItem) -> dict:
        return {
            "task_id": item.task_id,
            "video": item.video,
            "queued_at": item.queued_at,
            "options": item.options,
            "status": item.status,
            "pid": item.pid,
            "started_at": item.started_at,
        }

    def _worker(self) -> None:
        while True:
            with self._cond:
                while (
                    (not self._items or len(self._running) >= self._max_concurrency)
                    and not self._stop
                ):
                    self._cond.wait(timeout=1.0)
                if self._stop and not self._items:
                    return
                if not self._items:
                    continue
                item = self._items.pop(0)
                item.status = "running"
                item.started_at = now_iso()
                self._running[item.task_id] = item
                self._save_queue_locked()
            try:
                self._run_item(item)
            finally:
                with self._cond:
                    self._running.pop(item.task_id, None)
                    self._processes.pop(item.task_id, None)
                    self._save_queue_locked()
                    self._cond.notify_all()

    def _run_item(self, item: QueueItem) -> None:
        append_log(item.task_id, "后台队列开始执行任务")
        cmd = entrypoint_command(
            ORCHESTRATOR,
            ["run", item.video],
            root=ROOT,
        )
        opts = item.options or {}
        if opts.get("draft"):
            cmd += ["--draft", str(opts["draft"])]
        if opts.get("phase2"):
            cmd += ["--phase2"]
        if opts.get("start_from") not in (None, "", 0):
            cmd += ["--start-from", str(opts["start_from"])]
        if opts.get("stop_after") not in (None, "", 0):
            cmd += ["--stop-after", str(opts["stop_after"])]
        if opts.get("bgm") is not None and str(opts.get("bgm")) != "":
            cmd += ["--bgm", str(opts["bgm"])]
        if opts.get("style"):
            cmd += ["--style", str(opts["style"])]
        if opts.get("enable_flower_text"):
            cmd += ["--enable-flower-text"]
        if opts.get("watermark"):
            cmd += ["--watermark"]
        if opts.get("snapshot_mode") in {"json", "copy", "off"}:
            cmd += ["--snapshot-mode", str(opts["snapshot_mode"])]
        if opts.get("max_attempts"):
            cmd += ["--max-attempts", str(opts["max_attempts"])]
        if opts.get("fresh"):
            cmd += ["--fresh"]
        if opts.get("force"):
            cmd += ["--force"]
        if opts.get("smooth_audio") is False:
            cmd += ["--no-smooth-audio"]
        if opts.get("review_subtitles") is False:
            cmd += ["--no-review-subtitles"]
        if opts.get("no_close_jianying"):
            cmd += ["--no-close-jianying"]
        if opts.get("no_restore"):
            cmd += ["--no-restore"]
        if opts.get("dry_run"):
            cmd += ["--dry-run"]

        append_log(item.task_id, "启动: " + " ".join(cmd))
        env = os.environ.copy()
        apply_runtime_settings(env)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
        except Exception as exc:
            append_log(item.task_id, f"无法启动剪辑进程: {exc}")
            _force_state(item.task_id, "failed", str(exc))
            return

        with self._cond:
            self._processes[item.task_id] = proc
            item.pid = proc.pid
            item.status = "running"
            self._save_queue_locked()
        returncode = proc.wait()
        if returncode != 0:
            state = _load_state(item.task_id)
            if state and state.get("status") == "running":
                _force_state(item.task_id, "failed", "剪辑进程已停止（可能被手动取消）")
        append_log(item.task_id, f"后台进程退出码: {returncode}")


def append_log(task_id: str, message: str) -> None:
    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with (LOG_DIR / f"{task_id}.log").open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {message}\n")
    except OSError:
        pass


def _load_state(task_id: str) -> dict:
    path = STATE_DIR / f"{task_id}.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    state["updated_at"] = now_iso()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"{state['task_id']}.json"
    atomic_write_text(path, json.dumps(state, ensure_ascii=False, indent=2))


def _force_state(task_id: str, status: str, error: str) -> None:
    state = _load_state(task_id)
    if not state:
        state = {"task_id": task_id, "video": "", "status": status, "steps": {}}
    state["status"] = status
    state["last_error"] = error
    _save_state(state)


def _state_files() -> list[Path]:
    if not STATE_DIR.is_dir():
        return []
    return sorted(STATE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def _collect_videos(raw_path: str, recursive: bool) -> tuple[list[Path], str]:
    p = Path(raw_path).expanduser()
    if not p.exists():
        return [], f"路径不存在: {raw_path}"
    if p.is_file():
        return ([p.resolve()] if p.suffix.lower() in VIDEO_EXTS else []), ""
    if not p.is_dir():
        return [], f"不是文件或目录: {raw_path}"
    iterator = p.rglob("*") if recursive else p.glob("*")
    videos = sorted(
        child.resolve()
        for child in iterator
        if child.is_file() and child.suffix.lower() in VIDEO_EXTS
    )
    if not videos:
        return [], f"目录中没有支持的视频: {raw_path}"
    return videos, ""


def _resolve_draft_value(value: str) -> Optional[Path]:
    p = Path(value).expanduser()
    if p.is_dir():
        return p.resolve()
    candidate = DEFAULT_DRAFT_ROOT / value
    if candidate.is_dir():
        return candidate.resolve()
    return None


def _draft_video_candidate(draft: Path) -> Optional[str]:
    candidates: list[str] = []
    dc_path = draft / "draft_content.json"
    if dc_path.is_file():
        try:
            dc = json.loads(dc_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            dc = {}
        for material in dc.get("materials", {}).get("videos", []) or []:
            raw = material.get("path") or ""
            if raw.startswith("##_draftpath_placeholder_"):
                raw = re.sub(r"##_draftpath_placeholder_[^#]+_##", draft.as_posix(), raw)
            if raw:
                candidates.append(raw)
    candidates.append(str(draft / "video_only.mp4"))
    for raw in candidates:
        p = Path(raw)
        if p.is_file():
            return str(p.resolve())
    for raw in candidates:
        if raw and Path(raw).suffix.lower() in VIDEO_EXTS:
            return raw
    return None


def _video_for_draft(draft: Path) -> Optional[str]:
    target = str(draft.resolve())
    for state_file in _state_files():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if state.get("draft") == target:
            video = state.get("video") or ""
            if video and Path(video).is_file():
                return str(Path(video).resolve())
    return _draft_video_candidate(draft)


def list_jianying_drafts() -> list[dict]:
    if not DEFAULT_DRAFT_ROOT.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(DEFAULT_DRAFT_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_dir() or not (path / "draft_content.json").is_file():
            continue
        video = _video_for_draft(path)
        rows.append(
            {
                "name": path.name,
                "path": str(path.resolve()),
                "video": video or "",
                "video_name": Path(video).name if video else "",
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            }
        )
    return rows


def _task_base_from_item(item: dict) -> dict:
    video = item.get("video") or ""
    status = "running" if item.get("status") == "running" else "queued"
    draft = ""
    options = item.get("options") or {}
    if options.get("draft"):
        draft = str(options["draft"])
    return {
        "id": item.get("task_id") or "",
        "video": video,
        "video_name": Path(video).name,
        "draft": draft,
        "draft_name": Path(draft).name if draft else "",
        "status": status,
        "queued": status != "running",
        "created_at": item.get("queued_at") or now_iso(),
        "updated_at": item.get("queued_at") or now_iso(),
        "error": "",
        "current_step": 0,
        "progress": 0,
        "steps": [],
    }


def _enrich_task(state: dict) -> dict:
    task_id = state.get("task_id") or ""
    video = state.get("video") or ""
    draft = state.get("draft") or ""
    status = state.get("status") or "pending"
    steps = []
    completed = 0
    for step in STEPS:
        raw = state.get("steps", {}).get(step.key, {})
        step_status = raw.get("status", "pending")
        steps.append(
            {
                "key": step.key,
                "label": step.label,
                "order": step.order,
                "status": step_status,
                "attempts": raw.get("attempts", 0),
                "duration_s": raw.get("duration_s"),
                "error": raw.get("last_error") or "",
                "started_at": raw.get("started_at") or "",
                "finished_at": raw.get("finished_at") or "",
            }
        )
        if step_status == "completed":
            completed += 1
    progress = 100 if status == "completed" else round(completed / max(len(STEPS), 1) * 100)
    current_step = max(
        [step["order"] for step in steps if step["status"] == "completed"] or [0]
    )
    return {
        "id": task_id,
        "video": video,
        "video_name": Path(video).name,
        "draft": draft,
        "draft_name": Path(draft).name if draft else "",
        "status": status,
        "created_at": state.get("created_at") or "",
        "updated_at": state.get("updated_at") or "",
        "error": state.get("last_error") or "",
        "current_step": current_step,
        "progress": progress,
        "steps": steps,
        "report_exists": (REPORT_DIR / f"{task_id}.md").is_file(),
    }


def bootstrap_payload() -> dict:
    queue = task_queue.snapshot()
    tasks: dict[str, dict] = {}
    for path in _state_files():
        state = _load_state(path.stem)
        if state:
            tasks[state["task_id"]] = _enrich_task(state)

    for item in queue["pending"]:
        task = tasks.setdefault(item["task_id"], _task_base_from_item(item))
        task["status"] = "queued"
        task["queued"] = True
        task["updated_at"] = item["queued_at"]
    for item in queue.get("running", []) or []:
        task = tasks.setdefault(item["task_id"], _task_base_from_item(item))
        task["status"] = "running"
        task["queued"] = False
        task["updated_at"] = item.get("started_at") or item["queued_at"]

    ordered = sorted(
        tasks.values(),
        key=lambda t: (
            0 if t.get("status") in {"queued", "running"} else 1,
            t.get("updated_at") or "",
        ),
        reverse=True,
    )
    return {
        "app": {"name": "RealCut Hybrid", "version": "0.2.1", "platform": "windows"},
        "queue": queue,
        "tasks": ordered,
        "paths": {
            "root": str(ROOT),
            "state": str(STATE_DIR),
            "logs": str(LOG_DIR),
            "reports": str(REPORT_DIR),
        },
        "environment": environment_payload(),
        "settings": masked_settings_payload(),
        "styles": {
            "available": postprocess.available_style_names(
                Path(task["draft"]).parent
                for task in ordered
                if task.get("draft")
            ),
            "default": postprocess.configured_default_style(),
        },
        "steps": [
            {"key": step.key, "label": step.label, "order": step.order, "phase": step.phase}
            for step in STEPS
        ],
    }


def environment_payload() -> dict:
    return {
        "ok": getattr(environment_cache, "ok", False),
        "checked_at": getattr(environment_cache, "checked_at", ""),
        "checks": getattr(environment_cache, "checks", []),
    }


def run_environment_check() -> dict:
    env = os.environ.copy()
    apply_runtime_settings(env)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        proc = subprocess.run(
            entrypoint_command(ORCHESTRATOR, ["check"], root=ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            cwd=str(ROOT),
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
        output = proc.stdout
    except Exception as exc:
        output = f"环境检查失败: {exc}"
        proc = None
    checks = []
    ok = True
    for line in output.splitlines():
        match = re.match(r"^\[(PASS|FAIL)\]\s*(.+?):\s*(.*)$", line.strip())
        if not match:
            continue
        passed = match.group(1) == "PASS"
        checks.append(
            {
                "ok": passed,
                "name": match.group(2).strip(),
                "detail": match.group(3).strip(),
            }
        )
        if not passed:
            ok = False
    payload = {
        "ok": ok,
        "checked_at": now_iso(),
        "checks": checks,
        "output": output,
        "exit_code": proc.returncode if proc is not None else -1,
    }
    environment_cache.ok = ok
    environment_cache.checked_at = payload["checked_at"]
    environment_cache.checks = checks
    return payload


class EnvironmentCache:
    ok = False
    checked_at = ""
    checks: list[dict] = []


environment_cache = EnvironmentCache()
task_queue = TaskQueue()


def _read_tail(path: Path, limit: int = 200_000) -> str:
    if not path.is_file():
        return ""
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return data[-limit:]


def _browse_path(mode: str, raw_path: str) -> dict:
    mode = mode if mode in {"video", "folder"} else "video"
    roots: list[dict] = []
    entries: list[dict] = []
    current = ""
    parent = ""

    if not raw_path:
        drives = []
        if os.name == "nt":
            import string

            for letter in string.ascii_uppercase:
                candidate = f"{letter}:\\"
                if os.path.exists(candidate):
                    drives.append(candidate)
        else:
            drives = ["/"]
        for drive in drives:
            roots.append({"name": drive, "path": drive, "kind": "folder"})
        return {
            "current": "",
            "parent": "",
            "roots": roots,
            "entries": [],
            "mode": mode,
        }

    p = Path(raw_path).expanduser()
    if not p.exists():
        p = Path.cwd()
    if p.is_file():
        p = p.parent
    p = p.resolve()

    try:
        children = sorted(
            p.iterdir(),
            key=lambda child: (not child.is_dir(), child.name.casefold()),
        )
    except OSError:
        children = []

    if os.name == "nt" and p.drive:
        parent = str(p.parent) if p != p.anchor else ""
    else:
        parent = str(p.parent) if p != p.anchor else ""

    for child in children:
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        if is_dir:
            entries.append(
                {"name": child.name, "path": str(child.resolve()), "kind": "folder"}
            )
        elif mode == "video" and child.suffix.lower() in VIDEO_EXTS:
            entries.append(
                {"name": child.name, "path": str(child.resolve()), "kind": "video"}
            )
    return {
        "current": str(p),
        "parent": parent,
        "roots": roots,
        "entries": entries,
        "mode": mode,
    }


def _send_json(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _send_static(handler: BaseHTTPRequestHandler, relative: str) -> None:
    relative = unquote(relative.lstrip("/"))
    candidate = (WEB_DIR / relative).resolve()
    try:
        candidate.relative_to(WEB_DIR.resolve())
    except ValueError:
        _send_json(handler, {"error": "禁止访问目录之外的文件"}, HTTPStatus.FORBIDDEN)
        return
    if candidate.is_dir():
        candidate = candidate / "index.html"
    if not candidate.is_file():
        _send_json(handler, {"error": "文件不存在"}, HTTPStatus.NOT_FOUND)
        return
    mime = MIME_TYPES.get(candidate.suffix.lower()) or mimetypes.guess_type(str(candidate))[0]
    body = candidate.read_bytes()
    handler.send_response(HTTPStatus.OK)
    if mime:
        handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class RealCutHandler(BaseHTTPRequestHandler):
    server_version = "RealCutHybridWeb/0.2.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        try:
            if path == "/api/bootstrap":
                return _send_json(self, bootstrap_payload())
            if path == "/api/settings":
                return _send_json(self, {"settings": masked_settings_payload()})
            if path == "/api/drafts":
                return _send_json(
                    self,
                    {
                        "draft_root": str(DEFAULT_DRAFT_ROOT),
                        "drafts": list_jianying_drafts(),
                    },
                )
            if path == "/api/tasks":
                return _send_json(self, {"tasks": bootstrap_payload()["tasks"]})
            match = re.fullmatch(r"/api/tasks/([^/]+)", path)
            if match:
                task_id = match.group(1)
                state = _load_state(task_id)
                if not state:
                    return _send_json(self, {"error": "任务不存在"}, HTTPStatus.NOT_FOUND)
                return _send_json(self, {"task": _enrich_task(state)})
            match = re.fullmatch(r"/api/tasks/([^/]+)/log", path)
            if match:
                task_id = match.group(1)
                if not (LOG_DIR / f"{task_id}.log").is_file():
                    return _send_json(self, {"log": "", "error": "暂无日志"}, HTTPStatus.OK)
                return _send_json(self, {"log": _read_tail(LOG_DIR / f"{task_id}.log")})
            match = re.fullmatch(r"/api/tasks/([^/]+)/subtitle-review", path)
            if match:
                task_id = match.group(1)
                state = _load_state(task_id)
                if not state:
                    return _send_json(self, {"error": "任务不存在"}, HTTPStatus.NOT_FOUND)
                draft = Path(state.get("draft") or "")
                j = draft / "subtitle_review.json" if draft.is_dir() else None
                md = draft / "subtitle_review.md" if draft.is_dir() else None
                review = None
                if j and j.is_file():
                    try:
                        review = json.loads(j.read_text(encoding="utf-8-sig"))
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        review = None
                price_roles = None
                price_path = draft / "price_roles.json" if draft.is_dir() else None
                if price_path and price_path.is_file():
                    try:
                        price_roles = json.loads(price_path.read_text(encoding="utf-8-sig"))
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        price_roles = None
                return _send_json(
                    self,
                    {
                        "exists": bool(j and j.is_file()),
                        "review": review,
                        "review_md": _read_tail(md, 200_000) if md and md.is_file() else "",
                        "price_roles": price_roles,
                    },
                )
            match = re.fullmatch(r"/api/tasks/([^/]+)/report", path)
            if match:
                task_id = match.group(1)
                md = REPORT_DIR / f"{task_id}.md"
                j = REPORT_DIR / f"{task_id}.json"
                report_md = _read_tail(md, 300_000) if md.is_file() else ""
                report_json = _load_state(task_id)
                if j.is_file():
                    try:
                        report_json = json.loads(j.read_text(encoding="utf-8-sig"))
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        pass
                return _send_json(
                    self,
                    {
                        "report_md": report_md,
                        "report_json": report_json,
                        "state": _load_state(task_id),
                    },
                )
            if path == "/" or path == "":
                return _send_static(self, "index.html")
            return _send_static(self, path)
        except Exception as exc:
            _send_json(self, {"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        try:
            if path == "/api/run" or path == "/api/batch":
                payload = self._json_body()
                return self._submit_run(payload)
            if path == "/api/queue/config":
                payload = self._json_body()
                queue = task_queue.set_concurrency(
                    enabled=payload.get("parallel_enabled"),
                    max_concurrency=payload.get("max_concurrency"),
                )
                return _send_json(self, {"ok": True, "queue": queue})
            if path == "/api/settings":
                client_ip = self.client_address[0].split("%", 1)[0]
                if not ipaddress.ip_address(client_ip).is_loopback:
                    return _send_json(
                        self,
                        {"error": "API Key 只能在本机页面修改"},
                        HTTPStatus.FORBIDDEN,
                    )
                payload = self._json_body()
                update_runtime_settings(payload)
                apply_runtime_settings()
                environment = run_environment_check()
                return _send_json(
                    self,
                    {
                        "ok": True,
                        "settings": masked_settings_payload(),
                        "environment": environment,
                    },
                )
            if path == "/api/check":
                return _send_json(self, run_environment_check())
            if path == "/api/browse":
                payload = self._json_body()
                mode = payload.get("mode", "video")
                return _send_json(self, _browse_path(mode, payload.get("path", "")))
            match = re.fullmatch(r"/api/tasks/([^/]+)/resume", path)
            if match:
                return self._resume_task(match.group(1))
            match = re.fullmatch(r"/api/tasks/([^/]+)/cancel", path)
            if match:
                task_id = match.group(1)
                cancelled = task_queue.cancel(task_id)
                if not cancelled:
                    return _send_json(
                        self,
                        {"error": "该任务未在运行或等待队列中"},
                        HTTPStatus.CONFLICT,
                    )
                return _send_json(self, {"ok": True, "task_id": task_id})
            _send_json(self, {"error": "未知接口"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            _send_json(self, {"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _submit_run(self, payload: dict) -> None:
        raw_paths = payload.get("paths") or payload.get("path") or payload.get("video_path")
        if isinstance(raw_paths, str):
            raw_paths = [raw_paths]
        draft_values = payload.get("drafts") or payload.get("draft_names") or []
        if isinstance(draft_values, str):
            draft_values = [draft_values]
        if not raw_paths and not draft_values:
            raise ValueError("请提供视频/目录路径，或选择至少一个剪映草稿")
        options = payload.get("options") or {}
        recursive = bool(payload.get("recursive", options.get("recursive", True)))
        queued: list[dict] = []
        skipped: list[dict] = []
        errors: list[str] = []
        if raw_paths:
            for raw in raw_paths:
                videos, err = _collect_videos(str(raw), recursive)
                if err:
                    errors.append(err)
                    continue
                for video in videos:
                    ok, result = task_queue.submit(video, options)
                    if ok:
                        queued.append({"task_id": result, "video": str(video)})
                    else:
                        skipped.append({"video": str(video), "reason": result})
        for raw in draft_values:
            draft = _resolve_draft_value(str(raw))
            if draft is None:
                errors.append(f"草稿不存在: {raw}")
                continue
            if not (draft / "draft_content.json").is_file():
                errors.append(f"草稿缺少 draft_content.json: {draft.name}")
                continue
            video = _video_for_draft(draft)
            if not video:
                skipped.append({"draft": draft.name, "reason": "草稿内未找到可用源视频或 video_only.mp4"})
                continue
            opts = dict(options)
            opts["draft"] = str(draft)
            opts["phase2"] = True
            opts["force"] = True
            ok, result = task_queue.submit(Path(video), opts)
            if ok:
                queued.append({"task_id": result, "draft": draft.name, "video": str(video)})
            else:
                skipped.append({"draft": draft.name, "video": str(video), "reason": result})
        _send_json(
            self,
            {
                "queued": queued,
                "skipped": skipped,
                "errors": errors,
                "queued_count": len(queued),
            },
        )

    def _resume_task(self, task_id: str) -> None:
        state = _load_state(task_id)
        if not state:
            _send_json(self, {"error": "任务不存在"}, HTTPStatus.NOT_FOUND)
            return
        video = state.get("video")
        if not video or not Path(video).is_file():
            _send_json(self, {"error": "源视频不存在，无法继续"}, HTTPStatus.CONFLICT)
            return
        options = self._json_body().get("options") or {}
        if state.get("draft") and not options.get("draft"):
            options["draft"] = state["draft"]
        if options.get("phase2"):
            options.setdefault("force", True)
        if options.get("phase2") and not options.get("style") and state.get("style"):
            options["style"] = state["style"]
        ok, result = task_queue.submit(Path(video), options)
        if not ok:
            _send_json(self, {"error": result}, HTTPStatus.CONFLICT)
            return
        _send_json(self, {"task_id": result, "ok": True})


def _lan_url(port: int) -> Optional[str]:
    """Return a LAN URL when binding to all interfaces, if one can be detected."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return None
    for info in infos:
        ip = info[4][0]
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        return f"http://{ip}:{port}"
    return None


def serve(host: str, start_port: int, no_browser: bool = False) -> None:
    handler = RealCutHandler
    last_error = None
    for port in range(start_port, start_port + 20):
        try:
            server = ThreadingHTTPServer((host, port), handler)
            break
        except OSError as exc:
            last_error = exc
    else:
        raise RuntimeError(f"端口 {start_port}-{start_port + 19} 均不可用: {last_error}")

    url = f"http://127.0.0.1:{port}"
    print(f"RealCut Hybrid Web: {url}")
    if host in ("0.0.0.0", "::"):
        lan_url = _lan_url(port)
        if lan_url:
            print(f"RealCut Hybrid LAN: {lan_url}")
    if not no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        task_queue.shutdown()
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="RealCut Hybrid Web")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="本地端口")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址；0.0.0.0 允许局域网访问")
    parser.add_argument("--max-concurrency", type=int, default=None, help="启动时最大并发 1-3；Web 中的设置会持久化并覆盖此值")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()
    if args.max_concurrency is not None:
        task_queue.set_concurrency(max_concurrency=args.max_concurrency)
    try:
        run_environment_check()
    except Exception:
        pass
    serve(args.host, args.port, no_browser=args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
