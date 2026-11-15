import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mtcodec import decode_image, encode_image, probe
from mtcodec import io_bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL = r"C:\Users\Administrator\Downloads"
OUTDIR = os.path.join(ROOT, "samples", "converted")


def log(*a):
    print(*a)
    sys.stdout.flush()


def _psnr(a, b):
    a = a[:, :, :3].astype(np.float64)
    b = b[:, :, :3].astype(np.float64)
    mse = float(np.mean((a - b) ** 2))
    return 99.0 if mse == 0 else 10.0 * np.log10(255.0 ** 2 / mse)


rows = []

# 1) 真正的 4 倍 4K：7680x4320
src = os.path.join(DL, "wallpaper_minecraft_bedrock_edition_1920x1080.png")
frames, alpha, ssz = io_bridge.load_image_frames(src, "4x4k")
log("4x4k target -> %dx%d" % (frames[0].shape[1], frames[0].shape[0]))
t0 = time.perf_counter()
blob = encode_image(frames[0], quality=80)
enc = time.perf_counter() - t0
t0 = time.perf_counter()
back = decode_image(blob)
dec = time.perf_counter() - t0
raw = frames[0].size * frames[0].dtype.itemsize
rows.append({"case": "7680x4320 from 1080p", "size": [frames[0].shape[1], frames[0].shape[0]],
             "bytes": len(blob), "ratio": raw / len(blob), "psnr": _psnr(frames[0], back),
             "enc_s": enc, "dec_s": dec})
log("7680x4320 -> mtb %.1f MB  %.2f:1  psnr %.1f  enc %.1f s  dec %.1f s"
    % (len(blob) / 1e6, raw / len(blob), rows[-1]["psnr"], enc, dec))
with open(os.path.join(OUTDIR, "wall_4x4k.mtb"), "wb") as f:
    f.write(blob)

# 2) 竖图 1080x1920 用 1080p 预设
vsrc = os.path.join(DL, "wallpaper_minecraft_bedrock_edition_1080x1920.png")
vf, va, vs = io_bridge.load_image_frames(vsrc, "1080p")
log("portrait 1080x1920 + '1080p' -> %dx%d" % (vf[0].shape[1], vf[0].shape[0]))
blob = encode_image(vf[0], quality=80)
raw = vf[0].size * vf[0].dtype.itemsize
rows.append({"case": "portrait 1080p", "size": [vf[0].shape[1], vf[0].shape[0]],
             "bytes": len(blob), "ratio": raw / len(blob),
             "psnr": _psnr(vf[0], decode_image(blob)), "enc_s": 0.0, "dec_s": 0.0})
log("portrait -> mtb %.1f KB  %.2f:1  psnr %.1f"
    % (len(blob) / 1024.0, raw / len(blob), rows[-1]["psnr"]))

# 3) 800x450 小图放到 8K 看是否吃得下（只编码不复算 psnr 之外的内容）
small = os.path.join(DL, "wallpaper_minecraft_bedrock_edition_800x450.png")
sf, sa, ss = io_bridge.load_image_frames(small, "8k")
log("800x450 + '8k' -> %dx%d" % (sf[0].shape[1], sf[0].shape[0]))
t0 = time.perf_counter()
blob = encode_image(sf[0], quality=80)
enc = time.perf_counter() - t0
rows.append({"case": "800x450 upscaled to 8k", "size": [sf[0].shape[1], sf[0].shape[0]],
             "bytes": len(blob), "ratio": sf[0].size * sf[0].dtype.itemsize / len(blob),
             "psnr": 99.0, "enc_s": enc, "dec_s": 0.0})
log("upscaled 8k -> mtb %.1f MB  enc %.1f s" % (len(blob) / 1e6, enc))

with open(os.path.join(ROOT, "results", "size_extra.json"), "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
log("done")
