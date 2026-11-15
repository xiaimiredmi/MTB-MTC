import os
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL = r"C:\Users\Administrator\Downloads"
OUT = os.path.join(ROOT, "samples", "converted")
os.makedirs(OUT, exist_ok=True)

# 造一张带透明通道的 PNG（圆形渐隐），用来演示 CLI 处理 alpha
src = os.path.join(DL, "wallpaper_minecraft_bedrock_edition_1920x1080.png")
arr = np.array(Image.open(src).convert("RGB").resize((960, 540), Image.LANCZOS))
h, w = arr.shape[:2]
yy, xx = np.mgrid[0:h, 0:w]
r = min(h, w) / 2.6
dist = np.sqrt((yy - h / 2.0) ** 2 + (xx - w / 2.0) ** 2)
alpha = np.clip((r - dist) / 2.0, 0, 255).astype(np.uint8)
rgba = np.dstack([arr, alpha])
png = os.path.join(OUT, "alpha_demo.png")
Image.fromarray(rgba, mode="RGBA").save(png)
print("made", png, rgba.shape)

CMDS = [
    ["-m", "mtcodec", "convert", os.path.join(DL, "wallpaper_minecraft_bedrock_edition_2048x2048.png"),
     os.path.join(OUT, "wall_2048.mtb"), "-q", "80"],
    ["-m", "mtcodec", "convert", png, os.path.join(OUT, "alpha_demo.mtb"), "-q", "85"],
    ["-m", "mtcodec", "convert", os.path.join(DL, "11月13日.mp4"),
     os.path.join(OUT, "mtc_audio.mtc"), "--size", "720p", "--fps", "12", "--max-frames", "12"],
    ["-m", "mtcodec", "export", os.path.join(OUT, "wall_2048.mtb"), os.path.join(OUT, "wall_2048_back.jpg")],
    ["-m", "mtcodec", "export", os.path.join(OUT, "mtc_audio.mtc"), os.path.join(OUT, "mtc_audio_back.mp4")],
    ["-m", "mtcodec", "info", os.path.join(OUT, "wall_2048.mtb")],
    ["-m", "mtcodec", "info", os.path.join(OUT, "mtc_audio.mtc")],
]

for args in CMDS:
    full = [sys.executable, "-X", "utf8"] + args
    res = subprocess.run(full, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    print("$ mtcodec " + " ".join(args[2:]))
    print(res.stdout.strip())
    if res.stderr.strip():
        print("ERR", res.stderr.strip()[:500])
    print("exit", res.returncode)
    print("-" * 60)
