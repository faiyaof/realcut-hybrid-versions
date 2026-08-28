@echo off
rem ============================================================
rem RealCutHybrid 开箱即用环境配置
rem 本包已内置 Python、ffmpeg、剪映 5.9、FunASR 模型和 OfficeCLI。
rem 新电脑通常只需要填写 API Key：
rem   把下面这行改为：
rem   set "DEEPSEEK_API_KEY=你的DeepSeek API Key"
rem 如果不用 DeepSeek，也可以留空并设置 DASHSCOPE_API_KEY（qwen 兜底）。
rem ============================================================
set "REALCUT_ROOT=%~dp0.."

if not defined DEEPSEEK_API_KEY set "DEEPSEEK_API_KEY="
if not defined DEEPSEEK_MODEL set "DEEPSEEK_MODEL=deepseek-flash"
if not defined DASHSCOPE_API_KEY set "DASHSCOPE_API_KEY="

if not defined REALCUT_DRAFT_ROOT set "REALCUT_DRAFT_ROOT=%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft"
if not exist "%REALCUT_DRAFT_ROOT%" mkdir "%REALCUT_DRAFT_ROOT%"
set "REALCUT_JIANYING_EXE=%REALCUT_ROOT%\runtime\JianyingPro\5.9.0.11632\JianyingPro.exe"
set "OFFICECLI_BIN=%REALCUT_ROOT%\runtime\officecli\officecli.exe"

set "REALCUT_STYLE_LIB=%REALCUT_ROOT%\assets\styles"
set "REALCUT_ASSETS_ROOT=%REALCUT_ROOT%\assets"
set "REALCUT_KEYWORD_FILE=%REALCUT_ROOT%\config\highlight_keywords.txt"
set "REALCUT_CLIP_LIB=%REALCUT_ROOT%\assets\clip_lib"
set "REALCUT_BAODIAN_LIB=%REALCUT_ROOT%\assets\clip_lib\爆点素材库\素材库"
set "REALCUT_MODELSCOPE_CACHE=%REALCUT_ROOT%\models_cache"
set "REALCUT_FONT_PATH=%REALCUT_ROOT%\assets\style_assets\fonts\字语圆体.ttf"

set "PATH=%REALCUT_ROOT%\runtime\ffmpeg;%PATH%"
set "PYTHONHOME=%REALCUT_ROOT%\runtime\python"

if not exist "%REALCUT_MODELSCOPE_CACHE%" mkdir "%REALCUT_MODELSCOPE_CACHE%"
