"""Load third-party packages from the bundled portable Python runtime."""

from __future__ import annotations

import importlib
import os
import site
import sys
from importlib.abc import MetaPathFinder
from importlib.machinery import PathFinder
from pathlib import Path


_CONFIGURED = False
_DLL_HANDLES = []


class _ExternalRuntimeFinder(MetaPathFinder):
    def __init__(self, roots: list[Path]):
        self.roots = roots

    def find_spec(self, fullname, path=None, target=None):
        parts = fullname.split(".")
        if len(parts) == 1:
            search_paths = [str(root) for root in self.roots]
        else:
            search_paths = [
                str(root.joinpath(*parts[:-1]))
                for root in self.roots
                if root.joinpath(*parts[:-1]).is_dir()
            ]
        if not search_paths:
            return None
        return PathFinder.find_spec(fullname, search_paths, target)


def _application_root() -> Path:
    configured = os.environ.get("REALCUT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    executable_dir = Path(os.path.dirname(os.path.abspath(sys.argv[0])))
    if executable_dir.name.lower() == "bin":
        return executable_dir.parent
    return Path(__file__).resolve().parents[3]


def configure_external_runtime() -> None:
    """Expose the portable stdlib/site-packages to compiled entry points."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = _application_root()
    runtime = Path(
        os.environ.get("REALCUT_PYTHON_RUNTIME", root / "runtime" / "python")
    ).expanduser().resolve()
    site_packages = runtime / "Lib" / "site-packages"

    module_roots = [runtime / "Lib", runtime / "DLLs", site_packages]
    for path in module_roots:
        if path.is_dir():
            site.addsitedir(str(path))

    finder_roots = [path for path in module_roots if path.is_dir()]
    if finder_roots:
        sys.meta_path.insert(0, _ExternalRuntimeFinder(finder_roots))

    dll_dirs = [
        runtime,
        runtime / "DLLs",
        site_packages / "torch" / "lib",
        site_packages / "torchaudio" / "lib",
        site_packages / "onnxruntime" / "capi",
        site_packages / "numpy.libs",
        site_packages / "scipy.libs",
    ]
    existing = [str(path) for path in dll_dirs if path.is_dir()]
    if existing:
        os.environ["PATH"] = os.pathsep.join(existing + [os.environ.get("PATH", "")])
        if hasattr(os, "add_dll_directory"):
            for path in existing:
                try:
                    _DLL_HANDLES.append(os.add_dll_directory(path))
                except OSError:
                    pass

    _CONFIGURED = True


def import_external(module_name: str):
    configure_external_runtime()
    return importlib.import_module(module_name)
