# -*- coding: utf-8 -*-
"""发布目录自检：配置可解析、文档引用可命中、忽略规则生效、关键文件齐全。

    python tools/check_release.py
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
errors = []
notes = []

# 1) pyproject 可解析
try:
    import tomllib
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
        cfg = tomllib.load(f)
    notes.append("pyproject ok  name=%s version=%s scripts=%s" % (
        cfg["project"]["name"], cfg["project"]["version"],
        list(cfg["project"].get("scripts", {}))))
except FileNotFoundError:
    errors.append("pyproject.toml missing")
except Exception as exc:
    errors.append("pyproject: %s: %s" % (type(exc).__name__, exc))

# 2) workflow 形状
wf = os.path.join(ROOT, ".github", "workflows", "release.yml")
try:
    text = io.open(wf, encoding="utf-8").read()
    if "\t" in text:
        errors.append("workflow: tab characters present")
    for key in ("on:", "jobs:", "runs-on:", "upload-artifact@"):
        if key not in text:
            errors.append("workflow missing %s" % key)
    notes.append("workflow ok  lines=%d" % len(text.splitlines()))
except Exception as exc:
    errors.append("workflow: %s: %s" % (type(exc).__name__, exc))

# 3) README 里的相对链接
LINK = re.compile(r"\[[^\]]*\]\((?!https?://|#)([^)]+)\)")
checked = 0
for name in ("README.md", "README.zh-CN.md", "CHANGELOG.md"):
    path = os.path.join(ROOT, name)
    if not os.path.isfile(path):
        errors.append("missing %s" % name)
        continue
    body = io.open(path, encoding="utf-8").read()
    for target in LINK.findall(body):
        rel = target.split("#")[0].strip()
        if not rel:
            continue
        checked += 1
        if not os.path.exists(os.path.normpath(os.path.join(ROOT, rel))):
            errors.append("%s -> missing %s" % (name, rel))
notes.append("readme links checked=%d" % checked)

# 4) docs 双语与篇幅
for name in ("FORMAT.md", "CONVERT.md", "BUILD.md", "PUBLISH.md"):
    path = os.path.join(ROOT, "docs", name)
    if not os.path.isfile(path):
        errors.append("missing docs/%s" % name)
        continue
    body = io.open(path, encoding="utf-8").read()
    if len(body) < 4000:
        errors.append("docs/%s too short (%d bytes)" % (name, len(body)))
    if "中文" not in body:
        errors.append("docs/%s missing 中文 section" % name)

# 5) 忽略规则
igp = os.path.join(ROOT, ".gitignore")
if os.path.isfile(igp):
    ig = io.open(igp, encoding="utf-8").read()
    for pat in ("__pycache__/", "release/*.exe", "release/*.zip", "dist/"):
        if pat not in ig:
            errors.append(".gitignore missing %s" % pat)
else:
    errors.append(".gitignore missing")

# 6) 关键文件
need = [
    "README.md", "README.zh-CN.md", "LICENSE", "CHANGELOG.md",
    "pyproject.toml", "requirements.txt",
    "mtcodec/__init__.py", "mtcodec/cli.py", "mtcodec/viewer.py",
    "mtcodec/image_codec.py", "mtcodec/video_codec.py", "mtcodec/io_bridge.py",
    "tools/batch_convert.py", "tools/build_exe.py", "tools/make_icons.py",
    "samples/photo_c.mtb", "samples/mtc_audio.mtc",
    "docs/FORMAT.md", "docs/CONVERT.md", "docs/BUILD.md", "docs/PUBLISH.md",
    ".github/workflows/release.yml",
]
for rel in need:
    if not os.path.isfile(os.path.join(ROOT, *rel.split("/"))):
        errors.append("missing file %s" % rel)

# 7) 体积
text_bytes = 0
bin_bytes = 0
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d != "__pycache__"]
    for f in filenames:
        sz = os.path.getsize(os.path.join(dirpath, f))
        if sz > 10 * 1024 * 1024:
            bin_bytes += sz
        else:
            text_bytes += sz
notes.append("source+docs=%.2f MB  binaries=%.2f MB" % (
    text_bytes / 1048576.0, bin_bytes / 1048576.0))

print("\n".join(notes))
print("")
print("ERRORS=%d" % len(errors))
for e in errors:
    print("  " + e)
sys.exit(1 if errors else 0)
