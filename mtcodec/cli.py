import argparse
import os
import sys
import time

import numpy as np
from PIL import Image

from . import decode_image, decode_video, encode_image, encode_video, probe, probe_video, psnr
from .format import EXT_IMAGE, EXT_VIDEO
from . import io_bridge


def _load(path):
    img = Image.open(path)
    mode = io_bridge._pil_mode(img)
    if mode == "RGBA":
        return np.array(img.convert("RGBA"))
    if img.mode != "L":
        img = img.convert("RGB")
    return np.array(img)


def _with_ext(path, ext):
    if os.path.splitext(path)[1]:
        return path
    return path + ext


def _save(path, arr):
    io_bridge.save_image(arr, path)


def cmd_encode(args):
    arr = _load(args.input)
    t0 = time.perf_counter()
    blob = encode_image(arr, quality=args.quality, subsample=args.subsample, lossless=args.lossless)
    dt = time.perf_counter() - t0
    out = _with_ext(args.output, EXT_IMAGE)
    with open(out, "wb") as f:
        f.write(blob)
    back = decode_image(blob)
    rgb_a = arr[:, :, :3] if arr.ndim == 3 and arr.shape[2] == 4 else arr
    rgb_b = back[:, :, :3] if back.ndim == 3 and back.shape[2] == 4 else back
    ratio = arr.size * arr.dtype.itemsize / len(blob)
    print(f"input {args.input} {arr.shape}")
    print(f"output {out} {len(blob)} bytes  ratio {ratio:.2f}:1  encode {dt:.2f}s")
    print(f"psnr {psnr(rgb_a, rgb_b):.2f} dB  identical {np.array_equal(arr, back)}")
    return 0


def cmd_decode(args):
    with open(args.input, "rb") as f:
        blob = f.read()
    t0 = time.perf_counter()
    arr = decode_image(blob)
    dt = time.perf_counter() - t0
    _save(args.output, arr)
    print(f"decoded {arr.shape} -> {args.output} in {dt:.2f}s")
    return 0


def cmd_info(args):
    with open(args.input, "rb") as f:
        blob = f.read()
    if blob[:4] == b"MTB1":
        print(probe(blob))
    else:
        print(probe_video(blob))
    return 0


def _convert_video_stream(args, out, t0):
    """Video -> MTC without ever holding the whole clip in memory."""
    tw, th = io_bridge.video_target_size(args.input, args.size)
    audio = b""
    if not args.no_audio:
        secs = float(args.max_frames) / float(args.fps) if args.max_frames > 0 else 0.0
        audio = io_bridge.load_audio_wav(args.input, seconds=secs)
    gen = io_bridge.iter_video_frames(
        args.input, fps=args.fps, size_spec=args.size,
        max_frames=args.max_frames, start=args.start)

    def _cb(n):
        print("  ... %d frames  %.1fs" % (n, time.perf_counter() - t0), flush=True)

    blob = encode_video(gen, quality=args.quality, subsample=args.subsample,
                        gop=args.gop, fps=args.fps, audio=audio, progress=_cb)
    dt = time.perf_counter() - t0
    with open(out, "wb") as fh:
        fh.write(blob)
    info = probe_video(blob)
    n = info["frames"]
    raw = n * tw * th * 3
    fps_note = "  audio %d bytes" % len(audio) if audio else "  no audio"
    print("in   %s  %d frames  %dx%d%s" % (
        os.path.basename(args.input), n, tw, th, fps_note))
    print("out  %s  %d bytes  ratio %.2f:1  %.2fs" % (
        out, len(blob), raw / len(blob), dt))
    return 0


def cmd_convert(args):
    """主流格式 -> MTB / MTC。"""
    ext = os.path.splitext(args.input)[1].lower()
    out = args.output
    out_ext = os.path.splitext(out)[1].lower()
    if not out_ext:
        out_ext = EXT_IMAGE if ext in io_bridge.IMAGE_EXTS else EXT_VIDEO
        out = out + out_ext

    t0 = time.perf_counter()
    audio = b""
    if ext in io_bridge.VIDEO_EXTS and out_ext == EXT_VIDEO:
        return _convert_video_stream(args, out, t0)
    if ext in io_bridge.IMAGE_EXTS:
        frames, has_alpha, src = io_bridge.load_image_frames(args.input, args.size)
    elif ext in io_bridge.VIDEO_EXTS:
        frames, src = io_bridge.load_video_frames(
            args.input, fps=args.fps, size_spec=args.size,
            max_frames=args.max_frames, start=args.start)
        has_alpha = False
        if not args.no_audio:
            audio = io_bridge.load_audio_wav(args.input, seconds=args.max_frames / float(args.fps))
    else:
        print("unsupported input type: %s" % ext)
        return 2

    if out_ext == EXT_IMAGE:
        if len(frames) > 1:
            print("note: animated / video input has %d frames, MTB keeps the first frame "
                  "(use .mtc to keep motion)" % len(frames))
        blob = encode_image(frames[0], quality=args.quality,
                            subsample=args.subsample, lossless=args.lossless)
        fps_note = ""
    elif out_ext == EXT_VIDEO:
        blob = encode_video(frames, quality=args.quality, subsample=args.subsample,
                            gop=args.gop, fps=args.fps, audio=audio)
        fps_note = "  audio %d bytes" % len(audio) if audio else "  no audio"
    else:
        print("output must end with .mtb or .mtc")
        return 2

    dt = time.perf_counter() - t0
    with open(out, "wb") as f:
        f.write(blob)
    raw = sum(f.size * (4 if f.ndim == 3 and f.shape[2] == 4 else 3) for f in frames)
    if out_ext == EXT_IMAGE:
        info = probe(blob)
        back = decode_image(blob)
        if has_alpha:
            mask = frames[0][:, :, 3] >= 8
            rgb_a = frames[0][:, :, :3][mask]
            rgb_b = back[:, :, :3][mask]
            psnr_note = " (visible pixels only)"
        else:
            rgb_a = frames[0]
            rgb_b = back[:, :, :3] if back.ndim == 3 and back.shape[2] == 4 else back
            psnr_note = ""
        print("in   %s  %dx%d frames=%d alpha=%s" % (
            os.path.basename(args.input), frames[0].shape[1], frames[0].shape[0],
            len(frames), has_alpha))
        print("out  %s  %d bytes  ratio %.2f:1  psnr %.2f dB%s  %.2fs" % (
            out, len(blob), raw / len(blob), psnr(rgb_a, rgb_b), psnr_note, dt))
    else:
        info = probe_video(blob)
        print("in   %s  %d frames  %dx%d%s" % (
            os.path.basename(args.input), len(frames), frames[0].shape[1],
            frames[0].shape[0], fps_note))
        print("out  %s  %d bytes  ratio %.2f:1  %.2fs" % (
            out, len(blob), raw / len(blob), dt))
    return 0


def cmd_export(args):
    """MTB / MTC -> PNG / JPG / MP4。"""
    with open(args.input, "rb") as f:
        blob = f.read()
    ext = os.path.splitext(args.output)[1].lower()

    if blob[:4] == b"MTB1":
        if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
            print("MTB can export to .png / .jpg / .bmp / .webp")
            return 2
        arr = decode_image(blob)
        _save(args.output, arr)
        print("exported %dx%d -> %s" % (arr.shape[1], arr.shape[0], args.output))
        return 0

    got = {}
    frames, stats = decode_video(blob, collect=got)
    fps = got.get("fps") or 24.0
    audio = got.get("audio", b"")
    if ext == ".mp4":
        io_bridge.export_mp4(frames, args.output, fps=fps, wav_bytes=audio)
        print("exported %d frames @%.2f fps%s -> %s" % (
            len(frames), fps, " + audio" if audio else "", args.output))
    else:
        paths = io_bridge.export_frames(frames, args.output)
        print("exported %d frames -> %s" % (len(paths), args.output))
        if audio:
            wav = os.path.join(args.output, "audio.wav")
            io_bridge.save_wav_file(audio, wav)
            print("also wrote %s" % wav)
    return 0


def cmd_video_encode(args):
    files = sorted(os.listdir(args.input))
    files = [f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))]
    frames = [_load(os.path.join(args.input, f)) for f in files]
    t0 = time.perf_counter()
    blob = encode_video(frames, quality=args.quality, subsample=args.subsample,
                        gop=args.gop, fps=args.fps)
    dt = time.perf_counter() - t0
    out = _with_ext(args.output, EXT_VIDEO)
    with open(out, "wb") as f:
        f.write(blob)
    raw = sum(f.size * f.dtype.itemsize for f in frames)
    print(f"frames {len(frames)} {frames[0].shape} -> {len(blob)} bytes  ratio {raw / len(blob):.2f}:1")
    print(f"encode {dt:.2f}s  ({len(frames) / dt:.2f} fps)")
    print(f"output {out}")
    return 0


def cmd_video_decode(args):
    with open(args.input, "rb") as f:
        blob = f.read()
    frames, stats = decode_video(blob)
    os.makedirs(args.output, exist_ok=True)
    for i, fr in enumerate(frames):
        _save(os.path.join(args.output, f"frame_{i:04d}.png"), fr)
    print(f"decoded {len(frames)} frames -> {args.output}")
    return 0


def cmd_video_info(args):
    with open(args.input, "rb") as f:
        blob = f.read()
    print(probe_video(blob))
    return 0


def cmd_open(args):
    from .viewer import open_path

    return open_path(args.input)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="mtcodec",
        description="MTB image / MTC video codec",
        epilog="feedback: xiaomitv14@outlook.com  |  https://github.com/xiaimiredmi/MTB-MTC/issues",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("encode", help="encode an image to .mtb")
    e.add_argument("input")
    e.add_argument("output")
    e.add_argument("-q", "--quality", type=int, default=85)
    e.add_argument("-s", "--subsample", choices=["420", "444"], default="420")
    e.add_argument("--lossless", action="store_true")
    e.set_defaults(func=cmd_encode)

    c = sub.add_parser("convert", help="PNG/JPG/GIF/APNG/MP4/MKV... -> .mtb or .mtc")
    c.add_argument("input")
    c.add_argument("output")
    c.add_argument("-q", "--quality", type=int, default=80)
    c.add_argument("-s", "--subsample", choices=["420", "444"], default="420")
    c.add_argument("--lossless", action="store_true")
    c.add_argument("--size", default=None, help="360p/480p/720p/1080p/4k/4x4k or 1920x1080")
    c.add_argument("--fps", type=float, default=12.0)
    c.add_argument("--gop", type=int, default=12)
    c.add_argument("--max-frames", type=int, default=24)
    c.add_argument("--start", type=float, default=0.0)
    c.add_argument("--no-audio", action="store_true")
    c.set_defaults(func=cmd_convert)

    x = sub.add_parser("export", help=".mtb -> PNG/JPG, .mtc -> MP4 or frame folder")
    x.add_argument("input")
    x.add_argument("output")
    x.set_defaults(func=cmd_export)

    d = sub.add_parser("decode", help="decode a .mtb image")
    d.add_argument("input")
    d.add_argument("output")
    d.set_defaults(func=cmd_decode)

    i = sub.add_parser("info", help="print header of .mtb / .mtc")
    i.add_argument("input")
    i.set_defaults(func=cmd_info)

    o = sub.add_parser("open", help="open a .mtb image or .mtc video in a window")
    o.add_argument("input")
    o.set_defaults(func=cmd_open)

    ve = sub.add_parser("video-encode", help="encode a frame folder to .mtc")
    ve.add_argument("input")
    ve.add_argument("output")
    ve.add_argument("-q", "--quality", type=int, default=85)
    ve.add_argument("-s", "--subsample", choices=["420", "444"], default="420")
    ve.add_argument("--gop", type=int, default=12)
    ve.add_argument("--fps", type=float, default=24.0)
    ve.set_defaults(func=cmd_video_encode)

    vd = sub.add_parser("video-decode", help="decode a .mtc video to a frame folder")
    vd.add_argument("input")
    vd.add_argument("output")
    vd.set_defaults(func=cmd_video_decode)

    vi = sub.add_parser("video-info", help="print .mtc header")
    vi.add_argument("input")
    vi.set_defaults(func=cmd_video_info)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
