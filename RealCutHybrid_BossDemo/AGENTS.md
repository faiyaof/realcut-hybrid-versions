# RealCutHybrid 开发与使用约定

本项目的剪辑引擎来自 real-cut skill 的原样副本，不允许直接修改
`vendor/real-cut` 下的脚本或文档。测试新逻辑时，请先在项目内复制一份到其他目录，
例如 `vendor/experimental/`。

常用入口：

```powershell
python realcut_hybrid.py check
python realcut_hybrid.py run "视频路径" --dry-run
python realcut_hybrid.py run "视频路径"
python realcut_hybrid.py batch "素材目录" --recursive --continue-on-error
python realcut_hybrid.py summary
python realcut_hybrid.py run "视频路径" --draft 草稿名 --phase2 --force
python realcut_hybrid.py manifest manifests\realcut-batch.xlsx --force
python realcut_hybrid.py batch "素材目录" --recursive --manifest manifests\realcut-batch.xlsx --group-size 10
python realcut_hybrid.py restyle 32 33 34 --style 风格2 --manifest manifests\realcut-batch.xlsx
python realcut_hybrid.py force-font 131 132 133 --style 风格2 --manifest manifests\realcut-batch.xlsx
python realcut_hybrid.py fill-gaps 32 33 34 --check --manifest manifests\realcut-batch.xlsx

# Claude CLI 独立剪辑必须带 --run-root，不要用项目根的 state/logs/reports
python realcut_hybrid.py check --run-root runs\jingjian-20260821
python realcut_hybrid.py claude "D:\工作空间\精剪\素材" --recursive --mode edit `
  --run-root runs\jingjian-20260821 `
  --manifest runs\jingjian-20260821\manifests\jingjian-all.xlsx `
  --group-size 10 --max-budget-usd 5 --continue-on-error --dry-run
```

Web 工作台：

```powershell
python web_server.py
# 双击 Start-RealCutHybridWeb.bat 也可以
```

Web 源码位于 `web/`，其中 `styles.css`、`modal.css` 和 lucide 图标直接复用了
LiveClipAgent 的本地工作台视觉资产；`app.js` 是本项目精简版前端逻辑。

运行结果目录：

- `state/`：任务状态
- `logs/`：运行日志
- `snapshots/`：步骤前快照
- `reports/`：Markdown/JSON 报告
- `manifests/`：批次/视频/异常三表（xlsx + json；xlsx 由 officecli 读写）

**目录边界**：不传 `--run-root` 时，以上目录都在项目根 `RealCutHybrid/` 下，Web 工作台和旧会话使用这一套。Claude CLI 独立剪辑时传 `--run-root runs/<名称>`，以上目录全部落在该 run-root 下，Claude 子批次会自动继承同一个 run-root，互不读取。


修改调度器后至少执行：

1. `python -m py_compile realcut_hybrid.py`
2. `python realcut_hybrid.py check`
3. `python realcut_hybrid.py run <存在的视频> --dry-run`
4. `python realcut_hybrid.py manifest <临时.xlsx> --force`
5. `python realcut_hybrid.py batch <存在的视频> --manifest <临时.xlsx> --manifest-force --dry-run`

修改 manifest/后处理逻辑时也要 py_compile `manifest.py`、`postprocess.py`。

Claude Code 只作为批次会话包装器：优先执行本仓库 CLI，不要直接改 `vendor/real-cut`，
不要用 pywinauto/剪映窗口点击做自动化。

Claude Code 独立批次必须传 `--run-root`。独立项目已建在
`C:\Users\JT\Documents\ChatGPT\realcut-claude-cli`，实测归档在
`C:\Users\JT\Documents\ChatGPT\realcut-claude-cli\runs\cc-cli-jingjian-20260821`；不要再把它和本项目根目录的 `manifests/jingjian-all.xlsx` 当作同一份交接文件。

`D:\ai-edit-studio` 是另一个独立项目，正在处理草稿 `161-190`，直接调用系统 real-cut
scripts，不读写本项目的 `runs/` 和根目录状态。

修改 Web 层后至少执行：

1. `python -m py_compile web_server.py`
2. `node --check web/app.js`
3. 启动 `web_server.py` 后验证 `/api/bootstrap` 和页面截图

不要在本项目里启动 LiveClipAgent 的剪映 UI 自动导出；当前调度器只负责剪辑草稿。
