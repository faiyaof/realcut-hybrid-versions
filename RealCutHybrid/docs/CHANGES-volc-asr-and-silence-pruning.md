# 改动说明：火山引擎 ASR + 静音净化

> 提交 `3bcad03` · 分支 `feat/volcengine-asr`（已推送 GitHub）
> 面向本版相比 `main`（`ae29f2f`）的代码改动，写给接手/回看的人。

---

## 一、背景

RealCut Hybrid 的完整剪辑流水线（导入→分离音频→**ASR→切割排序**→…→字幕）有两个已知短板：

1. **ASR 依赖本地 FunASR**：中文口播转写准确率有限（价格数字出汉字、断句粘连、错字），
   效果明显不如云端中文专用引擎（对比见 §4）。
2. **成片可能出现"大段无声"**：步骤4 按 ASR 句子 `[start,end]` 整段切片，若某句来自一段
   音量极低 / 长停顿的源区间，会被当有效口播整段切进成片，造成几秒甚至十几秒没有声音。

本版针对这两点改动：接入**火山引擎 Seed-ASR（豆包录音文件识别）**作为可切换的云端 ASR 后端，
并在步骤4 增加**语音质量净化**（丢弃近无声 / 低语音占比段）。

---

## 二、改动总览

### 2.1 文件清单

| 文件 | 状态 | 作用 |
|---|---|---|
| `vendor/experimental/scripts/_volc_asr.py` | 🆕 新增 | 火山 Seed-ASR 后端：TOS 预签名上传 → 识别 → 归一化成系统契约 |
| `vendor/real-cut/scripts/_volc_asr.py` | 🆕 新增 | 同上（real-cut 只读副本保持一致，未激活） |
| `vendor/experimental/scripts/_trim_segments.py` | 🆕 新增 | 语音质量净化器：音量/静音检测、近声段判定 |
| `vendor/real-cut/scripts/_trim_segments.py` | 🆕 新增 | 同上（real-cut 只读副本） |
| `vendor/experimental/scripts/_funasr.py` | ✏️ 修改 | `recognize_audio()` 支持 `engine='volc'`，失败自动回退 FunASR |
| `vendor/real-cut/scripts/_funasr.py` | ✏️ 修改 | 同上 |
| `vendor/experimental/scripts/步骤3-FunASR.py` | ✏️ 修改 | 加 `--engine volc` 参数；默认 `funasr`（修复默认误写 volc 的 bug） |
| `vendor/real-cut/scripts/步骤3-FunASR.py` | ✏️ 修改 | 同上 |
| `vendor/experimental/scripts/步骤4-切割排序.py` | ✏️ 修改 | 切片前接入 `_trim_segments` 净化 + 结构位补回 |
| `vendor/real-cut/scripts/步骤4-切割排序.py` | ✏️ 修改 | 同上 |
| `realcut_hybrid.py` | ✏️ 修改 | 主控加 `--asr-engine {funasr,volc}`，步骤3 传递引擎 |
| `web_server.py` | ✏️ 修改 | 后台任务把 `options.asr_engine` 映射成 `--asr-engine` |
| `web/app.js` | ✏️ 修改 | 任务表单读取引擎下拉值 |
| `web/index.html` | ✏️ 修改 | 新建任务表单新增「识别引擎」下拉 |
| `.gitignore` | ✏️ 修改 | 新增 `**/asr_volc.env`（防止密钥入库） |

> 说明：本项目调度器实际运行 **`vendor/experimental/scripts`**（见根 README）。
> `vendor/real-cut` 是只读原版副本，改动仅为保持一致，不参与运行。

### 2.2 凭证文件（本地，不入库）

火山凭证读 `asr_volc.env`（各 scripts 目录下，已被 `.gitignore` 忽略，**不会上传 GitHub**）：

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

- **低音量**：段平均音量 < 源音频整体 − `VOL_DIFF_DB`(6dB) → 判近无声，丢弃
- **低语音占比**：有效语音(剔除 >500ms 静音后) < `MIN_SPEECH_RATIO`(0.40) → 判无效，丢弃

用**相对判定**（对比源音频整体音量），避免绝对阈值误伤本就偏小的收音。
素材库整段（`source='file'`）不参与校验。

### 4.3 步骤4 集成

`步骤4-切割排序.py` 在 `build_ordered_segments()` 之后、压时长之前：

```python
segs, dropped = _ts.clean_ordered_segments(segs, str(audio_src), baseline_vol=base_vol)
if dropped:
    segs = _refill_dropped(segs, dropped, grouped, sentences, str(audio_src), _ts)
```

- 净化丢弃近声段
- `_refill_dropped()`：若被丢弃段属于结构位（爆点/痛点/金句/价格）且该分类因此空缺，
  从 `grouped` 同分类的**剩余正常音量候选**补一条，保住带货叙事结构。
- 时长约束本就是"超 30s 才压缩"（`limit_segments_to_max_duration`），净化后成片自然 ≤30s。

### 4.4 实测验证（视频54 完整重跑）

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 25-40s 低音长段(14.7s) | 进成片 → 12s 无声 | **被剔除** |
| 成片音频轨 >0.5s 空隙 | 有 | **0 处** |
| 成片时长 | 30s(含噪音) | 30s(全有效口播) |

正常音量段（-22~-26dB）全部保留，无误伤。

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

# 火山云端识别（需 asr_volc.env 凭证 + 已开通）
python realcut_hybrid.py run D:/素材库/x.mp4 --asr-engine volc

# 或 Web：新建任务时把「识别引擎」选成「火山 Seed-ASR」

# 只重跑步骤3（某草稿）用火山
python vendor/experimental/scripts/步骤3-FunASR.py <草稿路径> --engine volc --no-open
```

---

## 七、安全提醒

- 火山 AK/SK 以明文在对话中短暂出现过，**建议到火山 IAM 控制台轮换该组 Access Key**。
- `asr_volc.env` 已入 `.gitignore`，**不会**随仓库上传。
