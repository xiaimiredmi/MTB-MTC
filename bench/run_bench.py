import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from mtcodec import decode_image, encode_image, psnr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "testdata")
OUT = os.path.join(ROOT, "results")
QUALITIES = [5, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
TARGETS = [30.0, 33.0, 36.0, 39.0, 42.0]


def bpp(nbytes, h, w):
    return nbytes * 8.0 / (h * w)


def pil_size(arr, fmt, **kw):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format=fmt, **kw)
    return len(buf.getvalue()), buf.getvalue()


def run_image(name, arr):
    h, w = arr.shape[:2]
    rows = []

    for q in QUALITIES:
        for sub in ("420", "444"):
            t0 = time.perf_counter()
            blob = encode_image(arr, quality=q, subsample=sub)
            enc = time.perf_counter() - t0
            t0 = time.perf_counter()
            back = decode_image(blob)
            dec = time.perf_counter() - t0
            rows.append({
                "codec": f"pyc1-{sub}",
                "quality": q,
                "bytes": len(blob),
                "bpp": bpp(len(blob), h, w),
                "psnr": psnr(arr, back),
                "enc_s": enc,
                "dec_s": dec,
            })

    for q in QUALITIES:
        size, data = pil_size(arr, "JPEG", quality=q)
        back = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
        rows.append({"codec": "jpeg", "quality": q, "bytes": size,
                     "bpp": bpp(size, h, w), "psnr": psnr(arr, back)})
        size, data = pil_size(arr, "JPEG", quality=q, subsampling=0)
        back = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
        rows.append({"codec": "jpeg444", "quality": q, "bytes": size,
                     "bpp": bpp(size, h, w), "psnr": psnr(arr, back)})
        size, data = pil_size(arr, "WEBP", quality=q, method=4)
        back = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
        rows.append({"codec": "webp", "quality": q, "bytes": size,
                     "bpp": bpp(size, h, w), "psnr": psnr(arr, back)})

    size, data = pil_size(arr, "PNG", optimize=True)
    rows.append({"codec": "png", "quality": 100, "bytes": size, "bpp": bpp(size, h, w), "psnr": 99.0})

    t0 = time.perf_counter()
    blob = encode_image(arr, lossless=True)
    enc = time.perf_counter() - t0
    t0 = time.perf_counter()
    back = decode_image(blob)
    dec = time.perf_counter() - t0
    rows.append({"codec": "pyc1-lossless", "quality": 100, "bytes": len(blob),
                 "bpp": bpp(len(blob), h, w), "psnr": 99.0,
                 "exact": bool(np.array_equal(arr, back)), "enc_s": enc, "dec_s": dec})

    for r in rows:
        r["image"] = name
        r["w"] = w
        r["h"] = h
    return rows


def matched(rows, codec, target, key="psnr"):
    pts = sorted([(r[key], r["bpp"]) for r in rows if r["codec"] == codec], key=lambda p: p[0])
    if not pts:
        return None
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if x0 <= target <= x1 and x1 > x0:
            t = (target - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    names = sorted(f[:-4] for f in os.listdir(ASSETS) if f.endswith(".png") and not f.startswith("frame"))
    all_rows = []
    for name in names:
        arr = np.array(Image.open(os.path.join(ASSETS, name + ".png")).convert("RGB"))
        rows = run_image(name, arr)
        all_rows.extend(rows)
        print(f"{name} done", flush=True)

    with open(os.path.join(OUT, "image_results.json"), "w", encoding="utf-8") as f:
        json.dump([{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in all_rows],
                  f, indent=1)

    codecs = ["pyc1-420", "pyc1-444", "jpeg", "jpeg444", "webp"]
    table = []
    for target in TARGETS:
        for name in names:
            rows = [r for r in all_rows if r["image"] == name]
            entry = {"image": name, "target_psnr": target}
            for c in codecs:
                entry[c] = matched(rows, c, target)
            table.append(entry)

    with open(os.path.join(OUT, "matched_psnr.json"), "w", encoding="utf-8") as f:
        json.dump([{k: (round(v, 4) if isinstance(v, float) else v) for k, v in e.items()} for e in table],
                  f, indent=1)

    lines = ["| image | psnr | " + " | ".join(codecs) + " |",
             "|---|---|" + "---|" * len(codecs)]
    for e in table:
        cells = []
        for c in codecs:
            v = e[c]
            cells.append("n/a" if v is None else f"{v:.3f}")
        lines.append(f"| {e['image']} | {e['target_psnr']:.0f} dB | " + " | ".join(cells) + " |")
    report = "\n".join(lines)
    with open(os.path.join(OUT, "matched_table.md"), "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(report)

    gap = []
    for e in table:
        if e["pyc1-420"] and e["jpeg"]:
            gap.append({"image": e["image"], "psnr": e["target_psnr"],
                        "our_bpp": e["pyc1-420"], "jpeg_bpp": e["jpeg"],
                        "gain_pct": (e["jpeg"] - e["pyc1-420"]) / e["jpeg"] * 100})
    with open(os.path.join(OUT, "jpeg_gain.json"), "w", encoding="utf-8") as f:
        json.dump(gap, f, indent=1)
    if gap:
        print(f"mean gain vs jpeg: {np.mean([g['gain_pct'] for g in gap]):.1f}%")


if __name__ == "__main__":
    main()
