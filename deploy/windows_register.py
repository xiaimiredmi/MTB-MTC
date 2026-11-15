import os
import sys
import winreg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.join(ROOT, "deploy", "mtb_launcher.py")
ICON_DIR = os.path.join(ROOT, "deploy", "icons")

TYPES = [
    {
        "ext": ".mtb",
        "progid": "MTB.Image",
        "label": "MTB 图像",
        "mime": "image/x-mtb",
        "perceived": "image",
        "icon": os.path.join(ICON_DIR, "mtb.ico"),
    },
    {
        "ext": ".mtc",
        "progid": "MTB.Video",
        "label": "MTB 视频",
        "mime": "video/x-mtc",
        "perceived": "video",
        "icon": os.path.join(ICON_DIR, "mtc.ico"),
    },
]


def _arg(flag, default=None):
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def open_command():
    exe = _arg("--exe")
    if exe:
        return '"%s" "%%1"' % os.path.abspath(exe)
    return '"%s" "%s" "%%1"' % (pythonw(), LAUNCHER)


def pythonw():
    exe = _arg("--python")
    if exe:
        return _as_windowless(exe)
    return _as_windowless(sys.executable)


def _as_windowless(exe):
    if exe.lower().endswith("python.exe"):
        cand = exe[:-10] + "pythonw.exe"
        if os.path.exists(cand):
            return cand
    return exe


def set_value(path, name, value):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def register():
    cmd = open_command()
    for t in TYPES:
        if not os.path.exists(t["icon"]):
            raise SystemExit("missing icon: %s" % t["icon"])
        set_value(r"Software\Classes\%s" % t["ext"], "", t["progid"])
        set_value(r"Software\Classes\%s" % t["ext"], "Content Type", t["mime"])
        base = r"Software\Classes\%s" % t["progid"]
        set_value(base, "", t["label"])
        set_value(base, "FriendlyTypeName", t["label"])
        set_value(base + r"\DefaultIcon", "", t["icon"])
        set_value(base + r"\shell\open", "", "打开")
        set_value(base + r"\shell\open\command", "", cmd)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
            winreg.SetValueEx(key, "PerceivedType", 0, winreg.REG_SZ, t["perceived"])
        print("registered %s -> %s" % (t["ext"], t["progid"]))
    print("command: %s" % cmd)
    print("icon:    %s" % ICON_DIR)


def unregister():
    for t in TYPES:
        for path in (r"Software\Classes\%s" % t["ext"], r"Software\Classes\%s" % t["progid"]):
            for sub in ("", r"\DefaultIcon", r"\shell\open\command", r"\shell\open"):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path + sub)
                except FileNotFoundError:
                    pass
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except (FileNotFoundError, OSError):
                pass
        print("removed %s" % t["ext"])


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("this script only runs on Windows")
    if "--unregister" in sys.argv:
        unregister()
    else:
        register()
