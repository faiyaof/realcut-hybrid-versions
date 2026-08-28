# -*- coding: utf-8 -*-
"""剪映草稿解密/加密工具（调用 videoeditor.dll 的 EncryptUtils）。
用法:
  python jy_crypt.py decrypt <草稿路径>   # 解密 draft_content.json -> 打印/返回
  python jy_crypt.py encrypt <草稿路径>   # 加密
基于 jy-draftc (wenshui330) 的逆向原理，用 ctypes 调用 DLL。
"""
import ctypes
import ctypes.util
import os
import sys
import json
from pathlib import Path

# 剪映 videoeditor.dll（支持环境变量 JY_DLL 覆盖；默认路径已验证有效）
JY_DLL = os.environ.get(
    'JY_DLL',
    r'C:\Users\JT\Desktop\剪映5.9Windows\JianyingPro\5.9.0.11632\videoeditor.dll',
)

# C++ mangled 导出名
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
    """MSVC std::string 内存布局（x64）: 16字节缓冲 + size + capacity。"""
    _fields_ = [
        ("buf", ctypes.c_byte * 16),
        ("size", ctypes.c_ulonglong),
        ("capacity", ctypes.c_ulonglong),
    ]


# x64 Windows 统一调用约定，用 WINFUNCTYPE（等价于默认）
DecryptFn = ctypes.WINFUNCTYPE(
    ctypes.POINTER(MsvcString),   # return: MsvcString* (out)
    ctypes.c_void_p,              # this
    ctypes.POINTER(MsvcString),   # return-out
    ctypes.POINTER(MsvcString),   # input
    ctypes.POINTER(MsvcString),   # param
    ctypes.POINTER(ctypes.c_bool),  # ok
)
EncryptFn = ctypes.WINFUNCTYPE(
    ctypes.POINTER(MsvcString),
    ctypes.c_void_p,
    ctypes.POINTER(MsvcString),
    ctypes.POINTER(MsvcString),
)
EnableFn = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_bool)


def make_str_arg(data: bytes) -> MsvcString:
    """把 bytes 包装成 MsvcString。超过15字节用堆指针。"""
    s = MsvcString()
    n = len(data)
    if n < 16:
        for i, b in enumerate(data):
            s.buf[i] = b
        s.buf[n] = 0  # null terminator
        s.size = n
        s.capacity = 15
    else:
        buf = ctypes.create_string_buffer(data)
        # 前8字节存指针
        ctypes.memmove(s.buf, ctypes.byref(ctypes.c_void_p(ctypes.addressof(buf))), 8)
        s.size = n
        s.capacity = n
        # 保存引用防GC
        s._buf = buf  # type: ignore
    return s


def get_str(s: MsvcString) -> str:
    """从 MsvcString 提取字符串。"""
    if s.size >= 16:
        ptr = ctypes.c_void_p()
        ctypes.memmove(ctypes.byref(ptr), s.buf, 8)
        raw = ctypes.string_at(ptr, s.size)
    else:
        raw = bytes(s.buf)[:s.size]
    return raw.decode('utf-8', errors='replace')


class JyCrypt:
    def __init__(self, dll_path=JY_DLL):
        if not os.path.exists(dll_path):
            raise FileNotFoundError(f'videoeditor.dll not found: {dll_path}')
        # 加载 DLL（需搜索其依赖目录）
        import ctypes.wintypes
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR = 0x100
        LOAD_LIBRARY_SEARCH_APPLICATION_DIR = 0x200
        LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x800
        LOAD_LIBRARY_SEARCH_USER_DIRS = 0x400
        flags = (LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_APPLICATION_DIR |
                 LOAD_LIBRARY_SEARCH_SYSTEM32 | LOAD_LIBRARY_SEARCH_USER_DIRS)
        # 确保 DLL 目录在搜索路径
        dll_dir = os.path.dirname(dll_path)
        os.add_dll_directory(dll_dir)
        self._dll = ctypes.WinDLL(dll_path, use_last_error=True)
        # 获取函数指针并绑定正确原型
        dec_addr = self._dll[DECRYPT_NAME]
        enc_addr = self._dll[ENCRYPT_NAME]
        enb_addr = self._dll[ENABLE_NAME]
        self._dec = ctypes.cast(dec_addr, DecryptFn)
        self._enc = ctypes.cast(enc_addr, EncryptFn)
        self._enable = ctypes.cast(enb_addr, EnableFn)
        print(f'[OK] 已加载 {os.path.basename(dll_path)}')

    def decrypt(self, data: str) -> str:
        in_arg = make_str_arg(data.encode('utf-8'))
        param_arg = make_str_arg(b'{}')
        out = MsvcString()
        ok = ctypes.c_bool(False)
        self._dec(None, ctypes.byref(out), ctypes.byref(in_arg), ctypes.byref(param_arg), ctypes.byref(ok))
        if not ok.value:
            raise RuntimeError('decrypt failed (ok=false)')
        return get_str(out)

    def encrypt(self, data: str) -> str:
        self._enable(None, True)
        in_arg = make_str_arg(data.encode('utf-8'))
        out = MsvcString()
        self._enc(None, ctypes.byref(out), ctypes.byref(in_arg))
        return get_str(out)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    mode, dp = sys.argv[1], sys.argv[2]
    draft_dir = Path(dp)
    dc = draft_dir / 'draft_content.json'
    raw = dc.read_bytes()
    text = raw.decode('utf-8', errors='replace')

    jy = JyCrypt()
    if mode == 'decrypt':
        result = jy.decrypt(text)
        print(f'解密后长度: {len(result)}')
        print(f'开头: {result[:200]}')
        # 尝试解析JSON
        try:
            j = json.loads(result)
            print(f'[OK] 解密后是有效JSON! keys: {list(j.keys())[:10]}')
        except Exception as e:
            print(f'非JSON: {e}')
        out = draft_dir / 'draft_decrypted.json'
        out.write_text(result, encoding='utf-8')
        print(f'已保存: {out}')
    elif mode == 'encrypt':
        result = jy.encrypt(text)
        out = draft_dir / 'draft_reencrypted.json'
        out.write_text(result, encoding='utf-8')
        print(f'加密后保存: {out} ({len(result)}B)')
    else:
        print('未知模式:', mode)


if __name__ == '__main__':
    main()
