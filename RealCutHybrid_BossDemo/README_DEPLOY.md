# RealCut Auto 老板演示版部署包说明

这个包是从 `RealCutHybrid_BossDemo` 整理出来的可换机部署版。包内已带上风格2模板、模板引用到的字体/BGM/贴纸、关键词库、爆点与金句素材；不包含 Python、ffmpeg、剪映 5.9、FunASR 模型缓存和 API Key。

## 部署包结构

```text
RealCutAuto_BossDemo_Deploy_20260822_v2/
  Start-RealCutHybridWeb.bat  双击启动 Web 工作台
  config/demo_env.bat         新电脑主要修改这个文件
  realcut_hybrid.py           CLI 调度器
  web_server.py               Web 服务
  web/                        前端页面
  vendor/                     real-cut 原样副本 + 实验引擎
  assets/styles/风格2模板      固定套用的风格2模板
  assets/style_assets/        模板字体、BGM、贴纸、转场特效
  assets/clip_lib/            爆点/金句素材库
  config/highlight_keywords.txt  字幕标黄关键词库
  models_cache/               首次运行自动下载 FunASR 模型
```

## 新电脑安装步骤

1. 安装 Python 3.12 或更高版本，安装时勾选 `Add python.exe to PATH`。
2. 安装 ffmpeg/ffprobe，并确保命令行里能直接执行 `ffmpeg -version` 和 `ffprobe -version`。
3. 安装剪映 5.9。部署版会直接读写剪映草稿目录，不负责打开剪映导出。
4. 进入部署包目录，安装 Python 依赖：

```bat
pip install -r requirements.txt
```

5. 编辑 `config\demo_env.bat`，至少修改两处：

```bat
set "DEEPSEEK_API_KEY=你的DeepSeek API Key"
set "REALCUT_JIANYING_EXE=你的剪映主程序路径"
```

如果要用 qwen 兜底而不是 DeepSeek，把 `DEEPSEEK_API_KEY` 留空，并在系统环境变量里设置 `DASHSCOPE_API_KEY`。

6. 双击 `Start-RealCutHybridWeb.bat`，浏览器打开：

```text
http://127.0.0.1:8766/
```

## 验证环境

在部署包目录执行：

```bat
call config\demo_env.bat
set PYTHONIOENCODING=utf-8
python realcut_hybrid.py check
```

全部显示 `PASS` 后即可在 Web 页投入单个视频或文件夹。文件夹会递归导入其中所有视频，后台固定单任务顺序执行。

## FunASR 模型缓存

- 首次运行会自动下载到包内 `models_cache`，大约 2.2GB，需要网络。
- 如果本机已有一份 `D:\.cache\modelscope` 或旧机器的模型缓存，直接把里面的目录复制到 `models_cache`，可以跳过下载。
- 部署包不内置模型缓存，避免把 2GB 以上的个人缓存打进去。

## 本包固定行为

- 完整剪辑：导入、分离音频、FunASR、AI 切割排序、镜像/开盒补位、画面匹配、转场、BGM、音频平滑、字幕、字体样式；按演示节奏约 15 分钟一条。
- 固定套用风格2模板。
- 保留字幕复核清单、音频平滑、BGM 归一化、字幕空隙补齐。
- 不开放并行、不开放风格选择、不执行字幕字体统一步骤。
- 每次任务只把草稿剪辑到步骤完成，最终导出仍在剪映里操作。

## 常见问题

- `check` 显示“剪映主程序”失败：说明 `REALCUT_JIANYING_EXE` 还没改成这台电脑的真实路径。
- 字幕或金句素材为空：检查 `config\demo_env.bat` 里的 `REALCUT_CLIP_LIB` 和 `REALCUT_BAODIAN_LIB` 是否存在。
- 流水线会在每个真实步骤前后自动关闭剪映；如果连续杀不掉会停止任务，避免写坏草稿。
- 任务状态、日志、快照、报告都会生成在部署包当前目录，不影响其他电脑的原始项目。
