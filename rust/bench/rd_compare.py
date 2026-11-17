"""Compare two codec measurement runs at matched PSNR.

`mtbench` writes one row per (image, quality, mode). Two encoder settings cannot
be compared at the same `-q`: whichever spends more bits looks better. This
script interpolates each curve in log(bytes) against PSNR and reports the byte
difference at the PSNR levels the baseline actually reaches.

usage: python bench/rd_compare.py base.csv alt.csv [--mode ctx] [--alt-mode ctx]
"""

import argparse
import csv
import math
from collections import defaultdict


def load(path):
    curves = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            curves[row["mode"]].append(
                (float(row["psnr"]), int(row["bytes"]), row["image"])
            )
    out = defaultdict(lambda: defaultdict(list))
    for mode, rows in curves.items():
        for psnr, nbytes, image in rows:
            out[mode][image].append((psnr, nbytes))
    for mode in out:
        for image in out[mode]:
            out[mode][image].sort()
    return out


def interp(points, psnr):
    """log-bytes at `psnr`; None when `psnr` is outside the measured range."""
    if len(points) < 2 or psnr < points[0][0] or psnr > points[-1][0]:
        return None
    for (p0, b0), (p1, b1) in zip(points, points[1:]):
        if p0 <= psnr <= p1:
            if p1 == p0:
                return float(b0)
            t = (psnr - p0) / (p1 - p0)
            return math.exp(math.log(b0) + t * (math.log(b1) - math.log(b0)))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("alt")
    ap.add_argument("--mode", default="ctx")
    ap.add_argument("--alt-mode", default=None)
    ap.add_argument("--label", default="alt")
    args = ap.parse_args()

    base = load(args.base)
    alt = load(args.alt)
    bmode = args.mode
    amode = args.alt_mode or bmode
    if bmode not in base or amode not in alt:
        raise SystemExit(f"missing mode: base has {list(base)}, alt has {list(alt)}")

    ratios = []
    print(f"mode {bmode}: {args.label} vs base, bytes at matched PSNR")
    for image in sorted(base[bmode]):
        bpts = base[bmode][image]
        apts = alt[amode].get(image, [])
        print(f"\n{image}")
        print(f"  {'psnr':>6} {'base B':>9} {'alt B':>9} {'delta':>8}")
        for ps, _ in bpts:
            b = interp(bpts, ps)
            a = interp(apts, ps)
            if b is None or a is None:
                continue
            ratios.append(a / b)
            print(f"  {ps:6.2f} {b:9.0f} {a:9.0f} {(a / b - 1) * 100:7.2f}%")

    if ratios:
        gm = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
        print(
            f"\ngeometric mean over {len(ratios)} probes: "
            f"{(gm - 1) * 100:+.2f}% bytes vs baseline"
        )


if __name__ == "__main__":
    main()
