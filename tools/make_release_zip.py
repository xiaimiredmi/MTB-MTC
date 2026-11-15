# -*- coding: utf-8 -*-
"""打 GitHub 发布包：整个仓库文本（含 docs、README、CI），排除二进制与缓存。

    python tools/make_release_zip.py
-> release/MTB-MTC-v1.2.1.zip
"""
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP = "MTB-MTC-v1.2.1"
OUT = os.path.join(ROOT, "release", TOP + ".zip")

SKIP_DIRS = {"__pycache__", "_shots", "build", "dist", "release", ".git",
             ".venv", "venv", "node_modules"}
SKIP_EXT = {".pyc", ".pyo", ".log", ".exe", ".zip"}
SKIP_NAMES = {"Thumbs.db", "desktop.ini", ".DS_Store"}
KEEP_ROOT_TXT = {"打包与安装说明.txt"}


def main():
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name in SKIP_NAMES:
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in SKIP_EXT:
                continue
            if dirpath == ROOT and ext == ".txt" and name not in KEEP_ROOT_TXT:
                continue  # 根目录只保留发布说明，运行日志不进包
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            files.append((p, TOP + "/" + rel))
    files.sort(key=lambda t: t[1])

    if os.path.exists(OUT):
        os.remove(OUT)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src, arc in files:
            zf.write(src, arc)

    # 立刻自检 CRC
    with zipfile.ZipFile(OUT) as zf:
        bad = zf.testzip()
    size = os.path.getsize(OUT) / 1024.0 / 1024.0
    print("entries=%d  size=%.1f MB  crc=%s" % (len(files), size, "ok" if bad is None else bad))
    print(OUT)


if __name__ == "__main__":
    main()
