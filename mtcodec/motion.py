# -*- coding: utf-8 -*-
"""Block motion estimation for the MTC video codec.

The frame-to-frame predictor used to be strictly co-located: a block in frame
N was predicted from the block in exactly the same place in frame N-1. That
throws away every bit of camera and object motion, which is why the bitrate
sits far above what the material actually needs.

Search runs in two stages:

1. a coarse pass on a 4x downsampled luma plane, +/-16 pixels, which is cheap
   enough to cover the whole frame;
2. a full-resolution verification of the best coarse vector plus its
   neighbours *and* the zero vector. Without that second stage a 4-pixel
   quantised vector can be worse than not moving at all, which is exactly what
   showed up as a PSNR drop in the first attempt.

``predict`` rebuilds a prediction plane by gathering each block from the
previous frame at its displaced position, clamped at the edges. It is fully
vectorised, and the decoder runs the same function on the same table, so both
sides agree bit for bit.
"""
import numpy as np

from . import fastenc

BLOCK = 16
RADIUS = 16
REFINE = 2


def _down4(plane):
    """4x box downsample; used only for the coarse search, never for prediction."""
    h, w = plane.shape
    h4, w4 = h // 4, w // 4
    if h4 < 1 or w4 < 1:
        return plane.astype(np.int32)
    src = plane[: h4 * 4, : w4 * 4].astype(np.int32)
    return (src.reshape(h4, 4, w4, 4).sum(axis=(1, 3)) >> 4).astype(np.int32)


def _block_sad(a, b, block):
    h, w = a.shape
    nbh, nbw = h // block, w // block
    if nbh < 1 or nbw < 1:
        return np.zeros((1, 1), np.int32)
    d = np.abs(a[: nbh * block, : nbw * block] - b[: nbh * block, : nbw * block])
    return d.reshape(nbh, block, nbw, block).sum(axis=(1, 3))


def blocks_of(plane, block=BLOCK):
    """View a plane as ``(nbh, nbw, block, block)``."""
    h, w = plane.shape
    nbh, nbw = h // block, w // block
    a = plane[: nbh * block, : nbw * block]
    return a.reshape(nbh, block, nbw, block).transpose(0, 2, 1, 3)


def gather(ref, mv, block=BLOCK):
    """Fetch every block of ``ref`` at its displaced position.

    ``mv`` is ``(nbh, nbw, 2)`` in pixels, ``(dx, dy)``. Returns
    ``(nbh, nbw, block, block)``.
    """
    h, w = ref.shape
    nbh, nbw = mv.shape[0], mv.shape[1]
    yy = np.arange(nbh * block).reshape(nbh, 1, block, 1)
    xx = np.arange(nbw * block).reshape(1, nbw, 1, block)
    dy = mv[:, :, None, None, 1].astype(np.int32)
    dx = mv[:, :, None, None, 0].astype(np.int32)
    rows = np.clip(yy + dy, 0, h - 1)
    cols = np.clip(xx + dx, 0, w - 1)
    return ref[rows, cols]


def search(cur, ref, block=BLOCK, radius=RADIUS, refine=REFINE):
    """Per-block motion vectors, ``(nbh, nbw, 2)`` as int8, in luma pixels."""
    h, w = cur.shape
    nbh, nbw = h // block, w // block
    mv = np.zeros((nbh, nbw, 2), np.int8)
    if nbh < 1 or nbw < 1 or radius <= 0:
        return mv
    if fastenc.me_available():
        return fastenc.me_search(cur, ref, block, radius, refine)

    cs = _down4(cur)
    rs = _down4(ref)
    b4 = max(1, block // 4)
    r4 = max(1, radius // 4)
    pad = r4
    big = np.pad(rs, pad, mode="edge")
    ch, cw = cs.shape
    best = np.full((nbh, nbw), 1 << 30, np.int32)
    seed = np.zeros((nbh, nbw, 2), np.int32)
    for dy in range(-r4, r4 + 1):
        for dx in range(-r4, r4 + 1):
            sh = big[pad + dy : pad + dy + ch, pad + dx : pad + dx + cw]
            sad = _block_sad(cs, sh, b4)
            if sad.shape[0] != nbh or sad.shape[1] != nbw:
                continue
            better = sad < best
            if not better.any():
                continue
            best[better] = sad[better]
            seed[better, 0] = dx * 4
            seed[better, 1] = dy * 4

    curb = blocks_of(cur, block)
    best2 = np.full((nbh, nbw), 1 << 30, np.int32)
    cands = [np.zeros((nbh, nbw, 2), np.int32)]
    for oy in (-refine, 0, refine):
        for ox in (-refine, 0, refine):
            cands.append(seed + np.array([ox, oy], np.int32))
    for cand in cands:
        sad = np.abs(curb - gather(ref, cand, block)).sum(axis=(2, 3))
        better = sad < best2
        if not better.any():
            continue
        best2[better] = sad[better]
        mv[better, 0] = np.clip(cand[better, 0], -127, 127)
        mv[better, 1] = np.clip(cand[better, 1], -127, 127)
    return mv


def predict(ref, mv, block=BLOCK):
    """Rebuild a prediction plane from ``ref`` using per-block vectors."""
    h, w = ref.shape
    nbh, nbw = h // block, w // block
    if nbh >= 1 and nbw >= 1 and fastenc.me_available():
        return fastenc.me_predict(ref, mv, block)
    # gather gives (nbh, nbw, block, block); a plane needs the block index to
    # sit between the two row/column axes, so transpose before flattening.
    blocks = np.ascontiguousarray(gather(ref, mv, block).transpose(0, 2, 1, 3))
    pred = blocks.reshape(nbh * block, nbw * block)
    if pred.shape[0] < h or pred.shape[1] < w:
        pred = np.pad(pred, ((0, h - pred.shape[0]), (0, w - pred.shape[1])),
                      mode="edge")
    return np.ascontiguousarray(pred, dtype=np.int32)


def scale(mv, div):
    """Halve (chroma) or otherwise scale a vector table, clipped to int8."""
    if div in (1, None):
        return mv
    out = mv.astype(np.int16) / float(div)
    return np.clip(np.rint(out), -127, 127).astype(np.int8)


def hp_available():
    return fastenc.hp_available()


def hp_plane(ref):
    """Half-pel grid of a reference plane, built once per frame and plane."""
    return fastenc.hp_interp(ref)


def search_subpel(cur, ref, hp, block=BLOCK, radius=RADIUS, refine=REFINE):
    """Quarter-pel vectors from the integer seed plus a half/quarter ring."""
    return fastenc.me_search_hp(cur, ref, hp, block, radius, refine)


def predict_subpel(hp, mv, block=BLOCK):
    return fastenc.me_predict_hp(hp, mv, block)


def scale_sub(mv, div=2):
    """Scale quarter-pel vectors, rounding halves away from zero."""
    v = np.ascontiguousarray(mv, dtype=np.int32)
    if div in (1, None):
        return np.clip(v, -32768, 32767).astype(np.int16)
    out = np.where(v >= 0, (v + 1) >> 1, -(((-v) + 1) >> 1))
    return np.clip(out, -32768, 32767).astype(np.int16)


def pack(mv, subpel=False):
    dt = np.int16 if subpel else np.int8
    return np.ascontiguousarray(mv, dtype=dt).tobytes()


def unpack(blob, nbh, nbw, subpel=False):
    dt = np.int16 if subpel else np.int8
    arr = np.frombuffer(blob, dtype=dt, count=nbh * nbw * 2)
    return arr.reshape(nbh, nbw, 2).copy()
