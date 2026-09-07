# RealCut Hybrid 火山 ASR 工作交接

更新时间：2026-09-07（Asia/Shanghai）

> **RC5 未签名预发布版（2026-09-07）**：已从当前源码重新编译
> `2026.09.05-volc-asr-rc5` 完整离线包，包含 15-45 秒连续原声、禁止静音
> `mirror_fill`、步骤4/6/7性能修复、安装器严格校验和 Web 安全加固。源码单元测试
> 72/72、源码环境检查16/16、编译包与全新静默安装后的环境检查均为17/17；安装器外层
> 5个交付文件哈希全部通过。由于本机没有代码签名证书，`Setup.exe` 仍为 `NotSigned`，
> 将仅作为 GitHub prerelease 发布；火山 API Key 和 AK/SK 的控制台轮换仍须由交付人完成。
> GitHub 仓库当前为公开仓库，推送后的源码可被任何人获取。

RC5 交付包：

```text
dist\RealCutHybrid-Handover-2026.09.05-volc-asr-rc5
dist\installer\RealCutHybrid-2026.09.05-volc-asr-rc5-Setup.exe
dist\installer\RealCutHybrid-2026.09.05-volc-asr-rc5-Setup-1.bin
dist\installer\RealCutHybrid-2026.09.05-volc-asr-rc5-Setup-2.bin
dist\installer\SHA256SUMS.txt
dist\installer\Verify-RealCutHybrid.cmd
dist\installer\Verify-RealCutHybrid.ps1
```

> **RC4 状态更新（2026-09-04）**：本文第 1-13 节保留的是最初审查现场，
> 其中“尚未修复/尚未打包”已不再代表当前状态。以下状态更新优先于后文。

> **后续源码加固（2026-09-05）**：在 RC4 之后新增安装器严格校验脚本、双击核验入口、
> 可选 Authenticode 签名和 `-Release` 正式构建门禁。门禁要求构建人明确确认已轮换泄露凭据，
> 且正式包必须完成签名与哈希复验。Web 默认监听由 `0.0.0.0` 收紧为 `127.0.0.1`，写接口
> 增加请求标记、同源校验和 DNS 重绑定防护。现有 RC4 产物未重打，仍为未签名且默认开放
> 局域网监听的内部候选包，不包含 2026-09-05 的发布与 Web 安全加固。

> **有声时长策略修复（2026-09-05）**：步骤4及后续补位已改为 15-45 秒的连续原声策略。
> 核心内容不足时回捞合规原声和闲聊，禁止静音 `mirror_fill`、重复人声或外部主播音频补时长；
> 原视频确实不足 15 秒有效口播时明确失败。草稿 20、27、39 已用当前源码完整重建或重跑并
> 验证通过。现有 RC4 安装器没有重打，因此不包含本次时长策略修复。

## 0. RC4 当前状态

已在未提交的工作区修复：

- 火山多字符 token 时间戳对齐。
- ASR 缓存按请求引擎隔离，并保存请求/实际引擎与后端版本。
- 火山失败显式回退 FunASR，断点续跑和重试保留引擎。
- 违禁价格句统一过滤，不再被价格角色或画面复核重新加回。
- 火山凭据通过 Windows DPAPI 管理，Web 只显示配置状态，不回显明文。
- TOS 临时对象在成功或失败后都尝试删除。
- 静音净化改为默认关闭的可选功能；全音频仅扫描一次，支持边界裁剪、低语音比删除及 JSON 报告。
- Web 队列增加跨进程所有权锁，且在 HTTP 端口绑定后才初始化队列。
- 历史提交误改的五个 `vendor/real-cut/scripts` 文件已恢复为 `main` 原样。
- 交接包不再保留 `ai_edit_studio` editable 开发元数据；无论通过启动脚本还是直接运行编译入口，外部 Python 运行时都不再生成 `.pyc`。

验证结果：

- Python/JavaScript 语法检查、`git diff --check` 通过。
- `python realcut_hybrid.py check`：16/16 通过。
- 单元测试：24/24 通过，含直接启动编译入口不落盘字节码的行为测试。
- 真实 TOS 上传/删除和火山识别通过；账户未开通极速档，已正确回退火山标准档。
- RC4 编译包环境检查 17/17 通过；21.87 秒中文验收音频得到 6 句、76 个字级时间戳，实际引擎为 `volc`，第二次 74ms 命中缓存。
- RC4 包内 36,708 个 payload 文件全部在内部 SHA-256 清单中且哈希一致；无额外文件、`.pyc`、editable 元数据、明文凭据或项目 Python 源码。
- 安装器在全新本地目录静默安装成功；安装后环境检查 17/17，隔离配置完成 DPAPI 保存、重启解密和清除验收，响应与磁盘均无明文。
- 新版 Web 已在 `127.0.0.1:8765` 启动：页面返回 200、环境检查 16/16、
  火山五项配置完整，且第二实例被队列所有权锁正确拒绝。

RC4 最终交接包：

```text
dist\RealCutHybrid-Handover-2026.09.04-volc-asr-rc4
dist\installer\RealCutHybrid-2026.09.04-volc-asr-rc4-Setup.exe
dist\installer\RealCutHybrid-2026.09.04-volc-asr-rc4-Setup-1.bin
dist\installer\RealCutHybrid-2026.09.04-volc-asr-rc4-Setup-2.bin
dist\installer\SHA256SUMS.txt
```

正式对外交付前仍需：

1. 由于真实凭据曾出现在对话中，必须先在火山控制台轮换 API Key 和 AK/SK，再通过 Web 设置页录入新值。
2. 将 `Setup.exe`、全部 `.bin` 和 `SHA256SUMS.txt` 同目录交付，接手电脑先核对 SHA-256 再安装。本机全新目录已验收，仍建议在实际接手电脑复验一次。
3. 当前安装器未做 Authenticode 签名，Windows 可能出现 SmartScreen 提示；如用于正式组织分发，应配置代码签名。
4. 本轮未提交、未合并 `main`、未推送、未发布正式版。

## 0.1 有声时长修复与实草稿验收

用户发现草稿 20、27、39 的时间线上出现大段 `mirror_fill_*.wav`，画面继续播放但口播完全
无声。截图与草稿数据确认这些 WAV 不是导出或播放器故障，而是旧补位脚本主动生成的全零音频。

同时确认了四个放大问题：

- 步骤4曾直接删除所有 `<1s` ASR 句子，短口播和承接词大量丢失。
- LLM 分类只要覆盖约 70% 就被接受，漏分类句子不会进入后续候选。
- 原价/上车价重新分桶后又被通用清桶逻辑删除；款号 `2771170K`、`90560G` 还会被误识别为价格。
- 镜像和开盒补位只延长画面，没有配套原声，最终只能用静音音轨填满时间线。

当前源码行为：

- 相邻短句按最多 400ms 间隔、6.5 秒跨度合成完整口播单元，不再因为单句短于 1 秒而删除。
- 补齐 LLM 漏分类并去重，价格角色重新分桶后不会再次丢失。
- 款号子句从价格分析中剔除，但同一口播单元后面的真实报价仍保留；中文逗号按口播停顿处理。
- 成片范围固定为 15-45 秒。结构内容不足时回捞未使用合规原声，闲聊最后使用；超过 45 秒
  只删除完整口播单元，不截断半句话。
- `mirror_通用.py` 和 `步骤4后-开盒补位.py` 保留为兼容 no-op，只检查，不写轨道或延长时长。
- 步骤4输出 `duration_policy_report.json`；调度器在步骤4、镜像和开盒之后验证总时长、主口播
  连续覆盖、音频与元数据一一对应，并拒绝任何 `mirror_fill` 引用。
- 步骤10的短 BGM 会循环铺满到时间线末尾；步骤9音效不得越过当前口播段或草稿结尾。
- 本机已把失效的 DeepSeek 模型名 `deepseek-flash` 迁移为接口当前支持的
  `deepseek-v4-flash`；DeepSeek 返回不可重试的 4xx 时立即回退千问，不再重复无效请求。

2026-09-05 实草稿验收结果：

| 草稿 | 最终时长 | 主口播 | 字幕 | `mirror_fill` 文件/引用 | 口播响度检查 |
|---|---:|---:|---:|---:|---|
| 20 | 16.912s | 5 段，0 到结尾连续 | 18 段 | 0 / 0 | 每段均有声，mean -17.7 至 -20.6dB |
| 27 | 16.137s | 4 段，0 到结尾连续 | 16 段 | 0 / 0 | 每段均有声，mean -19.5 至 -20.7dB |
| 39 | 15.040s | 5 段，0 到结尾连续 | 12 段 | 0 / 0 | 每段均有声，mean -18.6 至 -21.9dB |

27、39 的重跑前完整备份位于：

```text
C:\Users\JT\Documents\ChatGPT\搽屁股\_jianying_backups\voiced_duration_fix_20260905_161000
```

草稿20旧事故报告也已另存到该目录的 `20_pre_rebuild_reports`。20 原草稿目录曾被外部删除，
已从原始 `20.mp4` 按原配置重新导入、火山识别并完整生成。

本次源码回归：50/50 `unittest` 通过，`realcut_hybrid.py check` 16/16 通过，`py_compile` 与
`git diff --check` 通过。没有提交、合并、推送、发布或重打安装器。

## 0.2 性能回归定位与修复

2026-09-05 实际批量运行发现，有声时长修复后的首批任务明显变慢。对 7 个同源视频的旧/新
报告严格配对后，新流程总耗时从 2115.31 秒增加到 4992.32 秒，约为 2.36 倍；其中步骤4
约为 4.01 倍、步骤6约为 1.75 倍、步骤7约为 3.85 倍。现场采样 CPU 约 7%、磁盘约 1%、
内存仍余约 12.9GB，瓶颈不是本机算力，而是云端请求等待和错误缓存失效。

根因：

- 成片从旧的约 30 秒扩展到 15-45 秒后，字幕句子更多；步骤7原先先做一次整段审校，随后
  又对每个 ASR 句子串行调用一次 DeepSeek 断句，单条视频常有 22-30 次请求。
- 本机 DeepSeek 模型从失效的 `deepseek-flash` 改为可用的 `deepseek-v4-flash` 后，不再快速
  400 回退 Qwen，而会真实等待接口响应；并发 3 时三个任务会同时争用云接口。
- 步骤4曾逐个用 Qwen-VL 复核所有废弃候选，即使已有足够时长和服装展示内容也照常调用。
- 步骤6曾因 `step4_segments.json` 更新而删除 `_frame_full_cache_1s.json`，但该缓存只依赖
  源视频帧，与步骤4排序无关；一次错误失效会把约 0.17 秒的缓存命中变成数分钟全视频扫描。

当前源码已修复：

- 步骤4只有在合规核心口播不足 15 秒，或完全没有“展示衣服”段时才运行视觉捞回；候选最多
  6 个，并优先补足时长及靠近已选上下文的片段。
- 步骤4会先复用当前草稿或同源兄弟草稿的 1 秒画面缓存；明确标签可直接判定，只有缓存缺失
  或模糊的候选才请求 Qwen-VL。
- 步骤6缓存改为按源视频大小、mtime、首尾快速哈希、抽帧间隔和 VL 模型校验，不再受步骤4
  文件更新时间影响；换风格生成 `20_1`、`27_1` 等新草稿时也能复用同源草稿缓存。
- 步骤6在 DashScope 返回欠费、无效 Key、401/403 或明确权限错误时首帧熔断，立即回退原
  位置，不再继续请求剩余几十到上百帧；全空结果不会写入或复用缓存，少数偶发空帧不影响
  其余有效标签缓存。
- 步骤7把整段审校、每句不超过 10 字的断句和关键词提取合并为一次批量 LLM 请求，完整语音
  轨路径不再逐句请求。
- 步骤7可按 `index` 接收 Qwen 乱序、漏项或部分返回；只有缺失或无效的单句使用本地断句
  回退，不再因一个坏项废弃整批结果或重新发起整批云端请求。
- 步骤4分类、价格角色识别和步骤7批量字幕请求均将 DeepSeek 单次等待限制为 30 秒且不内部
  重试；超时立即回退 Qwen。原有数字、违禁词、保护词和文本保真度校验仍保留。
- 15-45 秒连续原声、允许闲聊补足、禁止 `mirror_fill` 静音补位的质量规则保持不变。

真实队列验证：

- 草稿 `20_1` 的步骤6从同源草稿复用缓存，只耗时 0.46 秒；同一视频此前完整扫描约 53 秒。
- 草稿 `27_1`：步骤4 53.16 秒、步骤6 0.42 秒、步骤7 59.27 秒，整条任务约 2 分 02 秒；
  步骤7在 DeepSeek 30 秒超时后立即回退 `qwen-plus`，只进行一次批量字幕请求。
- 第一个完整加载步骤4快速回退参数的任务 28，步骤4耗时 38.70 秒。
- 17:40 后启动步骤7的草稿 31、30、24 已确认加载批量字幕代码，耗时分别为 64.42、73.00、
  74.96 秒，平均 70.79 秒；对比修复前 7 条平均 332.48 秒，下降 78.7%，约快 4.70 倍。
  与三个同视频旧正常任务的平均 83.52 秒相比也快 15.2%。三条均一次执行成功；其中一条
  批量响应整体不可解析后使用本地断句完成，没有再次整批请求。
- 新源视频首次运行时，步骤6仍是主要固定成本：32、34、36号分别对93、101、48帧串行调用
  Qwen-VL，共242次请求。720宽JPEG和原尺寸高质量JPEG虽然将平均单帧延迟从3.47秒降至
  1.66秒和1.29秒，但32帧A/B标签一致率仅78.12%和87.50%，未达到95%质量门槛，因此未
  上线有损压缩或降低采样频率。批量运行建议最大并发设为2；3属于云接口压力档。

本轮性能源码回归：72/72 `unittest` 通过，`realcut_hybrid.py check` 16/16 通过，相关脚本
`py_compile` 与 `git diff --check` 通过。运行中的 Web 队列未停止或重启；没有提交、合并、
推送、发布或重打安装器。

## 1. 交接目标

这份文档供一个完全没有前文上下文的新 Codex 窗口使用。

当前工作是审查 `feat/volcengine-asr` 分支中参考 ChatCut 增加的火山引擎 ASR、静音过滤及违禁词修复，判断这些改动是否适合合并、打包和交接给其他电脑使用。

当前只完成了代码审查和只读验证，尚未修复代码、合并 `main`、重新打安装包或发布 GitHub Release。

## 2. 用户真实诉求

- RealCut Hybrid 是用户准备离职后交给后续人员使用的剪映自动剪辑系统。
- 用户希望以编译后的安装包交接，尽量不暴露或让别人直接修改 Python 源码。
- 安装包必须能在别的 Windows 电脑上部署，并能在 Web 页面配置 API Key。
- 用户发现 ChatCut 的火山引擎 ASR 对中文、数字和价格识别更准，因此新增了可切换的火山 Seed-ASR。
- 用户当前要求先审查改动是否有正面影响，不是立即合并或发布。

## 3. 仓库与 Git 状态

工作区：

```text
C:\Users\JT\Documents\ChatGPT\搽屁股\RealCutHybrid
```

Git 根目录：

```text
C:\Users\JT\Documents\ChatGPT\搽屁股
```

远程仓库：

```text
ssh://git@ssh.github.com:443/faiyaof/realcut-hybrid-versions.git
```

当前分支及提交：

```text
feat/volcengine-asr
4ca5af1 Fix banned-word filter so visual check cannot resurrect sensitive segments
5a023b0 Add change notes for Volcengine ASR and silence pruning
3bcad03 Add Volcengine ASR backend and silence-aware segment pruning
```

基线：

```text
main / origin/main / tag v2026.08.31.1-handover
ae29f2f Add timeline-only visual matching mode
```

当前分支已推送到：

```text
origin/feat/volcengine-asr
```

跟踪文件没有未提交修改。Git 根目录有两个与本任务无关的未跟踪项：

```text
_jianying_backups/
restore_style5_template.py
```

不要删除、移动、还原或提交这两个项目；它们可能是用户的本地备份。

## 4. 代码实际运行路径

主控 `realcut_hybrid.py` 当前明确使用：

```text
vendor/experimental/scripts
```

相关位置：

```text
realcut_hybrid.py:47-49
packaging/build_handover.ps1:26
packaging/deploy_env.bat:22
```

`vendor/real-cut/scripts` 是另一份副本，目前不由交接安装包主控执行，但它已经与 `experimental` 发生漂移，不能把两套文件视为完全一致。

## 5. 本分支做了什么

相对 `main` 共改动 16 个文件，约新增 1360 行：

1. 新增 `vendor/experimental/scripts/_volc_asr.py`，通过 TOS 上传音频并调用火山 Seed-ASR。
2. 在步骤3增加 `--engine volc`。
3. 在主控增加 `--asr-engine {funasr,volc}`。
4. Web 新建任务弹窗增加 FunASR/火山选择框。
5. 新增 `_trim_segments.py`，步骤4按音量和静音占比删除低质量片段。
6. 修改违禁词过滤，防止部分句子被视觉复核重新捞回。
7. `vendor/real-cut/scripts` 下也复制了大部分实现。
8. 新增 `docs/CHANGES-volc-asr-and-silence-pruning.md`。
9. `.gitignore` 忽略 `**/asr_volc.env`，避免把凭证提交到 Git。

## 6. 审查结论

技术方向值得保留，火山 ASR 对中文口播、价格数字和短句断句确实优于当前 FunASR。但当前实现不是纯正面改动，存在多个发布阻断问题，暂不应合并到 `main` 或生成正式安装包。

### 6.1 阻断：多字符 token 导致句子时间戳错位

文件：

```text
vendor/experimental/scripts/_volc_asr.py:204-243
```

`_split_utterance()` 遍历句子中的每个字符，却每遇到一个非标点字符就消费一个火山 `word`。实际火山 `word.text` 不一定是单字，可能是：

```text
72
379
准备好了
```

因此一个多字符 token 会被当成一个字符，后面的时间戳整体错位。下游步骤4按错误边界切音频，步骤7也可能生成错位字幕。

真实样本：

```text
C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\2_2\asr_result.json
```

该样本有 416 个 API word、4 个多字符 token、79 个句子，其中 4 个句子边界已确认错误。例如：

```text
“衣长是72，”
记录结束：27420ms
按 token 对齐应结束：27260ms

“准备好了吗？”
记录开始：27420ms
按 token 对齐应开始：27300ms
```

### 6.2 阻断：ASR 缓存没有区分识别引擎

文件：

```text
vendor/experimental/scripts/步骤3-FunASR.py:118-138
vendor/experimental/scripts/步骤3-FunASR.py:179
vendor/experimental/scripts/步骤3-FunASR.py:196-218
```

缓存指纹只有音频文件名、大小和 mtime，没有 `engine`。`asr_result.json` 也不保存请求引擎或实际使用引擎。

结果是已有 FunASR 缓存时，即使传入 `--engine volc`，步骤3仍会直接复用 FunASR 结果，界面看起来选择了火山，实际没有发起火山识别。

已用临时目录复现：传入 `engine='volc'` 后，识别函数调用记录仍为空，保存结果中的 `engine` 也是空。

### 6.3 阻断：Web 断点续跑和重试会丢失火山选择

文件：

```text
realcut_hybrid.py:722-749
web_server.py:1023-1041
web/app.js:348-376
```

任务 state 只保存了 `visual_match`，没有保存 `asr_engine`。Web 的“断点续跑”发送空 options，“重新执行”也只发送 `fresh/force`。

因此原火山任务失败后点击继续或重试，会恢复成默认 FunASR。即使显式强制重跑步骤3，还会同时遇到上一条缓存问题。

### 6.4 阻断：违禁价格句仍可重新进入成片

文件：

```text
vendor/experimental/scripts/步骤4-切割排序.py:142-161
vendor/experimental/scripts/步骤4-切割排序.py:413-440
vendor/experimental/scripts/_price_roles.py:75-138
```

最新提交已经把违禁词检查应用到 LLM 分类和视觉捞回，这是正确修复。但随后 `detect_price_roles(sentences)` 又扫描全部原始句子，并把识别出的原价/上车价索引重新加入 `grouped`。

`_price_roles.py` 不知道哪些句子已经因违禁词被丢弃。已验证单句“南沙港仓库原价599元，上车379元”仍会返回 `(0, 0)`，随后被重新放回价格结构位。

### 6.5 阻断：交接安装包没有火山凭证配置入口

文件：

```text
runtime_settings.py:16-24
runtime_settings.py:148-270
web/index.html:107-134
vendor/experimental/scripts/_volc_asr.py:29-69
```

火山实现需要以下五项：

```text
VOLCENGINE_API_KEY
VOLCENGINE_ACCESS_KEY_ID
VOLCENGINE_SECRET_ACCESS_KEY
VOLCENGINE_TOS_BUCKET
VOLCENGINE_TOS_REGION
```

Web 设置页和 Windows DPAPI 当前只管理 DeepSeek、DashScope。安装包也不会复制被忽略的 `asr_volc.env`。虽然高级用户可以手工在安装根目录创建该文件或设置 Windows 环境变量，但交接用户在页面上选火山后只会看到任务失败。

环境检查也没有显示火山凭证是否完整、网络是否可用或对应资源是否开通。

### 6.6 中等风险：文档声称自动回退 FunASR，实际步骤3不会

文件：

```text
vendor/experimental/scripts/_funasr.py:81-99
vendor/experimental/scripts/步骤3-FunASR.py:140-157
docs/CHANGES-volc-asr-and-silence-pruning.md:90-101
```

`_funasr.recognize_audio(engine='volc')` 实现了火山失败后回退 FunASR，但步骤3没有使用该入口，而是直接调用 `_volc_asr.recognize_audio()`。

因此缺凭证、网络失败、额度不足、两档模型都未开通或接口超时都会导致步骤3失败。当前只有火山极速档未开通时回退火山标准档，不能回退本地 FunASR。

### 6.7 中等风险：TOS 音频对象不会清理

文件：

```text
vendor/experimental/scripts/_volc_asr.py:104-116
vendor/experimental/scripts/_volc_asr.py:280-302
```

每次识别都会上传到：

```text
realcut-asr/<uuid>.<format>
```

预签名 GET URL 一小时后失效，但桶里的对象不会随 URL 失效而删除。代码没有 DELETE、`finally` 清理或生命周期策略校验，会形成录音留存、隐私和存储费用风险。

### 6.8 中等风险：静音过滤无条件影响旧 FunASR 流程

文件：

```text
vendor/experimental/scripts/_trim_segments.py:28-130
vendor/experimental/scripts/步骤4-切割排序.py:453-467
```

即使用户不选择火山，步骤4也会无条件启用静音净化，所以“默认仍是 FunASR”不等于旧流程行为不变。

当前每个候选段至少会：

1. 重编码一个临时 MP3。
2. 再运行一次 ffmpeg `volumedetect`。
3. 再运行一次 ffmpeg `silencedetect`。

N 个片段约产生 `1 + 3N` 个 ffmpeg 进程，结构位补候选时还会继续增加。其他电脑本来就偏慢，这会进一步拖慢步骤4。

此外代码只会删除整个句子，并没有实现模块注释所说的“收缩到有效语音边界”。相对全局低 6dB 的真实轻声口播也可能被整句误删。

### 6.9 次要问题：两套 vendor 副本已发生漂移

文件：

```text
vendor/real-cut/scripts/步骤3-FunASR.py:249-262
vendor/real-cut/scripts/步骤4-切割排序.py
```

`vendor/real-cut` 的步骤3仍默认 `engine='volc'`，与文档“默认一律 FunASR”矛盾；最新违禁词补丁也只修改了 `experimental`。虽然当前安装包不执行它，但直接使用该副本或以后切换路径会出现不同结果。

`_trim_segments.clean_ordered_segments()` 的返回注解写成 `list[dict]`，实际返回 `(kept, dropped)`；文件底部自检把 tuple 当列表使用，因此自检结果不可信。主流水线正确解包，不影响当前生产调用。

## 7. 已确认的正面影响

- 火山 Seed-ASR 在现有真实视频上已经成功运行。
- 火山对中文数字、价格、短句断句的识别明显优于本地 Paraformer/FunASR。
- Web -> `web_server.py` -> 主控 -> 步骤3的参数传递已经接通。
- 主安装路径 `vendor/experimental` 的默认识别引擎仍为 FunASR。
- 火山极速档未开通时回退火山标准档已经工作。
- 最新提交把 LLM 分类和视觉捞回两条路径的违禁词过滤补得更完整，方向正确。
- Git 跟踪内容中没有发现真实火山密钥，只有空白示例和环境变量名称。

## 8. 已完成验证

已经运行：

```powershell
python -m py_compile <本分支改动的 12 个 Python 文件>
python -m unittest discover -s tests -v
git diff --check main...HEAD
```

结果：

```text
12 个 Python 文件语法编译通过
3 个现有单元测试全部通过
git diff --check 通过
```

现有测试只有：

```text
tests/test_visual_match_switch.py
```

它只覆盖关闭画面识别的功能。当前没有测试覆盖：

- 火山响应归一化。
- 多字符 token。
- ASR 引擎缓存隔离。
- 火山失败回退。
- Web 断点续跑保留引擎。
- TOS 清理。
- 静音过滤误删及性能。
- 价格角色重新引入违禁句。

## 9. 推荐修复顺序

### 第一批：合并阻断

1. 重写火山 token 归一化。
   - 不要按“一个 token 等于一个字符”推进。
   - 按 token 文本长度展开字符时间戳，或用累计字符偏移映射句子边界。
   - 数字、英文品牌和多字符中文 token 都必须覆盖。
   - 对重复字符不能使用 `str.index(char)` 计算位置。

2. 给 ASR 缓存增加元数据。
   - 至少保存 `requested_engine`、`actual_engine`、后端版本。
   - 缓存命中必须同时比较音频指纹和识别引擎。
   - 老缓存没有 engine 时应视为 FunASR 或直接失效一次，不能当成火山结果。

3. 保存任务的 `asr_engine`。
   - `run_task()` 写入 state。
   - Web resume/retry 默认继承 state 中的选择。
   - 任务详情和报告显示请求引擎、实际引擎以及是否发生回退。

4. 统一违禁词检查。
   - 抽成单一 `contains_banned_text()` 或 `is_allowed_sentence()`。
   - LLM 分类、fallback、视觉捞回、价格角色识别、结构补位全部调用同一检查。
   - 更稳妥的做法是只把允许的 sentence indices 传给价格检测器。

5. 补齐交接端凭证设置。
   - 把火山 API Key、AK、SK、Bucket、Region 加入 DPAPI 设置。
   - Web 不回显明文，只显示已配置/未配置。
   - 环境检查增加完整性和资源可用性检查。
   - 未配置时禁用火山选项或在提交任务前明确阻止。

### 第二批：可靠性与隐私

6. 接通真实回退。
   - 步骤3统一走一个识别入口。
   - 火山失败时根据明确策略回退 FunASR。
   - 日志和 state 必须记录回退，不能静默伪装成火山成功。

7. 删除 TOS 临时对象。
   - 上传函数同时返回对象 key。
   - 识别在 `finally` 中尝试 DELETE。
   - TOS 桶另设短周期生命周期规则作为兜底。

8. 把静音净化做成独立开关。
   - 建议默认关闭，先灰度验证。
   - 用一次全音频 `silencedetect` 结果计算所有区间，避免每段启动三次 ffmpeg。
   - 真正实现裁边界，只有接近全静音时才删除整句。
   - 报告中列出被裁和被删片段，方便人工复核。

9. 同步或移除 `vendor/real-cut` 重复实现，避免后续继续漂移。

### 第三批：测试与发布

10. 新增单元测试和一条真实草稿回归测试。
11. 用 FunASR 和火山分别完整跑同一个短视频，比较文字、切割边界、字幕时序和总耗时。
12. 在一台没有开发环境的新 Windows 电脑上验证 Web 配置、断点续跑和安装包。
13. 全部通过后再合并 `main`、构建安装包、生成哈希并发布新 Release。

## 10. 建议新增的最小测试集合

```text
test_volc_normalize_single_char_tokens
test_volc_normalize_multi_char_numeric_token
test_volc_normalize_multi_char_chinese_token
test_volc_normalize_english_and_repeated_chars
test_asr_cache_isolated_by_engine
test_legacy_cache_does_not_masquerade_as_volc
test_volc_failure_falls_back_and_records_actual_engine
test_resume_preserves_asr_engine
test_price_role_cannot_restore_banned_sentence
test_silence_pruning_off_preserves_old_behavior
test_tos_object_deleted_on_success_and_failure
```

所有网络调用、TOS 上传/删除、ffmpeg 分析和 ASR 模型都应 mock，避免单元测试依赖真实密钥、网络或 2GB 模型。

## 11. 新窗口开始工作时可直接运行

```powershell
Set-Location 'C:\Users\JT\Documents\ChatGPT\搽屁股\RealCutHybrid'
git status --short --branch
git log --oneline --decorate main..HEAD
git diff --stat main...HEAD
python -m unittest discover -s tests -v
```

查看核心文件：

```powershell
git diff main...HEAD -- realcut_hybrid.py web_server.py web/index.html web/app.js
git diff main...HEAD -- 'vendor/experimental/scripts/步骤3-FunASR.py'
git diff main...HEAD -- 'vendor/experimental/scripts/步骤4-切割排序.py'
```

PowerShell 下中文文件名若被 Git 转义，可临时使用：

```powershell
git -c core.quotePath=false diff --name-only main...HEAD
```

## 12. 工作边界与注意事项

- 不要改动或删除 Git 根目录中的 `_jianying_backups/` 和 `restore_style5_template.py`。
- 不要执行 `git reset --hard`、`git checkout --` 或清理未跟踪文件。
- 不要把 `asr_volc.env`、API Key、AK、SK 提交到 Git 或写进日志。
- 文档记录火山凭证曾在此前对话中短暂出现，正式交接前应在火山 IAM/语音控制台轮换。
- 不要未经用户明确要求删除 GitHub Release、合并分支、推送修复、重打安装包或发布新版本。
- 当前 GitHub 最新正式版本仍是 `v2026.08.31.1-handover`；本火山分支不是正式发布版本。
- 修复时优先改 `vendor/experimental/scripts`，同时明确决定如何处理 `vendor/real-cut/scripts`，不要无意识维护两套不同逻辑。

## 13. 给接手窗口的一句话结论

保留火山 ASR 方向，但先修复时间戳、缓存/续跑、违禁价格句和交接凭证四个阻断问题；之后处理失败回退、TOS 清理和静音性能，再测试、合并和发布。
