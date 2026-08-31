# RealCut Hybrid

RealCut Hybrid 是一个薄调度层：把已验证的 `real-cut` skill 原样复制到
`vendor/real-cut`，再把实验性修复复制到 `vendor/experimental/scripts` 作为当前
调度器实际使用的引擎，外面补上 LiveClipAgent 风格的任务状态、步骤快照、断点续跑、
失败重试、批量调度、Web 工作台和结构化报告。

原版 real-cut skill 仍在 `C:\Users\JT\.codex\skills\real-cut\SKILL.md`，本项目的
`vendor/real-cut` 只用于保留原版，**不要直接修改**。实验副本 `vendor/experimental`
可以继续迭代，复制方式就是把 `vendor/real-cut/scripts` 整体复制过去后打补丁。

## 目录

```text
RealCutHybrid/
  realcut_hybrid.py       CLI 调度器（默认跑 vendor/experimental）
  vendor/real-cut/        real-cut skill 原样副本（只读）
  vendor/experimental/   当前实验引擎：60ms 淡入淡出、音频平滑、字幕审校、字体统一
  vendor/experimental/   当前实验引擎：60ms 淡入淡出、音频平滑、字幕审校、字体统一、字幕空隙补齐
  manifest.py             批次 JSON + Excel 双写状态
  postprocess.py          风格2/强制字体/字幕补缝后处理
  manifests/              批次/视频/异常三表交接文件
  config/                字幕领域词表、人工覆盖、Web/CLI 共享配置
  state/                  每个视频一个任务状态 JSON
  logs/                   每次运行日志
  snapshots/              步骤前草稿快照
  reports/                Markdown + JSON 任务报告
  web_server.py           本地 Web 服务与后台任务队列
  Start-RealCutHybridWeb.bat  双击启动 Web 工作台
  web/                    LiveClipAgent 风格精简前端
```

`runs/` 用于 Claude CLI 独立批次：每个 `--run-root runs/<名称>` 会单独保存自己的
`state/ logs/ reports/ snapshots/ manifests/`，不会和 Web/旧会话共享。

Web 前端复用 LiveClipAgent 的本地工作台视觉框架，但只保留对 RealCutHybrid
有用的部分：任务队列、步骤详情、字幕复核、日志、报告、本地路径选择器和提交任务
表单。LiveClipAgent 的 Agent 总控、Skill 导入、模型配置和质量门禁没有并入。

## 为什么是 Hybrid

- 保留 real-cut 的确定性剪辑规则：30 秒收敛、AI 分类排序、镜像/开盒补位、画面匹配、
  转场、BGM、字幕断句、关键字标黄、字体样式。
- 吸收 LiveClipAgent 的优点：任务状态持久化、步骤 checkpoint、失败后快照回滚、
  有界重试、批量队列、日志与结构化报告。
- 新增质量修复：字幕领域词表 + AI 受限审校、人声响度归一化、过短片段合并、BGM
  压低、动态字幕字体统一。
- 不吸收 LiveClipAgent 的 7.4GB 打包运行环境、剪映 UI 自动打开/导出，以及偏重的
  自动重剪质量闭环。当前版本只负责把草稿剪辑到步骤完成，导出仍由你在剪映里处理。

## 环境要求

- Python 3.12+
- `ffmpeg`、`ffprobe` 在 PATH 中
- 已安装 Python 包：`funasr modelscope dashscope requests jieba`
- 已安装 `officecli`（Excel 快照读写；可用 `OFFICECLI_BIN` 指定二进制路径）
- 在 Web“设置”页填写 DeepSeek 或 DashScope API Key；CLI 也支持同名 Windows 环境变量
- 剪映 5.9 草稿根目录和主程序路径存在

可用 `pip install -r requirements.txt` 安装 Python 依赖。

运行环境自检：

```powershell
$env:PYTHONIOENCODING='utf-8'
python realcut_hybrid.py check
```

## DeepSeek 配置（推荐）

字幕审校、价格角色判断和 AI 断句默认优先走 DeepSeek API。Web 用户直接在“设置”页填写；
Key 会用 Windows DPAPI 按当前用户加密，不写入项目或安装目录的配置脚本。CLI 用户也可设置：

```text
DEEPSEEK_API_KEY=你的 DeepSeek API Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

如果账号使用的是其他模型名，例如 `deepseek-flash` 或类似名字，只设置 `DEEPSEEK_MODEL` 即可；
未设置 `DEEPSEEK_API_KEY` 时自动回退 `qwen-plus`。

## 快速开始

### Web 工作台

双击 `Start-RealCutHybridWeb.bat`，或运行：

```powershell
python web_server.py
```

服务默认打开 `http://127.0.0.1:8765`。Web 页面支持：
服务默认监听 `0.0.0.0:8765`，本机访问 `http://127.0.0.1:8765`；同一局域网电脑可访问 `http://<本机局域网IP>:8765`。如需指定监听地址，运行 `python web_server.py --host 0.0.0.0`。首次局域网访问时需在 Windows 防火墙放行 TCP 8765。

- 选择单个视频或素材目录，加入持久化后台队列；Web 重启后会自动恢复未完成任务
- 队列页可开启并行处理，最大 3 个任务同时执行；关闭后回到单任务队列
- 设置页可保存 DeepSeek/DashScope API Key 和 DeepSeek 模型，保存后立即刷新环境预检
- 交接包自带便携剪映 5.9、风格1/风格2及 BGM 6-13；目标电脑无需预装剪映或复制模板缓存
  - 并行适合完整新视频；对同一草稿的续跑/补字幕/重跑阶段任务建议保持单任务，避免同时写同一个剪映草稿
- 查看任务状态、步骤断点、进度和失败原因
- 查看运行日志、Markdown/JSON 报告和字幕复核清单
- 断点续跑、只重跑字幕阶段、从头重跑
- Dry Run 预演、AI 画面识别、音频平滑、字幕复核、BGM/水印/花字/风格/快照模式等常用开关
- 一键“只补字幕空隙”：对已有草稿任务直接跑 `subtitle_gaps`，不重跑前面步骤

Web 服务通过 `realcut_hybrid.py run` 调用同一套 CLI，因此不会绕过已验证的调度

队列状态保存在 `web_queue.json`，包括待办、运行中和并发设置；提交任务时先落盘再入队，所以 Web 进程重启不会再把排队任务丢光。并发上限固定为 1-3，开启后多个任务会各自启动独立剪辑进程。
逻辑；也不会修改 `vendor/real-cut`。

单视频完整处理：

```powershell
python realcut_hybrid.py run "D:\工作空间\素材\你的视频.mp4"
```

默认行为：

- 自动执行步骤 1-6、8、10、音频平滑、11、7、12、字幕空隙补齐；指定 `--style` 后追加风格套用、BGM 归一化、字幕字体统一。
- 步骤 9 花字音效默认关闭。
- 步骤 11 水印默认关闭。
- BGM 默认使用序号 10。
- 音频平滑默认开启，字幕复核清单默认开启；价格角色判断随步骤4自动生成。
- 每个步骤开始前保存轻量 JSON 快照；失败时自动恢复快照并最多重试 2 次。

只打印执行计划，不改草稿：

```powershell
python realcut_hybrid.py run "D:\工作空间\素材\你的视频.mp4" --dry-run
```

使用已有草稿并跳过导入：

```powershell
python realcut_hybrid.py run "D:\工作空间\素材\你的视频.mp4" --draft 28
```

断点续跑：同一命令再执行一次即可。已完成的步骤会跳过，失败步骤会先恢复上次快照再重跑。

```powershell
# 从步骤 4 继续；已有草稿必须存在
python realcut_hybrid.py run "D:\工作空间\素材\你的视频.mp4" --draft 28 --start-from 4

# 只跑到步骤 6，用于调试
python realcut_hybrid.py run "D:\工作空间\素材\你的视频.mp4" --start-from 1 --stop-after 6

# 强制重跑已完成步骤
python realcut_hybrid.py run "D:\工作空间\素材\你的视频.mp4" --force

# 字幕阶段 + 风格后处理重跑（保留原有风格时建议显式 --style）
python realcut_hybrid.py run "D:\工作空间\素材\你的视频.mp4" --draft 28 --phase2 --force --style 风格2
```

批量处理：

```powershell
# 多个视频
python realcut_hybrid.py batch "D:\素材\1.mp4" "D:\素材\2.mp4"

# 扫描目录中的视频
python realcut_hybrid.py batch "D:\素材" --recursive

# 某个失败后继续处理后面的视频
python realcut_hybrid.py batch "D:\素材" --recursive --continue-on-error
```

批次 manifest（每 10 个一组，写 Excel 交接）：

```powershell
# 初始化 manifest；不传 --force 且文件已存在时会拒绝清空
python realcut_hybrid.py manifest manifests\realcut-batch.xlsx --force

# 每 10 个视频一组；每组独立 batch_id，视频状态和异常实时写入 Excel
python realcut_hybrid.py batch "D:\素材" --recursive --continue-on-error \
  --manifest manifests\realcut-batch.xlsx --group-size 10
```

`manifest.xlsx` 固定三张表：`批次`、`视频`、`异常`。视频表按
`batch_id + phase + task_id` 记录状态；异常表记录失败步骤、错误签名、日志尾部。同一
manifest 可以同时承载 `edit / restyle / font / gaps` 四类任务，阶段互不覆盖。

Excel 快照由 `officecli create/batch/close` 生成，JSON 仍是主状态源；
`manifest.xlsx` 只用于 WPS/Excel 和 Claude Code 交接查看。

常用开关：

```text
--draft <路径或名称>       使用已有草稿，跳过步骤 1
--phase2                   只跑字幕阶段 + 音频/字体/BGM 后处理
--start-from <步骤号>     从指定步骤开始
--stop-after <步骤号>     只跑到指定步骤
--bgm 6..13               切换 BGM 序号；0 表示关闭
--smooth-audio            开启音频平滑（默认开）
--no-smooth-audio         关闭音频平滑
--review-subtitles        开启字幕复核清单（默认开）
--no-review-subtitles     关闭字幕复核清单
--visual-match            开启 AI 画面识别（默认开）
--no-visual-match         跳过抽帧和视觉模型，按字幕时间轴快速配画
--enable-flower-text      开启步骤 9 花字音效
--watermark               开启步骤 11 水印
--style <风格名>          完成后套用风格模板
--snapshot-mode json      轻量快照（默认，只保存 JSON/TXT 等）
--snapshot-mode copy      完整目录快照（更稳，但更占空间）
--max-attempts N          单步最大尝试次数，默认 2
--fresh                   忽略旧状态，重新开始
--force                   已完成的步骤也重跑
--continue-on-error       batch 中某个视频失败后继续
--no-close-jianying       不要自动关闭剪映（步骤 7/12 仍会检查）
--no-restore              续跑失败步骤时不自动恢复快照
--dry-run                 只打印计划，不执行脚本
```

## 四类完整流程

当前置顶四个会话对应以下四类任务，都已经收成正式子命令：

1. real-cut 全流程 + 风格1：`batch`
2. 风格1转风格2 + 镜像重排：`restyle`
3. 字幕统一为风格2圆体：`force-font`
4. 字幕空隙补满：`fill-gaps`

```powershell
# 全流程（edit）
python realcut_hybrid.py batch "D:\素材库" --recursive --group-size 10 \
  --manifest manifests\realcut-batch.xlsx --continue-on-error

# 成品草稿：风格2 + 首段保留、后续视频段随机重排
python realcut_hybrid.py restyle 32 33 34 --style 风格2 \
  --manifest manifests\realcut-batch.xlsx --group-size 10

# 强制字幕字体为风格2模板字体
python realcut_hybrid.py force-font 131 132 133 --style 风格2 \
  --manifest manifests\realcut-batch.xlsx --group-size 10

# 先检查字幕空隙；去掉 --check 才是写盘
python realcut_hybrid.py fill-gaps 32 33 34 --check \
  --manifest manifests\realcut-batch.xlsx --group-size 10
```

这些命令都接受草稿路径、草稿编号或含 `draft_content.json` 的目录；重复执行时由
manifest/state 判断进度，不再需要每个会话重写一套批量脚本。

## 字幕质量修复

实验版步骤7先做领域词表/人工覆盖，再用 DeepSeek 做受限审校（没有 DeepSeek key 时回退
qwen-plus）。审校不允许增删句子、
改变顺序、改价格数字，AI 保真度低于 85% 时回退词表结果。每次生成：

- `draft/subtitle_review.json`：结构化复核清单，Web 和报告中可读
- `draft/subtitle_review.md`：Markdown 复核清单

`subtitle_review.json` 会记录 `ai_provider`（如 `deepseek:deepseek-chat` 或
`qwen:qwen-plus`）。完整语音轨的 ASR 结果会先做本地词表修正，再交给
同一个受限审校流程修错别字。

可维护词表：

- `config/subtitle_glossary.json`：`preserve` 保护词、`replace` 硬替换、`suspicious` 疑似词
- `config/subtitle_overrides.json`：人工 `from -> to` 覆盖，可记录确定修正后重跑

默认保护 `天丝、桑蚕丝、莱赛尔、开骨、全包边、内衬、饰品` 等；`小屁莲/金工/拿开骨全包`
这类不确定项只进可疑清单，不自动乱改。

## 音频质量修复

- 步骤4按新音频结构排序：原价句和上车价句放开头，其余非废话按原视频时间顺序保留，
  金句放最后；30 秒裁剪也会保持这个顺序，优先从金句前的尾部截断。
- 价格角色由 DeepSeek 读取完整 ASR 字幕后写入 `draft/price_roles.json`；LLM 不可用时用
  价格数值/关键词回退。
- 金句只保留原视频 ASR 分类出的金句，不再从外部素材库补充；步骤4也不再从素材库补
  爆点/价格口播。镜像/倒放补位只补画面，使用静音音轨，避免不同人物视频混入老板姐口播。
- 步骤5淡入淡出改为 60ms，减少短片段一顿一顿的听感。
- `audio_smooth.py` 在人声片段上做 EBU R128 响度归一化到 `-16 LUFS`，增益上限
  `±12dB`，加 true-peak 限幅；相邻且各自低于 1.3 秒的展示衣服段合并，合并后不超过
  3 秒。处理前会把原始 clip 备份到 `draft/.audio_smooth_backup/`。
- `bgm_normalize.py` 把模板 BGM 压到 `-20dB`（音量 0.1），并加 300ms 首尾淡入淡出。
- v1 不做自动 BGM 闪避，因为本地剪映 5.9 草稿还没有已验证的音量关键帧/自动闪避结构。
  先通过人声归一化 + BGM 压低 + 短淡入淡出解决主体问题。

## 字体修复

`font_unify.py` 只处理动态字幕轨 `flag=1` 的 subtitle 素材，把字体统一为风格模板或
草稿中多数动态字幕使用的字体；不修改 `flag=0` 的风格固定文字/贴纸元素。

## 字幕空隙补齐

`fill_subtitle_gaps.py` 在全部字幕/风格处理完成后自动运行，把动态字幕轨 `flag=1` 的
subtitle 段从 0 铺到草稿总时长，相邻字幕首尾相连；不修改 `flag=0` 的风格固定文字。
每次生成 `draft/subtitle_gaps_report.json`，记录补前空隙和实际修改段，Web/CLI 可复核。

## 两套方式怎么区分

- **Web 工作台和旧会话**：不传 `--run-root`，继续使用项目根目录的
  `state/ logs/ reports/ snapshots/ manifests/`。`web_server.py` 目前也只读这套根目录。
- **Claude CLI 独立剪辑**：每次运行必须传 `--run-root runs/<名称>`。该名称下的
  `state/ logs/ reports/ snapshots/ manifests/` 全部独立，Claude 子批次也会自动带同一个
  `--run-root`，所以每组新开会话不会去读 Web/旧会话的状态。
- **其他独立项目**：`D:\ai-edit-studio` 是另一套项目，当前直接处理剪映草稿 `161-190`，
  使用 `C:\Users\JT\.codex\skills\real-cut\scripts`，不读写本项目的 `runs/` 和根目录交接文件。
- **本次已归档的实测批次**：已移到独立项目 `C:\Users\JT\Documents\ChatGPT\realcut-claude-cli\runs\cc-cli-jingjian-20260821`，里面包含
  `manifests/jingjian-all.xlsx`、`claude-sessions/` 和 `batch-logs/`，和项目根目录的
  `manifests/jingjian-all.xlsx` 不是同一份数据。

## Claude Code 批次生命周期

推荐不要把 Claude 当成一个普通剪辑引擎逐视频编脚本，而是让每个 Claude 会话负责一组
确定性 CLI 任务：会话读取 manifest，执行调度命令，失败时读 `logs/` 和 `reports/` 修复，
完成后非交互退出。这样每 10 个一组新开会话，上下文不会被前面批次拖垮。

```powershell
# 先用 dry-run 查看会生成哪些提示词和命令；目录和 manifest 都在独立 run-root 下
python realcut_hybrid.py claude "D:\素材库" --recursive --mode edit \
  --run-root runs\claude-20260821 \
  --manifest runs\claude-20260821\manifests\realcut-batch.xlsx \
  --group-size 10 --max-budget-usd 5 --continue-on-error --dry-run

# 实际执行：每组启动一个 claude -p 非交互会话，处理完自动关闭
python realcut_hybrid.py claude "D:\素材库" --recursive --mode edit \
  --run-root runs\claude-20260821 \
  --manifest runs\claude-20260821\manifests\realcut-batch.xlsx \
  --group-size 10 --max-budget-usd 5 --continue-on-error
```

刚才的素材目录实测命令（每组 10 个，处理完成自动接力下一组）：

```powershell
python realcut_hybrid.py claude "D:\工作空间\精剪\素材" --recursive --mode edit `
  --run-root runs\jingjian-20260821 `
  --manifest runs\jingjian-20260821\manifests\jingjian-all.xlsx `
  --group-size 10 --max-budget-usd 5 --continue-on-error
```

`--mode` 可选 `edit / restyle / font / gaps`，对应上面的四类任务。每个会话的提示词和
输出保存在 `runs/<名称>/logs/` 下（`claude_*.md` 和 `claude_*.out.log`）。Claude 被明确
禁止修改 `vendor/real-cut`，也禁止做剪映窗口 UI 自动化。

`batch --dry-run` 只打印计划，不写 `state/`、`reports/` 或 manifest；Claude 实际会话
会前台同步运行批次命令并等待 `批次结束` 后再返回摘要，避免把 dry-run 当成真实完成。

## 状态与恢复规则

- 每个源视频按绝对路径生成固定 `task_id`，状态保存在 `state/<task_id>.json`。

- 视频文件变化后，调度器会识别并新建状态；`--fresh` 可强制重置。
- 步骤状态：`pending / running / completed / failed / skipped`。
- 失败重试前会恢复该步骤开始前的快照；相同错误签名不会无限重试。
- 步骤 7/12 属于字幕阶段，运行前会先关闭剪映，避免剪映内存副本覆盖草稿。
- 报告生成在 `reports/<task_id>.md` 和 `reports/<task_id>.json`。

## Web 接口

本地服务提供以下主要接口，方便后续继续复用 LiveClipAgent 风格前端：

```text
GET  /api/bootstrap
GET  /api/tasks
GET  /api/tasks/<id>
GET  /api/tasks/<id>/log
GET  /api/tasks/<id>/report
GET  /api/tasks/<id>/subtitle-review
POST /api/run
POST /api/batch
POST /api/browse
POST /api/check
POST /api/tasks/<id>/resume
POST /api/tasks/<id>/cancel
```

## 当前边界

- `vendor/real-cut` 是原样副本，脚本里的剪映路径、关键词库、素材库、模板库路径都是硬编码。
- `vendor/experimental/scripts` 是当前活跃引擎；上游 real-cut 更新后需要重新复制并重打实验补丁。
- 本调度器不自动导出 MP4；UI 自动导出是 LiveClipAgent 最不稳定的部分，因此不并入。
- `json` 快照只回滚草稿关键 JSON/TXT 文件；如果需要连生成的音频/视频素材一起回滚，
  请使用 `--snapshot-mode copy`。
- 若需要更进一步的 BGM 自动闪避，需要先手工做一份闪避草稿样例，验证剪映 5.9 的
  音量关键帧结构后再脚本化。
- Web 工作台目前仍直接读 `state/` 和 `reports/`，尚未把 manifest 作为唯一调度入口；
  下一轮可把 `/api/batch` 接到 `batch/restyle/force-font/fill-gaps` + 同一 manifest。
- Web 工作台目前仍直接读项目根的 `state/` 和 `reports/`；Claude CLI 独立批次必须使用
  `--run-root`，不要为了复用 Web 前端而把 `web_server.py` 指向 `runs/` 下的状态。

## 编译交接包

`packaging/build_handover.ps1` 使用 Nuitka multidist 把 Web、CLI 和全部剪辑步骤编译成
共享运行目录，再复用已验证部署包中的第三方 Python 依赖、FunASR 模型、FFmpeg、剪映、
OfficeCLI 和素材。交付目录不包含 RealCut Hybrid 自有 Python 源码。

```powershell
.\packaging\build_handover.ps1 `
  -RuntimeSource ..\RealCutHybrid_Deploy_20260826 `
  -Version 2026.08.28
```

构建产物位于 `dist/RealCutHybrid-Handover-<版本>/`，Inno Setup 分卷安装包位于
`dist/installer/`。详细使用和代码保护边界见 `packaging/README_HANDOVER.md`。
