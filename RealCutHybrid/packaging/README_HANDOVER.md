# RealCut Hybrid 编译交接版

本交接版把 RealCut Hybrid 自有 Python 代码编译为 Windows EXE，并保留经过验证的便携
Python 第三方依赖、FunASR 模型、FFmpeg、剪映 5.9、OfficeCLI 和风格素材。

## 使用

1. 安装或完整复制便携目录，推荐使用安装器默认短路径，不要放在系统保护目录或很深的多级目录。
2. 编辑 `config\deploy_env.bat`，填写 `DEEPSEEK_API_KEY`；也可以在 Windows 用户环境变量中设置。
3. 双击 `Start-RealCutHybridWeb.bat`。
4. 浏览器打开 `http://127.0.0.1:8766/`。

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
- API Key 不随安装包分发，换电脑后需要重新填写或设置环境变量。

## 代码保护说明

EXE 会显著提高直接查看和修改源码的门槛，但任何本地软件都无法做到绝对不可逆。可维护源码只保存在
私有 GitHub 仓库；日常使用者只拿安装包或便携目录。建议同时保留仓库访问控制、版本标签和发布包
SHA-256 校验，不向普通使用者分发源码仓库权限。
