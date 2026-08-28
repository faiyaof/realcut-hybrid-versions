# -*- coding: utf-8 -*-
"""剪映草稿批量换字体工具：解密→替换subtitle字体→重新加密写回。
用法: python batch_font_replace.py [--drafts 2,4,6] [--all]
- 对草稿2-46逐个处理
- 所有 type=subtitle 的字幕字体换成字语圆体
- 支持明文/加密草稿
"""
import ctypes
import json
import os
import sys
import shutil
import io
from pathlib import Path

# 保证 stdout 以 UTF-8 输出中文（父进程按 UTF-8 读取）
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 字语圆体配置
YUAN_TI_FONT_ID = '7495689259223880202'
YUAN_TI_PATH = 'C:/Users/JT/AppData/Local/JianyingPro/User Data/Cache/effect/113454943/f625722b0ce881a1182f8ae3d2fc7b9a/字语圆体.ttf'
YUAN_TI_FONTS = [{
    'category_id': 'preset', 'category_name': '剪映预设',
    'effect_id': '7495689259223880202', 'file_uri': '',
    'id': '63986AF3-3A1A-431a-87A4-4184C22FCFA3', 'path': '',
    'request_id': '20260810131504B0970274CB02E0AAB17C',
    'resource_id': '7495689259223880202', 'source_platform': 0,
    'team_id': '', 'title': '字语圆体',
}]

# 解密DLL（支持环境变量 JY_DLL 覆盖；默认路径已验证有效）
JY_DLL = os.environ.get(
    'JY_DLL',
    r'C:\Users\JT\Desktop\剪映5.9Windows\JianyingPro\5.9.0.11632\videoeditor.dll',
)
DECRYPT_NAME = (
    "?decrypt@EncryptUtils@lvve@@QEAA?AV?$basic_string@DU?$char_traits@D@std@@"
    "V?$allocator@D@2@@std@@AEBV34@0AEA_N@Z"
)
ENCRYPT_NAME = (
    "?encrypt@EncryptUtils@lvve@@QEAA?AV?$basic_string@DU?$char_traits@D@std@@"
    "V?$allocator@D@2@@std@@AEBV34@@Z"
)
ENABLE_NAME = "?enable@EncryptUtils@lvve@@QEAAX_N@Z"


class MsvcString(ctypes.Structure):
    _fields_ = [
        ("buf", ctypes.c_byte * 16),
        ("size", ctypes.c_ulonglong),
        ("capacity", ctypes.c_ulonglong),
    ]


DecryptFn = ctypes.WINFUNCTYPE(
    ctypes.POINTER(MsvcString), ctypes.c_void_p,
    ctypes.POINTER(MsvcString), ctypes.POINTER(MsvcString),
    ctypes.POINTER(MsvcString), ctypes.POINTER(ctypes.c_bool),
)
EncryptFn = ctypes.WINFUNCTYPE(
    ctypes.POINTER(MsvcString), ctypes.c_void_p,
    ctypes.POINTER(MsvcString), ctypes.POINTER(MsvcString),
)
EnableFn = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_bool)


def _make_str_arg(data: bytes) -> MsvcString:
    s = MsvcString()
    n = len(data)
    if n < 16:
        for i, b in enumerate(data):
            s.buf[i] = b
        s.buf[n] = 0
        s.size = n
        s.capacity = 15
    else:
        buf = ctypes.create_string_buffer(data)
        ctypes.memmove(s.buf, ctypes.byref(ctypes.c_void_p(ctypes.addressof(buf))), 8)
        s.size = n
        s.capacity = n
        s._buf = buf  # type: ignore
    return s


def _get_str(s: MsvcString) -> str:
    if s.size >= 16:
        ptr = ctypes.c_void_p()
        ctypes.memmove(ctypes.byref(ptr), s.buf, 8)
        raw = ctypes.string_at(ptr, s.size)
    else:
        raw = bytes(s.buf)[:s.size]
    return raw.decode('utf-8', errors='replace')


class JyCrypt:
    _instance = None

    def __init__(self):
        if not os.path.exists(JY_DLL):
            raise FileNotFoundError(f'videoeditor.dll not found: {JY_DLL}')
        os.add_dll_directory(os.path.dirname(JY_DLL))
        self._dll = ctypes.WinDLL(JY_DLL, use_last_error=True)
        self._dec = ctypes.cast(self._dll[DECRYPT_NAME], DecryptFn)
        self._enc = ctypes.cast(self._dll[ENCRYPT_NAME], EncryptFn)
        self._enable = ctypes.cast(self._dll[ENABLE_NAME], EnableFn)

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def decrypt(self, data: str) -> str:
        in_arg = _make_str_arg(data.encode('utf-8'))
        param_arg = _make_str_arg(b'{}')
        out = MsvcString()
        ok = ctypes.c_bool(False)
        self._dec(None, ctypes.byref(out), ctypes.byref(in_arg),
                  ctypes.byref(param_arg), ctypes.byref(ok))
        if not ok.value:
            raise RuntimeError('decrypt failed')
        return _get_str(out)

    def encrypt(self, data: str) -> str:
        self._enable(None, True)
        in_arg = _make_str_arg(data.encode('utf-8'))
        out = MsvcString()
        self._enc(None, ctypes.byref(out), ctypes.byref(in_arg))
        return _get_str(out)


def read_draft_json(dc: Path) -> dict:
    """读取草稿（明文/加密），返回dict。BOM 明文不被误判加密。"""
    raw = dc.read_bytes()
    text = raw.lstrip(b'\xef\xbb\xbf').decode('utf-8', errors='replace')
    if not text.lstrip().startswith('{'):
        # 加密
        jy = JyCrypt.get()
        text = jy.decrypt(text)
    return json.loads(text)


def write_draft_json(dc: Path, draft: dict, reencrypt: bool):
    """写回草稿（按原格式明文/加密）。"""
    text = json.dumps(draft, ensure_ascii=False)
    if reencrypt:
        jy = JyCrypt.get()
        text = jy.encrypt(text)
    dc.write_text(text, encoding='utf-8')
    # 同步备份文件
    for fn in ['draft_info.json', 'template-2.tmp']:
        p = dc.parent / fn
        if p.exists():
            raw = p.read_bytes()
            if raw.lstrip(b'\xef\xbb\xbf').startswith(b'{'):
                # 明文备份也更新（如果是明文，含 BOM 明文）
                p.write_text(text, encoding='utf-8')


def replace_font(draft: dict) -> int:
    """把所有 subtitle 字幕字体换成字语圆体，返回修改条数。"""
    n = 0
    for mat in draft.get('materials', {}).get('texts', []):
        if mat.get('type') != 'subtitle':
            continue
        old_font = mat.get('font_resource_id')
        if old_font == YUAN_TI_FONT_ID:
            continue  # 已是圆体
        mat['font_resource_id'] = YUAN_TI_FONT_ID
        mat['font_path'] = YUAN_TI_PATH
        mat['fonts'] = json.loads(json.dumps(YUAN_TI_FONTS))
        mat['font_size'] = 10.0
        mat['text_color'] = '#ffffff'
        mat['border_color'] = '#000000'
        mat['border_width'] = 0.08
        # content 里的 font 也替换
        c = mat.get('content', '')
        if isinstance(c, str) and c.startswith('{'):
            try:
                j = json.loads(c)
                for st in j.get('styles', []):
                    st['font'] = {'id': YUAN_TI_FONT_ID, 'path': YUAN_TI_PATH}
                mat['content'] = json.dumps(j, ensure_ascii=False)
            except Exception:
                pass
        bc = mat.get('base_content', '')
        if isinstance(bc, str) and bc.startswith('{'):
            try:
                j = json.loads(bc)
                for st in j.get('styles', []):
                    st['font'] = {'id': YUAN_TI_FONT_ID, 'path': YUAN_TI_PATH}
                mat['base_content'] = json.dumps(j, ensure_ascii=False)
            except Exception:
                pass
        n += 1
    return n


def process_draft(name: str, base: Path, backup: bool = True):
    dp = base / str(name)
    dc = dp / 'draft_content.json'
    if not dc.exists():
        print(f'草稿{name}: 无draft_content.json，跳过')
        return None
    # 判断是否加密：去掉可能的 BOM 后再判断（带 BOM 的明文不能被误判为加密）
    raw = dc.read_bytes()
    plain = raw.lstrip(b'\xef\xbb\xbf')
    is_encrypted = not plain.startswith(b'{')
    try:
        draft = read_draft_json(dc)
    except Exception as e:
        print(f'草稿{name}: 读取失败 {e}')
        return None
    n = replace_font(draft)
    if n == 0:
        print(f'草稿{name}: 无subtitle需替换')
        return 0
    # 备份原始（明文/加密都备份，时间戳命名防覆盖）
    if backup:
        bak = dp / 'draft_content.json.orig'
        if not bak.exists():
            shutil.copy(dc, bak)
            print(f'草稿{name}: 已备份原始到 .orig')
    try:
        write_draft_json(dc, draft, reencrypt=is_encrypted)
        print(f'草稿{name}: 已替换 {n} 条字幕字体→字语圆体（{"加密" if is_encrypted else "明文"}）')
        return n
    except Exception as e:
        print(f'草稿{name}: 写回失败 {e}')
        return None


def main():
    base = Path(r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft')
    drafts = []
    if '--all' in sys.argv:
        drafts = [str(n) for n in range(2, 47)]
    else:
        for a in sys.argv:
            if a.startswith('--drafts='):
                drafts = a.split('=')[1].split(',')
    if not drafts:
        print(__doc__)
        sys.exit(1)
    total = 0
    for name in drafts:
        try:
            r = process_draft(name, base)
            if r:
                total += r
        except Exception as e:
            print(f'草稿{name}: 错误 {e}')
    print(f'\n完成，共替换 {total} 条字幕字体')


if __name__ == '__main__':
    main()
