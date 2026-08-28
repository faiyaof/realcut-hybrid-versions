# RealCutHybrid 开箱即用部署包

这是 `RealCutHybrid` 当前版本的完整便携部署包。解压后不需要安装 Python、ffmpeg、剪映 5.9、FunASR 模型或 OfficeCLI，只需要填一个 API Key，然后双击启动。

## 包里已内置

- Python 运行环境及项目依赖
- ffmpeg / ffprobe
- 剪映 5.9 便携运行目录
- FunASR 离线模型缓存
- OfficeCLI
- 风格2模板、字体、BGM、贴纸、转场素材、爆点素材库
- 当前 `RealCutHybrid` 的完整 Web 调度系统与实验版剪辑脚本

当前剪辑流程不会再自动从外部素材库注入固定“金句”，适合不同人物素材混剪。

## 启动步骤

1. 把整个文件夹解压到目标电脑，路径中不要有系统保护目录。
2. 编辑 `config\deploy_env.bat`，填写 API Key：

```bat
set "DEEPSEEK_API_KEY=你的DeepSeek API Key"
```

   如果目标电脑已经设置了 `DEEPSEEK_API_KEY` 或 `DASHSCOPE_API_KEY` 环境变量，可以跳过这一步。
3. 双击 `Start-RealCutHybridWeb.bat`。
4. 浏览器会自动打开 `http://127.0.0.1:8766/`。

## 验证环境

在包目录执行：

```bat
call config\deploy_env.bat
set PYTHONIOENCODING=utf-8
"%REALCUT_ROOT%\runtime\python\python.exe" realcut_hybrid.py check
```

所有关键项显示 `PASS` 即可使用。

## 说明

- Web 端保留当前系统功能，包括批量任务、队列、并发开关、字幕复核、音频平滑、BGM 归一化、字幕空隙补齐和已跑草稿修复入口。
- 默认剪映草稿目录使用目标电脑的 `%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft`，可在 `config\deploy_env.bat` 里改 `REALCUT_DRAFT_ROOT`。
- 默认剪映主程序使用包内 `runtime\JianyingPro\5.9.0.11632\JianyingPro.exe`。
- 任务状态、日志、快照、报告和交接清单会生成在当前包目录，不影响目标电脑原有项目。
- `vendor\real-cut` 保持原样作为参考；当前调度使用 `vendor\experimental` 的改进版脚本。
