"""
secret_store.py - keeps API keys in the Windows Credential Manager (the place where Windows and browsers keep
saved passwords), instead of as plain text in the settings file.

    available()            True on Windows when the store works
    save(name, secret)     returns True when stored
    load(name)             the secret, or ""
    delete(name)

Where the store is not available (other systems, or an error) every function reports that, and the app
falls back to the settings file, as before. Nothing here needs an extra package.
"""
import sys

PREFIX = "PhotoTools/"
CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE = 1, 2
_api = None


def _load():
    """The Windows API, or None."""
    global _api
    if _api is not None:
        return _api or None
    _api = False
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                        ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                        ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                        ("UserName", wintypes.LPWSTR)]

        adv = ctypes.windll.advapi32
        adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
        adv.CredWriteW.restype = wintypes.BOOL
        adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
        adv.CredReadW.restype = wintypes.BOOL
        adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        adv.CredDeleteW.restype = wintypes.BOOL
        adv.CredFree.argtypes = [ctypes.c_void_p]
        _api = (ctypes, CREDENTIAL, adv)
    except Exception:
        _api = False
    return _api or None


def available():
    return _load() is not None


def save(name, secret):
    api = _load()
    if not api or not secret:
        return False
    ctypes, CREDENTIAL, adv = api
    try:
        blob = secret.encode("utf-16-le")
        buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = CREDENTIAL()
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = PREFIX + name
        cred.UserName = name
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        return bool(adv.CredWriteW(ctypes.byref(cred), 0))
    except Exception:
        return False


def load(name):
    api = _load()
    if not api:
        return ""
    ctypes, CREDENTIAL, adv = api
    try:
        p = ctypes.POINTER(CREDENTIAL)()
        if not adv.CredReadW(PREFIX + name, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
            return ""
        try:
            c = p.contents
            return bytes(c.CredentialBlob[:c.CredentialBlobSize]).decode("utf-16-le")
        finally:
            adv.CredFree(p)
    except Exception:
        return ""


def delete(name):
    api = _load()
    if not api:
        return False
    try:
        return bool(api[2].CredDeleteW(PREFIX + name, CRED_TYPE_GENERIC, 0))
    except Exception:
        return False
