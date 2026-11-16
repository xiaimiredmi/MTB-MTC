from .arithmetic import PROB_INIT, enc_tree, dec_tree, enc_bits, dec_bits

NBAND = 8


def _group(k):
    """Zig-zag band; the context layout splits every band by neighbour zero."""
    return k >> 3


class Model:
    def __init__(self, planes, layout=1):
        self.planes = planes
        self.layout = 2 if layout == 2 else 1
        ctx = self.layout == 2
        self.last = [PROB_INIT] * ((128 if ctx else 64) * planes)
        self.sig = [PROB_INIT] * ((32 if ctx else 8) * planes)
        self.ac_cls = [PROB_INIT] * ((32 if ctx else 8) * 16 * planes)
        self.ac_sign = [PROB_INIT] * ((32 if ctx else 8) * planes)
        self.ac_extra = [PROB_INIT] * ((32 if ctx else 8) * 16 * planes)
        self.dc_cls = [PROB_INIT] * ((32 if ctx else 16) * planes)
        self.dc_sign = [PROB_INIT] * ((2 if ctx else 1) * planes)
        self.dc_extra = [PROB_INIT] * ((32 if ctx else 16) * planes)
        self.res_cls = [PROB_INIT] * (5 * 16 * planes)
        self.res_sign = [PROB_INIT] * (5 * planes)
        self.res_extra = [PROB_INIT] * (5 * 16 * planes)


def enc_block(enc, m, pl, qc, prev_dc, zero_ctx=0):
    ctx = getattr(m, "layout", 1) == 2
    z = zero_ctx if ctx else 0
    dc_stride = 32 if ctx else 16
    sign_stride = 2 if ctx else 1
    last_stride = 128 if ctx else 64

    d = qc[0] - prev_dc
    sign = 0
    if d < 0:
        d = -d
        sign = 1
    c = d.bit_length()
    enc_tree(enc, m.dc_cls, pl * dc_stride + z * 16, 4, c)
    if c:
        enc.encode(m.dc_sign, pl * sign_stride + z, sign)
        if c > 1:
            enc_bits(enc, m.dc_extra, pl * dc_stride + z * 16, c - 1,
                     d - (1 << (c - 1)))

    last = 0
    for i in range(63, 0, -1):
        if qc[i]:
            last = i
            break
    enc_tree(enc, m.last, pl * last_stride + z * 64, 6, last)

    prev_nz = 0
    for i in range(1, last + 1):
        v = qc[i]
        if ctx:
            sidx = pl * 32 + z * 16 + prev_nz * 8 + (i >> 3)
        else:
            sidx = pl * 8 + (i >> 3)
        if v:
            enc.encode(m.sig, sidx, 1)
            sign = 0
            if v < 0:
                v = -v
                sign = 1
            c = v.bit_length()
            enc_tree(enc, m.ac_cls, sidx * 16, 4, c)
            enc.encode(m.ac_sign, sidx, sign)
            if c > 1:
                enc_bits(enc, m.ac_extra, sidx * 16, c - 1, v - (1 << (c - 1)))
            prev_nz = 1
        else:
            enc.encode(m.sig, sidx, 0)
            prev_nz = 0


def dec_block(dec, m, pl, prev_dc, zero_ctx=0):
    ctx = getattr(m, "layout", 1) == 2
    z = zero_ctx if ctx else 0
    dc_stride = 32 if ctx else 16
    sign_stride = 2 if ctx else 1
    last_stride = 128 if ctx else 64

    c = dec_tree(dec, m.dc_cls, pl * dc_stride + z * 16, 4)
    dc = 0
    if c:
        sign = dec.decode(m.dc_sign, pl * sign_stride + z)
        mag = 1 << (c - 1)
        if c > 1:
            mag += dec_bits(dec, m.dc_extra, pl * dc_stride + z * 16, c - 1)
        dc = -mag if sign else mag
    dc += prev_dc

    last = dec_tree(dec, m.last, pl * last_stride + z * 64, 6)
    qc = [0] * 64
    qc[0] = dc
    prev_nz = 0
    for i in range(1, last + 1):
        if ctx:
            sidx = pl * 32 + z * 16 + prev_nz * 8 + (i >> 3)
        else:
            sidx = pl * 8 + (i >> 3)
        if dec.decode(m.sig, sidx):
            c = dec_tree(dec, m.ac_cls, sidx * 16, 4)
            sign = dec.decode(m.ac_sign, sidx)
            mag = 1 << (c - 1)
            if c > 1:
                mag += dec_bits(dec, m.ac_extra, sidx * 16, c - 1)
            qc[i] = -mag if sign else mag
            prev_nz = 1
        else:
            prev_nz = 0
    return qc


def enc_res(enc, m, pl, ctx, value):
    sign = 0
    if value < 0:
        value = -value
        sign = 1
    base = (pl * 5 + ctx) * 16
    c = value.bit_length()
    enc_tree(enc, m.res_cls, base, 4, c)
    if c:
        enc.encode(m.res_sign, pl * 5 + ctx, sign)
        if c > 1:
            enc_bits(enc, m.res_extra, base, c - 1, value - (1 << (c - 1)))


def dec_res(dec, m, pl, ctx):
    base = (pl * 5 + ctx) * 16
    c = dec_tree(dec, m.res_cls, base, 4)
    if not c:
        return 0
    sign = dec.decode(m.res_sign, pl * 5 + ctx)
    value = 1 << (c - 1)
    if c > 1:
        value += dec_bits(dec, m.res_extra, base, c - 1)
    return -value if sign else value


class ModeModel:
    def __init__(self, planes, layout=1):
        self.layout = 2 if layout == 2 else 1
        self.skip = [PROB_INIT] * (planes * (4 if self.layout == 2 else 2))


def enc_skip(enc, m, pl, ctx, bit, above=0):
    if getattr(m, "layout", 1) == 2:
        enc.encode(m.skip, pl * 4 + above * 2 + ctx, bit)
    else:
        enc.encode(m.skip, pl * 2 + ctx, bit)


def dec_skip(dec, m, pl, ctx, above=0):
    if getattr(m, "layout", 1) == 2:
        return dec.decode(m.skip, pl * 4 + above * 2 + ctx)
    return dec.decode(m.skip, pl * 2 + ctx)
