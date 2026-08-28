"""Resolve source and packaged RealCut Hybrid entry points."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable


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
    return binary_dir(root) / f"{Path(source).stem}.exe"


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
