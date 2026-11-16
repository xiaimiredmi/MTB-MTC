"""Optional native fast path for the arithmetic block decoder.

The pure Python decoder spends most of its time inside
``arithmetic.Decoder.decode`` — one call per bit, tens of millions of calls per
clip. ``native/`` builds a small Rust cdylib that runs the identical bit-level
algorithm and decodes a whole plane per call. Everything here degrades
gracefully: if the library is missing (or ``MTCODEC_NO_NATIVE=1`` is set) the
caller just keeps using the pure Python path.
"""

import ctypes
import os
import sys

import numpy as np

OFF_COUNT = 9
TABLE_KEYS = ("dc_cls", "dc_sign", "dc_extra", "last", "sig", "ac_cls",
              "ac_sign", "ac_extra", "skip")
# Legacy layout: 8 zig-zag bands, left-skip only.
_FIRST = (0, 16, 17, 33, 97, 105, 233, 241, 369)
_TOTAL_PER_PLANE = 371
# Context layout: DC plus eight zig-zag bands, each split by whether the left
# block was all-zero and whether the previous coefficient was nonzero; skip
# flags also see the block above.
_FIRST_CTX = (0, 32, 34, 66, 194, 226, 738, 770, 1282)
_TOTAL_CTX = 1286
_UNSET = None


def _candidates():
    here = os.path.dirname(os.path.abspath(__file__))
    roots = [here]
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        roots.insert(0, mei)
        roots.insert(1, os.path.join(mei, "mtcodec"))
    names = ("mtfastdec.dll", "libmtfastdec.so", "libmtfastdec.dylib")
    for root in roots:
        for name in names:
            path = os.path.join(root, name)
            if os.path.exists(path):
                yield path
    # 开发树
    dev = os.path.join(os.path.dirname(here), "native", "target", "release",
                       "mtfastdec.dll")
    if os.path.exists(dev):
        yield dev


def _load():
    if os.environ.get("MTCODEC_NO_NATIVE"):
        return None, None
    for path in _candidates():
        try:
            lib = ctypes.CDLL(path)
        except OSError:
            continue
        try:
            fn = lib.mt_dec_recon_plane_p
        except AttributeError:
            try:
                fn = lib.mt_dec_recon_plane
            except AttributeError:
                continue
        try:
            rgb = lib.mt_planes_rgb_p
        except AttributeError:
            rgb = lib.mt_planes_rgb
        fn.restype = ctypes.c_int
        fn.argtypes = [
            ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint32,
        ]
        rgb.restype = ctypes.c_int
        rgb.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ]
        try:
            plain = lib.mt_dec_plane
            plain.restype = ctypes.c_int
            plain.argtypes = [
                ctypes.c_void_p, ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
            ]
        except AttributeError:
            pass
        lib._recon = fn
        lib._rgb = rgb
        return lib, path
    return None, None


_LIB, PATH = _load()


def available():
    return _LIB is not None


def planes_to_rgb(planes, subsample, out_h, out_w):
    """YCgCo planes -> packed RGB through the native stage."""
    if _LIB is None:
        raise RuntimeError("native library not available")
    ph, pw = planes[0].shape
    out = np.zeros((out_h, out_w, 3), np.uint8)
    arrs = [np.ascontiguousarray(p, dtype=np.int32) for p in planes]
    rc = _LIB._rgb(
        ctypes.c_void_p(arrs[0].ctypes.data),
        ctypes.c_void_p(arrs[1].ctypes.data),
        ctypes.c_void_p(arrs[2].ctypes.data),
        int(ph), int(pw), 1 if subsample else 0,
        int(out_h), int(out_w),
        ctypes.c_void_p(out.ctypes.data),
    )
    if rc != 0:
        raise RuntimeError("native rgb stage failed (rc=%d)" % rc)
    return out


class PlaneDecoder:
    """Decode planes of one clip through the native library.

    Probability state lives here across frames (it is adaptive), while the
    bitstream state comes from the per-frame ``arithmetic.Decoder`` that
    ``attach`` copies in.
    """

    def __init__(self, model, mode_model, planes=3, layout=1):
        self.layout = 2 if layout == 2 else 1
        first = _FIRST_CTX if self.layout == 2 else _FIRST
        per = _TOTAL_CTX if self.layout == 2 else _TOTAL_PER_PLANE
        total = per * planes
        self.probs = np.zeros(total, np.int16)
        self.offsets = np.array(
            [off * planes for off in first], dtype=np.uint32)
        self.planes = planes
        self._buf = None
        self.dec = None
        self._fill(model, mode_model)

    def _fill(self, model, mode_model):
        planes = self.planes
        first = _FIRST_CTX if self.layout == 2 else _FIRST
        src = [
            model.dc_cls, model.dc_sign, model.dc_extra, model.last,
            model.sig, model.ac_cls, model.ac_sign, model.ac_extra,
            mode_model.skip,
        ]
        for k, values in enumerate(src):
            start = first[k] * planes
            stop = start + len(values)
            self.probs[start:stop] = np.asarray(values, dtype=np.int16)

    def attach(self, dec):
        self.dec = dec
        data = dec.data
        self._buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(
            bytes(data))

    def decode_plane(self, pl, hb, wb, inter):
        """Decode coefficients only (kept for the arithmetic self-check)."""
        if self.dec is None or self._buf is None:
            raise RuntimeError("native decoder not attached")
        pos = ctypes.c_size_t(self.dec.pos)
        rng = ctypes.c_uint32(self.dec.range)
        cde = ctypes.c_uint32(self.dec.code)
        out = np.zeros((hb, wb, 64), np.int32)
        rc = _LIB.mt_dec_plane(
            ctypes.c_void_p(ctypes.addressof(self._buf)), len(self._buf),
            ctypes.byref(pos), ctypes.byref(rng), ctypes.byref(cde),
            ctypes.c_void_p(self.probs.ctypes.data), int(self.probs.size),
            ctypes.c_void_p(self.offsets.ctypes.data),
            int(pl), int(hb), int(wb), 1 if inter else 0,
            ctypes.c_void_p(out.ctypes.data), int(self.layout),
        )
        self.dec.pos = int(pos.value)
        self.dec.range = int(rng.value)
        self.dec.code = int(cde.value)
        if rc != 0:
            raise RuntimeError("native decoder failed (rc=%d)" % rc)
        return out

    def decode_plane_pixels(self, pl, hb, wb, inter, step, pred, clip, aq=None):
        """Decode + dequantise + IDCT (+ prediction) + clip, straight to pixels."""
        if self.dec is None or self._buf is None:
            raise RuntimeError("native decoder not attached")
        tab = np.ascontiguousarray(step, dtype=np.float64)
        pos = ctypes.c_size_t(self.dec.pos)
        rng = ctypes.c_uint32(self.dec.range)
        cde = ctypes.c_uint32(self.dec.code)
        out = np.zeros((hb * 8, wb * 8), np.int32)
        pred_ptr = None
        if pred is not None:
            pred_arr = np.ascontiguousarray(pred, dtype=np.int32)
            pred_ptr = ctypes.c_void_p(pred_arr.ctypes.data)
        aq_ptr = None
        if aq is not None:
            aq_arr = np.ascontiguousarray(aq, dtype=np.float32)
            aq_ptr = ctypes.c_void_p(aq_arr.ctypes.data)
        rc = _LIB._recon(
            ctypes.c_void_p(ctypes.addressof(self._buf)), len(self._buf),
            ctypes.byref(pos), ctypes.byref(rng), ctypes.byref(cde),
            ctypes.c_void_p(self.probs.ctypes.data),
            ctypes.c_void_p(self.offsets.ctypes.data),
            int(pl), int(hb), int(wb), 1 if inter else 0,
            ctypes.c_void_p(tab.ctypes.data), pred_ptr, aq_ptr,
            ctypes.c_void_p(out.ctypes.data),
            int(clip[0]), int(clip[1]), int(self.layout),
        )
        self.dec.pos = int(pos.value)
        self.dec.range = int(rng.value)
        self.dec.code = int(cde.value)
        if rc != 0:
            raise RuntimeError("native decoder failed (rc=%d)" % rc)
        return out

    def planes_to_rgb(self, planes, subsample, out_h, out_w):
        ph, pw = planes[0].shape
        out = np.zeros((out_h, out_w, 3), np.uint8)
        arrs = [np.ascontiguousarray(p, dtype=np.int32) for p in planes]
        rc = _LIB._rgb(
            ctypes.c_void_p(arrs[0].ctypes.data),
            ctypes.c_void_p(arrs[1].ctypes.data),
            ctypes.c_void_p(arrs[2].ctypes.data),
            int(ph), int(pw), 1 if subsample else 0,
            int(out_h), int(out_w),
            ctypes.c_void_p(out.ctypes.data),
        )
        if rc != 0:
            raise RuntimeError("native rgb stage failed (rc=%d)" % rc)
        return out
