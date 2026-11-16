"""Image format bridge: PNG / JPG / BMP / WEBP / GIF / APNG <-> numpy."""

import os

import numpy as np
from PIL import Image

SIZE_PRESETS = {
    "360p": (640, 360),
    "480p": (854, 480),
    "540p": (960, 540),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "2k": (2560, 1440),
    "4k": (3840, 2160),
    "4x4k": (7680, 4320),
    "8k": (7680, 4320),
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".apng",
              ".tif", ".tiff"}


def parse_size(spec):
    """'1080p' / '1920x1080' / 'orig' -> (w, h) or None."""
    if spec is None:
        return None
    s = str(spec).strip().lower()
    if s in ("", "orig", "native", "none", "0"):
        return None
    if s in SIZE_PRESETS:
        return SIZE_PRESETS[s]
    if "x" in s:
        w, h = s.split("x", 1)
        return int(w), int(h)
    raise ValueError("unknown size spec: %s" % spec)


def target_size(w, h, spec):
    box = parse_size(spec)
    if box is None:
        return w, h
    tw, th = box
    if h > w:
        tw, th = th, tw
    scale = min(tw / float(w), th / float(h))
    return max(1, int(round(w * scale))), max(1, int(round(h * scale)))


def resize_arr(arr, size):
    if size is None or (arr.shape[1], arr.shape[0]) == tuple(size):
        return arr
    mode = "RGBA" if arr.ndim == 3 and arr.shape[2] == 4 else "RGB"
    img = Image.fromarray(arr, mode=mode)
    return np.array(img.resize(tuple(size), Image.LANCZOS))


def _pil_mode(img):
    if img.mode in ("RGBA", "LA", "PA"):
        return "RGBA"
    if img.mode == "P" and "transparency" in img.info:
        return "RGBA"
    return "RGB"


def load_image_frames(path, size_spec=None):
    """Read PNG / JPG / WEBP / GIF / APNG, return (frames, has_alpha, size)."""
    img = Image.open(path)
    n = getattr(img, "n_frames", 1) or 1
    src = img.size
    out = []
    for i in range(n):
        img.seek(i)
        tw, th = target_size(src[0], src[1], size_spec)
        frame = img.convert(_pil_mode(img))
        if (tw, th) != src:
            frame = frame.resize((tw, th), Image.LANCZOS)
        out.append(np.array(frame))
    has_alpha = out[0].ndim == 3 and out[0].shape[2] == 4
    return out, has_alpha, src


def save_image(arr, path, quality=95):
    ext = os.path.splitext(path)[1].lower()
    img = Image.fromarray(arr)
    if ext in (".jpg", ".jpeg") and img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    if ext in (".jpg", ".jpeg"):
        img.save(path, quality=quality, subsampling=0)
    else:
        img.save(path)


def export_frames(frames, out_dir, prefix="frame"):
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for i, fr in enumerate(frames):
        p = os.path.join(out_dir, "%s_%04d.png" % (prefix, i))
        save_image(fr, p)
        paths.append(p)
    return paths
