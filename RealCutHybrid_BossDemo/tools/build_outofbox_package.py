#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a fully portable out-of-box boss demo package.

This bundles Python 3.12, the installed site-packages, ffmpeg, JianYing 5.9,
FunASR models, OfficeCLI, app code, and style assets into one folder. The
launcher uses only files inside the package, so another Windows computer can
unzip it and double-click Start-RealCutHybridWeb.bat without installing
Python/ffmpeg/JianYing/FunASR models.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_PARENT = ROOT.parent
BUILD_NAME = "RealCutAuto_BossDemo_OutOfBox_20260822_v1"
BUILD_DIR = BUILD_PARENT / BUILD_NAME
ZIP_PATH = BUILD_PARENT / f"{BUILD_NAME}.zip"
BASE_DEPLOY = BUILD_PARENT / "RealCutAuto_BossDemo_Deploy_20260822_v2"

PYTHON_BASE = Path(r"C:\Program Files\Python312")
PYTHON_USER_SITE = Path(r"C:\Users\JT\AppData\Roaming\Python\Python312\site-packages")
FFMPEG_SRC = Path(r"C:\Users\JT\Desktop\ffmpeg")
JIANYING_SRC = Path(r"C:\Users\JT\Desktop\剪映5.9Windows\JianyingPro")
OFFICECLI_SRC = Path(r"C:\Users\JT\AppData\Local\OfficeCLI")
MODELSCOPE_SRC = Path(r"D:\.cache\modelscope")

RUN_DIRS = {"state", "logs", "snapshots", "reports", "manifests", "__pycache__", "##_pkg_assets_"}


def _rm(path: Path) -> None:
    if path.exists():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _robocopy(src: Path, dst: Path, extra: tuple[str, ...] = ()) -> None:
    if not src.is_dir():
        raise FileNotFoundError(f"源目录不存在: {src}")
    dst.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "robocopy",
            str(src),
            str(dst),
            "/E",
            "/R:1",
            "/W:1",
            "/MT:16",
            "/XJ",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NP",
            *extra,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode >= 8:
        raise RuntimeError(f"robocopy 失败: {src} -> {dst}\n{proc.stderr[-2000:]}")


def copy_app_code() -> None:
    _rm(BUILD_DIR)
    if not BASE_DEPLOY.is_dir():
        raise FileNotFoundError(f"缺少基础部署包目录: {BASE_DEPLOY}")
    shutil.copytree(BASE_DEPLOY, BUILD_DIR, ignore=shutil.ignore_patterns("__pycache__"))
    print(f"  [app] 已复制应用代码: {BUILD_DIR}")


def copy_runtime() -> None:
    runtime = BUILD_DIR / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)

    _robocopy(PYTHON_BASE, runtime / "python")
    _robocopy(PYTHON_USER_SITE, runtime / "python" / "Lib" / "site-packages")
    print("  [runtime] 已复制 Python + 依赖")

    _robocopy(FFMPEG_SRC, runtime / "ffmpeg")
    print("  [runtime] 已复制 ffmpeg/ffprobe")

    # update.exe 被系统 ACL 保护且只用于自动更新，离线剪辑不需要。
    _robocopy(JIANYING_SRC, runtime / "JianyingPro", ("/XF", "update.exe"))
    print("  [runtime] 已复制剪映 5.9")

    _robocopy(OFFICECLI_SRC, runtime / "officecli")
    print("  [runtime] 已复制 OfficeCLI")

    _robocopy(MODELSCOPE_SRC, BUILD_DIR / "models_cache")
    print("  [runtime] 已复制 FunASR 模型缓存")


def patch_launchers() -> None:
    env_path = BUILD_DIR / "config" / "demo_env.bat"
    env_path.write_text(
        """@echo off
rem ============================================================
rem RealCut Auto 开箱即用环境配置
rem 本包已内置 Python、ffmpeg、剪映 5.9、FunASR 模型和 OfficeCLI。
rem 新电脑通常只需要填 API Key：
rem   set "DEEPSEEK_API_KEY=你的DeepSeek API Key"
rem 如果不用 DeepSeek，也可以把 DEEPSEEK_API_KEY 留空并设置
rem DASHSCOPE_API_KEY（qwen 兜底）。
rem ============================================================
set "REALCUT_ROOT=%~dp0.."

if not defined DEEPSEEK_API_KEY set "DEEPSEEK_API_KEY="
if not defined DEEPSEEK_MODEL set "DEEPSEEK_MODEL=deepseek-flash"
if not defined DASHSCOPE_API_KEY set "DASHSCOPE_API_KEY="

if not defined REALCUT_DRAFT_ROOT set "REALCUT_DRAFT_ROOT=%LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\com.lveditor.draft"
if not exist "%REALCUT_DRAFT_ROOT%" mkdir "%REALCUT_DRAFT_ROOT%"
set "REALCUT_JIANYING_EXE=%REALCUT_ROOT%\\runtime\\JianyingPro\\5.9.0.11632\\JianyingPro.exe"
set "OFFICECLI_BIN=%REALCUT_ROOT%\\runtime\\officecli\\officecli.exe"

set "REALCUT_STYLE_LIB=%REALCUT_ROOT%\\assets\\styles"
set "REALCUT_ASSETS_ROOT=%REALCUT_ROOT%\\assets"
set "REALCUT_KEYWORD_FILE=%REALCUT_ROOT%\\config\\highlight_keywords.txt"
set "REALCUT_CLIP_LIB=%REALCUT_ROOT%\\assets\\clip_lib"
set "REALCUT_BAODIAN_LIB=%REALCUT_ROOT%\\assets\\clip_lib\\爆点素材库\\素材库"
set "REALCUT_MODELSCOPE_CACHE=%REALCUT_ROOT%\\models_cache"
set "REALCUT_FONT_PATH=%REALCUT_ROOT%\\assets\\style_assets\\fonts\\字语圆体.ttf"

set "PATH=%REALCUT_ROOT%\\runtime\\ffmpeg;%PATH%"
set "PYTHONHOME=%REALCUT_ROOT%\\runtime\\python"

if not exist "%REALCUT_MODELSCOPE_CACHE%" mkdir "%REALCUT_MODELSCOPE_CACHE%"
""",
        encoding="utf-8",
    )

    bat_path = BUILD_DIR / "Start-RealCutHybridWeb.bat"
    text = bat_path.read_text(encoding="utf-8-sig")
    old = 'start "RealCut Auto Web" /min python web_server.py --port 8766\n'
    new = (
        'start "RealCut Auto Web" /min "%REALCUT_ROOT%\\runtime\\python\\python.exe" web_server.py --port 8766\n'
        'timeout /t 5 /nobreak >nul\n'
        'start "" "http://127.0.0.1:8766/"\n'
    )
    if old not in text:
        raise RuntimeError(f"未找到待替换文本: {old} in {bat_path}")
    bat_path.write_text(text.replace(old, new), encoding="utf-8")

    readme = BUILD_DIR / "README_DEPLOY.md"
    readme.write_text(
        """# RealCut Auto 开箱即用版

这是给老板演示用的全量便携包。解压后不需要安装 Python、ffmpeg、剪映 5.9、FunASR 模型或 OfficeCLI，只需要配置一个 API Key，然后双击启动即可。

## 包里已内置

- Python 3.12 及全部 Python 依赖
- ffmpeg / ffprobe
- 剪映 5.9 便携运行目录
- FunASR 三个离线模型（约 2.1GB）
- OfficeCLI（用于 Excel 交接文件）
- 风格2模板、字体、BGM、贴纸、爆点/金句素材库

## 启动步骤

1. 把整个文件夹解压到目标电脑，路径中不要有系统保护目录。
2. 编辑 `config\\demo_env.bat`，填入 API Key：

```bat
set "DEEPSEEK_API_KEY=你的DeepSeek API Key"
```

   如果目标电脑已经设置了 `DEEPSEEK_API_KEY` 或 `DASHSCOPE_API_KEY` 环境变量，可以跳过这一步。
3. 双击 `Start-RealCutHybridWeb.bat`。
4. 浏览器会自动打开 `http://127.0.0.1:8766/`。

## 验证环境

在包目录执行：

```bat
call config\\demo_env.bat
set PYTHONIOENCODING=utf-8
"%REALCUT_ROOT%\\runtime\\python\\python.exe" realcut_hybrid.py check
```

所有显示 `PASS` 即可使用。

## 固定行为

- 只选择单个视频或文件夹。
- 文件夹会自动导入其中所有视频，递归扫描子目录。
- 固定完整剪辑：导入、分离音频、FunASR、AI 切割排序、镜像/开盒补位、画面匹配、转场、BGM、音频平滑、字幕、字体样式。
- 固定套用风格2模板。
- 固定开启字幕复核、音频平滑、BGM 归一化、字幕空隙补齐。
- 单任务顺序执行，不开放并行和风格选择。
- 每个真实步骤前后会自动关闭剪映，避免草稿被运行中的剪映覆盖。
- 最终导出仍由剪映完成，系统只负责把草稿剪辑到步骤完成。

## 常见问题

- `check` 显示剪映主程序失败：确认 `runtime\\JianyingPro\\5.9.0.11632\\JianyingPro.exe` 存在，或临时修改 `config\\demo_env.bat` 里的 `REALCUT_JIANYING_EXE`。
- 字幕审核没有生效：检查 `DEEPSEEK_API_KEY` 是否已填写；没有 DeepSeek Key 时会自动尝试 qwen 兜底，需要 `DASHSCOPE_API_KEY`。
- 任务状态、日志、快照、报告会生成在当前包目录，不会影响其他电脑上的原始项目。
""",
        encoding="utf-8",
    )
    print("  [launcher] 已改写为内置运行环境")


def build_zip() -> Path:
    _rm(ZIP_PATH)
    for name in RUN_DIRS:
        _rm(BUILD_DIR / name)
    _rm(BUILD_DIR / "web_queue.json")
    count = 0
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for p in sorted(BUILD_DIR.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(BUILD_DIR)
            if set(rel.parts) & RUN_DIRS or p.name == "web_queue.json":
                continue
            zf.write(p, p.relative_to(BUILD_PARENT).as_posix())
            count += 1
    size_gb = ZIP_PATH.stat().st_size / (1024 ** 3)
    print(f"  [zip] {ZIP_PATH} ({size_gb:.2f} GB, {count} files)")
    return ZIP_PATH


def main() -> int:
    required = {
        "基础部署包": BASE_DEPLOY,
        "Python": PYTHON_BASE,
        "Python 依赖": PYTHON_USER_SITE,
        "ffmpeg": FFMPEG_SRC,
        "剪映 5.9": JIANYING_SRC,
        "OfficeCLI": OFFICECLI_SRC,
        "FunASR 模型": MODELSCOPE_SRC,
    }
    for name, path in required.items():
        if not path.exists():
            print(f"缺少打包源: {name} -> {path}")
            return 1

    print("1/4 复制应用代码 ...")
    copy_app_code()
    print("2/4 复制运行环境 ...")
    copy_runtime()
    print("3/4 改写启动脚本 ...")
    patch_launchers()
    print("4/4 生成 zip ...")
    build_zip()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
