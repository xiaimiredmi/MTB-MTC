"""打包 MTBViewer。

用法：
    python tools/build_exe.py             # onefile，单个 exe（发布用，启动要解压，慢）
    python tools/build_exe.py --onedir    # onedir，目录版（日常用，双击秒开）

说明：onefile 每次启动都要把 numpy / Pillow / Tcl-Tk 解压到临时目录，
体积越大越慢；onedir 直接加载目录里的 dll，冷启动通常快数倍。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODE = "onedir" if "--onedir" in sys.argv else "onefile"
BUNDLE = "--onedir" if MODE == "onedir" else "--onefile"

ARGS = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--clean",
    BUNDLE,
    "--windowed",
    "--name", "MTBViewer",
    "--icon", os.path.join(ROOT, "deploy", "icons", "mtb.ico"),
    "--paths", ROOT,
    "--hidden-import", "mtcodec.viewer",
    "--hidden-import", "PIL.ImageTk",
]

NATIVE = os.path.join(ROOT, "mtcodec", "mtfastdec.dll")
if os.path.exists(NATIVE):
    ARGS += ["--add-binary", NATIVE + ";mtcodec"]
    print("native decoder included")
else:
    print("native decoder missing — the player will use the pure Python path")

ARGS.append(os.path.join(ROOT, "deploy", "mtb_app.py"))

print("mode", MODE)
print(" ".join(ARGS))
rc = subprocess.call(ARGS, cwd=ROOT)
print("pyinstaller exit", rc)

if MODE == "onedir":
    exe = os.path.join(ROOT, "dist", "MTBViewer", "MTBViewer.exe")
    root_dir = os.path.join(ROOT, "dist", "MTBViewer")
else:
    exe = os.path.join(ROOT, "dist", "MTBViewer.exe")
    root_dir = None

if os.path.exists(exe):
    print("exe size %.1f MB" % (os.path.getsize(exe) / 1024.0 / 1024.0))
if root_dir and os.path.isdir(root_dir):
    total = 0
    for base, _dirs, files in os.walk(root_dir):
        for name in files:
            total += os.path.getsize(os.path.join(base, name))
    print("bundle size %.1f MB (%s)" % (total / 1024.0 / 1024.0, root_dir))
raise SystemExit(rc)
