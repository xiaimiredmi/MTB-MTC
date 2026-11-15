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
