//! Coefficient block coder: DC difference, last position, significance,
//! magnitude class, sign and extra bits, over eight zig-zag bands.

use crate::arith::{dec_bits, dec_tree, enc_bits, enc_tree, Dec, Enc, PROB_INIT};

pub const PLANES_MAX: usize = 4;

/// Per-plane probability table size (no skip flags in images).
pub const PER_PLANE: usize = 369;

pub fn new_probs(planes: usize) -> Vec<i16> {
    vec![PROB_INIT; PER_PLANE * planes]
}

#[inline]
fn bit_len(v: i32) -> u32 {
    let mut n = 0;
    let mut x = v;
    while x > 0 {
        n += 1;
        x >>= 1;
    }
    n
}

#[inline]
fn bases(planes: usize, pl: usize) -> [usize; 8] {
    [
        pl * 16,              // dc_cls
        16 * planes + pl,     // dc_sign
        17 * planes + pl * 16, // dc_extra
        33 * planes + pl * 64, // last
        97 * planes + pl * 8,  // sig
        105 * planes + pl * 128, // ac_cls
        233 * planes + pl * 8, // ac_sign
        241 * planes + pl * 128, // ac_extra
    ]
}

pub fn enc_block(e: &mut Enc, probs: &mut [i16], planes: usize, pl: usize, qc: &[i32; 64],
                 prev_dc: i32) {
    let b = bases(planes, pl);
    let mut d = qc[0] - prev_dc;
    let mut sign = 0u32;
    if d < 0 {
        d = -d;
        sign = 1;
    }
    let c = bit_len(d);
    enc_tree(e, probs, b[0], 4, c as i32);
    if c > 0 {
        e.bit(probs, b[1], sign);
        if c > 1 {
            enc_bits(e, probs, b[2], c - 1, d - (1 << (c - 1)));
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
    enc_tree(e, probs, b[3], 6, last as i32);

    for i in 1..=last {
        let mut v = qc[i];
        let sidx = b[4] + (i >> 3);
        if v != 0 {
            e.bit(probs, sidx, 1);
            let mut sg = 0u32;
            if v < 0 {
                v = -v;
                sg = 1;
            }
            let c2 = bit_len(v);
            enc_tree(e, probs, b[5] + (sidx - b[4]) * 16, 4, c2 as i32);
            e.bit(probs, b[6] + (sidx - b[4]), sg);
            if c2 > 1 {
                enc_bits(e, probs, b[7] + (sidx - b[4]) * 16, c2 - 1, v - (1 << (c2 - 1)));
            }
        } else {
            e.bit(probs, sidx, 0);
        }
    }
}

pub fn dec_block(d: &mut Dec, probs: &mut [i16], planes: usize, pl: usize,
                 prev_dc: i32) -> [i32; 64] {
    let b = bases(planes, pl);
    let c = dec_tree(d, probs, b[0], 4);
    let mut dc = 0i32;
    if c > 0 {
        let sign = d.bit(probs, b[1]);
        let mut mag = 1i32 << (c - 1);
        if c > 1 {
            mag += dec_bits(d, probs, b[2], c - 1) as i32;
        }
        dc = if sign != 0 { -mag } else { mag };
    }
    dc += prev_dc;

    let last = dec_tree(d, probs, b[3], 6) as usize;
    let mut qc = [0i32; 64];
    qc[0] = dc;
    for i in 1..=last {
        let base = b[4] + (i >> 3);
        if d.bit(probs, base) != 0 {
            let cls = dec_tree(d, probs, b[5] + (base - b[4]) * 16, 4);
            let sign = d.bit(probs, b[6] + (base - b[4]));
            let mut mag = 1i32 << (cls - 1);
            if cls > 1 {
                mag += dec_bits(d, probs, b[7] + (base - b[4]) * 16, cls - 1) as i32;
            }
            qc[i] = if sign != 0 { -mag } else { mag };
        }
    }
    qc
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn block_roundtrip() {
        let planes = 3;
        let mut enc = Enc::new();
        let mut probs = new_probs(planes);
        let mut blocks: Vec<([i32; 64], usize, i32)> = Vec::new();
        let mut seed = 7u32;
        let mut prev = [0i32; 3];
        for n in 0..200 {
            let pl = n % planes;
            let mut qc = [0i32; 64];
            for i in 0..64 {
                seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
                let r = (seed >> 24) as i32 % 17 - 8;
                qc[i] = if (seed >> 8) & 3 == 0 { r } else { 0 };
            }
            enc_block(&mut enc, &mut probs, planes, pl, &qc, prev[pl]);
            blocks.push((qc, pl, prev[pl]));
            prev[pl] = qc[0];
        }
        let data = enc.finish();

        let mut dec = Dec::new(&data);
        let mut probs2 = new_probs(planes);
        let mut prev2 = [0i32; 3];
        for (qc, pl, pdc) in blocks {
            let got = dec_block(&mut dec, &mut probs2, planes, pl, prev2[pl]);
            assert_eq!(got, qc, "plane {}", pl);
            prev2[pl] = got[0];
            let _ = pdc;
        }
    }
}
