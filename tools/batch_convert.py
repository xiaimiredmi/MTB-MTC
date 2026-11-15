# -*- coding: utf-8 -*-
"""批量把一整个目录的图片 / 视频转成 .mtb / .mtc（或反向导回主流格式）。

用法：
    python tools/batch_convert.py <输入目录> [--out 输出目录]
        [-q 80] [-s 420] [--lossless] [--size 1080p]
        [--fps 12] [--gop 12] [--max-frames 24] [--start 0]
        [--no-audio] [--export] [--overwrite] [--quiet]

示例：
    python tools/batch_convert.py D:\\pics --out D:\\pics\\mtb
    python tools/batch_convert.py D:\\video --size 720p --fps 10 --max-frames 20
    python tools/batch_convert.py D:\\pics\\mtb --export --out D:\\pics\\back
"""
import argparse
import os
import sys
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mtcodec import cli, io_bridge  # noqa: E402

IMAGE_IN = tuple(io_bridge.IMAGE_EXTS)
VIDEO_IN = tuple(io_bridge.VIDEO_EXTS)


def scan(folder, export_mode):
    names = sorted(os.listdir(folder))
    hits = []
    for name in names:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if export_mode:
            if ext in (".mtb", ".mtc"):
                hits.append(path)
        else:
            if ext in IMAGE_IN or ext in VIDEO_IN:
                hits.append(path)
    return hits


def target_name(path, export_mode):
    stem = os.path.splitext(os.path.basename(path))[0]
    if export_mode:
        with open(path, "rb") as f:
            head = f.read(4)
        return stem + (".png" if head == b"MTB1" else ".mp4")
    ext = os.path.splitext(path)[1].lower()
    return stem + (".mtb" if ext in IMAGE_IN else ".mtc")


def main(argv=None):
    ap = argparse.ArgumentParser(description="batch convert images / videos to .mtb / .mtc")
    ap.add_argument("input", help="folder to scan")
    ap.add_argument("--out", default=None, help="output folder (default: <input>\\converted)")
    ap.add_argument("-q", "--quality", type=int, default=80)
    ap.add_argument("-s", "--subsample", choices=["420", "444"], default="420")
    ap.add_argument("--lossless", action="store_true")
    ap.add_argument("--size", default=None, help="360p/480p/540p/720p/1080p/1440p/2k/4k/4x4k/8k or WxH")
    ap.add_argument("--fps", type=float, default=12.0)
    ap.add_argument("--gop", type=int, default=12)
    ap.add_argument("--max-frames", type=int, default=24)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--export", action="store_true", help=".mtb/.mtc -> png/mp4 instead")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.input):
        print("not a folder: %s" % args.input)
        return 2
    out_dir = args.out or os.path.join(args.input, "converted")
    os.makedirs(out_dir, exist_ok=True)

    files = scan(args.input, args.export)
    if not files:
        print("nothing to convert in %s" % args.input)
        return 1

    ok = 0
    failed = []
    skipped = []
    t0 = time.perf_counter()
    for i, path in enumerate(files, 1):
        out = os.path.join(out_dir, target_name(path, args.export))
        if os.path.exists(out) and not args.overwrite:
            skipped.append(path)
            if not args.quiet:
                print("[%d/%d] skip (exists) %s" % (i, len(files), os.path.basename(path)))
            continue
        print("[%d/%d] %s -> %s" % (i, len(files), os.path.basename(path), os.path.basename(out)))
        try:
            if args.export:
                rc = cli.cmd_export(SimpleNamespace(input=path, output=out))
            else:
                rc = cli.cmd_convert(SimpleNamespace(
                    input=path, output=out, quality=args.quality,
                    subsample=args.subsample, lossless=args.lossless, size=args.size,
                    fps=args.fps, gop=args.gop, max_frames=args.max_frames,
                    start=args.start, no_audio=args.no_audio))
            if rc == 0 and os.path.exists(out):
                ok += 1
            else:
                failed.append((path, "rc=%s" % rc))
        except Exception as exc:  # noqa: BLE001 - 单个文件失败不影响整批
            failed.append((path, "%s: %s" % (type(exc).__name__, exc)))
            print("    FAILED %s" % exc)

    dt = time.perf_counter() - t0
    print("")
    print("done: ok=%d failed=%d skipped=%d  %.1fs  -> %s" % (
        ok, len(failed), len(skipped), dt, out_dir))
    for path, why in failed:
        print("  failed %s (%s)" % (os.path.basename(path), why))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
