# -*- coding: utf-8 -*-
"""Block motion estimation for the MTC video codec.

The frame-to-frame predictor used to be strictly co-located: a block in frame
N was predicted from the block in exactly the same place in frame N-1. That
throws away every bit of camera and object motion, which is why the bitrate
sits one to two orders of magnitude above H.264.

This module adds a real search. Everything happens on a quarter-resolution
copy of the luma plane so the whole thing costs tens of milliseconds per
1080p frame instead of seconds:

* ``search`` compares each 16x16 luma block against a 4x downsampled previous
  frame over a +/-16 pixel window and returns one integer motion vector per
  block, in *full* resolution pixels.
* ``predict`` rebuilds a prediction plane by fetching each block from the
  previous frame at its displaced position, clamping at the edges.

Both the encoder and the decoder call ``predict`` with the same vector table,
so the two sides agree bit for bit and no drift appears.
"""
import numpy as np

BLOCK = 16
RADIUS = 16


def _down4(plane):
    """4x box downsample; used only for the search, never for prediction."""
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


def search(cur, ref, block=BLOCK, radius=RADIUS):
    """Per-block motion vectors, ``(nbh, nbw, 2)`` as int8, in luma pixels."""
    h, w = cur.shape
    nbh, nbw = h // block, w // block
    mv = np.zeros((nbh, nbw, 2), np.int8)
    if nbh < 1 or nbw < 1 or radius <= 0:
        return mv

    cs = _down4(cur)
    rs = _down4(ref)
    b4 = max(1, block // 4)
    r4 = max(1, radius // 4)

    pad = r4
    big = np.pad(rs, pad, mode="edge")
    ch, cw = cs.shape
    # 4x downsampled plane is 1/4 the size, so a window of r4 here is r4*4
    # full-resolution pixels; that is exactly the radius we advertise.
    best = np.full((nbh, nbw), 1 << 30, np.int32)
    for dy in range(-r4, r4 + 1):
        for dx in range(-r4, r4 + 1):
            sh = big[pad + dy : pad + dy + ch, pad + dx : pad + dx + cw]
            sad = _block_sad(cs, sh, b4)
            # the downsampled plane has block//4 blocks per side per block,
            # so map the coarse grid back onto the full block grid
            if sad.shape[0] != nbh or sad.shape[1] != nbw:
                step = int(round(nbh / float(max(1, sad.shape[0])))) or 1
                idx_y = np.clip(np.arange(nbh) // step, 0, sad.shape[0] - 1)
                idx_x = np.clip(np.arange(nbw) // step, 0, sad.shape[1] - 1)
                sad = sad[np.ix_(idx_y, idx_x)]
            better = sad < best
            if better.any():
                best[better] = sad[better]
                mv[better, 0] = dx * 4
                mv[better, 1] = dy * 4
    return mv


def predict(ref, mv, block=BLOCK):
    """Rebuild a prediction plane from ``ref`` using per-block vectors."""
    h, w = ref.shape
    nbh, nbw = h // block, w // block
    ph, pw = nbh * block, nbw * block
    pred = np.empty((ph, pw), np.int32)
    for r in range(nbh):
        y0 = r * block
        for c in range(nbw):
            x0 = c * block
            dy = int(mv[r, c, 1])
            dx = int(mv[r, c, 0])
            if dx == 0 and dy == 0:
                pred[y0 : y0 + block, x0 : x0 + block] = ref[y0 : y0 + block, x0 : x0 + block]
                continue
            sy = np.clip(np.arange(y0, y0 + block) + dy, 0, h - 1)
            sx = np.clip(np.arange(x0, x0 + block) + dx, 0, w - 1)
            pred[y0 : y0 + block, x0 : x0 + block] = ref[sy[:, None], sx[None, :]]
    if ph < h or pw < w:
        pad_h = h - ph
        pad_w = w - pw
        pred = np.pad(pred, ((0, pad_h), (0, pad_w)), mode="edge")
    return pred


def scale(mv, div):
    """Halve (chroma) or otherwise scale a vector table, clipped to int8."""
    if div in (1, None):
        return mv
    out = (mv.astype(np.int16) / float(div))
    return np.clip(np.rint(out), -127, 127).astype(np.int8)


def pack(mv):
    return np.ascontiguousarray(mv, dtype=np.int8).tobytes()


def unpack(blob, nbh, nbw):
    arr = np.frombuffer(blob, dtype=np.int8, count=nbh * nbw * 2)
    return arr.reshape(nbh, nbw, 2).copy()


def table_bytes(h, w, block=BLOCK):
    return ((h + block - 1) // block) * ((w + block - 1) // block) * 2
