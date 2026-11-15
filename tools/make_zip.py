import io
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP = "MTB-MTC-encoder-v1.2"
OUT = os.path.join(ROOT, TOP + ".zip")

INCLUDE_DIRS = ["mtcodec", "deploy", "tools", "samples", "assets", "tests",
                "testdata", "bench", "results", "dist"]
INCLUDE_FILES = ["编码器实验报告.html", "格式互转与多分辨率测试报告.html",
                 "打包与安装说明.txt"]
SKIP_DIRS = {"__pycache__", "build", "_shots"}
SKIP_EXT = {".pyc", ".pyo", ".log"}


def add_file(zf, path, arcname):
    zf.write(path, arcname)


def collect(rel, files):
    full = os.path.join(ROOT, rel)
    if os.path.isdir(full):
        for dirpath, dirnames, filenames in os.walk(full):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if os.path.splitext(name)[1].lower() in SKIP_EXT:
                    continue
                p = os.path.join(dirpath, name)
                r = os.path.relpath(p, ROOT).replace("\\", "/")
                files.append((p, TOP + "/" + r))
    elif os.path.isfile(full):
        files.append((full, TOP + "/" + rel))


def main():
    # 说明文件存成 UTF-8 BOM，Windows 记事本才不会把中文显示成方块
    txt = os.path.join(ROOT, "打包与安装说明.txt")
    text = io.open(txt, encoding="utf-8-sig").read()
    io.open(txt, "w", encoding="utf-8-sig", newline="\r\n").write(text)

    files = []
    for rel in INCLUDE_DIRS + INCLUDE_FILES:
        collect(rel, files)

    if os.path.exists(OUT):
        os.remove(OUT)
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src, arc in files:
            add_file(zf, src, arc)
    size = os.path.getsize(OUT) / 1024.0 / 1024.0
    print("entries", len(files))
    print("zip", OUT, "%.1f MB" % size)


if __name__ == "__main__":
    main()
