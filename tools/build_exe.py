import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARGS = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--clean",
    "--onefile",
    "--windowed",
    "--name", "MTBViewer",
    "--icon", os.path.join(ROOT, "deploy", "icons", "mtb.ico"),
    "--paths", ROOT,
    "--hidden-import", "mtcodec.viewer",
    "--hidden-import", "PIL.ImageTk",
    os.path.join(ROOT, "deploy", "mtb_app.py"),
]

print(" ".join(ARGS))
rc = subprocess.call(ARGS, cwd=ROOT)
print("pyinstaller exit", rc)
exe = os.path.join(ROOT, "dist", "MTBViewer.exe")
if os.path.exists(exe):
    print("exe size %.1f MB" % (os.path.getsize(exe) / 1024.0 / 1024.0))
raise SystemExit(rc)
