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
    prep = None
    try:
        prep = lib.mt_prep_frame
    except AttributeError:
        prep = None
    if prep is not None:
        prep.restype = ctypes.c_int
        prep.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
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
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    recon.restype = ctypes.c_int
    recon.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
    ]
    me = None
    me_pred = None
    try:
        me = lib.mt_me_search
        me_pred = lib.mt_me_predict
    except AttributeError:
        me = None
    if me is not None:
        me.restype = ctypes.c_int
        me.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        me_pred.restype = ctypes.c_int
        me_pred.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p,
        ]
    hp = None
    search_hp = None
    predict_hp = None
    aq = None
    try:
        hp = lib.mt_hp_interp
        search_hp = lib.mt_me_search_hp
        predict_hp = lib.mt_me_predict_hp
        aq = lib.mt_aq_table
    except AttributeError:
        hp = None
    if hp is not None:
        hp.restype = ctypes.c_int
        hp.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                       ctypes.c_void_p]
        search_hp.restype = ctypes.c_int
        search_hp.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ]
        predict_hp.restype = ctypes.c_int
        predict_hp.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        aq.restype = ctypes.c_int
        aq.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_double, ctypes.c_double, ctypes.c_double,
            ctypes.c_void_p,
        ]
    return {"new": new, "plane": plane, "flush": flush, "free": free,
            "quant": quant, "recon": recon, "prep": prep,
            "me": me, "me_pred": me_pred,
            "hp": hp, "search_hp": search_hp, "predict_hp": predict_hp,
            "aq": aq}


_ENC = _bind(_LIB)


def available():
    return _ENC is not None


def prep_available():
    return _ENC is not None and _ENC.get("prep") is not None


def me_available():
    return _ENC is not None and _ENC.get("me") is not None


def hp_available():
    return _ENC is not None and _ENC.get("hp") is not None


def aq_available():
    return _ENC is not None and _ENC.get("aq") is not None


def aq_table(ref, block=8, strength=0.35, lo=0.70, hi=1.40):
    """Per-block AQ multipliers, ``(nbh, nbw)`` float32, computed in Rust."""
    if not aq_available():
        raise RuntimeError("native AQ table not available")
    ref = np.ascontiguousarray(ref, dtype=np.int32)
    h, w = ref.shape
    nbh, nbw = h // block, w // block
    out = np.zeros((nbh, nbw), np.float32)
    rc = _ENC["aq"](
        ctypes.c_void_p(ref.ctypes.data), w, h, block,
        ctypes.c_double(strength), ctypes.c_double(lo), ctypes.c_double(hi),
        ctypes.c_void_p(out.ctypes.data),
    )
    if rc != 0:
        raise RuntimeError("native AQ table failed")
    return out


def me_search(cur, ref, block=16, radius=16, refine=2):
    """Per-block motion vectors, ``(nbh, nbw, 2)`` int8, entirely in Rust."""
    if not me_available():
        raise RuntimeError("native motion search not available")
    cur = np.ascontiguousarray(cur, dtype=np.int32)
    ref = np.ascontiguousarray(ref, dtype=np.int32)
    h, w = cur.shape
    nbh, nbw = h // block, w // block
    mv = np.zeros((nbh, nbw, 2), np.int8)
    rc = _ENC["me"](
        ctypes.c_void_p(cur.ctypes.data), ctypes.c_void_p(ref.ctypes.data),
        w, h, block, radius, refine, ctypes.c_void_p(mv.ctypes.data),
    )
    if rc != 0:
        raise RuntimeError("native motion search failed")
    return mv


def me_predict(ref, mv, block=16):
    """Prediction plane built from ``ref`` and the vector table, in Rust."""
    if not me_available():
        raise RuntimeError("native motion prediction not available")
    ref = np.ascontiguousarray(ref, dtype=np.int32)
    mv = np.ascontiguousarray(mv, dtype=np.int8)
    h, w = ref.shape
    out = np.zeros((h, w), np.int32)
    rc = _ENC["me_pred"](
        ctypes.c_void_p(ref.ctypes.data), ctypes.c_void_p(mv.ctypes.data),
        w, h, block, ctypes.c_void_p(out.ctypes.data),
    )
    if rc != 0:
        raise RuntimeError("native motion prediction failed")
    return out


def hp_interp(ref):
    """Half-pel grid of ``ref``: ``(2h, 2w)`` int32, built once per plane."""
    if not hp_available():
        raise RuntimeError("native half-pel interpolation not available")
    ref = np.ascontiguousarray(ref, dtype=np.int32)
    h, w = ref.shape
    out = np.zeros((2 * h, 2 * w), np.int32)
    rc = _ENC["hp"](
        ctypes.c_void_p(ref.ctypes.data), w, h,
        ctypes.c_void_p(out.ctypes.data),
    )
    if rc != 0:
        raise RuntimeError("native half-pel interpolation failed")
    return out


def me_search_hp(cur, ref, hp, block=16, radius=16, refine=2):
    """Quarter-pel motion vectors, ``(nbh, nbw, 2)`` int16."""
    if not hp_available():
        raise RuntimeError("native sub-pixel motion search not available")
    cur = np.ascontiguousarray(cur, dtype=np.int32)
    ref = np.ascontiguousarray(ref, dtype=np.int32)
    hp = np.ascontiguousarray(hp, dtype=np.int32)
    h, w = cur.shape
    nbh, nbw = h // block, w // block
    mv = np.zeros((nbh, nbw, 2), np.int16)
    rc = _ENC["search_hp"](
        ctypes.c_void_p(cur.ctypes.data), ctypes.c_void_p(ref.ctypes.data),
        ctypes.c_void_p(hp.ctypes.data),
        w, h, block, radius, refine, ctypes.c_void_p(mv.ctypes.data),
    )
    if rc != 0:
        raise RuntimeError("native sub-pixel motion search failed")
    return mv


def me_predict_hp(hp, mv, block=16):
    """Prediction plane sampled at quarter-pel vectors."""
    if not hp_available():
        raise RuntimeError("native sub-pixel prediction not available")
    hp = np.ascontiguousarray(hp, dtype=np.int32)
    mv = np.ascontiguousarray(mv, dtype=np.int16)
    h, w = hp.shape[0] // 2, hp.shape[1] // 2
    out = np.zeros((h, w), np.int32)
    rc = _ENC["predict_hp"](
        ctypes.c_void_p(hp.ctypes.data), ctypes.c_void_p(mv.ctypes.data),
        w, h, block, ctypes.c_void_p(out.ctypes.data),
    )
    if rc != 0:
        raise RuntimeError("native sub-pixel prediction failed")
    return out


def prep_frame(frame, mult, subsample):
    """RGB uint8 frame -> padded YCoCg float64 planes, entirely in Rust."""
    if not prep_available():
        raise RuntimeError("native prep not available")
    rgb = np.ascontiguousarray(frame, dtype=np.uint8)
    h, w = rgb.shape[0], rgb.shape[1]
    ph = -(-h // mult) * mult
    pw = -(-w // mult) * mult
    y = np.zeros((ph, pw), np.float64)
    if subsample:
        co = np.zeros((ph // 2, pw // 2), np.float64)
        cg = np.zeros((ph // 2, pw // 2), np.float64)
    else:
        co = np.zeros((ph, pw), np.float64)
        cg = np.zeros((ph, pw), np.float64)
    rc = _ENC["prep"](
        ctypes.c_void_p(rgb.ctypes.data), w, h, pw, ph, 1 if subsample else 0,
        ctypes.c_void_p(y.ctypes.data),
        ctypes.c_void_p(co.ctypes.data),
        ctypes.c_void_p(cg.ctypes.data),
    )
    if rc != 0:
        raise RuntimeError("native prep failed (rc=%d)" % rc)
    return [y, co, cg]


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


def quantize_plane(plane, step, pred=None, aq=None):
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
    aq_ptr = None
    if aq is not None:
        aqa = np.ascontiguousarray(aq, dtype=np.float32)
        aq_ptr = ctypes.c_void_p(aqa.ctypes.data)
    rc = _ENC["quant"](
        ctypes.c_void_p(src.ctypes.data), hb, wb,
        ctypes.c_void_p(tab.ctypes.data), pred_ptr, aq_ptr,
        ctypes.c_void_p(out.ctypes.data),
    )
    if rc != 0:
        raise RuntimeError("native quantise failed (rc=%d)" % rc)
    return out


def recon_plane(qz, step, pred, clip, aq=None):
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
    aq_ptr = None
    if aq is not None:
        aqa = np.ascontiguousarray(aq, dtype=np.float32)
        aq_ptr = ctypes.c_void_p(aqa.ctypes.data)
    rc = _ENC["recon"](
        ctypes.c_void_p(q.ctypes.data), hb, wb,
        ctypes.c_void_p(tab.ctypes.data), pred_ptr, aq_ptr,
        ctypes.c_void_p(out.ctypes.data),
        int(clip[0]), int(clip[1]),
    )
    if rc != 0:
        raise RuntimeError("native reconstruction failed (rc=%d)" % rc)
    return out
