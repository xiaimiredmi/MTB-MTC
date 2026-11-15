import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["MTCODEC_VIEWER_AUTOCLOSE_MS"] = "1500"

from mtcodec.viewer import open_path

TARGETS = [
    "samples/photo_c.mtb",
    "samples/demo.mtc",
    "samples/converted/wall_2048.mtb",
    "samples/converted/alpha_demo.mtb",
    "samples/converted/mtc_audio.mtc",
]

for name in TARGETS:
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        print("skip (missing)", name)
        continue
    print("open", name, "->", open_path(path))
print("viewer PASS")
