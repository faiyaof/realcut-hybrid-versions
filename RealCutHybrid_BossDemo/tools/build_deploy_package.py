#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the portable boss-demo deploy package.

Run from the demo root:
    python tools/build_deploy_package.py

The script writes local assets into `assets/`, then creates
`../RealCutAuto_BossDemo_Deploy_20260822_v2.zip` for another computer.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_PARENT = ROOT.parent
BUILD_NAME = "RealCutAuto_BossDemo_Deploy_20260822_v2"
BUILD_DIR = BUILD_PARENT / BUILD_NAME
ZIP_PATH = BUILD_PARENT / f"{BUILD_NAME}.zip"

TEMPLATE_SRC = Path(r"D:\10  jianyin\JianyingPro Drafts\风格2模板")
CLIP_LIB_SRC = Path(r"C:\Users\JT\Documents\剪辑\爆点+金句 素材库")
KEYWORD_SRC = Path(r"C:\Users\JT\Documents\剪辑\highlight_keywords.txt")
TRANSITION_EFFECT_SRC = [
    Path(r"C:\Users\JT\AppData\Local\JianyingPro\User Data\Cache\effect\51784590\a2c4ddc0f96c5694e941d738ed52cdf4"),
    Path(r"C:\Users\JT\AppData\Local\JianyingPro\User Data\Cache\effect\321493\3bca53e9f3dfa2c184fbee96438ea097"),
]

PKG_PLACEHOLDER = "##_pkg_assets_"
EXCLUDE_DIRS = {
    "state", "logs", "snapshots", "reports", "manifests",
    "__pycache__", "assets", "models_cache", "tools", "deploy",
    "##_pkg_assets_",
}
EXCLUDE_FILES = {"web_queue.json"}
JSON_SUFFIXES = {".json", ".tmp"}


def _rm(path: Path) -> None:
    if path.exists():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _copy_tree(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    elif src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    else:
        raise FileNotFoundError(f"源路径不存在: {src}")


def _json_files(template_dir: Path):
    names = {"draft_content.json", "draft_info.json", "template-2.tmp", "template.json.bak"}
    return [template_dir / name for name in names if (template_dir / name).is_file()]


def _collect_paths(template_dir: Path) -> set[str]:
    found: set[str] = set()
    pattern = re.compile(r"[A-Za-z]:[\\/][^\"\\,]+")
    for p in _json_files(template_dir):
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue

        def walk(value):
            if isinstance(value, str):
                for m in pattern.finditer(value):
                    raw = m.group(0).rstrip("\\/")
                    if raw.startswith(("http", "https", "data:", "file:", "##")):
                        continue
                    if "://" in raw:
                        continue
                    found.add(raw)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, dict):
                for item in value.values():
                    walk(item)

        walk(data)
    return found


def _map_asset_path(raw: str) -> str:
    norm = raw.replace("\\", "/")
    name = norm.rsplit("/", 1)[-1]
    lower = norm.lower()
    if name.lower().endswith(".ttf"):
        return f"{PKG_PLACEHOLDER}/style_assets/fonts/{name}"
    if name.lower().endswith((".mp3", ".wav", ".m4a", ".aac", ".flac")):
        return f"{PKG_PLACEHOLDER}/style_assets/music/{name}"
    if "artistEffect" in norm:
        return f"{PKG_PLACEHOLDER}/style_assets/stickers/{name}"
    if name.lower().endswith((".mp4", ".mkv", ".mov", ".avi", ".flv")):
        return f"{PKG_PLACEHOLDER}/style_assets/sample/{name}"
    if Path(name).suffix:
        return f"{PKG_PLACEHOLDER}/style_assets/files/{name}"
    return f"{PKG_PLACEHOLDER}/style_assets/dirs/{name}"


def _copy_asset(src: str, dst: str, assets_root: Path) -> None:
    src_path = Path(src)
    rel = dst.replace(PKG_PLACEHOLDER + "/", "").replace("\\", "/")
    dst_path = assets_root / rel
    if not src_path.exists():
        print(f"  [warn] 模板引用资源不存在，跳过: {src}")
        return
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    if src_path.is_file():
        shutil.copy2(src_path, dst_path)
    else:
        if dst_path.exists():
            shutil.rmtree(dst_path)
        shutil.copytree(src_path, dst_path)
    print(f"  [asset] {src_path.name} -> {dst_path}")


def _rewrite_paths(value, mapping: dict[str, str]):
    if isinstance(value, str):
        for src, dst in mapping.items():
            if src in value:
                value = value.replace(src, dst)
            alt_src = src.replace("\\", "/")
            alt_dst = dst.replace("\\", "/")
            if alt_src in value:
                value = value.replace(alt_src, alt_dst)
        return value
    if isinstance(value, list):
        return [_rewrite_paths(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_paths(item, mapping) for key, item in value.items()}
    return value


def rewrite_transitions_template(path: Path) -> None:
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    changed = False
    for item in data.get("transitions", []):
        raw = item.get("path", "")
        if raw and not raw.startswith(PKG_PLACEHOLDER):
            name = raw.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            item["path"] = f"{PKG_PLACEHOLDER}/style_assets/effects/{name}"
            changed = True
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")


def prepare_assets(target_root: Path) -> None:
    assets_root = target_root / "assets"
    models_root = target_root / "models_cache"
    _rm(assets_root)
    _rm(models_root)
    _rm(target_root / "##_pkg_assets_")
    assets_root.mkdir(parents=True, exist_ok=True)
    models_root.mkdir(parents=True, exist_ok=True)
    (models_root / "README.txt").write_text(
        "FunASR 模型缓存目录。首次运行会自动下载；也可把旧机器 modelscope 缓存复制到这里。\n",
        encoding="utf-8",
    )

    style_dst = assets_root / "styles" / "风格2模板"
    style_dst.mkdir(parents=True)
    for item in TEMPLATE_SRC.iterdir():
        if item.is_dir():
            _copy_tree(item, style_dst / item.name)
        else:
            style_dst.joinpath(item.name).write_bytes(item.read_bytes())

    raw_paths = _collect_paths(style_dst)
    mapping = {}
    style_assets = assets_root / "style_assets"
    for raw in sorted(raw_paths):
        dst = _map_asset_path(raw)
        mapping[raw] = dst
        _copy_asset(raw, dst, assets_root)

    for p in _json_files(style_dst):
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        data = _rewrite_paths(data, mapping)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    print(f"  [style] 已复制并重写模板: {style_dst}")

    clip_dst = assets_root / "clip_lib"
    for rel in ("金句", "爆点", Path("爆点素材库") / "素材库"):
        _copy_tree(CLIP_LIB_SRC / rel, clip_dst / rel)
    print(f"  [clip] 已复制爆点/金句素材库: {clip_dst}")

    effects_dst = assets_root / "style_assets" / "effects"
    effects_dst.mkdir(parents=True, exist_ok=True)
    for src_path in TRANSITION_EFFECT_SRC:
        if src_path.is_dir():
            _copy_tree(src_path, effects_dst / src_path.name)
            print(f"  [asset] 转场特效缓存: {src_path.name}")

    config_dst = target_root / "config"
    config_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(KEYWORD_SRC, config_dst / "highlight_keywords.txt")
    print(f"  [keywords] 已复制关键词库: {config_dst / 'highlight_keywords.txt'}")

    (assets_root / "README.txt").write_text(
        "assets/ 是部署包随附资源：styles=风格2模板，style_assets=模板字体/BGM/贴纸/转场，clip_lib=爆点金句素材库。\n",
        encoding="utf-8",
    )


def copy_project_code(src: Path, dst: Path) -> None:
    _rm(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if child.name in EXCLUDE_DIRS or child.name in EXCLUDE_FILES:
            continue
        target = dst / child.name
        if child.is_dir():
            _copy_tree(child, target)
        else:
            shutil.copy2(child, target)
    print(f"  [code] 已复制项目代码: {dst}")


def build_zip() -> Path:
    _rm(ZIP_PATH)
    for name in ("state", "logs", "reports", "snapshots", "manifests", "__pycache__", "web_queue.json"):
        _rm(BUILD_DIR / name)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(BUILD_DIR.rglob("*")):
            if not p.is_file():
                continue
            parts = set(p.relative_to(BUILD_DIR).parts)
            if parts & {"__pycache__", "state", "logs", "reports", "snapshots", "manifests", "##_pkg_assets_"}:
                continue
            if p.name == "web_queue.json":
                continue
            zf.write(p, p.relative_to(BUILD_PARENT).as_posix())
    size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    print(f"  [zip] {ZIP_PATH} ({size_mb:.1f} MB)")
    return ZIP_PATH


def main() -> int:
    for name, path in (
        ("风格2模板", TEMPLATE_SRC),
        ("爆点金句素材库", CLIP_LIB_SRC),
        ("关键词库", KEYWORD_SRC),
    ):
        if not path.exists():
            print(f"缺少打包源: {name} -> {path}")
            return 1

    print("1/3 准备本地演示 assets ...")
    prepare_assets(ROOT)

    print("2/3 复制项目代码到部署目录 ...")
    copy_project_code(ROOT, BUILD_DIR)
    print("     重新生成部署目录 assets ...")
    prepare_assets(BUILD_DIR)
    rewrite_transitions_template(BUILD_DIR / "vendor" / "experimental" / "scripts" / "transitions_template.json")
    rewrite_transitions_template(BUILD_DIR / "vendor" / "real-cut" / "scripts" / "transitions_template.json")

    print("3/3 生成 zip ...")
    build_zip()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
