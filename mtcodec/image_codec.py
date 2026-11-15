import struct

import numpy as np

from . import arithmetic as ac
from . import color
from . import transform as tf
from .entropy import Model, dec_block, dec_res, enc_block, enc_res

MAGIC = b"MTB1"
VERSION = 1
HDR = struct.Struct("<4sBBBBHH")

MODE_GRAY_LOSSY = 0
MODE_RGB444_LOSSY = 1
MODE_RGB420_LOSSY = 2
MODE_GRAY_LOSSLESS = 3
MODE_RGB_LOSSLESS = 4

FLAG_ALPHA = 1

CHROMA_STEP_GAIN = 1.35


def _align(v, mult):
    return -(-v // mult) * mult


def _pad(arr, mult):
    h, w = arr.shape[:2]
    ph = _align(h, mult)
    pw = _align(w, mult)
    if ph == h and pw == w:
        return arr
    pad = ((0, ph - h), (0, pw - w)) + ((0, 0),) * (arr.ndim - 2)
    return np.pad(arr, pad, mode="edge")


def _plane_step(step, index):
    if index == 0:
        return step
    return step * CHROMA_STEP_GAIN


def _encode_plane(enc, m, pl, plane, step):
    blocks = tf.blocks_of(plane.astype(np.float64))
    coeffs = tf.fdct(blocks)
    q = np.rint(coeffs / step).astype(np.int32)
    qz = np.ascontiguousarray(q[:, :, tf.ZZ_U, tf.ZZ_V])
    hb, wb = qz.shape[0], qz.shape[1]
    for r in range(hb):
        prev = 0
        row = qz[r]
        for c in range(wb):
            blk = row[c].tolist()
            enc_block(enc, m, pl, blk, prev)
            prev = blk[0]
    return qz


def _decode_plane(dec, m, pl, shape, step, index):
    h, w = shape
    hb, wb = h // 8, w // 8
    qz = np.zeros((hb, wb, 64), np.int32)
    for r in range(hb):
        prev = 0
        for c in range(wb):
            blk = dec_block(dec, m, pl, prev)
            qz[r, c] = blk
            prev = blk[0]
    q8 = np.zeros((hb, wb, 8, 8), np.float64)
    q8[:, :, tf.ZZ_U, tf.ZZ_V] = qz
    recon = tf.idct(q8 * step)
    plane = np.rint(tf.plane_of(recon)).astype(np.int32)
    return color.clip_plane(plane, index), qz


def _residuals(plane):
    zeros_col = np.zeros((plane.shape[0], 1), np.int32)
    a = np.concatenate([zeros_col, plane[:, :-1]], axis=1)
    b = np.vstack([a[0:1, :], plane[:-1, :]])
    c = np.vstack([a[0:1, :], a[:-1, :]])
    pa = a
    pb = b
    pc = c
    mx = np.maximum(pa, pb)
    mn = np.minimum(pa, pb)
    pred = np.where(pc >= mx, mn, np.where(pc <= mn, mx, pa + pb - pc))
    res = plane - pred
    act = np.abs(a - c) + np.abs(b - c)
    return res, act


def _ctx_of(activity):
    if activity <= 1:
        return 0
    if activity <= 3:
        return 1
    if activity <= 7:
        return 2
    if activity <= 15:
        return 3
    return 4


def _lossless_payload(planes):
    enc = ac.Encoder()
    m = Model(len(planes))
    for i, plane in enumerate(planes):
        res, act = _residuals(plane)
        flat_res = res.ravel().tolist()
        flat_act = act.ravel().tolist()
        n = len(flat_res)
        for k in range(n):
            enc_res(enc, m, i, _ctx_of(flat_act[k]), flat_res[k])
    return enc.flush()


def _decode_plane_lossless(dec, m, index, w, h):
    plane = np.zeros((h, w), np.int32)
    for y in range(h):
        row = plane[y]
        prev = plane[y - 1] if y else None
        for x in range(w):
            a = row[x - 1] if x else 0
            if prev is None:
                b = a
                c = a
            else:
                b = prev[x]
                c = prev[x - 1] if x else a
            mx = a if a > b else b
            mn = b if a > b else a
            if c >= mx:
                p = mn
            elif c <= mn:
                p = mx
            else:
                p = a + b - c
            actv = abs(a - c) + abs(b - c)
            row[x] = p + dec_res(dec, m, index, _ctx_of(actv))
    return plane


def _decode_lossless_planes(payload, planes_count, w, h, clips=None):
    dec = ac.Decoder(payload)
    m = Model(planes_count)
    out = []
    for i in range(planes_count):
        plane = _decode_plane_lossless(dec, m, i, w, h)
        lo, hi = (0, 255) if clips is None else clips[i]
        out.append(np.clip(plane, lo, hi))
    return out


def _decode_alpha(payload, w, h):
    plane = _decode_lossless_planes(payload, 1, w, h, [(0, 255)])[0]
    return plane.astype(np.uint8)


def _encode_lossless_payload(arr, gray):
    if gray:
        mode = MODE_GRAY_LOSSLESS
        planes = [arr.astype(np.int32)]
    else:
        mode = MODE_RGB_LOSSLESS
        planes = list(color.rgb_to_ycocg(arr.astype(np.int32)))
    return mode, _lossless_payload(planes)


def _decode_lossless(payload, mode, w, h):
    planes_count = 1 if mode == MODE_GRAY_LOSSLESS else 3
    clips = [color.CLIP[i] for i in range(planes_count)]
    out = _decode_lossless_planes(payload, planes_count, w, h, clips)
    if mode == MODE_GRAY_LOSSLESS:
        return out[0].astype(np.uint8)
    r, g, b = color.ycocg_to_rgb(out[0], out[1], out[2])
    return color.to_uint8(np.stack([r, g, b], axis=2))


def split_alpha(img):
    """把 RGBA 拆成 (RGB, alpha uint8) 或 (原图, None)。"""
    arr = np.asarray(img)
    if arr.ndim == 3 and arr.shape[2] == 4:
        alpha = arr[:, :, 3].astype(np.uint8)
        rgb = arr[:, :, :3].copy()
        return rgb, alpha
    return arr, None


def encode_image(img, quality=85, subsample="420", lossless=False, collect=None):
    rgb, alpha = split_alpha(img)
    arr = np.asarray(rgb)
    if arr.dtype != np.uint8:
        arr = np.clip(np.rint(arr), 0, 255).astype(np.uint8)
    gray = arr.ndim == 2
    if arr.ndim == 3 and arr.shape[2] == 1:
        arr = arr[:, :, 0]
        gray = True
    if not gray and (arr.ndim != 3 or arr.shape[2] != 3):
        raise ValueError("supports gray, RGB or RGBA input only")
    if alpha is not None:
        if alpha.shape[:2] != arr.shape[:2]:
            raise ValueError("alpha plane size mismatch")
        arr = arr.copy()
        arr[alpha < 8] = 0
    h, w = arr.shape[:2]

    if lossless:
        mode, payload = _encode_lossless_payload(arr, gray)
    else:
        if gray:
            mode = MODE_GRAY_LOSSY
            mult = 8
            planes = [_pad(arr.astype(np.int32), 8)]
        else:
            mode = MODE_RGB420_LOSSY if subsample == "420" else MODE_RGB444_LOSSY
            mult = 16 if mode == MODE_RGB420_LOSSY else 8
            rgbp = _pad(arr.astype(np.int32), mult)
            y, co, cg = color.rgb_to_ycocg(rgbp)
            if mode == MODE_RGB420_LOSSY:
                co = color.down2(co)
                cg = color.down2(cg)
            planes = [_pad(y, 8), _pad(co, 8), _pad(cg, 8)]

        step = tf.step_table(tf.quality_scale(quality))
        m = Model(len(planes))
        enc = ac.Encoder()
        qzs = []
        for i, plane in enumerate(planes):
            qzs.append(_encode_plane(enc, m, i, plane, _plane_step(step, i)))
        payload = enc.flush()
        if collect is not None:
            collect["qz"] = qzs
            collect["planes"] = [p.shape for p in planes]

    flags = 0
    alpha_blob = b""
    if alpha is not None:
        apayload = _lossless_payload([alpha.astype(np.int32)])
        alpha_blob = struct.pack("<I", len(apayload)) + apayload
        flags |= FLAG_ALPHA
    head = HDR.pack(MAGIC, VERSION, mode, int(min(100, max(1, int(quality)))), flags, w, h)
    return head + alpha_blob + payload


def decode_image(data, collect=None):
    if len(data) < HDR.size:
        raise ValueError("truncated header")
    magic, ver, mode, quality, flags, w, h = HDR.unpack(data[: HDR.size])
    if magic != MAGIC:
        raise ValueError("not an MTB stream")
    if ver != VERSION:
        raise ValueError("unsupported version")
    payload = data[HDR.size:]
    alpha = None
    if flags & FLAG_ALPHA:
        if len(payload) < 4:
            raise ValueError("truncated alpha length")
        alen = struct.unpack("<I", payload[:4])[0]
        alpha = _decode_alpha(payload[4 : 4 + alen], w, h)
        payload = payload[4 + alen :]

    if mode in (MODE_GRAY_LOSSLESS, MODE_RGB_LOSSLESS):
        img = _decode_lossless(payload, mode, w, h)
        return _attach_alpha(img, alpha)

    if mode == MODE_RGB420_LOSSY:
        ph = _align(h, 16)
        pw = _align(w, 16)
        shapes = [(ph, pw), (ph // 2, pw // 2), (ph // 2, pw // 2)]
    else:
        ph = _align(h, 8)
        pw = _align(w, 8)
        shapes = [(ph, pw)] if mode == MODE_GRAY_LOSSY else [(ph, pw)] * 3

    step = tf.step_table(tf.quality_scale(quality))
    dec = ac.Decoder(payload)
    m = Model(len(shapes))
    planes = []
    qzs = []
    for i, shape in enumerate(shapes):
        plane, qz = _decode_plane(dec, m, i, shape, _plane_step(step, i), i)
        planes.append(plane)
        qzs.append(qz)
    if collect is not None:
        collect["qz"] = qzs

    if mode == MODE_GRAY_LOSSY:
        return _attach_alpha(planes[0][:h, :w].astype(np.uint8), alpha)
    if mode == MODE_RGB420_LOSSY:
        co = color.up2(planes[1], ph, pw)
        cg = color.up2(planes[2], ph, pw)
    else:
        co = planes[1]
        cg = planes[2]
    r, g, b = color.ycocg_to_rgb(planes[0], co, cg)
    rgb = np.stack([r, g, b], axis=2)[:h, :w]
    return _attach_alpha(color.to_uint8(rgb), alpha)


def _attach_alpha(img, alpha):
    if alpha is None:
        return img
    if img.ndim == 2:
        img = np.stack([img, img, img], axis=2)
    return np.dstack([img, alpha])


def probe(data):
    magic, ver, mode, quality, flags, w, h = HDR.unpack(data[: HDR.size])
    return {
        "magic": magic.decode("ascii", "replace"),
        "version": ver,
        "mode": mode,
        "quality": quality,
        "has_alpha": bool(flags & FLAG_ALPHA),
        "width": w,
        "height": h,
        "bytes": len(data),
    }


def psnr(a, b, peak=255.0):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if a.shape != b.shape:
        b = b[:, :, : a.shape[2]] if a.ndim == 3 else b
    mse = float(np.mean((a - b) ** 2))
    if mse == 0:
        return 99.0
    return 10.0 * np.log10(peak * peak / mse)
