"""Resolve source and packaged RealCut Hybrid entry points."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable


BINARY_ALIASES = {
    "mirror_通用": "mirror_general",
    "导入视频到剪映": "step_01_import",
    "步骤2-分离音频": "step_02_separate_audio",
    "步骤3-FunASR": "step_03_funasr",
    "步骤4-切割排序": "step_04_select_sort",
    "步骤4后-开盒补位": "step_04_open_box",
    "步骤5-淡入淡出": "step_05_fade",
    "步骤6-画面匹配": "step_06_visual_match",
    "步骤7-生成字幕": "step_07_subtitles",
    "步骤8-转场特效": "step_08_transitions",
    "步骤9-花字音效": "step_09_flower_sfx",
    "步骤10-添加BGM": "step_10_bgm",
    "步骤11-添加水印": "step_11_watermark",
    "步骤12-字体样式": "step_12_style",
    "导入字幕": "import_subtitles",
}


def application_root(anchor: str | Path) -> Path:
    """Return the project root in source and packaged layouts."""
    configured = os.environ.get("REALCUT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    source_root = Path(anchor).resolve().parent
    if (source_root / "config").is_dir():
        return source_root

    executable_dir = Path(os.path.dirname(os.path.abspath(sys.argv[0])))
    candidates = [executable_dir, executable_dir.parent]
    for candidate in candidates:
        if (candidate / "config").is_dir():
            return candidate
    return source_root


def binary_dir(root: str | Path) -> Path:
    configured = os.environ.get("REALCUT_BIN_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(root).resolve() / "bin"


def entrypoint_binary(source: str | Path, root: str | Path) -> Path:
    stem = Path(source).stem
    return binary_dir(root) / f"{BINARY_ALIASES.get(stem, stem)}.exe"


def entrypoint_exists(source: str | Path, root: str | Path) -> bool:
    return entrypoint_binary(source, root).is_file() or Path(source).is_file()


def entrypoint_command(
    source: str | Path,
    args: Iterable[str] = (),
    *,
    root: str | Path,
) -> list[str]:
    """Prefer a compiled entry point and fall back to the Python source."""
    binary = entrypoint_binary(source, root)
    tail = [str(arg) for arg in args]
    if binary.is_file():
        return [str(binary), *tail]
    return [sys.executable, str(source), *tail]
