"""Register the Rust toolchain and the MTBViewer shim on the user PATH.

This is the missing companion to ``windows_register.py``, which only handles
file associations. Both registrations are idempotent and act on the *User*
environment only, so no elevation is needed.

    python deploy/add_to_path.py
    python deploy/add_to_path.py --unregister

The PATH value lives under ``HKCU\\Environment``; it is written with the same
type it already had and a ``WM_SETTINGCHANGE`` broadcast asks Explorer to pick
it up without a reboot.
"""

import ctypes
import os
import sys
import winreg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARGO_BIN = os.path.join(os.path.expanduser("~"), ".cargo", "bin")
SHIM_DIR = os.path.join(os.path.expanduser("~"), "bin")
SHIM_NAME = "MTBViewer.cmd"
ENV_KEY = "Environment"
# Build output directories must never sit on PATH: a rebuild replaces the
# binary and an old copy would keep winning the lookup.
STALE_ENTRIES = (
    os.path.join(ROOT, "release", "viewer"),
    os.path.join(ROOT, "dist"),
)


def _arg(flag, default=None):
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _read_path():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ENV_KEY, 0, winreg.KEY_READ) as key:
            value, kind = winreg.QueryValueEx(key, "Path")
            return value, kind
    except FileNotFoundError:
        return "", winreg.REG_EXPAND_SZ


def _broadcast():
    try:
        hwnd_broadcast = 0xFFFF
        wm_settingchange = 0x001A
        smto_abortifhung = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast, wm_settingchange, 0, "Environment",
            smto_abortifhung, 5000, ctypes.byref(result))
    except Exception:
        pass


def _write_path(value, kind):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, ENV_KEY) as key:
        winreg.SetValueEx(key, "Path", 0, kind, value)
    _broadcast()


def _entries(path):
    seen = set()
    out = []
    for part in (path or "").split(";"):
        part = part.strip()
        if not part:
            continue
        key = part.rstrip("\\").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(part)
    return out


def _key(entry):
    return entry.rstrip("\\").lower()


def _add(path, entry):
    entries = _entries(path)
    if any(_key(e) == _key(entry) for e in entries):
        return path, False
    entries.append(entry)
    return ";".join(entries), True


def _remove(path, entry):
    entries = [e for e in _entries(path) if _key(e) != _key(entry)]
    return ";".join(entries), len(entries) != len(_entries(path))


def _show(path):
    print("user PATH entries:")
    for entry in _entries(path):
        print("  %s" % entry)


def _write_shim(exe):
    os.makedirs(SHIM_DIR, exist_ok=True)
    shim = os.path.join(SHIM_DIR, SHIM_NAME)
    content = '@echo off\r\n"{0}" %*\r\n'.format(exe)
    with open(shim, "w", encoding="ascii", newline="") as f:
        f.write(content)
    return shim


def register():
    exe = os.path.abspath(_arg("--exe", os.path.join(ROOT, "dist", "MTBViewer.exe")))
    if not os.path.exists(exe):
        raise SystemExit("missing packaged viewer: %s" % exe)
    shim = _write_shim(exe)
    path, kind = _read_path()
    for stale in STALE_ENTRIES:
        path, removed = _remove(path, stale)
        if removed:
            print("pruned build path: %s" % stale)
    path, added_cargo = _add(path, CARGO_BIN)
    path, added_shim = _add(path, SHIM_DIR)
    _write_path(path, kind)
    print("shim:  %s" % shim)
    print("cargo: %s" % ("added" if added_cargo else "already on PATH"))
    print("viewer: %s" % ("added" if added_shim else "already on PATH"))
    _show(path)


def unregister():
    path, kind = _read_path()
    path, removed_cargo = _remove(path, CARGO_BIN)
    path, removed_shim = _remove(path, SHIM_DIR)
    _write_path(path, kind)
    shim = os.path.join(SHIM_DIR, SHIM_NAME)
    if os.path.exists(shim):
        os.remove(shim)
    try:
        os.rmdir(SHIM_DIR)
    except OSError:
        pass
    print("cargo: %s" % ("removed" if removed_cargo else "not present"))
    print("viewer: %s" % ("removed" if removed_shim else "not present"))
    _show(path)


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("this script only runs on Windows")
    if "--unregister" in sys.argv:
        unregister()
    else:
        register()
