"""Per-user runtime settings protected with Windows DPAPI."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any, MutableMapping


SCHEMA_VERSION = 1
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
_SECRET_FIELDS = {
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "dashscope_api_key": "DASHSCOPE_API_KEY",
}
_MANAGED_ENV = (*_SECRET_FIELDS.values(), "DEEPSEEK_MODEL")
_INITIAL_ENV = {name: os.environ.get(name) for name in _MANAGED_ENV}
_ENTROPY = b"RealCutHybrid/runtime-settings/v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def settings_path() -> Path:
    override = os.environ.get("REALCUT_SETTINGS_FILE", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "RealCutHybrid" / "settings.json"


def _blob(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    value = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return value, buffer


def _native_apis() -> tuple[Any, Any]:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _protect_secret(value: str) -> str:
    if sys.platform != "win32":
        raise RuntimeError("API Key 加密仅支持 Windows")
    source, source_buffer = _blob(value.encode("utf-8"))
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DataBlob()
    crypt32, kernel32 = _native_apis()
    ok = crypt32.CryptProtectData(
        ctypes.byref(source),
        "RealCut Hybrid API setting",
        ctypes.byref(entropy),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output),
    )
    # Keep the buffers alive through the native call.
    del source_buffer, entropy_buffer
    if not ok:
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(output.pbData, output.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def _unprotect_secret(value: str) -> str:
    if sys.platform != "win32":
        raise RuntimeError("API Key 解密仅支持 Windows")
    try:
        encrypted = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("加密设置格式无效") from exc
    source, source_buffer = _blob(encrypted)
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DataBlob()
    crypt32, kernel32 = _native_apis()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        ctypes.byref(entropy),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output),
    )
    del source_buffer, entropy_buffer
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def _read_document() -> dict[str, Any]:
    path = settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_runtime_settings() -> dict[str, str]:
    document = _read_document()
    settings: dict[str, str] = {}
    for field in _SECRET_FIELDS:
        protected = document.get(field)
        if not isinstance(protected, str) or not protected:
            continue
        try:
            secret = _unprotect_secret(protected)
        except (OSError, RuntimeError, ValueError, UnicodeError):
            continue
        if secret:
            settings[field] = secret
    model = document.get("deepseek_model")
    if isinstance(model, str) and model.strip():
        settings["deepseek_model"] = model.strip()
    return settings


def _normalize_secret(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("API Key 必须是文本")
    value = value.strip()
    if not value:
        return ""
    if len(value) > 4096 or any(char in value for char in "\r\n\x00"):
        raise ValueError("API Key 格式无效")
    return value


def _normalize_model(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("模型名称必须是文本")
    value = value.strip()
    if not value:
        return DEFAULT_DEEPSEEK_MODEL
    if len(value) > 100 or any(char.isspace() for char in value):
        raise ValueError("模型名称格式无效")
    return value


def save_runtime_settings(settings: dict[str, str]) -> None:
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "protection": "windows-dpapi-current-user",
        "deepseek_model": _normalize_model(
            settings.get("deepseek_model", DEFAULT_DEEPSEEK_MODEL)
        ),
    }
    for field in _SECRET_FIELDS:
        secret = _normalize_secret(settings.get(field, ""))
        if secret:
            document[field] = _protect_secret(secret)

    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def update_runtime_settings(payload: dict[str, Any]) -> dict[str, str]:
    settings = load_runtime_settings()
    if payload.get("clear_keys") is True:
        for field in _SECRET_FIELDS:
            settings.pop(field, None)
    else:
        for field in _SECRET_FIELDS:
            if field not in payload:
                continue
            secret = _normalize_secret(payload[field])
            if secret:
                settings[field] = secret
    if "deepseek_model" in payload:
        settings["deepseek_model"] = _normalize_model(payload["deepseek_model"])
    settings.setdefault("deepseek_model", DEFAULT_DEEPSEEK_MODEL)
    save_runtime_settings(settings)
    return settings


def apply_runtime_settings(
    env: MutableMapping[str, str] | None = None,
) -> MutableMapping[str, str]:
    target = os.environ if env is None else env
    settings = load_runtime_settings()
    for field, env_name in _SECRET_FIELDS.items():
        value = settings.get(field) or _INITIAL_ENV.get(env_name)
        if value:
            target[env_name] = value
        else:
            target.pop(env_name, None)
    model = (
        settings.get("deepseek_model")
        or _INITIAL_ENV.get("DEEPSEEK_MODEL")
        or DEFAULT_DEEPSEEK_MODEL
    )
    target["DEEPSEEK_MODEL"] = model
    return target


def masked_settings_payload() -> dict[str, Any]:
    settings = load_runtime_settings()

    def status(field: str, env_name: str) -> dict[str, Any]:
        if settings.get(field):
            return {"configured": True, "source": "本机加密设置"}
        if _INITIAL_ENV.get(env_name):
            return {"configured": True, "source": "Windows 环境变量"}
        return {"configured": False, "source": "未配置"}

    return {
        "deepseek_api_key": status("deepseek_api_key", "DEEPSEEK_API_KEY"),
        "dashscope_api_key": status("dashscope_api_key", "DASHSCOPE_API_KEY"),
        "deepseek_model": (
            settings.get("deepseek_model")
            or _INITIAL_ENV.get("DEEPSEEK_MODEL")
            or DEFAULT_DEEPSEEK_MODEL
        ),
        "storage": "Windows DPAPI（当前用户）",
    }
