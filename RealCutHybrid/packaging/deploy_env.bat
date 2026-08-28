@echo off
chcp 65001 >nul
rem RealCutHybrid compiled handover environment.
for %%I in ("%~dp0..") do set "REALCUT_ROOT=%%~fI"

if not defined DEEPSEEK_API_KEY set "DEEPSEEK_API_KEY="
if not defined DEEPSEEK_MODEL set "DEEPSEEK_MODEL=deepseek-chat"
if not defined DASHSCOPE_API_KEY set "DASHSCOPE_API_KEY="

if not defined REALCUT_DRAFT_ROOT set "REALCUT_DRAFT_ROOT=%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft"
if not exist "%REALCUT_DRAFT_ROOT%" mkdir "%REALCUT_DRAFT_ROOT%"

set "REALCUT_BIN_DIR=%REALCUT_ROOT%\bin"
set "REALCUT_PYTHON_RUNTIME=%REALCUT_ROOT%\runtime\python"
set "REALCUT_JIANYING_EXE=%REALCUT_ROOT%\runtime\JianyingPro\5.9.0.11632\JianyingPro.exe"
set "JY_DLL=%REALCUT_ROOT%\runtime\JianyingPro\5.9.0.11632\videoeditor.dll"
set "OFFICECLI_BIN=%REALCUT_ROOT%\runtime\officecli\officecli.exe"

set "REALCUT_STYLE_LIB=%REALCUT_ROOT%\assets\styles"
set "REALCUT_ASSETS_ROOT=%REALCUT_ROOT%\assets"
set "REALCUT_KEYWORD_FILE=%REALCUT_ROOT%\config\highlight_keywords.txt"
set "REALCUT_SCRIPT_DATA_DIR=%REALCUT_ROOT%\vendor\experimental\scripts"
set "REALCUT_BGM_DIR=%REALCUT_ROOT%\assets\style_assets\music"
set "REALCUT_CLIP_LIB=%REALCUT_ROOT%\assets\clip_lib"
set "REALCUT_BAODIAN_LIB=%REALCUT_ROOT%\assets\clip_lib\爆点素材库\素材库"
set "REALCUT_MODELSCOPE_CACHE=%REALCUT_ROOT%\models_cache"
set "MODELSCOPE_CACHE=%REALCUT_MODELSCOPE_CACHE%"
set "REALCUT_FONT_PATH=%REALCUT_ROOT%\assets\style_assets\fonts\字语圆体.ttf"

set "PATH=%REALCUT_ROOT%\runtime\ffmpeg;%REALCUT_ROOT%\runtime\python;%REALCUT_ROOT%\runtime\officecli;%PATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

if not exist "%REALCUT_MODELSCOPE_CACHE%" mkdir "%REALCUT_MODELSCOPE_CACHE%"
