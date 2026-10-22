"""Windows Credential Manager storage; no API keys in settings or plain files."""
import ctypes
import hashlib
import os
from ctypes import wintypes


def target(provider, base_url):
    suffix = hashlib.sha256((provider + "|" + base_url.rstrip("/")).encode()).hexdigest()[:32]
    return "IngeCAD/AI/" + suffix


class Credential(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)), ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


def api():
    if os.name != "nt":
        raise RuntimeError("Persistent keys require Windows Credential Manager; use a session-only key")
    lib = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    lib.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    lib.CredWriteW.restype = wintypes.BOOL
    lib.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
    lib.CredReadW.restype = wintypes.BOOL
    lib.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    lib.CredDeleteW.restype = wintypes.BOOL
    lib.CredFree.argtypes = [ctypes.c_void_p]
    return lib


def save(name, key):
    raw = key.encode("utf-8")
    if not raw or len(raw) > 2560:
        raise ValueError("API key must contain 1..2560 bytes")
    blob = (wintypes.BYTE * len(raw)).from_buffer_copy(raw)
    credential = Credential()
    credential.Type, credential.TargetName, credential.Persist = 1, name, 2
    credential.CredentialBlobSize, credential.CredentialBlob = len(raw), blob
    credential.UserName = "IngeCAD AI"
    if not api().CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def load(name):
    pointer = ctypes.POINTER(Credential)()
    lib = api()
    if not lib.CredReadW(name, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return ""
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        c = pointer.contents
        return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-8")
    finally:
        lib.CredFree(pointer)


def delete(name):
    if not api().CredDeleteW(name, 1, 0) and ctypes.get_last_error() != 1168:
        raise ctypes.WinError(ctypes.get_last_error())
