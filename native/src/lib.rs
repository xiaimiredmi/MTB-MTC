//! Fast arithmetic + block decoder for MTB / MTC.
//!
//! The Python codec spends ~76% of decode time in `entropy.dec_block`, i.e. in
//! `arithmetic.Decoder.decode` running one bit at a time. This crate implements
//! the exact same bit-level algorithm in Rust and decodes a whole plane per
//! call, so Python only pays one FFI crossing per plane instead of ~38M.

const PROB_BITS: u32 = 11;
const PROB_TOTAL: u32 = 1 << PROB_BITS;
const MOVE_BITS: u32 = 5;
const TOP: u32 = 1 << 24;
const MASK32: u32 = 0xFFFF_FFFF;

const OFF_COUNT: usize = 9;

struct Dec {
    data: *const u8,
    len: usize,
    pos: usize,
    range: u32,
    code: u32,
}

impl Dec {
    #[inline(always)]
    fn next_byte(&mut self) -> u32 {
        let p = self.pos;
        self.pos = p + 1;
        if p < self.len {
            unsafe { *self.data.add(p) as u32 }
        } else {
            0
        }
    }

    #[inline(always)]
    fn decode(&mut self, probs: &mut [i16], idx: usize) -> u32 {
        let p = probs[idx] as u32;
        let bound = (self.range >> PROB_BITS) * p;
        let bit;
        if self.code < bound {
            self.range = bound;
            probs[idx] = (p + ((PROB_TOTAL - p) >> MOVE_BITS)) as i16;
            bit = 0;
        } else {
            self.code -= bound;
            self.range -= bound;
            probs[idx] = (p - (p >> MOVE_BITS)) as i16;
            bit = 1;
        }
        while self.range < TOP {
            self.range <<= 8;
            self.code = (self.code.wrapping_shl(8) | self.next_byte()) & MASK32;
        }
        bit
    }
}

#[inline(always)]
fn dec_tree(d: &mut Dec, probs: &mut [i16], base: usize, bits: u32) -> u32 {
    let mut node: usize = 1;
    let mut i = bits;
    while i > 0 {
        i -= 1;
        let bit = d.decode(probs, base + node) as usize;
        node = (node << 1) | bit;
    }
    (node as u32) - (1u32 << bits)
}

#[inline(always)]
fn dec_bits(d: &mut Dec, probs: &mut [i16], base: usize, count: u32) -> u32 {
    let mut v = 0u32;
    let mut i = count;
    while i > 0 {
        i -= 1;
        v |= d.decode(probs, base + i as usize) << i;
    }
    v
}

struct Bases {
    dc_cls: usize,
    dc_sign: usize,
    dc_extra: usize,
    last: usize,
    sig: usize,
    ac_cls: usize,
    ac_sign: usize,
    ac_extra: usize,
    skip: usize,
}

impl Bases {
    fn new(off: &[u32; OFF_COUNT], pl: usize) -> Self {
        Bases {
            dc_cls: off[0] as usize + pl * 16,
            dc_sign: off[1] as usize + pl,
            dc_extra: off[2] as usize + pl * 16,
            last: off[3] as usize + pl * 64,
            sig: off[4] as usize + pl * 8,
            ac_cls: off[5] as usize + pl * 128,
            ac_sign: off[6] as usize + pl * 8,
            ac_extra: off[7] as usize + pl * 128,
            skip: off[8] as usize + pl * 2,
        }
    }
}

#[inline]
fn dec_block(d: &mut Dec, probs: &mut [i16], b: &Bases, prev_dc: i32, out: &mut [i32]) {
    let c = dec_tree(d, probs, b.dc_cls, 4);
    let mut dc: i32 = 0;
    if c != 0 {
        let sign = d.decode(probs, b.dc_sign);
        let mut mag: i32 = 1 << (c - 1);
        if c > 1 {
            mag += dec_bits(d, probs, b.dc_extra, c - 1) as i32;
        }
        dc = if sign != 0 { -mag } else { mag };
    }
    dc += prev_dc;
    out[0] = dc;

    let last = dec_tree(d, probs, b.last, 6) as usize;
    let mut i: usize = 1;
    while i <= last {
        let band = i >> 3;
        if d.decode(probs, b.sig + band) != 0 {
            let cls = dec_tree(d, probs, b.ac_cls + band * 16, 4);
            let sign = d.decode(probs, b.ac_sign + band);
            let mut mag: i32 = 1 << (cls - 1);
            if cls > 1 {
                mag += dec_bits(d, probs, b.ac_extra + band * 16, cls - 1) as i32;
            }
            out[i] = if sign != 0 { -mag } else { mag };
        }
        i += 1;
    }
}

/// Decode one plane of `hb * wb` blocks.
///
/// `probs` is the concatenated adaptive probability table; `offsets` gives the
/// start of each sub-table inside it. Decoder state and probabilities are
/// updated in place.
#[no_mangle]
pub unsafe extern "C" fn mt_dec_plane(
    data: *const u8,
    data_len: usize,
    pos: *mut usize,
    range: *mut u32,
    code: *mut u32,
    probs: *mut i16,
    probs_len: usize,
    offsets: *const u32,
    pl: u32,
    hb: u32,
    wb: u32,
    inter: u32,
    out: *mut i32,
) -> i32 {
    if data.is_null() || pos.is_null() || range.is_null() || code.is_null() {
        return -1;
    }
    if probs.is_null() || offsets.is_null() || out.is_null() {
        return -1;
    }
    let mut off_arr = [0u32; OFF_COUNT];
    for k in 0..OFF_COUNT {
        off_arr[k] = *offsets.add(k);
    }
    let total = 371usize * 3;
    let _ = probs_len;
    let probs_slice = std::slice::from_raw_parts_mut(probs, total.max(1));

    let mut d = Dec {
        data,
        len: data_len,
        pos: *pos,
        range: *range,
        code: *code,
    };
    let bases = Bases::new(&off_arr, pl as usize);

    let cell = 64usize;
    let total_cells = (hb as usize) * (wb as usize);
    let out_slice = std::slice::from_raw_parts_mut(out, total_cells * cell);

    let mut r: usize = 0;
    while r < hb as usize {
        let mut prev: i32 = 0;
        let mut left_skip: u32 = 0;
        let mut c: usize = 0;
        while c < wb as usize {
            let slot = (r * (wb as usize) + c) * cell;
            let blk = &mut out_slice[slot..slot + cell];
            for v in blk.iter_mut() {
                *v = 0;
            }
            if inter != 0 && d.decode(probs_slice, bases.skip + left_skip as usize) != 0 {
                left_skip = 1;
                c += 1;
                continue;
            }
            dec_block(&mut d, probs_slice, &bases, prev, blk);
            prev = blk[0];
            left_skip = 0;
            c += 1;
        }
        r += 1;
    }

    *pos = d.pos;
    *range = d.range;
    *code = d.code;
    0
}


// ---------------------------------------------------------------------------
// Whole-plane reconstruction: dequantise, inverse DCT, add prediction, clip.
// ---------------------------------------------------------------------------

fn dct_matrix() -> [[f64; 8]; 8] {
    let mut m = [[0.0f64; 8]; 8];
    for u in 0..8usize {
        for x in 0..8usize {
            m[u][x] = (((2 * x + 1) as f64) * (u as f64) * std::f64::consts::PI / 16.0)
                .cos()
                * 0.5;
        }
    }
    for x in 0..8usize {
        m[0][x] = (1.0f64 / 8.0).sqrt();
    }
    m
}

fn zigzag() -> [(usize, usize); 64] {
    let mut out = [(0usize, 0usize); 64];
    let mut k = 0usize;
    for s in 0..15usize {
        let mut seq: Vec<(usize, usize)> = Vec::with_capacity(8);
        for v in 0..8usize {
            if s >= v && s - v < 8 {
                seq.push((s - v, v));
            }
        }
        if s % 2 == 1 {
            seq.reverse();
        }
        for p in seq {
            if k < 64 {
                out[k] = p;
                k += 1;
            }
        }
    }
    out
}

/// numpy's np.rint: round half to even.
#[inline]
fn rint(x: f64) -> f64 {
    let f = x.floor();
    let frac = x - f;
    if frac > 0.5 {
        f + 1.0
    } else if frac < 0.5 {
        f
    } else if (f as i64) & 1 == 0 {
        f
    } else {
        f + 1.0
    }
}

#[inline]
fn idct_block(c: &[[f64; 8]; 8], m: &[[f64; 8]; 8], out: &mut [[f64; 8]; 8]) {
    let mut tmp = [[0.0f64; 8]; 8];
    for a in 0..8usize {
        for v in 0..8usize {
            let mut s = 0.0f64;
            for b in 0..8usize {
                s += c[a][b] * m[b][v];
            }
            tmp[a][v] = s;
        }
    }
    for u in 0..8usize {
        for v in 0..8usize {
            let mut s = 0.0f64;
            for a in 0..8usize {
                s += m[a][u] * tmp[a][v];
            }
            out[u][v] = s;
        }
    }
}

/// Decode one plane and reconstruct it to pixels.
///
/// `step` points at the 64-entry quantisation table (row-major 8x8), `pred`
/// optionally points at the reference plane used as prediction (inter frames).
/// Output is `hb*8` rows by `wb*8` columns of i32 pixels, clipped for `pl`.
#[no_mangle]
pub unsafe extern "C" fn mt_dec_recon_plane(
    data: *const u8,
    data_len: usize,
    pos: *mut usize,
    range: *mut u32,
    code: *mut u32,
    probs: *mut i16,
    offsets: *const u32,
    pl: u32,
    hb: u32,
    wb: u32,
    inter: u32,
    step: *const f64,
    pred: *const i32,
    out_plane: *mut i32,
    clip_lo: i32,
    clip_hi: i32,
) -> i32 {
    if data.is_null() || pos.is_null() || range.is_null() || code.is_null() {
        return -1;
    }
    if probs.is_null() || offsets.is_null() || step.is_null() || out_plane.is_null() {
        return -1;
    }
    let mut off_arr = [0u32; OFF_COUNT];
    for k in 0..OFF_COUNT {
        off_arr[k] = *offsets.add(k);
    }
    let probs_slice = std::slice::from_raw_parts_mut(probs, 371usize * 3);

    let mut d = Dec {
        data,
        len: data_len,
        pos: *pos,
        range: *range,
        code: *code,
    };
    let bases = Bases::new(&off_arr, pl as usize);

    let m = dct_matrix();
    let zz = zigzag();
    let step_tab = std::slice::from_raw_parts(step, 64);

    let pw = (wb as usize) * 8;
    let ph = (hb as usize) * 8;
    let out = std::slice::from_raw_parts_mut(out_plane, pw * ph);
    let use_pred = !pred.is_null();

    let mut qz = [0i32; 64];
    let mut coef = [[0.0f64; 8]; 8];
    let mut recon = [[0.0f64; 8]; 8];

    let mut r = 0usize;
    while r < hb as usize {
        let mut prev: i32 = 0;
        let mut left_skip: u32 = 0;
        let mut c = 0usize;
        while c < wb as usize {
            if inter != 0 && d.decode(probs_slice, bases.skip + left_skip as usize) != 0 {
                left_skip = 1;
                if use_pred {
                    for u in 0..8usize {
                        for v in 0..8usize {
                            let oy = r * 8 + u;
                            let ox = c * 8 + v;
                            out[oy * pw + ox] = *pred.add(oy * pw + ox);
                        }
                    }
                }
                c += 1;
                continue;
            }
            for v in qz.iter_mut() {
                *v = 0;
            }
            dec_block(&mut d, probs_slice, &bases, prev, &mut qz);
            prev = qz[0];

            for u in 0..8usize {
                for v in 0..8usize {
                    coef[u][v] = 0.0;
                }
            }
            for k in 0..64usize {
                let (u, v) = zz[k];
                coef[u][v] = qz[k] as f64 * step_tab[u * 8 + v];
            }
            idct_block(&coef, &m, &mut recon);

            for u in 0..8usize {
                for v in 0..8usize {
                    let mut val = recon[u][v];
                    let oy = r * 8 + u;
                    let ox = c * 8 + v;
                    if use_pred {
                        val += *pred.add(oy * pw + ox) as f64;
                    }
                    let mut q = rint(val);
                    if q < clip_lo as f64 {
                        q = clip_lo as f64;
                    }
                    if q > clip_hi as f64 {
                        q = clip_hi as f64;
                    }
                    out[oy * pw + ox] = q as i32;
                }
            }
            left_skip = 0;
            c += 1;
        }
        r += 1;
    }

    *pos = d.pos;
    *range = d.range;
    *code = d.code;
    0
}

/// YCoCg planes -> packed RGB bytes, exactly like color.ycocg_to_rgb + to_uint8.
#[no_mangle]
pub unsafe extern "C" fn mt_planes_rgb(
    p0: *const i32,
    p1: *const i32,
    p2: *const i32,
    ph: u32,
    pw: u32,
    subsample: u32,
    out_h: u32,
    out_w: u32,
    out: *mut u8,
) -> i32 {
    if p0.is_null() || p1.is_null() || p2.is_null() || out.is_null() {
        return -1;
    }
    let rows = ph as usize;
    let cols = pw as usize;
    let y_plane = std::slice::from_raw_parts(p0, rows * cols);
    let sub = subsample != 0;
    let ch = if sub { (rows / 2).max(1) } else { rows };
    let cw = if sub { (cols / 2).max(1) } else { cols };
    let co_plane = std::slice::from_raw_parts(p1, ch * cw);
    let cg_plane = std::slice::from_raw_parts(p2, ch * cw);

    let oh = out_h as usize;
    let ow = out_w as usize;
    let dst = std::slice::from_raw_parts_mut(out, oh * ow * 3);

    let mut y = 0usize;
    while y < oh {
        let mut x = 0usize;
        while x < ow {
            let yy = y_plane[y * cols + x];
            let (i, j) = if sub {
                let iy = (y / 2).min(ch - 1);
                let ix = (x / 2).min(cw - 1);
                (iy * cw + ix, iy * cw + ix)
            } else {
                (y * cols + x, y * cols + x)
            };
            let co = co_plane[i];
            let cg = cg_plane[j];

            let t = yy - (cg >> 1);
            let g = cg + t;
            let b = t - (co >> 1);
            let r = co + b;

            let base = (y * ow + x) * 3;
            dst[base] = clamp_byte(r);
            dst[base + 1] = clamp_byte(g);
            dst[base + 2] = clamp_byte(b);
            x += 1;
        }
        y += 1;
    }
    0
}

#[inline]
fn clamp_byte(v: i32) -> u8 {
    if v < 0 {
        0
    } else if v > 255 {
        255
    } else {
        v as u8
    }
}
// ---------------------------------------------------------------------------
// Multithreaded reconstruction: decode stays serial (bitstream + contexts are
// inherently sequential), the inverse DCT and the RGB packing fan out across
// cores. Each block is computed with exactly the same arithmetic order, so the
// output is bit-identical to the serial path.
// ---------------------------------------------------------------------------

struct SendPtr<T>(*mut T);
unsafe impl<T> Send for SendPtr<T> {}
unsafe impl<T> Sync for SendPtr<T> {}

struct SendCPtr<T>(*const T);
unsafe impl<T> Send for SendCPtr<T> {}
unsafe impl<T> Sync for SendCPtr<T> {}

fn worker_count(bands: usize) -> usize {
    let cpus = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    if bands < 2 || cpus < 2 {
        1
    } else {
        cpus.min(bands)
    }
}

unsafe fn recon_band(
    rows: usize,
    nb: usize,
    common: *const ReconCtx,
) {
    let ctx = &*common;
    let m = dct_matrix();
    let zz = zigzag();
    let step_tab = std::slice::from_raw_parts(ctx.step, 64);
    let pw = ctx.pw;
    let out = ctx.out;
    let pred = ctx.pred;
    let clip_lo = ctx.clip_lo as f64;
    let clip_hi = ctx.clip_hi as f64;

    let mut coef = [[0.0f64; 8]; 8];
    let mut recon = [[0.0f64; 8]; 8];

    for r in 0..rows {
        for c in 0..nb {
            let slot = (r * nb + c) * 64;
            for u in 0..8usize {
                for v in 0..8usize {
                    coef[u][v] = 0.0;
                }
            }
            for k in 0..64usize {
                let (u, v) = zz[k];
                let q = *ctx.qz.add(slot + k);
                coef[u][v] = q as f64 * *step_tab.get_unchecked(u * 8 + v);
            }
            idct_block(&coef, &m, &mut recon);

            let oy0 = r * 8;
            for u in 0..8usize {
                for v in 0..8usize {
                    let mut val = recon[u][v];
                    let idx = (oy0 + u) * pw + c * 8 + v;
                    if !pred.is_null() {
                        val += *pred.add(idx) as f64;
                    }
                    let mut q = rint(val);
                    if q < clip_lo {
                        q = clip_lo;
                    }
                    if q > clip_hi {
                        q = clip_hi;
                    }
                    *out.add(idx) = q as i32;
                }
            }
        }
    }
}

#[repr(C)]
struct ReconCtx {
    qz: *const i32,
    step: *const f64,
    pred: *const i32,
    out: *mut i32,
    pw: usize,
    nb: usize,
    clip_lo: i32,
    clip_hi: i32,
}

#[no_mangle]
pub unsafe extern "C" fn mt_dec_recon_plane_p(
    data: *const u8,
    data_len: usize,
    pos: *mut usize,
    range: *mut u32,
    code: *mut u32,
    probs: *mut i16,
    offsets: *const u32,
    pl: u32,
    hb: u32,
    wb: u32,
    inter: u32,
    step: *const f64,
    pred: *const i32,
    out_plane: *mut i32,
    clip_lo: i32,
    clip_hi: i32,
) -> i32 {
    if data.is_null() || pos.is_null() || range.is_null() || code.is_null() {
        return -1;
    }
    if probs.is_null() || offsets.is_null() || step.is_null() || out_plane.is_null() {
        return -1;
    }
    let nb = wb as usize;
    let nrows = hb as usize;
    if nb == 0 || nrows == 0 {
        return -1;
    }

    let mut off_arr = [0u32; OFF_COUNT];
    for k in 0..OFF_COUNT {
        off_arr[k] = *offsets.add(k);
    }
    let probs_slice = std::slice::from_raw_parts_mut(probs, 371usize * 3);

    let blocks = nb * nrows;
    let mut qz_all = vec![0i32; blocks * 64];

    {
        let mut d = Dec {
            data,
            len: data_len,
            pos: *pos,
            range: *range,
            code: *code,
        };
        let bases = Bases::new(&off_arr, pl as usize);
        let mut r = 0usize;
        while r < nrows {
            let mut prev: i32 = 0;
            let mut left_skip: u32 = 0;
            let mut c = 0usize;
            while c < nb {
                let slot = (r * nb + c) * 64;
                if inter != 0 && d.decode(probs_slice, bases.skip + left_skip as usize) != 0 {
                    left_skip = 1;
                    c += 1;
                    continue;
                }
                let blk = &mut qz_all[slot..slot + 64];
                dec_block(&mut d, probs_slice, &bases, prev, blk);
                prev = blk[0];
                left_skip = 0;
                c += 1;
            }
            r += 1;
        }
        *pos = d.pos;
        *range = d.range;
        *code = d.code;
    }

    let ctx = ReconCtx {
        qz: qz_all.as_ptr(),
        step,
        pred,
        out: out_plane,
        pw: nb * 8,
        nb,
        clip_lo,
        clip_hi,
    };
    let cptr = SendCPtr(&ctx as *const ReconCtx);
    let nthreads = if nb * nrows < 1600 { 1 } else { worker_count(nrows) };
    if nthreads <= 1 {
        recon_band(nrows, nb, cptr.0);
    } else {
        let per = (nrows + nthreads - 1) / nthreads;
        std::thread::scope(|scope| {
            let mut start = 0usize;
            while start < nrows {
                let rows = per.min(nrows - start);
                let base = start;
                let cp_addr = cptr.0 as usize;
                scope.spawn(move || unsafe {
                    let ctx2 = &*(cp_addr as *const ReconCtx);
                    let sub = ReconCtx {
                        qz: ctx2.qz.add(base * nb * 64),
                        step: ctx2.step,
                        pred: if ctx2.pred.is_null() {
                            std::ptr::null()
                        } else {
                            ctx2.pred.add(base * 8 * ctx2.pw)
                        },
                        out: ctx2.out.add(base * 8 * ctx2.pw),
                        pw: ctx2.pw,
                        nb: ctx2.nb,
                        clip_lo: ctx2.clip_lo,
                        clip_hi: ctx2.clip_hi,
                    };
                    recon_band(rows, sub.nb, &sub);
                });
                start += rows;
            }
        });
    }
    0
}

/// Multithreaded YCoCg -> packed RGB.
#[no_mangle]
pub unsafe extern "C" fn mt_planes_rgb_p(
    p0: *const i32,
    p1: *const i32,
    p2: *const i32,
    ph: u32,
    pw: u32,
    subsample: u32,
    out_h: u32,
    out_w: u32,
    out: *mut u8,
) -> i32 {
    if p0.is_null() || p1.is_null() || p2.is_null() || out.is_null() {
        return -1;
    }
    let rows = ph as usize;
    let cols = pw as usize;
    let sub = subsample != 0;
    let ch = if sub { (rows / 2).max(1) } else { rows };
    let cw = if sub { (cols / 2).max(1) } else { cols };
    let oh = out_h as usize;
    let ow = out_w as usize;
    let nthreads = worker_count(oh);
    let share = RgbShare { p0, p1, p2, sub, ch, cw, cols, ow };
    let sptr = SendCPtr(&share as *const RgbShare);
    let dptr = SendPtr(out);

    if nthreads <= 1 {
        rgb_band(oh, &share, out);
    } else {
        let per = (oh + nthreads - 1) / nthreads;
        std::thread::scope(|scope| {
            let mut start = 0usize;
            while start < oh {
                let rows_here = per.min(oh - start);
                let base = start;
                let sp_addr = sptr.0 as usize;
                let dp_addr = dptr.0 as usize;
                scope.spawn(move || unsafe {
                    let sh = &*(sp_addr as *const RgbShare);
                    let dp = dp_addr as *mut u8;
                    rgb_band_from(rows_here, base, sh, dp.add(base * sh.ow * 3));
                });
                start += rows_here;
            }
        });
    }
    0
}

struct RgbShare {
    p0: *const i32,
    p1: *const i32,
    p2: *const i32,
    sub: bool,
    ch: usize,
    cw: usize,
    cols: usize,
    ow: usize,
}

#[inline]
unsafe fn rgb_px(share: &RgbShare, y: usize, x: usize) -> (i32, i32, i32) {
    let yy = *share.p0.add(y * share.cols + x);
    let (i, j) = if share.sub {
        let iy = (y / 2).min(share.ch - 1);
        let ix = (x / 2).min(share.cw - 1);
        let k = iy * share.cw + ix;
        (k, k)
    } else {
        let k = y * share.cols + x;
        (k, k)
    };
    let co = *share.p1.add(i);
    let cg = *share.p2.add(j);
    let t = yy - (cg >> 1);
    let g = cg + t;
    let b = t - (co >> 1);
    let r = co + b;
    (r, g, b)
}

unsafe fn rgb_band(rows: usize, share: &RgbShare, dst: *mut u8) {
    rgb_band_from(rows, 0, share, dst);
}

unsafe fn rgb_band_from(rows: usize, base: usize, share: &RgbShare, dst: *mut u8) {
    for ry in 0..rows {
        let y = base + ry;
        for x in 0..share.ow {
            let (r, g, b) = rgb_px(share, y, x);
            let o = (ry * share.ow + x) * 3;
            *dst.add(o) = clamp_byte(r);
            *dst.add(o + 1) = clamp_byte(g);
            *dst.add(o + 2) = clamp_byte(b);
        }
    }
}

/* -------------------------- encoder -------------------------- */
/* Exact mirror of mtcodec/arithmetic.py + mtcodec/entropy.py on the encode
   side: same 11-bit probabilities, same 5-bit adaptation, same symbol order,
   so the bytes match the Python encoder exactly. */

const P_BITS: u32 = 11;
const P_TOTAL: u64 = 2048;
const ENC_MOVE_BITS: u32 = 5;
const LOW_TOP: u32 = 1 << 24;
const ENC_MASK32: u64 = 0xFFFF_FFFF;
const PROBS_PER_PLANE: usize = 371;

pub struct Enc {
    low: u64,
    range: u32,
    cache: u64,
    cache_size: u32,
    out: Vec<u8>,
}

impl Enc {
    fn new() -> Enc {
        Enc {
            low: 0,
            range: ENC_MASK32 as u32,
            cache: 0,
            cache_size: 1,
            out: Vec::with_capacity(4096),
        }
    }

    #[inline]
    fn shift_low(&mut self) {
        let low = self.low;
        if low < 0xFF00_0000 || low > ENC_MASK32 {
            let carry = (low >> 32) as u8;
            self.out.push(self.cache.wrapping_add(carry as u64) as u8);
            let n = self.cache_size - 1;
            if n > 0 {
                let byte = 0xFFu8.wrapping_add(carry);
                for _ in 0..n {
                    self.out.push(byte);
                }
            }
            self.cache = (low >> 24) & 0xFF;
            self.cache_size = 0;
        }
        self.cache_size += 1;
        self.low = ((low & ENC_MASK32) << 8) & ENC_MASK32;
    }

    #[inline]
    fn encode(&mut self, probs: &mut [i16], idx: usize, bit: u32) {
        let p = probs[idx] as u64;
        let bound = ((self.range >> P_BITS) as u64) * p;
        if bit != 0 {
            self.low += bound;
            self.range -= bound as u32;
            probs[idx] = (p - (p >> ENC_MOVE_BITS)) as i16;
        } else {
            self.range = bound as u32;
            probs[idx] = (p + ((P_TOTAL - p) >> ENC_MOVE_BITS)) as i16;
        }
        while self.range < LOW_TOP {
            self.range <<= 8;
            self.shift_low();
        }
    }

    fn finish(mut self) -> Vec<u8> {
        for _ in 0..5 {
            self.shift_low();
        }
        self.out
    }
}

#[inline]
fn bit_len(v: i32) -> u32 {
    if v <= 0 {
        return 0;
    }
    let mut n = 0u32;
    let mut x = v;
    while x > 0 {
        n += 1;
        x >>= 1;
    }
    n
}

fn enc_tree(e: &mut Enc, probs: &mut [i16], base: usize, bits: u32, value: i32) {
    let mut node = 1usize;
    let mut i = bits as i32 - 1;
    while i >= 0 {
        let bit = ((value >> i) & 1) as u32;
        e.encode(probs, base + node, bit);
        node = (node << 1) | bit as usize;
        i -= 1;
    }
}

fn enc_bits(e: &mut Enc, probs: &mut [i16], base: usize, count: u32, value: i32) {
    let mut i = count as i32 - 1;
    while i >= 0 {
        let bit = ((value >> i) & 1) as u32;
        e.encode(probs, base + i as usize, bit);
        i -= 1;
    }
}

fn enc_block(
    e: &mut Enc,
    probs: &mut [i16],
    pl: usize,
    planes: usize,
    qc: &[i32],
    prev_dc: i32,
) {
    let b_dc_cls = 0usize;
    let b_dc_sign = 16 * planes;
    let b_dc_extra = 17 * planes;
    let b_last = 33 * planes;
    let b_sig = 97 * planes;
    let b_ac_cls = 105 * planes;
    let b_ac_sign = 233 * planes;
    let b_ac_extra = 241 * planes;

    let mut d = qc[0] - prev_dc;
    let mut sign = 0u32;
    if d < 0 {
        d = -d;
        sign = 1;
    }
    let c = bit_len(d);
    enc_tree(e, probs, b_dc_cls + pl * 16, 4, c as i32);
    if c > 0 {
        e.encode(probs, b_dc_sign + pl, sign);
        if c > 1 {
            enc_bits(e, probs, b_dc_extra + pl * 16, c - 1, d - (1 << (c - 1)));
        }
    }

    let mut last = 0usize;
    let mut i = 63usize;
    while i >= 1 {
        if qc[i] != 0 {
            last = i;
            break;
        }
        i -= 1;
    }
    enc_tree(e, probs, b_last + pl * 64, 6, last as i32);

    let mut k = 1usize;
    while k <= last {
        let mut v = qc[k];
        let sidx = pl * 8 + (k >> 3);
        if v != 0 {
            e.encode(probs, b_sig + sidx, 1);
            let mut sg = 0u32;
            if v < 0 {
                v = -v;
                sg = 1;
            }
            let c2 = bit_len(v);
            enc_tree(e, probs, b_ac_cls + sidx * 16, 4, c2 as i32);
            e.encode(probs, b_ac_sign + sidx, sg);
            if c2 > 1 {
                enc_bits(e, probs, b_ac_extra + sidx * 16, c2 - 1, v - (1 << (c2 - 1)));
            }
        } else {
            e.encode(probs, b_sig + sidx, 0);
        }
        k += 1;
    }
}

#[no_mangle]
pub extern "C" fn mt_enc_new() -> *mut Enc {
    Box::into_raw(Box::new(Enc::new()))
}

#[no_mangle]
pub extern "C" fn mt_enc_plane(
    e_ptr: *mut Enc,
    qc_ptr: *const i32,
    hb: u32,
    wb: u32,
    probs_ptr: *mut i16,
    planes: u32,
    pl: u32,
    inter: u32,
) -> i32 {
    if e_ptr.is_null() || qc_ptr.is_null() || probs_ptr.is_null() {
        return -1;
    }
    let nb = hb as usize * wb as usize;
    let pls = planes as usize;
    let e = unsafe { &mut *e_ptr };
    let qc = unsafe { std::slice::from_raw_parts(qc_ptr, nb * 64) };
    let probs = unsafe { std::slice::from_raw_parts_mut(probs_ptr, PROBS_PER_PLANE * pls) };
    let hb = hb as usize;
    let wb = wb as usize;
    let pl = pl as usize;
    let b_skip = 369 * pls;

    for r in 0..hb {
        let mut prev = 0i32;
        let mut left_skip = 0usize;
        for c in 0..wb {
            let off = (r * wb + c) * 64;
            let blk = &qc[off..off + 64];
            if inter != 0 {
                let mut skip = true;
                for v in blk.iter() {
                    if *v != 0 {
                        skip = false;
                        break;
                    }
                }
                e.encode(probs, b_skip + pl * 2 + left_skip, if skip { 1 } else { 0 });
                if skip {
                    left_skip = 1;
                    continue;
                }
                enc_block(e, probs, pl, pls, blk, prev);
                prev = blk[0];
                left_skip = 0;
            } else {
                enc_block(e, probs, pl, pls, blk, prev);
                prev = blk[0];
            }
        }
    }
    0
}

#[no_mangle]
pub extern "C" fn mt_enc_flush(e_ptr: *mut Enc, out_len: *mut usize) -> *mut u8 {
    if e_ptr.is_null() || out_len.is_null() {
        return std::ptr::null_mut();
    }
    let e = unsafe { Box::from_raw(e_ptr) };
    let bytes = e.finish();
    let len = bytes.len();
    let ptr = bytes.as_ptr() as *mut u8;
    std::mem::forget(bytes);
    unsafe {
        *out_len = len;
    }
    ptr
}

#[no_mangle]
pub extern "C" fn mt_enc_free(ptr: *mut u8, len: usize) {
    if ptr.is_null() || len == 0 {
        return;
    }
    unsafe {
        drop(Vec::from_raw_parts(ptr, len, len));
    }
}

#[no_mangle]
pub extern "C" fn mt_enc_quant_plane(
    plane: *const f64,
    hb: u32,
    wb: u32,
    step: *const f64,
    pred: *const f64,
    out_qz: *mut i32,
) -> i32 {
    if plane.is_null() || step.is_null() || out_qz.is_null() {
        return -1;
    }
    let hb = hb as usize;
    let wb = wb as usize;
    let pw = wb * 8;
    let ph = hb * 8;
    let m = dct_matrix();
    let zz = zigzag();
    let mut st = [[0.0f64; 8]; 8];
    for u in 0..8usize {
        for v in 0..8usize {
            st[u][v] = unsafe { *step.add(u * 8 + v) };
        }
    }
    let src = unsafe { std::slice::from_raw_parts(plane, ph * pw) };
    let pre = if pred.is_null() {
        None
    } else {
        Some(unsafe { std::slice::from_raw_parts(pred, ph * pw) })
    };
    let out = unsafe { std::slice::from_raw_parts_mut(out_qz, hb * wb * 64) };

    for r in 0..hb {
        for c in 0..wb {
            let mut blk = [[0.0f64; 8]; 8];
            for x in 0..8usize {
                let row = (r * 8 + x) * pw + c * 8;
                for y in 0..8usize {
                    let mut v = src[row + y];
                    if let Some(p) = pre {
                        v -= p[row + y];
                    }
                    blk[x][y] = v;
                }
            }
            let mut coeff = [[0.0f64; 8]; 8];
            for u in 0..8usize {
                for v in 0..8usize {
                    let mut s = 0.0f64;
                    for x in 0..8usize {
                        let mut t = 0.0f64;
                        for y in 0..8usize {
                            t += blk[x][y] * m[v][y];
                        }
                        s += m[u][x] * t;
                    }
                    coeff[u][v] = s;
                }
            }
            let base = (r * wb + c) * 64;
            for k in 0..64usize {
                let (u, v) = zz[k];
                out[base + k] = rint(coeff[u][v] / st[u][v]) as i32;
            }
        }
    }
    0
}

#[no_mangle]
pub extern "C" fn mt_enc_recon_plane(
    qz: *const i32,
    hb: u32,
    wb: u32,
    step: *const f64,
    pred: *const i32,
    out_plane: *mut i32,
    clip_lo: i32,
    clip_hi: i32,
) -> i32 {
    if qz.is_null() || step.is_null() || out_plane.is_null() {
        return -1;
    }
    let hb = hb as usize;
    let wb = wb as usize;
    let pw = wb * 8;
    let ph = hb * 8;
    let m = dct_matrix();
    let zz = zigzag();
    let mut st = [[0.0f64; 8]; 8];
    for u in 0..8usize {
        for v in 0..8usize {
            st[u][v] = unsafe { *step.add(u * 8 + v) };
        }
    }
    let q = unsafe { std::slice::from_raw_parts(qz, hb * wb * 64) };
    let pre = if pred.is_null() {
        None
    } else {
        Some(unsafe { std::slice::from_raw_parts(pred, ph * pw) })
    };
    let out = unsafe { std::slice::from_raw_parts_mut(out_plane, ph * pw) };

    for r in 0..hb {
        for c in 0..wb {
            let base = (r * wb + c) * 64;
            let mut coeff = [[0.0f64; 8]; 8];
            for k in 0..64usize {
                let (u, v) = zz[k];
                coeff[u][v] = q[base + k] as f64 * st[u][v];
            }
            let mut blk = [[0.0f64; 8]; 8];
            idct_block(&coeff, &m, &mut blk);
            for x in 0..8usize {
                let row = (r * 8 + x) * pw + c * 8;
                for y in 0..8usize {
                    let mut v = blk[x][y];
                    if let Some(p) = pre {
                        v += p[row + y] as f64;
                    }
                    out[row + y] = (rint(v) as i32).clamp(clip_lo, clip_hi);
                }
            }
        }
    }
    0
}

/// RGB frame -> padded YCoCg planes (integer-exact mirror of `_prep_frame`).
///
/// Doing this in Rust removes eight full-frame temporary arrays per frame:
/// 1080p measured 90.7 ms in numpy and about 11 ms here.
#[no_mangle]
pub extern "C" fn mt_prep_frame(
    rgb: *const u8,
    w: u32,
    h: u32,
    pw: u32,
    ph: u32,
    subsample: u32,
    out_y: *mut f64,
    out_co: *mut f64,
    out_cg: *mut f64,
) -> i32 {
    if rgb.is_null() || out_y.is_null() || out_co.is_null() || out_cg.is_null() {
        return -1;
    }
    let w = w as usize;
    let h = h as usize;
    let pw = pw as usize;
    let ph = ph as usize;
    if w == 0 || h == 0 || pw < w || ph < h {
        return -2;
    }
    let y = unsafe { std::slice::from_raw_parts_mut(out_y, ph * pw) };
    for yy in 0..ph {
        let sy = if yy < h { yy } else { h - 1 };
        for xx in 0..pw {
            let sx = if xx < w { xx } else { w - 1 };
            let i = (sy * w + sx) * 3;
            let r = unsafe { *rgb.add(i) } as i32;
            let g = unsafe { *rgb.add(i + 1) } as i32;
            let b = unsafe { *rgb.add(i + 2) } as i32;
            let co = r - b;
            let t = b + (co >> 1);
            let cg = g - t;
            y[yy * pw + xx] = (t + (cg >> 1)) as f64;
        }
    }
    if subsample != 0 {
        let cw = pw / 2;
        let ch = ph / 2;
        let co_p = unsafe { std::slice::from_raw_parts_mut(out_co, ch * cw) };
        let cg_p = unsafe { std::slice::from_raw_parts_mut(out_cg, ch * cw) };
        for j in 0..ch {
            let y0 = (2 * j).min(h - 1);
            let y1 = (2 * j + 1).min(h - 1);
            for i in 0..cw {
                let x0 = (2 * i).min(w - 1);
                let x1 = (2 * i + 1).min(w - 1);
                let mut sco = 0i32;
                let mut scg = 0i32;
                for k in 0..4usize {
                    let sy = if k < 2 { y0 } else { y1 };
                    let sx = if k % 2 == 0 { x0 } else { x1 };
                    let o = (sy * w + sx) * 3;
                    let r = unsafe { *rgb.add(o) } as i32;
                    let g = unsafe { *rgb.add(o + 1) } as i32;
                    let b = unsafe { *rgb.add(o + 2) } as i32;
                    let co = r - b;
                    let t = b + (co >> 1);
                    sco += co;
                    scg += g - t;
                }
                let o = j * cw + i;
                co_p[o] = sco.div_euclid(4) as f64;
                cg_p[o] = scg.div_euclid(4) as f64;
            }
        }
    } else {
        let co_p = unsafe { std::slice::from_raw_parts_mut(out_co, ph * pw) };
        let cg_p = unsafe { std::slice::from_raw_parts_mut(out_cg, ph * pw) };
        for yy in 0..ph {
            let sy = if yy < h { yy } else { h - 1 };
            for xx in 0..pw {
                let sx = if xx < w { xx } else { w - 1 };
                let i = (sy * w + sx) * 3;
                let r = unsafe { *rgb.add(i) } as i32;
                let g = unsafe { *rgb.add(i + 1) } as i32;
                let b = unsafe { *rgb.add(i + 2) } as i32;
                let co = r - b;
                let t = b + (co >> 1);
                let o = yy * pw + xx;
                co_p[o] = co as f64;
                cg_p[o] = (g - t) as f64;
            }
        }
    }
    0
}

/// Per-block motion search: quarter-res coarse pass, then a full-resolution
/// verification of the winner, its neighbours and the zero vector.
///
/// `cur_p` and `ref_p` are single-channel i32 planes of `w*h`; `mv` receives
/// `nbh*nbw` pairs of (dx, dy) as i8 in the same block order the encoder uses.
/// Running this here instead of in numpy takes it from ~700 ms to a few tens
/// of milliseconds per 1080p frame.
#[no_mangle]
pub extern "C" fn mt_me_search(
    curp: *const i32,
    refp: *const i32,
    w: u32,
    h: u32,
    block: u32,
    radius: u32,
    refine: u32,
    out_mv: *mut i8,
) -> i32 {
    if curp.is_null() || refp.is_null() || out_mv.is_null() {
        return -1;
    }
    let w = w as usize;
    let h = h as usize;
    let block = block as usize;
    let radius = radius as usize;
    let refine = refine as i32;
    if block == 0 || w < block || h < block {
        return -1;
    }
    let nbh = h / block;
    let nbw = w / block;
    let cur_p = unsafe { std::slice::from_raw_parts(curp, w * h) };
    let ref_p = unsafe { std::slice::from_raw_parts(refp, w * h) };
    let mv = unsafe { std::slice::from_raw_parts_mut(out_mv, nbh * nbw * 2) };

    let cells = nbh * nbw;
    let mut seed = vec![0i32; cells * 2];
    let h4 = h / 4;
    let w4 = w / 4;
    let b4 = (block / 4).max(1);
    if radius >= 4 && h4 >= b4 && w4 >= b4 && h4 / b4 == nbh && w4 / b4 == nbw {
        let r4 = (radius / 4) as i32;
        let mut cs = vec![0i32; h4 * w4];
        let mut rs = vec![0i32; h4 * w4];
        for y in 0..h4 {
            for x in 0..w4 {
                let mut a = 0i32;
                let mut b = 0i32;
                for dy in 0..4usize {
                    let row = (y * 4 + dy) * w + x * 4;
                    for dx in 0..4usize {
                        a += cur_p[row + dx];
                        b += ref_p[row + dx];
                    }
                }
                cs[y * w4 + x] = a >> 4;
                rs[y * w4 + x] = b >> 4;
            }
        }
        let mut best = vec![i32::MAX; cells];
        for dy in -r4..=r4 {
            for dx in -r4..=r4 {
                for by in 0..nbh {
                    for bx in 0..nbw {
                        let mut sad = 0i32;
                        for y in 0..b4 {
                            let cy = by * b4 + y;
                            let crow = cy * w4 + bx * b4;
                            for x in 0..b4 {
                                let cx = bx * b4 + x;
                                let ry = (cy as i32 + dy).clamp(0, h4 as i32 - 1) as usize;
                                let rx = (cx as i32 + dx).clamp(0, w4 as i32 - 1) as usize;
                                sad += (cs[crow + x] - rs[ry * w4 + rx]).abs();
                            }
                        }
                        let i = by * nbw + bx;
                        if sad < best[i] {
                            best[i] = sad;
                            seed[i * 2] = dx * 4;
                            seed[i * 2 + 1] = dy * 4;
                        }
                    }
                }
            }
        }
    }

    let mut best2 = vec![i32::MAX; cells];
    for by in 0..nbh {
        for bx in 0..nbw {
            let mut sad = 0i32;
            for y in 0..block {
                let row = (by * block + y) * w + bx * block;
                for x in 0..block {
                    sad += (cur_p[row + x] - ref_p[row + x]).abs();
                }
            }
            let i = by * nbw + bx;
            best2[i] = sad;
            mv[i * 2] = 0;
            mv[i * 2 + 1] = 0;
        }
    }
    for oy in [-refine, 0, refine] {
        for ox in [-refine, 0, refine] {
            for by in 0..nbh {
                for bx in 0..nbw {
                    let i = by * nbw + bx;
                    let mxi = seed[i * 2] + ox;
                    let myi = seed[i * 2 + 1] + oy;
                    let mut sad = 0i32;
                    for y in 0..block {
                        let cy = (by * block + y) as i32 + myi;
                        let ry = cy.clamp(0, h as i32 - 1) as usize;
                        let crow = (by * block + y) * w + bx * block;
                        let srow = ry * w;
                        for x in 0..block {
                            let cx = (bx * block + x) as i32 + mxi;
                            let rx = cx.clamp(0, w as i32 - 1) as usize;
                            sad += (cur_p[crow + x] - ref_p[srow + rx]).abs();
                        }
                    }
                    if sad < best2[i] {
                        best2[i] = sad;
                        mv[i * 2] = mxi.clamp(-127, 127) as i8;
                        mv[i * 2 + 1] = myi.clamp(-127, 127) as i8;
                    }
                }
            }
        }
    }
    0
}

/// Rebuild a prediction plane from `ref_p` using the per-block vectors of `mv`.
#[no_mangle]
pub extern "C" fn mt_me_predict(
    refp: *const i32,
    mv: *const i8,
    w: u32,
    h: u32,
    block: u32,
    out_pred: *mut i32,
) -> i32 {
    if refp.is_null() || mv.is_null() || out_pred.is_null() {
        return -1;
    }
    let w = w as usize;
    let h = h as usize;
    let block = block as usize;
    if block == 0 || w < block || h < block {
        return -1;
    }
    let nbh = h / block;
    let nbw = w / block;
    let ref_p = unsafe { std::slice::from_raw_parts(refp, w * h) };
    let mv_p = unsafe { std::slice::from_raw_parts(mv, nbh * nbw * 2) };
    let out = unsafe { std::slice::from_raw_parts_mut(out_pred, w * h) };
    for by in 0..nbh {
        for bx in 0..nbw {
            let i = by * nbw + bx;
            let dx = mv_p[i * 2] as i32;
            let dy = mv_p[i * 2 + 1] as i32;
            for y in 0..block {
                let cy = (by * block + y) as i32 + dy;
                let ry = cy.clamp(0, h as i32 - 1) as usize;
                let drow = (by * block + y) * w + bx * block;
                let srow = ry * w;
                for x in 0..block {
                    let cx = (bx * block + x) as i32 + dx;
                    let rx = cx.clamp(0, w as i32 - 1) as usize;
                    out[drow + x] = ref_p[srow + rx];
                }
            }
        }
    }
    for y in nbh * block..h {
        for x in 0..w {
            out[y * w + x] = out[(nbh * block - 1) * w + x];
        }
    }
    for y in 0..h {
        for x in nbw * block..w {
            out[y * w + x] = out[y * w + nbw * block - 1];
        }
    }
    0
}
