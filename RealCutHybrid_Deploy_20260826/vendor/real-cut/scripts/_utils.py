# -*- coding: utf-8 -*-
"""
_utils.py - Jianying automated editing shared utilities

Centralized management of:
- 3-file sync (draft_content.json / draft_info.json / template-2.tmp)
- UUID generation
- Atomic write (tmp -> os.replace) + timestamped .bak backup (keep latest 3)
- ensure_jianying_closed(): 写盘前关闭剪映进程，防止内存副本覆盖成品
- read_draft(): 明文/加密成品草稿统一读取

写盘铁律（所有走 write_draft 的脚本自动获得）：
  1. 写前确保剪映已关闭（taskkill，失败仅告警）
  2. 写前把现有 draft_content.json 备份为 .bak_YYYYMMDD_HHMMSS（保留最近3个，不删除）
  3. 三文件全部原子写（tmp -> os.replace）；任一失败则告警并尝试回滚
"""

import json, shutil, uuid, os, sys, time, subprocess
from pathlib import Path


def uid():
    return str(uuid.uuid4()).upper()


def ensure_utf8_stdout():
    """保证 stdout 以 UTF-8 输出中文（父进程按 UTF-8 读取）。幂等。"""
    out = sys.stdout
    if out is None:
        return
    try:
        enc = (out.encoding or '').lower()
    except Exception:
        enc = ''
    if 'utf' in enc:
        return  # 已经是 UTF-8，不重复包装
    try:
        buf = out.buffer
    except Exception:
        return
    try:
        import io
        sys.stdout = io.TextIOWrapper(buf, encoding='utf-8')
    except Exception:
        pass


def ensure_jianying_closed():
    """写盘前确保剪映已关闭（剪映运行时会用内存副本覆盖外部修改）。

    taskkill 失败仅告警，不中断流程。步骤7/12 已前置 kill，重复调用无害。
    """
    try:
        flags = 0
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            flags |= subprocess.CREATE_NO_WINDOW
        r = subprocess.run(
            ['taskkill', '/f', '/im', 'JianyingPro.exe'],
            capture_output=True, text=True, timeout=10, creationflags=flags,
        )
        # 0=成功结束; 128=没有该进程（同样视为已关闭）
        if r.returncode not in (0, 128):
            msg = (r.stderr or r.stdout or '').strip()
            print(f'[utils] 警告: taskkill 剪映退出码 {r.returncode}: {msg[:200]}')
    except Exception as e:
        print(f'[utils] 警告: 无法关闭剪映进程: {e}')


def _backup_draft(dp):
    """写盘前把现有 draft_content.json 备份为 .bak_YYYYMMDD_HHMMSS，保留最近3个。"""
    dc = dp / 'draft_content.json'
    if not dc.exists():
        return None
    ts = time.strftime('%Y%m%d_%H%M%S')
    bak = dp / f'draft_content.json.bak_{ts}'
    try:
        shutil.copy2(str(dc), str(bak))
        # 只保留最近3个时间戳备份
        baks = sorted(
            (p for p in dp.glob('draft_content.json.bak_*') if p.is_file()),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        for old in baks[3:]:
            try:
                old.unlink()
            except Exception:
                pass
        print(f'[utils] 已备份草稿: {bak.name}')
        return bak
    except Exception as e:
        print(f'[utils] 警告: 草稿备份失败 {bak}: {e}')
        return None


def _atomic_write(path, text):
    """写 .tmp 文件后 os.replace 原子改名（中途中断不会留半 JSON）。"""
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(str(tmp), str(path))


def write_draft(dp, draft, indent=4):
    """
    三文件原子写盘 + 写前备份 + 写前关闭剪映。

    Args:
        dp: draft directory path (str or Path)
        draft: draft_content dict
        indent: JSON indent (default 4, matching JianYing format)

    保证：
      - 写盘前 ensure_jianying_closed()（剪映运行会被 kill）
      - 写盘前备份现有 draft_content.json（.bak_时间戳，保留最近3个，不删除）
      - draft_content.json / draft_info.json / template-2.tmp 全部原子写
      - 任一失败：告警并尝试用已成功文件内容回滚未成功文件
    """
    dp = Path(dp)
    dc = dp / 'draft_content.json'

    # 0. 保证 stdout 以 UTF-8 输出中文（父进程按 UTF-8 读取）
    ensure_utf8_stdout()

    # 1. 写盘前确保剪映关闭（防止内存副本覆盖成品）
    ensure_jianying_closed()

    # 2. 写盘前备份现有草稿（时间戳命名，保留最近3个，不删除旧备份）
    _backup_draft(dp)

    # 3. 三文件原子写
    text = json.dumps(draft, ensure_ascii=False, indent=indent)
    targets = ['draft_content.json', 'draft_info.json', 'template-2.tmp']
    done = []
    failed = None
    for fn in targets:
        try:
            _atomic_write(dp / fn, text)
            done.append(fn)
        except Exception as e:
            failed = fn
            break

    if failed is not None:
        print(f'[utils] 致命错误: 写盘失败，失败文件: {failed}，已成功: {done}，错误: {e}')
        # 回滚：用已成功文件的内容补齐未成功文件（尽力而为，避免三文件不一致）
        try:
            if done:
                with open(dp / done[0], 'r', encoding='utf-8') as f:
                    ok_text = f.read()
                for fn in targets:
                    if fn not in done:
                        _atomic_write(dp / fn, ok_text)
                        done.append(fn)
                print('[utils] 已尝试回滚：用成功文件内容补齐了未写入文件')
            else:
                print('[utils] 无法回滚：首个文件写入即失败，请用最近 .bak_* 备份恢复')
        except Exception as e2:
            print(f'[utils] 回滚失败: {e2}，请手动用 .bak_* 备份恢复')
        raise

    return dc


def read_draft(dp):
    """读取草稿 draft_content.json（明文直接读，加密则用 jy_crypt 解密）。

    Args:
        dp: draft directory path (str or Path)

    Returns:
        dict: draft_content 内容
    """
    dp = Path(dp)
    dc = dp / 'draft_content.json'
    raw = dc.read_bytes()
    # 去掉可能的 BOM，再判断是否加密
    text = raw.lstrip(b'\xef\xbb\xbf').decode('utf-8', errors='replace')
    if not text.lstrip().startswith('{'):
        from jy_crypt import JyCrypt
        text = JyCrypt().decrypt(text)
    return json.loads(text)


# 模板草稿库（10.0 风格模板）
STYLE_LIB = Path(r'D:/10  jianyin/JianyingPro Drafts')
# 5.9 模板草稿（com.lveditor.draft 下按风格名分目录）
DRAFT_ROOT = Path(r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft')
STYLE_CONFIG_FILE = DRAFT_ROOT.parent / 'style_config.json'


def resolve_template_dir():
    """解析共享模板草稿目录（供步骤9花字/10BGM/11水印共用）。

    优先级：
      1. style_config.json 的 default_style -> STYLE_LIB/{风格}模板（10.0模板库）
      2. 回退 com.lveditor.draft/{风格}（5.9 模板草稿）
      3. 最后回退历史硬编码 com.lveditor.draft/草稿

    返回 (Path, 模板名)。找不到任何模板返回 (None, None)。
    """
    style_name = None
    if STYLE_CONFIG_FILE.exists():
        try:
            import json as _json
            cfg = _json.load(open(STYLE_CONFIG_FILE, encoding='utf-8'))
            style_name = cfg.get('default_style')
        except Exception:
            style_name = None
    if style_name:
        cand = STYLE_LIB / f'{style_name}模板'
        if (cand / 'draft_content.json').exists():
            return cand, style_name
        cand = DRAFT_ROOT / f'{style_name}模板'
        if (cand / 'draft_content.json').exists():
            return cand, style_name
        cand = DRAFT_ROOT / style_name
        if (cand / 'draft_content.json').exists():
            return cand, style_name
    fallback = DRAFT_ROOT / '草稿'
    if (fallback / 'draft_content.json').exists():
        return fallback, '草稿'
    return None, None
