"""Command line for the MTC image codec."""

import argparse
import os

from . import image_codec as ic
from . import io_bridge
from .format import EXT_IMAGE


def _load(path):
    if os.path.splitext(path)[1].lower() == EXT_IMAGE:
        with open(path, "rb") as f:
            return ic.decode_image(f.read())
    frames, _alpha, _src = io_bridge.load_image_frames(path)
    return frames[0]


def _with_ext(path, ext):
    if not os.path.splitext(path)[1]:
        return path + ext
    return path


def cmd_encode(args):
    frames, has_alpha, src = io_bridge.load_image_frames(args.input, args.size)
    if len(frames) > 1:
        print("note: %d frames, MTC keeps the first frame (use a still image)"
              % len(frames))
    arr = frames[0]
    blob = ic.encode_image(arr, quality=args.quality, subsample=args.subsample,
                           lossless=args.lossless)
    out = _with_ext(args.output, EXT_IMAGE)
    with open(out, "wb") as f:
        f.write(blob)
    back = ic.decode_image(blob)
    raw = arr.size * (arr.dtype.itemsize)
    ps = ic.psnr(arr, back)
    print("in   %s  %dx%d  %d bytes" % (os.path.basename(args.input),
                                       arr.shape[1], arr.shape[0], raw))
    print("out  %s  %d bytes  ratio %.2f:1  psnr %.2f dB"
          % (out, len(blob), raw / float(len(blob)), ps))
    return 0


def cmd_decode(args):
    with open(args.input, "rb") as f:
        arr = ic.decode_image(f.read())
    io_bridge.save_image(arr, args.output)
    print("decoded %dx%d -> %s" % (arr.shape[1], arr.shape[0], args.output))
    return 0


def cmd_info(args):
    with open(args.input, "rb") as f:
        print(ic.probe(f.read()))
    return 0


def cmd_open(args):
    from .viewer import open_path

    return open_path(args.input)


def cmd_convert(args):
    out_ext = os.path.splitext(args.output)[1].lower()
    if out_ext == EXT_IMAGE:
        return cmd_encode(args)
    if os.path.splitext(args.input)[1].lower() == EXT_IMAGE:
        return cmd_decode(args)
    return cmd_encode(args)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="mtcodec",
        description="MTC image codec",
        epilog="feedback: xiaomitev14@outlook.com  |  https://github.com/xiaimiredmi/MTB-MTC/issues",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("encode", help="图片 -> .mtc")
    e.add_argument("input")
    e.add_argument("output")
    e.add_argument("-q", "--quality", type=int, default=85)
    e.add_argument("-s", "--subsample", choices=["420", "444"], default="420")
    e.add_argument("--lossless", action="store_true")
    e.add_argument("--size", default=None)
    e.set_defaults(func=cmd_encode)

    d = sub.add_parser("decode", help=".mtc -> PNG/JPG/BMP/WEBP")
    d.add_argument("input")
    d.add_argument("output")
    d.set_defaults(func=cmd_decode)

    c = sub.add_parser("convert", help="图片 <-> .mtc（按扩展名判断方向）")
    c.add_argument("input")
    c.add_argument("output")
    c.add_argument("-q", "--quality", type=int, default=85)
    c.add_argument("-s", "--subsample", choices=["420", "444"], default="420")
    c.add_argument("--lossless", action="store_true")
    c.add_argument("--size", default=None)
    c.set_defaults(func=cmd_convert)

    i = sub.add_parser("info", help="打印 .mtc 头")
    i.add_argument("input")
    i.set_defaults(func=cmd_info)

    o = sub.add_parser("open", help="用窗口打开 .mtc")
    o.add_argument("input")
    o.set_defaults(func=cmd_open)

    args = p.parse_args(argv)
    return args.func(args)
