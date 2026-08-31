# RealCut Hybrid 编译交接版

本交接版把 RealCut Hybrid 自有 Python 代码编译为 Windows EXE，并保留经过验证的便携
Python 第三方依赖、FunASR 模型、FFmpeg、剪映 5.9、OfficeCLI、风格1/风格2模板及其字体、BGM、贴纸素材。

## 使用

1. 安装或完整复制便携目录，推荐使用安装器默认短路径，不要放在系统保护目录或很深的多级目录。
2. 双击 `Start-RealCutHybridWeb.bat`。
3. 浏览器打开本机工作台，在“设置”页填写 DeepSeek 或 DashScope API Key。
4. 保存后环境预检会立即刷新，之后提交的任务会自动使用新配置。

目标电脑处理较慢时，可在新建任务中关闭“AI 画面识别（较慢）”。关闭后不再逐帧调用
视觉模型，系统按 ASR/字幕对应的原视频时间轴重建画面；速度会明显提高，但不会再主动
避开空手、开盒或其他商品画面。

目标电脑不需要预装剪映 5.9，也不需要手工复制模板或剪映缓存。新建任务时可在风格框选择随包的风格1/风格2，默认使用风格1。

## 体积说明

这是可断网部署的完整版，包含约 2.0 GiB FunASR 模型、1.3 GiB 精简 Python AI 运行时、
1.27 GiB 剪映 5.9，以及 FFmpeg、OfficeCLI 和风格素材。安装后的占用会明显大于下载包，
但接手电脑不需要另装 Python、模型或剪映。

首次使用前可在包目录打开命令提示符执行：

```bat
call config\deploy_env.bat
bin\realcut_hybrid.exe check
```

## 交接边界

- `bin\` 是编译后的共享运行目录，各步骤 EXE 共用同一套 DLL。
- `runtime\python` 只承载 Python 标准库和第三方 AI 依赖，不包含 RealCut Hybrid 自有源码。
- 任务状态、日志、报告和清单写在安装目录下的 `state/logs/reports/manifests`。
- 剪映草稿默认写到当前 Windows 用户的 `%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft`。
- API Key 使用 Windows DPAPI 按当前用户加密保存在 `%LOCALAPPDATA%\RealCutHybrid\settings.json`，不随安装包分发；换用户或换电脑后需要重新填写。

## 代码保护说明

EXE 会显著提高直接查看和修改源码的门槛，但任何本地软件都无法做到绝对不可逆。可维护源码只保存在
私有 GitHub 仓库；日常使用者只拿安装包或便携目录。建议同时保留仓库访问控制、版本标签和发布包
SHA-256 校验，不向普通使用者分发源码仓库权限。
