@echo off
rem ============================================================
rem RealCut Auto 部署环境配置
rem 新电脑首次部署时，至少修改两项：
rem   1. DEEPSEEK_API_KEY
rem   2. REALCUT_JIANYING_EXE（指向本机剪映5.9主程序）
rem 其余路径默认指向本部署包 assets/ 或本机 LOCALAPPDATA。
rem ============================================================
set "REALCUT_ROOT=%~dp0.."

if not defined DEEPSEEK_API_KEY set "DEEPSEEK_API_KEY="
if not defined DEEPSEEK_MODEL set "DEEPSEEK_MODEL=deepseek-flash"
if not defined DASHSCOPE_API_KEY set "DASHSCOPE_API_KEY="

if not defined REALCUT_DRAFT_ROOT set "REALCUT_DRAFT_ROOT=%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft"
if not defined REALCUT_JIANYING_EXE (
    if exist "C:\Program Files\JianyingPro\JianyingPro.exe" set "REALCUT_JIANYING_EXE=C:\Program Files\JianyingPro\JianyingPro.exe"
    if not defined REALCUT_JIANYING_EXE if exist "C:\Program Files (x86)\JianyingPro\JianyingPro.exe" set "REALCUT_JIANYING_EXE=C:\Program Files (x86)\JianyingPro\JianyingPro.exe"
    if not defined REALCUT_JIANYING_EXE if exist "%USERPROFILE%\Desktop\剪映5.9Windows\JianyingPro\5.9.0.11632\JianyingPro.exe" set "REALCUT_JIANYING_EXE=%USERPROFILE%\Desktop\剪映5.9Windows\JianyingPro\5.9.0.11632\JianyingPro.exe"
    if not defined REALCUT_JIANYING_EXE set "REALCUT_JIANYING_EXE=C:\Program Files\JianyingPro\JianyingPro.exe"
)

set "REALCUT_STYLE_LIB=%REALCUT_ROOT%\assets\styles"
set "REALCUT_ASSETS_ROOT=%REALCUT_ROOT%\assets"
set "REALCUT_KEYWORD_FILE=%REALCUT_ROOT%\config\highlight_keywords.txt"
set "REALCUT_CLIP_LIB=%REALCUT_ROOT%\assets\clip_lib"
set "REALCUT_BAODIAN_LIB=%REALCUT_ROOT%\assets\clip_lib\爆点素材库\素材库"
set "REALCUT_MODELSCOPE_CACHE=%REALCUT_ROOT%\models_cache"
set "REALCUT_FONT_PATH=%REALCUT_ROOT%\assets\style_assets\fonts\字语圆体.ttf"

if not exist "%REALCUT_MODELSCOPE_CACHE%" mkdir "%REALCUT_MODELSCOPE_CACHE%"
