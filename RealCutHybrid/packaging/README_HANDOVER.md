# RealCut Hybrid 编译交接版

本交接版把 RealCut Hybrid 自有 Python 代码编译为 Windows EXE，并保留经过验证的便携
Python 第三方依赖、FunASR 模型、FFmpeg、剪映 5.9、OfficeCLI、风格1/风格2模板及其字体、BGM、贴纸素材。

## 使用

1. 安装或完整复制便携目录，推荐使用安装器默认短路径，不要放在系统保护目录或很深的多级目录。
2. 双击 `Start-RealCutHybridWeb.bat`。
3. 浏览器打开本机工作台，在“设置”页填写 DeepSeek 或 DashScope API Key。需要使用火山
   Seed-ASR 时，再填写火山 API Key、AK、SK、TOS Bucket 和 Region；页面只显示配置状态，
   不回显明文。
4. 保存后环境预检会立即刷新，之后提交的任务会自动使用新配置。

工作台默认仅监听 `127.0.0.1`，不会向局域网开放。维护者显式传入 `--host 0.0.0.0` 才会
启用局域网模式；该模式没有用户登录，只应在受信任网络临时使用。

目标电脑处理较慢时，可在新建任务中关闭“AI 画面识别（较慢）”。关闭后不再逐帧调用
视觉模型，系统按 ASR/字幕对应的原视频时间轴重建画面；速度会明显提高，但不会再主动
避开空手、开盒或其他商品画面。

识别引擎默认使用本地 FunASR。火山五项配置完整后，新建任务才可选择火山 Seed-ASR；
火山请求失败时会回退本地 FunASR，并在任务详情和报告中标明请求引擎、实际引擎及原因。
实验性静音净化默认关闭，建议仅在确认源视频含长静音段时单独开启。启用后会裁掉句首句尾长静音，仅删除近全静音句子，不再按相对音量删除轻声口播。

目标电脑不需要预装剪映 5.9，也不需要手工复制模板或剪映缓存。新建任务时可在风格框选择随包的风格1/风格2，默认使用风格1。

## 体积说明

这是可断网部署的完整版，包含约 2.0 GiB FunASR 模型、1.3 GiB 精简 Python AI 运行时、
1.27 GiB 剪映 5.9，以及 FFmpeg、OfficeCLI 和风格素材。安装后的占用会明显大于下载包，
但接手电脑不需要另装 Python、模型或剪映。

安装器可能因体积较大输出为一个 `Setup.exe` 和若干 `Setup-*.bin` 分卷。交付时必须把
`Setup.exe`、全部 `.bin`、`SHA256SUMS.txt`、`Verify-RealCutHybrid.cmd` 和
`Verify-RealCutHybrid.ps1` 放在同一目录，不能只发送主程序。接收方应先双击
`Verify-RealCutHybrid.cmd`；出现哈希不一致、文件缺失或多出未列入清单的文件时，不要安装。

当前内部交接安装器没有 Authenticode 代码签名，Windows 可能显示 SmartScreen 提示。
哈希只能证明文件与清单一致，不能证明发布者身份；正式组织分发必须使用受信任的
Authenticode 证书。正式包的核验结果必须显示 `Authenticode: Valid`，并且仍应只从受信任的
交付渠道获取。

维护者生成正式包时，先在火山控制台轮换曾出现在对话中的 API Key 和 AK/SK，再执行：

```powershell
$env:REALCUT_SIGNING_CERT_THUMBPRINT = "<代码签名证书指纹>"
.\packaging\build_handover.ps1 `
  -RuntimeSource ..\RealCutHybrid_Deploy_20260826 `
  -Version <版本号> `
  -Release `
  -ConfirmCredentialsRotated
```

`-Release` 不允许跳过安装器或哈希，并会在生成哈希前签名所有 RealCut Hybrid 自有 EXE 和
`Setup.exe`，随后强制复验签名。`-ConfirmCredentialsRotated` 仅是人工确认门禁，不会自动访问
或修改火山控制台。

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

EXE 会显著提高直接查看和修改源码的门槛，但任何本地软件都无法做到绝对不可逆。可维护源码保存在
GitHub 仓库；当前仓库为公开仓库，任何人都可以获取源码。若后续需要限制源码访问，应先把仓库改为
私有并配置访问控制。安装包仍应保留版本标签和 SHA-256 校验。
