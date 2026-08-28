# RealCut Hybrid Versions

This repository keeps three RealCut Hybrid source snapshots side by side.

| Directory | Purpose |
| --- | --- |
| `RealCutHybrid/` | Main development version and full local Web workspace |
| `RealCutHybrid_BossDemo/` | Boss demo variant with the required demo assets |
| `RealCutHybrid_Deploy_20260826/` | Source snapshot used by the 2026-08-26 portable deployment package |

Each directory has its own README and startup instructions. Generated jobs,
logs, snapshots, manifests, downloaded model caches, bundled Python/Torch,
Jianying, FFmpeg, and other portable runtimes are intentionally excluded from
Git history. They contain local working data or files that exceed GitHub's
normal repository limits.

The complete portable package is distributed separately from the source
repository. See `RealCutHybrid_Deploy_20260826/README_DEPLOY.md` for its bundled
components and startup instructions.
