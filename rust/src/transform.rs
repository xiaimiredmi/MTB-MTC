//! 8x8 DCT, zig-zag scan and the quantiser table.
//!
//! Blocks are row-major: `blk[y][x]` holds the sample at row `y`, column `x`.
//! The coefficient at `[u][v]` therefore has `u` as the vertical frequency and
//! `v` as the horizontal one, which is the convention the Python encoder
//! established and every existing `.mtc` file is written in.

pub const ZZ: [(usize, usize); 64] = {
    let mut out = [(0usize, 0usize); 64];
    let mut k = 0usize;
    let mut s = 0usize;
    while s < 15 {
        let mut v = 0usize;
        // Even diagonals run down-left, odd diagonals up-right.
        if s % 2 == 0 {
            while v <= s {
                if s - v < 8 && v < 8 {
                    out[k] = (s - v, v);
                    k += 1;
                }
                v += 1;
            }
        } else {
            while v <= s {
                if s - v < 8 && v < 8 {
                    out[k] = (v, s - v);
                    k += 1;
                }
                v += 1;
            }
        }
        s += 1;
    }
    out
};

pub fn dct_matrix() -> [[f64; 8]; 8] {
    let mut m = [[0.0f64; 8]; 8];
    for u in 0..8 {
        for x in 0..8 {
            m[u][x] = (((2 * x + 1) as f64) * (u as f64) * std::f64::consts::PI / 16.0).cos()
                * 0.5;
        }
    }
    for x in 0..8 {
        m[0][x] = (1.0f64 / 8.0).sqrt();
    }
    m
}

/// `out[u][v] = sum_y sum_x M[u][y] blk[y][x] M[v][x]`.
pub fn fdct(blk: &[[f64; 8]; 8], m: &[[f64; 8]; 8]) -> [[f64; 8]; 8] {
    let mut out = [[0.0f64; 8]; 8];
    let mut tmp = [[0.0f64; 8]; 8];
    for u in 0..8 {
        for x in 0..8 {
            let mut s = 0.0;
            for y in 0..8 {
                s += m[u][y] * blk[y][x];
            }
            tmp[u][x] = s;
        }
    }
    for u in 0..8 {
        for v in 0..8 {
            let mut s = 0.0;
            for x in 0..8 {
                s += tmp[u][x] * m[v][x];
            }
            out[u][v] = s;
        }
    }
    out
}

/// `out[y][x] = sum_u sum_v M[u][y] coef[u][v] M[v][x]`.
pub fn idct(coef: &[[f64; 8]; 8], m: &[[f64; 8]; 8]) -> [[f64; 8]; 8] {
    let mut out = [[0.0f64; 8]; 8];
    let mut tmp = [[0.0f64; 8]; 8];
    for u in 0..8 {
        for x in 0..8 {
            let mut s = 0.0;
            for v in 0..8 {
                s += coef[u][v] * m[v][x];
            }
            tmp[u][x] = s;
        }
    }
    for y in 0..8 {
        for x in 0..8 {
            let mut s = 0.0;
            for u in 0..8 {
                s += m[u][y] * tmp[u][x];
            }
            out[y][x] = s;
        }
    }
    out
}

pub fn base_weight(u: usize, v: usize) -> f64 {
    let f = (((u * u + v * v) as f64)).sqrt();
    1.0 + 0.30 * f.powf(1.15)
}

pub fn quality_scale(quality: u8) -> f64 {
    let q = quality.clamp(1, 100) as f64;
    0.85 + (100.0 - q) * 0.40
}

pub fn step_table(quality: u8) -> [[f64; 8]; 8] {
    let scale = quality_scale(quality);
    let mut t = [[0.0f64; 8]; 8];
    for u in 0..8 {
        for v in 0..8 {
            t[u][v] = base_weight(u, v) * scale;
        }
    }
    t
}

/// Round half to even, like numpy's rint.
pub fn rint(x: f64) -> f64 {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zigzag_is_a_permutation() {
        let mut seen = [false; 64];
        for &(u, v) in ZZ.iter() {
            assert!(u < 8 && v < 8);
            assert!(!seen[u * 8 + v]);
            seen[u * 8 + v] = true;
        }
        assert!(seen.iter().all(|&b| b));
    }

    #[test]
    fn zigzag_matches_python_order() {
        // The order the Python encoder wrote: even diagonals descend, odd ones
        // ascend.
        let expect = [
            (0usize, 0usize),
            (0, 1),
            (1, 0),
            (2, 0),
            (1, 1),
            (0, 2),
            (0, 3),
            (1, 2),
            (2, 1),
            (3, 0),
        ];
        for (k, e) in expect.iter().enumerate() {
            assert_eq!(ZZ[k], *e, "coefficient {}", k);
        }
    }

    #[test]
    fn dct_roundtrip() {
        let m = dct_matrix();
        let mut blk = [[0.0f64; 8]; 8];
        for y in 0..8 {
            for x in 0..8 {
                blk[y][x] = ((x * 17 + y * 31) % 256) as f64 - 128.0;
            }
        }
        let coef = fdct(&blk, &m);
        let back = idct(&coef, &m);
        for y in 0..8 {
            for x in 0..8 {
                assert!((back[y][x] - blk[y][x]).abs() < 1e-9);
            }
        }
    }

    #[test]
    fn dct_axes_are_not_interchangeable() {
        // A vertical ramp must concentrate energy in u, not in v.
        let m = dct_matrix();
        let mut blk = [[0.0f64; 8]; 8];
        for y in 0..8 {
            for x in 0..8 {
                blk[y][x] = (y * 24) as f64;
            }
        }
        let coef = fdct(&blk, &m);
        let vertical: f64 = (1..8).map(|u| coef[u][0].abs()).sum();
        let horizontal: f64 = (1..8).map(|v| coef[0][v].abs()).sum();
        assert!(vertical > 100.0 * horizontal, "{} vs {}", vertical, horizontal);
    }

    #[test]
    fn step_table_matches_python() {
        let t = step_table(85);
        assert!((t[0][0] - 6.85).abs() < 1e-12);
        let f = (2.0f64).sqrt();
        let w11 = 1.0 + 0.30 * f.powf(1.15);
        assert!((t[1][1] - w11 * 6.85).abs() < 1e-12);
    }
}
