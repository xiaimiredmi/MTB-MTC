import ctypes
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "samples", "demo.mtc")
IMAGE = sys.argv[1] if len(sys.argv) > 1 else "MTBViewer.exe"


def pids(image):
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + image, "/FO", "CSV"],
                         capture_output=True, text=True)
    found = set()
    for line in out.stdout.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) > 1 and parts[1].strip('"').isdigit():
            found.add(int(parts[1].strip('"')))
    return found


shell32 = ctypes.WinDLL("shell32")
before = pids(IMAGE)
rc = shell32.ShellExecuteW(None, "open", TARGET, None, os.path.dirname(TARGET), 1)
print("ShellExecuteW returned", rc, "(>32 means success)")
time.sleep(10)
new = pids(IMAGE) - before
print("new %s processes: %s" % (IMAGE, new))
if new:
    print("launch PASS")
    for pid in new:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
else:
    print("launch FAIL: no %s process appeared" % IMAGE)
