# -*- coding: utf-8 -*-
"""Batch manifest store for RealCutHybrid.

The manifest keeps one machine-readable JSON state plus an Excel snapshot that
is easy to inspect in WPS/Excel. Every video and exception row is written after
the fact, so a crashed batch still leaves a usable handoff file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

BATCH_SHEET = "批次"
VIDEO_SHEET = "视频"
EXCEPTION_SHEET = "异常"

BATCH_HEADERS = [
    "batch_id",
    "group_index",
    "source_path",
    "mode",
    "group_size",
    "status",
    "started_at",
    "finished_at",
    "ok_count",
    "failed_count",
    "log_path",
]

VIDEO_HEADERS = [
    "batch_id",
    "task_id",
    "phase",
    "source_path",
    "draft_path",
    "draft_name",
    "status",
    "current_step",
    "error",
    "log_path",
    "report_path",
    "retry_count",
    "updated_at",
]

EXCEPTION_HEADERS = [
    "batch_id",
    "task_id",
    "phase",
    "timestamp",
    "step",
    "error_signature",
    "error",
    "log_tail",
    "action",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def manifest_paths(raw_path: str | Path) -> tuple[Path, Path]:
    p = Path(raw_path).expanduser().resolve()
    if p.suffix.lower() == ".xlsx":
        return p, p.with_name(f"{p.stem}.manifest.json")
    return p.with_suffix(".xlsx"), p


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def resolve_officecli() -> Optional[Path]:
    """Return an installed officecli executable, or None."""
    raw = os.environ.get("OFFICECLI_BIN")
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return candidate
    found = shutil.which("officecli")
    if found:
        return Path(found)
    local = Path(os.environ.get("LOCALAPPDATA", "")).expanduser() / "OfficeCLI" / "officecli.exe"
    if local.is_file():
        return local
    return None


def _run_officecli(args: list[str], input_text: str = "", timeout: int = 120) -> dict[str, Any]:
    """Run officecli and return its parsed JSON result."""
    exe = resolve_officecli()
    if exe is None:
        raise RuntimeError("未找到 officecli，请安装后重试或设置 OFFICECLI_BIN 环境变量")
    proc = subprocess.run(
        [str(exe), *args],
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    output = (proc.stdout or "") + ("\n" if proc.stdout and proc.stderr else "") + (proc.stderr or "")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        if proc.returncode == 0:
            return {"success": True, "data": {}, "raw": output.strip()}
        raise RuntimeError(f"officecli 返回非 JSON 输出: {output.strip()[:500]}")
    if proc.returncode != 0 or payload.get("success") is False:
        detail = json.dumps(payload.get("data") or payload, ensure_ascii=False)
        raise RuntimeError(f"officecli 执行失败: {detail[:500]}")
    return payload


def _column_letter(index: int) -> str:
    """Convert a 0-based column index to an Excel column letter."""
    letters = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _row_number(item_path: str) -> int:
    tail = item_path.rsplit("[", 1)[-1].rstrip("]")
    return int(tail) if tail.isdigit() else 0


def _query_rows_for_sheet(
    matches: list[dict[str, Any]], sheet_name: str, headers: list[str]
) -> list[dict[str, Any]]:
    """Convert officecli row-query results into header-keyed rows."""
    header_columns: dict[str, str] = {}
    rows_by_number: dict[int, dict[str, str]] = {}
    prefix = f"/{sheet_name}/"
    for item in matches:
        item_path = str(item.get("path") or "")
        if not item_path.startswith(prefix + "row["):
            continue
        row_no = _row_number(item_path)
        if not row_no:
            continue
        cells: dict[str, str] = {}
        for child in item.get("children") or []:
            child_path = str(child.get("path") or "")
            if child_path.startswith(prefix):
                cells[child_path[len(prefix):]] = str(child.get("text") or "")
        if row_no == 1:
            for ref, text in cells.items():
                column = ref.rstrip("0123456789")
                if column and column.isalpha():
                    header_columns[text] = column
        else:
            rows_by_number[row_no] = cells
    result: list[dict[str, Any]] = []
    for row_no in sorted(rows_by_number):
        cells = rows_by_number[row_no]
        row: dict[str, Any] = {}
        for header in headers:
            column = header_columns.get(header)
            row[header] = cells.get(f"{column}{row_no}") if column else None
        result.append(row)
    return result

class ManifestStore:
    """Small state store backed by JSON + an Excel snapshot."""

    def __init__(self, raw_path: str | Path):
        self.xlsx_path, self.json_path = manifest_paths(raw_path)
        self.state: dict[str, Any] = {
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "batches": {},
            "videos": {},
            "exceptions": [],
        }
        self.load()

    def load(self) -> None:
        if self.json_path.is_file():
            try:
                data = json.loads(self.json_path.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    self.state.update(data)
                    self.state.setdefault("batches", {})
                    self.state.setdefault("videos", {})
                    self.state.setdefault("exceptions", [])
                    return
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass

        if self.xlsx_path.is_file():
            self._load_xlsx()

    def _load_xlsx(self) -> None:
        try:
            payload = _run_officecli(["query", str(self.xlsx_path), "row", "--json"], timeout=120)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            return
        try:
            _run_officecli(["close", str(self.xlsx_path)], timeout=60)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        matches = (payload.get("data") or {}).get("results") or []
        for row in _query_rows_for_sheet(matches, BATCH_SHEET, BATCH_HEADERS):
            if row.get("batch_id"):
                self.state["batches"][str(row["batch_id"])] = row
        for row in _query_rows_for_sheet(matches, VIDEO_SHEET, VIDEO_HEADERS):
            if row.get("batch_id") and row.get("task_id"):
                key = self._video_key(
                    str(row["batch_id"]), str(row["task_id"]), str(row.get("phase") or "edit")
                )
                self.state["videos"][key] = row
        self.state["exceptions"] = _query_rows_for_sheet(matches, EXCEPTION_SHEET, EXCEPTION_HEADERS)

    @staticmethod
    def _video_key(batch_id: str, task_id: str, phase: str) -> str:
        return f"{batch_id}|{phase}|{task_id}"

    def init(self, force: bool = False) -> bool:
        if (self.xlsx_path.exists() or self.json_path.exists()) and not force:
            return False
        self.state = {
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "batches": {},
            "videos": {},
            "exceptions": [],
        }
        self.save()
        return True

    def save(self) -> None:
        self.state["updated_at"] = now_iso()
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(
            self.json_path,
            json.dumps(self.state, ensure_ascii=False, indent=2),
        )
        self._write_xlsx()

    def _write_xlsx(self) -> None:
        """Write the Excel snapshot with officecli batch."""
        exe = resolve_officecli()
        if exe is None:
            print("[manifest] 未找到 officecli，仅写入 JSON。可用 OFFICECLI_BIN 指定二进制路径。")
            try:
                self.xlsx_path.unlink(missing_ok=True)
            except OSError:
                pass
            return

        def rows_for(headers: list[str]) -> list[list[Any]]:
            if headers is BATCH_HEADERS:
                source = list(self.state["batches"].values())
            elif headers is VIDEO_HEADERS:
                source = list(self.state["videos"].values())
            else:
                source = list(self.state["exceptions"])
            return [[row.get(h) for h in headers] for row in source]

        commands: list[dict[str, Any]] = []
        for sheet_name, headers in (
            (BATCH_SHEET, BATCH_HEADERS),
            (VIDEO_SHEET, VIDEO_HEADERS),
            (EXCEPTION_SHEET, EXCEPTION_HEADERS),
        ):
            commands.append(
                {"command": "add", "path": "/", "type": "sheet", "props": {"name": sheet_name}}
            )
            all_rows = [headers, *rows_for(headers)]
            for r, values in enumerate(all_rows, start=1):
                for c, value in enumerate(values, start=1):
                    props: dict[str, Any] = {"value": "" if value is None else value}
                    if r == 1:
                        props["bold"] = True
                    commands.append(
                        {
                            "command": "set",
                            "path": f"/{sheet_name}/{_column_letter(c)}{r}",
                            "props": props,
                        }
                    )

            max_widths: list[int] = []
            for values in zip(*all_rows):
                max_widths.append(max((len(str(v or "")) for v in values), default=8))
            for c, width in enumerate(max_widths, start=1):
                cap = 40 if headers is BATCH_HEADERS else 50 if headers is VIDEO_HEADERS else 60
                commands.append(
                    {
                        "command": "set",
                        "path": f"/{sheet_name}/col[{_column_letter(c)}]",
                        "props": {"width": min(cap, max(8, width + 2))},
                    }
                )

        self.xlsx_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="realcut-manifest-") as tmpdir:
            tmp = Path(tmpdir) / self.xlsx_path.name
            _run_officecli(["create", str(tmp)], timeout=120)
            batch = json.dumps(commands, ensure_ascii=False)
            payload = _run_officecli(["batch", str(tmp), "--json"], input_text=batch, timeout=300)
            summary = (payload.get("data") or {}).get("summary") or {}
            failed = int(summary.get("failed") or 0)
            if failed:
                failed_items = [
                    r for r in (payload.get("data") or {}).get("results") or [] if not r.get("success")
                ]
                raise RuntimeError(
                    f"officecli 写入 manifest 失败 {failed} 项: {json.dumps(failed_items[:3], ensure_ascii=False)}"
                )
            try:
                _run_officecli(["close", str(tmp)], timeout=60)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass
            os.replace(tmp, self.xlsx_path)

    def add_batch(
        self,
        batch_id: str,
        source_path: str,
        mode: str,
        group_size: int = 10,
        log_path: str = "",
    ) -> None:
        self.state["batches"][batch_id] = {
            "batch_id": batch_id,
            "group_index": len(self.state["batches"]) + 1,
            "source_path": source_path,
            "mode": mode,
            "group_size": group_size,
            "status": "queued",
            "started_at": now_iso(),
            "finished_at": "",
            "ok_count": 0,
            "failed_count": 0,
            "log_path": log_path,
        }

    def add_video(
        self,
        batch_id: str,
        task_id: str,
        phase: str,
        source_path: str = "",
        draft_path: str = "",
    ) -> None:
        key = self._video_key(batch_id, task_id, phase)
        existing = self.state["videos"].get(key, {})
        self.state["videos"][key] = {
            "batch_id": batch_id,
            "task_id": task_id,
            "phase": phase,
            "source_path": source_path or existing.get("source_path", ""),
            "draft_path": draft_path or existing.get("draft_path", ""),
            "draft_name": Path(draft_path).name
            if draft_path
            else existing.get("draft_name", ""),
            "status": existing.get("status", "queued"),
            "current_step": existing.get("current_step", ""),
            "error": existing.get("error", ""),
            "log_path": existing.get("log_path", ""),
            "report_path": existing.get("report_path", ""),
            "retry_count": existing.get("retry_count", 0),
            "updated_at": existing.get("updated_at", now_iso()),
        }

    def update_video(
        self,
        batch_id: str,
        task_id: str,
        phase: str,
        **fields: Any,
    ) -> None:
        key = self._video_key(batch_id, task_id, phase)
        row = self.state["videos"].setdefault(
            key,
            {
                "batch_id": batch_id,
                "task_id": task_id,
                "phase": phase,
                "source_path": "",
                "draft_path": "",
                "draft_name": "",
                "status": "queued",
                "current_step": "",
                "error": "",
                "log_path": "",
                "report_path": "",
                "retry_count": 0,
                "updated_at": now_iso(),
            },
        )
        row.update(fields)
        row["updated_at"] = now_iso()

    def add_exception(
        self,
        batch_id: str,
        task_id: str,
        phase: str,
        step: str,
        error: str,
        error_signature: str = "",
        log_tail: str = "",
        action: str = "",
    ) -> None:
        self.state["exceptions"].append(
            {
                "batch_id": batch_id,
                "task_id": task_id,
                "phase": phase,
                "timestamp": now_iso(),
                "step": step,
                "error_signature": error_signature,
                "error": error,
                "log_tail": log_tail[:2000],
                "action": action,
            }
        )

    def finalize_batch(self, batch_id: str, ok_count: int, failed_count: int) -> None:
        row = self.state["batches"].get(batch_id, {})
        row.update(
            {
                "status": "completed" if failed_count == 0 else "failed",
                "finished_at": now_iso(),
                "ok_count": ok_count,
                "failed_count": failed_count,
            }
        )

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.state["videos"].values():
            status = str(row.get("status") or "queued")
            counts[status] = counts.get(status, 0) + 1
        return counts

    def backup(self) -> Optional[Path]:
        if not self.xlsx_path.is_file():
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.xlsx_path.with_name(f"{self.xlsx_path.stem}.bak_{ts}{self.xlsx_path.suffix}")
        try:
            shutil.copy2(self.xlsx_path, dest)
            return dest
        except OSError:
            return None
