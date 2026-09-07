# 改动说明：火山引擎 ASR + 静音净化

> 提交 `3bcad03` · 分支 `feat/volcengine-asr`（已推送 GitHub）
> 面向本版相比 `main`（`ae29f2f`）的代码改动，写给接手/回看的人。

## 有声时长策略追加修订（2026-09-05）

- 成片时长由旧的 30 秒上限改为 15-45 秒范围，45 秒封顶只删除完整口播单元。
- 相邻 ASR 短句会先合成口播单元，不再删除 `<1s` 句子；LLM 漏分类会自动补回。
- 结构内容不足 15 秒时回捞未使用合规原声，闲聊最后使用；原视频有效口播确实不足时明确失败。
- 禁止静音 `mirror_fill`、重复人声和外部主播音频补时长。镜像、开盒脚本改为兼容 no-op。
- 步骤4生成 `duration_policy_report.json`，调度器验证时长、连续主口播、元数据对应和零 mirror 引用。
- 草稿20、27、39已真实重跑，最终分别为 16.912s、16.137s、15.040s，全部为连续原声。
- DeepSeek 不可重试的 4xx 会立即回退千问；本机旧模型名已从 `deepseek-flash` 迁移为
  当前接口支持的 `deepseek-v4-flash`。

## 审查后修订（2026-09-04）

- 火山多字符 token 会展开为单字时间戳，数字、中文短语、英文和重复字符不再拖偏后续句界。
- `asr_result.json` 记录请求引擎、实际引擎、后端版本和回退原因；缓存按请求引擎隔离。
- 任务状态、断点续跑和从头重跑继承 ASR 选择，任务详情及报告显示实际使用的引擎。
- 火山失败会回退 FunASR；回退结果不会阻止下次重新尝试火山。
- TOS 临时音频在识别成功或失败后都会尝试删除。
- Web 设置页支持五项火山凭证的 DPAPI 加密保存；配置不完整时禁用并拒绝提交火山任务。
- 价格角色检测只接收通过合规过滤的句子，不能重新引入违禁价格句。
- 静音净化改为默认关闭的实验开关，通过 `--silence-pruning` 或 Web 显式启用。
- 静音分析改为全音频一次 ffmpeg 扫描；句首句尾长静音会裁边，只有近全静音句子会删除。
- Web 队列增加跨进程所有权锁，第二个实例不能再恢复或执行同一个持久化队列；测试实例可用 `REALCUT_QUEUE_FILE` 隔离。
- 历史提交误改的 `vendor/real-cut/scripts` 已恢复为 `main` 原样；新逻辑只保留在 `vendor/experimental/scripts`。

---

## 一、背景

RealCut Hybrid 的完整剪辑流水线（导入→分离音频→**ASR→切割排序**→…→字幕）有两个已知短板：

1. **ASR 依赖本地 FunASR**：中文口播转写准确率有限（价格数字出汉字、断句粘连、错字），
   效果明显不如云端中文专用引擎（对比见 §4）。
2. **成片可能出现"大段无声"**：步骤4 按 ASR 句子 `[start,end]` 整段切片，若某句来自一段
   音量极低 / 长停顿的源区间，会被当有效口播整段切进成片，造成几秒甚至十几秒没有声音。

本版针对这两点改动：接入**火山引擎 Seed-ASR（豆包录音文件识别）**作为可切换的云端 ASR 后端，
并在步骤4增加可选的**静音裁边**（裁掉句首句尾长静音，只丢弃近全静音段）。

---

## 二、改动总览

### 2.1 文件清单

| 文件 | 状态 | 作用 |
|---|---|---|
| `vendor/experimental/scripts/_volc_asr.py` | 🆕 新增 | 火山 Seed-ASR 后端：TOS 预签名上传 → 识别 → 归一化成系统契约 |
| `vendor/experimental/scripts/_trim_segments.py` | 🆕 新增 | 静音净化器：一次全音频分析、句首句尾裁边、近全静音判定 |
| `vendor/experimental/scripts/_funasr.py` | ✏️ 修改 | `recognize_audio()` 支持 `engine='volc'`，失败自动回退 FunASR |
| `vendor/experimental/scripts/步骤3-FunASR.py` | ✏️ 修改 | 加 `--engine volc` 参数；默认 `funasr`（修复默认误写 volc 的 bug） |
| `vendor/experimental/scripts/步骤4-切割排序.py` | ✏️ 修改 | 切片前接入 `_trim_segments` 净化 + 结构位补回 |
| `realcut_hybrid.py` | ✏️ 修改 | 主控加 `--asr-engine {funasr,volc}`，步骤3 传递引擎 |
| `web_server.py` | ✏️ 修改 | 后台任务把 `options.asr_engine` 映射成 `--asr-engine` |
| `web/app.js` | ✏️ 修改 | 任务表单读取引擎下拉值 |
| `web/index.html` | ✏️ 修改 | 新建任务表单新增「识别引擎」下拉 |
| `.gitignore` | ✏️ 修改 | 新增 `**/asr_volc.env`（防止密钥入库） |

> 说明：本项目调度器实际运行 **`vendor/experimental/scripts`**（见根 README）。
> `vendor/real-cut` 是只读原版副本，已与 `main` 完全一致，本次不在其中保留任何实验改动。

### 2.2 凭证存储（本地，不入库）

正式交接用法是在 Web 设置页录入五项火山配置。密钥由 Windows DPAPI
按当前用户加密，页面和 API 只返回“已配置/未配置”，不回显明文。
`asr_volc.env` 仅作为开发者兼容入口，已被 `.gitignore` 忽略：

```ini
VOLCENGINE_API_KEY=           # 语音技术控制台签发的 API Key
VOLCENGINE_ACCESS_KEY_ID=     # IAM AK（AKLT 开头）
VOLCENGINE_SECRET_ACCESS_KEY= # IAM SK
VOLCENGINE_TOS_BUCKET=        # TOS 桶名（录音文件需公网 URL，上传到该桶）
VOLCENGINE_TOS_REGION=        # 默认 cn-beijing
```

---

## 三、功能一：火山引擎 ASR 后端

### 3.1 数据契约（与 FunASR 对齐）

下游（步骤7 字幕、asr_result.json）只认统一的 `(words, sentences)`：

```python
sentences: [{text(带标点短句), start(ms), end(ms)}, ...]
words:     [{text(单字,无标点), start(ms), end(ms)}, ...]
```

火山返回是 `utterances`（一次自然停顿为一段，可能含多句），由 `_volc_asr.normalize_volc()`
按**逗号/句末标点**切成短句，并把词级时间戳逐一归位，输出与 FunASR 的
`sentence_info` 粒度一致，下游零改动。

### 3.2 识别流程

```
音频文件
  → TOS 预签名 PUT 上传（脚本内实现，无需 TOS SDK）
  → openspeech.bytedance.com 提交/轮询
       express: volc.bigasr.auc_turbo（极速，单次）
       standard: volc.seedasr.auc（标准，submit+query）
  → normalize_volc() → (words, sentences)
```

请求体开启 `enable_itn`（数字直出阿拉伯 169/499）、`enable_punc`（标点）、
`enable_ddc`（口语顺滑）、`show_utterances`、说话人。

> 注意：express 未开通时会自动回退 standard（`45000030 requested resource not granted`
> 处理）。两档都未开通则抛错并在 `_funasr`/步骤3 侧回退 FunASR。

### 3.3 引擎切换入口（四层一致）

1. **Web**：新建任务弹窗 →「识别引擎」下拉（FunASR 本地 / 火山云端）→ `options.asr_engine`
2. **web_server**：`_run_item` → `--asr-engine <val>`
3. **CLI 主控**：`python realcut_hybrid.py run xxx.mp4 --asr-engine volc`
4. **步骤3**：`python 步骤3-FunASR.py <草稿> --engine volc`
   环境变量 `REALCUT_ASR_ENGINE=volc` 也可生效。

默认一律 `funasr`（本地），只有显式指定才走火山。

### 3.4 实测：火山 vs FunASR（同一段中文带货）

| 原话 | 火山 Seed-ASR | FunASR(Paraformer) |
|---|---|---|
| 599 改价 499 | `499，来上车` | `五九八十一号链接` ❌ |
| 库存 15 件 | `15件` | `十五件` |
| 价格 6999/1888 | `6999`/`1千888` | `六千九百九十九`/`一千八百八十八` |
| 断句 | 短句干净 | 常两句并一句 |

结论：火山在**价格数字直出、断句粒度、字准**上全面优于本地 FunASR，更接近 ChatCut（其
中文引擎即为火山 Huoshan）的字幕质感。

---

## 四、功能二：步骤4 静音净化（消除大段无声）

### 4.1 问题实例（视频54）

```
源音频 25.29–40.02s（14.7 秒）
  ├─ 平均音量 -34.5dB（源整体 -24.4dB，差 10dB，近无声）
  ├─ 含 5 处长停顿，ASR 全段只识别出 1 句
  └─ 被分类为"痛点" → 整段切进成片 → 成片 15s 处 12 秒没声音
```

根因不在 ASR，而是步骤4 按句子边界整段切片、未过滤近无声区间。

### 4.2 `_trim_segments.clean_ordered_segments()` 判定

对每个 `source='asr'` 段：

- 整段源音频只运行一次 ffmpeg，同时取得整体平均音量和大于 500ms 的静音区间。
- 句首、句尾落在长静音中时，把 `src_start_ms` / `src_end_ms` 收缩到实际有声边界。
- 只有有效语音占比低于 `MIN_SPEECH_RATIO`(0.10)，即近乎整句无声时才删除。
- 句中停顿不拆句，不改变句子的首尾边界；素材库整段（`source='file'`）不参与校验。

不再用“低于全局平均音量 6dB”删除整句，避免误伤真实的轻声口播。所有候选和结构补位
共用同一份分析结果，耗时由约 `1 + 3N` 个 ffmpeg 进程降为 1 个。

### 4.3 步骤4 集成

`步骤4-切割排序.py` 在 `build_ordered_segments()` 之后、压时长之前：

```python
analysis = _ts.analyze_audio(str(audio_src))
segs, dropped = _ts.clean_ordered_segments(segs, str(audio_src), analysis=analysis)
if dropped:
    segs = _refill_dropped(segs, dropped, grouped, sentences, str(audio_src), _ts, analysis)
```

- 净化结果会在 `step4_segments.json` 中保留 `silence_trimmed` 和原始首尾时间，并生成
  `silence_pruning_report.json`；总任务报告会列出全部裁边和删除段，方便人工复核。
- `_refill_dropped()`：若被丢弃段属于结构位（爆点/痛点/金句/价格）且该分类因此空缺，
  从 `grouped` 同分类的剩余非静音候选补一条，保住带货叙事结构。
- 本节记录的是 2026-09-04 的旧 30 秒实现；2026-09-05 起已由上方 15-45 秒有声策略取代。

### 4.4 验证状态

原分支按低音量整句删除的实现曾对视频54完整重跑，结果如下：

| 指标 | 原始流程 | 原分支算法 |
|---|---|---|
| 25-40s 低音长段(14.7s) | 进成片 → 12s 无声 | **被剔除** |
| 成片音频轨 >0.5s 空隙 | 有 | **0 处** |
| 成片时长（历史样本） | 30s(含噪音) | 30s(全有效口播) |

审查后不再以相对低音量直接删除整句，因此上表不能当作新算法的回归结论。新算法已用 mock
覆盖一次扫描、首尾裁边、保留三分之一有声句子、删除约 3% 有声句子；对草稿54的只读扫描
在 `-40dB / 500ms` 条件下只找到一个约 0.5 秒静音区间，没有擅自删除低声口播。正式发布前
仍应选一批真实素材灰度比较，确认阈值后再决定是否把实验开关默认开启。

---

## 五、修复的 Bug

**experimental 步骤3 入口默认引擎写错**：`__main__` 里 `engine = 'volc'` 为硬编码默认，
不带 `--engine` 也会走火山；而火山账号两档未开通时直接崩（`requested resource not granted`），
导致整条流水线失败。已改为默认 `funasr`，仅显式 `--engine volc` 才走火山。

---

## 六、使用示例

```bash
# 本地 FunASR（默认，无需火山）
python realcut_hybrid.py run D:/素材库/x.mp4

# 火山云端识别（正式交接版先在 Web 设置页录入五项配置）
python realcut_hybrid.py run D:/素材库/x.mp4 --asr-engine volc

# 或 Web：新建任务时把「识别引擎」选成「火山 Seed-ASR」

# 只重跑步骤3（某草稿）用火山
python vendor/experimental/scripts/步骤3-FunASR.py <草稿路径> --engine volc --no-open
```

---

## 七、安全提醒

- 火山 API Key 和 AK/SK 以明文在对话中出现过，**正式交付前必须在火山控制台轮换**。
- `asr_volc.env` 已入 `.gitignore`，**不会**随仓库上传。

---

## 八、2026-09-04 RC 验收

- 五项火山配置已通过 Windows DPAPI 保存；隔离配置验收覆盖保存、进程重启后解密和清除，页面/API 与设置文件均不含明文。
- `cn-beijing` TOS 最小对象上传与删除成功；RC4 编译版对 21.87 秒中文样本识别返回 6 句、76 个字级时间戳。
- 正式步骤3临时草稿记录 `requested_engine=volc`、`actual_engine=volc`、
  `asr_backend_version=seedasr-v2`，第二次运行命中缓存。
- 当前账号未开通极速档，程序自动回退火山标准档并成功完成识别。
- OfficeCLI 1.0.147 能创建 `.xlsx` manifest，旧的 `System.Private.Xml` 初始化故障未再出现。
- 源码单元测试 24/24，源码环境检查 16/16；`2026.09.04-volc-asr-rc4` 编译包和安装后环境检查均为 17/17。
- RC4 内部清单覆盖 36,708 个 payload 且哈希全部一致；无 `.pyc`、editable 开发元数据、项目 Python 源码、明文凭据、设置文件或队列锁。
- 编译版 Web、队列锁、manifest、真实火山步骤3与缓存均通过；直接运行 FunASR 后仍为 0 个 `.pyc`。
- 安装器采用 Inno 分卷输出：一个 `Setup.exe` 和两个 `Setup-*.bin`，三份文件的 SHA-256
  均与 `dist/installer/SHA256SUMS.txt` 一致。

## 九、2026-09-05 源码交付加固（RC5 已包含）

- 新增 `packaging/verify_installer.ps1` 与双击入口，严格检查清单格式、缺失/多余文件、每份
  分卷 SHA-256 和 `Setup.exe` 的 Authenticode 状态。
- 构建脚本支持通过证书指纹签名 RealCut Hybrid 自有 EXE 与安装器；`-Release` 模式要求
  `-ConfirmCredentialsRotated`、有效代码签名证书、安装器和哈希，签名完成后才冻结清单。
- Web 默认监听从 `0.0.0.0` 改为 `127.0.0.1`；状态变更接口要求工作台请求标记和同源
  `Origin`，所有请求拒绝与本机端点不匹配的 `Host`，降低局域网误暴露、跨站请求和 DNS
  重绑定风险。
- 上述内容已进入 `2026.09.05-volc-asr-rc5` 完整离线安装器。RC5 的源码测试为72/72，
  编译包及全新静默安装后的环境检查均为17/17，外层5个交付文件哈希全部通过。
- RC5 仍未做 Authenticode 签名，只能作为预发布候选包；正式组织分发前仍须轮换曾泄露的
  火山凭据并配置受信任代码签名证书。
