"""Optional native fast path for the entropy encoder.

``mtcodec.entropy.enc_block`` is a Python loop over every quantised coefficient
of every block — about 97k blocks per 1080p frame, which is where almost all of
encode time goes. ``native/`` carries a Rust mirror of ``arithmetic.Encoder``
plus ``enc_block``/``enc_skip`` that emits a bit-identical stream, so anything
written here decodes with the existing Python and native decoders.

Everything degrades gracefully: with no library (or ``MTCODEC_NO_NATIVE=1``)
``available()`` is False and the caller keeps the pure Python path.
"""

import ctypes

import numpy as np

from .fastdec import _FIRST, _LIB, _TOTAL_PER_PLANE


def _bind(lib):
    if lib is None:
        return None
    try:
        new = lib.mt_enc_new
        plane = lib.mt_enc_plane
        flush = lib.mt_enc_flush
        free = lib.mt_enc_free
        quant = lib.mt_enc_quant_plane
        recon = lib.mt_enc_recon_plane
    except AttributeError:
        return None
    new.restype = ctypes.c_void_p
    new.argtypes = []
    plane.restype = ctypes.c_int
    plane.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
    ]
    flush.restype = ctypes.c_void_p
    flush.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    free.restype = None
    free.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    quant.restype = ctypes.c_int
    quant.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    recon.restype = ctypes.c_int
    recon.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_int, ctypes.c_int,
    ]
    return {"new": new, "plane": plane, "flush": flush, "free": free,
            "quant": quant, "recon": recon}


_ENC = _bind(_LIB)


def available():
    return _ENC is not None


class PlaneEncoder:
    """Encode whole planes of one clip through the native library.

    The adaptive probability state lives here across frames, exactly like
    ``fastdec.PlaneDecoder`` does on the decode side.
    """

    def __init__(self, model, mode_model, planes=3):
        if _ENC is None:
            raise RuntimeError("native encoder not available")
        self.planes = planes
        self.probs = np.zeros(_TOTAL_PER_PLANE * planes, np.int16)
        self._fill(model, mode_model)

    def _fill(self, model, mode_model):
        planes = self.planes
        src = [
            model.dc_cls, model.dc_sign, model.dc_extra, model.last,
            model.sig, model.ac_cls, model.ac_sign, model.ac_extra,
            mode_model.skip,
        ]
        for k, values in enumerate(src):
            start = _FIRST[k] * planes
            stop = start + len(values)
            self.probs[start:stop] = np.asarray(values, dtype=np.int16)

    def encode(self, planes_qz, inter):
        """Encode 3 quantised planes into one frame payload."""
        handle = _ENC["new"]()
        if not handle:
            raise RuntimeError("native encoder alloc failed")
        for pl, qz in enumerate(planes_qz):
            arr = np.ascontiguousarray(qz, dtype=np.int32)
            if arr.ndim != 3 or arr.shape[2] != 64:
                raise ValueError("quantised plane must be hb*wb*64")
            rc = _ENC["plane"](
                ctypes.c_void_p(handle),
                ctypes.c_void_p(arr.ctypes.data),
                int(arr.shape[0]), int(arr.shape[1]),
                ctypes.c_void_p(self.probs.ctypes.data),
                int(self.planes), int(pl), 1 if inter else 0,
            )
            if rc != 0:
                raise RuntimeError("native encoder failed (rc=%d)" % rc)
        n = ctypes.c_size_t(0)
        ptr = _ENC["flush"](ctypes.c_void_p(handle), ctypes.byref(n))
        if not ptr:
            raise RuntimeError("native encoder flush failed")
        data = ctypes.string_at(ptr, n.value)
        _ENC["free"](ctypes.c_void_p(ptr), n.value)
        return data


def quantize_plane(plane, step, pred=None):
    """Forward DCT + quantise one plane into hb*wb*64 zig-zag coefficients."""
    if _ENC is None:
        raise RuntimeError("native encoder not available")
    src = np.ascontiguousarray(plane, dtype=np.float64)
    hb, wb = src.shape[0] // 8, src.shape[1] // 8
    tab = np.ascontiguousarray(step, dtype=np.float64)
    out = np.zeros((hb, wb, 64), np.int32)
    pred_ptr = None
    if pred is not None:
        pa = np.ascontiguousarray(pred, dtype=np.float64)
        pred_ptr = ctypes.c_void_p(pa.ctypes.data)
    rc = _ENC["quant"](
        ctypes.c_void_p(src.ctypes.data), hb, wb,
        ctypes.c_void_p(tab.ctypes.data), pred_ptr,
        ctypes.c_void_p(out.ctypes.data),
    )
    if rc != 0:
        raise RuntimeError("native quantise failed (rc=%d)" % rc)
    return out


def recon_plane(qz, step, pred, clip):
    """Dequantise + inverse DCT (+ prediction) + clip into a pixel plane."""
    if _ENC is None:
        raise RuntimeError("native encoder not available")
    q = np.ascontiguousarray(qz, dtype=np.int32)
    hb, wb = q.shape[0], q.shape[1]
    tab = np.ascontiguousarray(step, dtype=np.float64)
    out = np.zeros((hb * 8, wb * 8), np.int32)
    pred_ptr = None
    if pred is not None:
        pa = np.ascontiguousarray(pred, dtype=np.int32)
        pred_ptr = ctypes.c_void_p(pa.ctypes.data)
    rc = _ENC["recon"](
        ctypes.c_void_p(q.ctypes.data), hb, wb,
        ctypes.c_void_p(tab.ctypes.data), pred_ptr,
        ctypes.c_void_p(out.ctypes.data),
        int(clip[0]), int(clip[1]),
    )
    if rc != 0:
        raise RuntimeError("native reconstruction failed (rc=%d)" % rc)
    return out
