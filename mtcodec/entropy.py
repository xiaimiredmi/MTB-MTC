from .arithmetic import PROB_INIT, enc_tree, dec_tree, enc_bits, dec_bits

NBAND = 8


class Model:
    def __init__(self, planes):
        self.planes = planes
        self.last = [PROB_INIT] * (64 * planes)
        self.sig = [PROB_INIT] * (8 * planes)
        self.ac_cls = [PROB_INIT] * (8 * 16 * planes)
        self.ac_sign = [PROB_INIT] * (8 * planes)
        self.ac_extra = [PROB_INIT] * (8 * 16 * planes)
        self.dc_cls = [PROB_INIT] * (16 * planes)
        self.dc_sign = [PROB_INIT] * planes
        self.dc_extra = [PROB_INIT] * (16 * planes)
        self.res_cls = [PROB_INIT] * (5 * 16 * planes)
        self.res_sign = [PROB_INIT] * (5 * planes)
        self.res_extra = [PROB_INIT] * (5 * 16 * planes)


def enc_block(enc, m, pl, qc, prev_dc):
    d = qc[0] - prev_dc
    sign = 0
    if d < 0:
        d = -d
        sign = 1
    c = d.bit_length()
    enc_tree(enc, m.dc_cls, pl * 16, 4, c)
    if c:
        enc.encode(m.dc_sign, pl, sign)
        if c > 1:
            enc_bits(enc, m.dc_extra, pl * 16, c - 1, d - (1 << (c - 1)))

    last = 0
    for i in range(63, 0, -1):
        if qc[i]:
            last = i
            break
    enc_tree(enc, m.last, pl * 64, 6, last)

    for i in range(1, last + 1):
        v = qc[i]
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
        else:
            enc.encode(m.sig, sidx, 0)


def dec_block(dec, m, pl, prev_dc):
    c = dec_tree(dec, m.dc_cls, pl * 16, 4)
    dc = 0
    if c:
        sign = dec.decode(m.dc_sign, pl)
        mag = 1 << (c - 1)
        if c > 1:
            mag += dec_bits(dec, m.dc_extra, pl * 16, c - 1)
        dc = -mag if sign else mag
    dc += prev_dc

    last = dec_tree(dec, m.last, pl * 64, 6)
    qc = [0] * 64
    qc[0] = dc
    for i in range(1, last + 1):
        sidx = pl * 8 + (i >> 3)
        if dec.decode(m.sig, sidx):
            c = dec_tree(dec, m.ac_cls, sidx * 16, 4)
            sign = dec.decode(m.ac_sign, sidx)
            mag = 1 << (c - 1)
            if c > 1:
                mag += dec_bits(dec, m.ac_extra, sidx * 16, c - 1)
            qc[i] = -mag if sign else mag
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
    def __init__(self, planes):
        self.skip = [PROB_INIT] * (planes * 2)


def enc_skip(enc, m, pl, ctx, bit):
    enc.encode(m.skip, pl * 2 + ctx, bit)


def dec_skip(dec, m, pl, ctx):
    return dec.decode(m.skip, pl * 2 + ctx)
