import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from mtcodec import decode_video, encode_video, psnr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "testdata")
OUT = os.path.join(ROOT, "results")
NFRAMES = 24


def scene_static(base):
    frames = []
    h, w = base.shape[:2]
    for i in range(NFRAMES):
        frame = base.copy()
        box = 96
        cx = 30 + i * 14
        cy = 210 + int(18 * np.sin(i / 3.0))
        x0, x1 = min(cx, w - 1), min(cx + box, w)
        y0, y1 = min(cy, h - 1), min(cy + box, h)
        frame[y0:y1, x0:x1] = np.array([238, 242, 246], np.uint8)
        frame[y0 + 10 : y1 - 10, x0 + 10 : x1 - 10] = np.array([52, 96, 148], np.uint8)
        frames.append(frame)
    return frames


def scene_pan(base):
    frames = []
    for i in range(NFRAMES):
        frames.append(np.roll(base, 3 * i, axis=1))
    return frames


def run_scene(name, frames):
    h, w = frames[0].shape[:2]
    raw = len(frames) * h * w * 3
    out = []
    for quality, gop in ((80, 12), (80, 0), (60, 12)):
        coll = {}
        t0 = time.perf_counter()
        blob = encode_video(frames, quality=quality, subsample="420", gop=gop, collect=coll)
        enc_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        back, stats = decode_video(blob)
        dec_s = time.perf_counter() - t0
        psnrs = [psnr(frames[i], back[i]) for i in range(len(frames))]
        rec = {
            "scene": name,
            "codec": "pycv",
            "quality": quality,
            "gop": gop,
            "bytes": len(blob),
            "ratio": raw / len(blob),
            "psnr_mean": float(np.mean(psnrs)),
            "psnr_min": float(np.min(psnrs)),
            "enc_s": enc_s,
            "dec_s": dec_s,
            "enc_fps": len(frames) / enc_s,
            "dec_fps": len(frames) / dec_s,
            "frame_bytes": [s["bytes"] for s in stats],
            "frame_types": [s["type"] for s in stats],
        }
        out.append(rec)
        print(f"{name} pycv q{quality} gop{gop}: {len(blob)} B ratio {raw / len(blob):.2f}x "
              f"psnr {np.mean(psnrs):.2f} enc {enc_s:.2f}s", flush=True)

    for quality in (80,):
        total = 0
        psnrs = []
        sizes = []
        for fr in frames:
            buf = io.BytesIO()
            Image.fromarray(fr).save(buf, format="JPEG", quality=quality)
            total += buf.tell()
            sizes.append(buf.tell())
            back = np.array(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))
            psnrs.append(psnr(fr, back))
        out.append({
            "scene": name, "codec": "mjpeg", "quality": quality, "gop": 0,
            "bytes": total, "ratio": raw / total,
            "psnr_mean": float(np.mean(psnrs)), "psnr_min": float(np.min(psnrs)),
            "frame_bytes": sizes, "frame_types": ["i"] * len(frames),
        })
        print(f"{name} mjpeg q{quality}: {total} B ratio {raw / total:.2f}x psnr {np.mean(psnrs):.2f}", flush=True)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    base = np.array(Image.open(os.path.join(ASSETS, "photo_a.png")).convert("RGB"))
    runs = []
    runs += run_scene("fixed_camera", scene_static(base))
    runs += run_scene("panning_camera", scene_pan(base))
    with open(os.path.join(OUT, "video_results.json"), "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=1)
    print("saved")


if __name__ == "__main__":
    main()
