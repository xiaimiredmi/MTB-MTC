import io
import winreg

PATHS = [
    r"Software\Classes\.mtb",
    r"Software\Classes\.mtc",
    r"Software\Classes\MTB.Image",
    r"Software\Classes\MTB.Image\DefaultIcon",
    r"Software\Classes\MTB.Image\shell\open\command",
    r"Software\Classes\MTB.Video",
    r"Software\Classes\MTB.Video\DefaultIcon",
    r"Software\Classes\MTB.Video\shell\open\command",
]

with io.open("reg_check.txt", "w", encoding="utf-8") as f:
    for p in PATHS:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, p) as k:
                val, _ = winreg.QueryValueEx(k, "")
                f.write("%s => %s\n" % (p, val))
        except FileNotFoundError:
            f.write("%s => MISSING\n" % p)
print("done")
