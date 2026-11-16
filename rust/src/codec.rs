//! MTC container for single-plane (gray) images. Colour follows next.

use crate::arith::{Dec, Enc};
use crate::entropy::{dec_block, enc_block, new_probs, PER_PLANE};
use crate::transform::{dct_matrix, fdct, idct, rint, step_table, ZZ};

const MAGIC: &[u8; 4] = b"MTB1";
const HDR: usize = 12;

pub struct Gray {
    pub width: usize,
    pub height: usize,
    pub pixels: Vec<u8>,
}

fn align(v: usize, m: usize) -> usize {
    (v + m - 1) / m * m
}

pub fn encode_gray(w: usize, h: usize, px: &[u8], quality: u8) -> Vec<u8> {
    let pw = align(w, 8);
    let ph = align(h, 8);
    let m = dct_matrix();
    let step = step_table(quality);
    let mut probs = new_probs(1);
    let mut enc = Enc::new();
    let hb = ph / 8;
    let wb = pw / 8;
    for by in 0..hb {
        let mut prev = 0i32;
        for bx in 0..wb {
            let mut blk = [[0.0f64; 8]; 8];
            for y in 0..8 {
                for x in 0..8 {
                    let sy = (by * 8 + y).min(h - 1);
                    let sx = (bx * 8 + x).min(w - 1);
                    blk[x][y] = px[sy * w + sx] as f64;
                }
            }
            let coef = fdct(&blk, &m);
            let mut qz = [0i32; 64];
            for k in 0..64 {
                let (u, v) = ZZ[k];
                qz[k] = rint(coef[u][v] / step[u][v]) as i32;
            }
            enc_block(&mut enc, &mut probs, 1, 0, &qz, prev);
            prev = qz[0];
        }
    }
    let payload = enc.finish();
    let mut out = Vec::with_capacity(HDR + payload.len());
    out.extend_from_slice(MAGIC);
    out.push(1); // version
    out.push(0); // gray lossy
    out.push(quality.min(100).max(1));
    out.push(0); // flags
    out.extend_from_slice(&(w as u16).to_le_bytes());
    out.extend_from_slice(&(h as u16).to_le_bytes());
    out.extend_from_slice(&payload);
    out
}

pub fn decode_gray(data: &[u8]) -> Result<Gray, String> {
    if data.len() < HDR || &data[0..4] != MAGIC {
        return Err("not an MTC image".into());
    }
    let mode = data[5];
    if mode != 0 {
        return Err(format!("mode {} is not gray lossy", mode));
    }
    let quality = data[6];
    let w = u16::from_le_bytes([data[8], data[9]]) as usize;
    let h = u16::from_le_bytes([data[10], data[11]]) as usize;
    let pw = align(w, 8);
    let ph = align(h, 8);
    let m = dct_matrix();
    let step = step_table(quality);
    let mut probs = new_probs(1);
    let mut dec = Dec::new(&data[HDR..]);
    let mut plane = vec![0u8; pw * ph];
    for by in 0..ph / 8 {
        let mut prev = 0i32;
        for bx in 0..pw / 8 {
            let qz = dec_block(&mut dec, &mut probs, 1, 0, prev);
            prev = qz[0];
            let mut coef = [[0.0f64; 8]; 8];
            for k in 0..64 {
                let (u, v) = ZZ[k];
                coef[u][v] = qz[k] as f64 * step[u][v];
            }
            let blk = idct(&coef, &m);
            for y in 0..8 {
                for x in 0..8 {
                    let v = rint(blk[x][y]).clamp(0.0, 255.0) as u8;
                    plane[(by * 8 + y) * pw + bx * 8 + x] = v;
                }
            }
        }
    }
    let mut pixels = Vec::with_capacity(w * h);
    for y in 0..h {
        pixels.extend_from_slice(&plane[y * pw..y * pw + w]);
    }
    Ok(Gray {
        width: w,
        height: h,
        pixels,
    })
}

pub struct Rgb {
    pub width: usize,
    pub height: usize,
    pub pixels: Vec<u8>,
}

#[inline]
fn fwd(r: i32, g: i32, b: i32) -> (i32, i32, i32) {
    let co = r - b;
    let t = b + (co >> 1);
    let cg = g - t;
    (t + (cg >> 1), co, cg)
}

#[inline]
fn inv(y: i32, co: i32, cg: i32) -> (i32, i32, i32) {
    let t = y - (cg >> 1);
    let g = cg + t;
    let b = t - (co >> 1);
    (co + b, g, b)
}

fn plane_steps(quality: u8) -> [[[f64; 8]; 8]; 3] {
    let base = step_table(quality);
    let mut s = [base; 3];
    for u in 0..8 {
        for v in 0..8 {
            s[1][u][v] = base[u][v] * 1.35;
            s[2][u][v] = base[u][v] * 1.35;
        }
    }
    s
}

pub fn encode_rgb444(w: usize, h: usize, rgb: &[u8], quality: u8) -> Vec<u8> {
    let pw = align(w, 8);
    let ph = align(h, 8);
    let mut planes = vec![vec![0i32; pw * ph]; 3];
    for y in 0..ph {
        let sy = y.min(h - 1);
        for x in 0..pw {
            let sx = x.min(w - 1);
            let i = (sy * w + sx) * 3;
            let (yy, co, cg) = fwd(rgb[i] as i32, rgb[i + 1] as i32, rgb[i + 2] as i32);
            let p = y * pw + x;
            planes[0][p] = yy;
            planes[1][p] = co;
            planes[2][p] = cg;
        }
    }
    let m = dct_matrix();
    let steps = plane_steps(quality);
    let mut probs = new_probs(3);
    let mut enc = Enc::new();
    for pl in 0..3 {
        for by in 0..ph / 8 {
            let mut prev = 0i32;
            for bx in 0..pw / 8 {
                let mut blk = [[0.0f64; 8]; 8];
                for y in 0..8 {
                    for x in 0..8 {
                        blk[x][y] = planes[pl][(by * 8 + y) * pw + bx * 8 + x] as f64;
                    }
                }
                let coef = fdct(&blk, &m);
                let mut qz = [0i32; 64];
                for k in 0..64 {
                    let (u, v) = ZZ[k];
                    qz[k] = rint(coef[u][v] / steps[pl][u][v]) as i32;
                }
                enc_block(&mut enc, &mut probs, 3, pl, &qz, prev);
                prev = qz[0];
            }
        }
    }
    let payload = enc.finish();
    let mut out = Vec::with_capacity(HDR + payload.len());
    out.extend_from_slice(MAGIC);
    out.push(1);
    out.push(1); // rgb444 lossy
    out.push(quality.min(100).max(1));
    out.push(0);
    out.extend_from_slice(&(w as u16).to_le_bytes());
    out.extend_from_slice(&(h as u16).to_le_bytes());
    out.extend_from_slice(&payload);
    out
}

pub fn decode_rgb444(data: &[u8]) -> Result<Rgb, String> {
    if data.len() < HDR || &data[0..4] != MAGIC {
        return Err("not an MTC image".into());
    }
    if data[5] != 1 {
        return Err(format!("mode {} is not rgb444 lossy", data[5]));
    }
    let quality = data[6];
    let w = u16::from_le_bytes([data[8], data[9]]) as usize;
    let h = u16::from_le_bytes([data[10], data[11]]) as usize;
    let pw = align(w, 8);
    let ph = align(h, 8);
    let m = dct_matrix();
    let steps = plane_steps(quality);
    let mut probs = new_probs(3);
    let mut dec = Dec::new(&data[HDR..]);
    let mut planes = vec![vec![0i32; pw * ph]; 3];
    for pl in 0..3 {
        for by in 0..ph / 8 {
            let mut prev = 0i32;
            for bx in 0..pw / 8 {
                let qz = dec_block(&mut dec, &mut probs, 3, pl, prev);
                prev = qz[0];
                let mut coef = [[0.0f64; 8]; 8];
                for k in 0..64 {
                    let (u, v) = ZZ[k];
                    coef[u][v] = qz[k] as f64 * steps[pl][u][v];
                }
                let blk = idct(&coef, &m);
                for y in 0..8 {
                    for x in 0..8 {
                        planes[pl][(by * 8 + y) * pw + bx * 8 + x] =
                            rint(blk[x][y]) as i32;
                    }
                }
            }
        }
    }
    let mut pixels = vec![0u8; w * h * 3];
    for y in 0..h {
        for x in 0..w {
            let p = y * pw + x;
            let (r, g, b) = inv(
                planes[0][p].clamp(0, 255),
                planes[1][p].clamp(-300, 300),
                planes[2][p].clamp(-300, 300),
            );
            let o = (y * w + x) * 3;
            pixels[o] = r.clamp(0, 255) as u8;
            pixels[o + 1] = g.clamp(0, 255) as u8;
            pixels[o + 2] = b.clamp(0, 255) as u8;
        }
    }
    Ok(Rgb {
        width: w,
        height: h,
        pixels,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rgb_roundtrip() {
        let (w, h) = (32usize, 24usize);
        let mut px = vec![0u8; w * h * 3];
        for y in 0..h {
            for x in 0..w {
                let o = (y * w + x) * 3;
                px[o] = (x * 8) as u8;
                px[o + 1] = (y * 10) as u8;
                px[o + 2] = ((x + y) * 5) as u8;
            }
        }
        let blob = encode_rgb444(w, h, &px, 85);
        let got = decode_rgb444(&blob).unwrap();
        let mut se = 0f64;
        for (a, b) in px.iter().zip(got.pixels.iter()) {
            let d = *a as f64 - *b as f64;
            se += d * d;
        }
        let mse = se / (w * h * 3) as f64;
        let psnr = 10.0 * (255.0 * 255.0 / mse).log10();
        assert!(psnr > 25.0, "psnr {:.2}", psnr);
    }

    #[test]
    fn gray_roundtrip() {
        let (w, h) = (64usize, 48usize);
        let mut px = vec![0u8; w * h];
        for y in 0..h {
            for x in 0..w {
                px[y * w + x] = ((x * 3 + y * 5) % 256) as u8;
            }
        }
        let blob = encode_gray(w, h, &px, 85);
        let got = decode_gray(&blob).unwrap();
        assert_eq!((got.width, got.height), (w, h));
        let mut se = 0f64;
        for (a, b) in px.iter().zip(got.pixels.iter()) {
            let d = *a as f64 - *b as f64;
            se += d * d;
        }
        let mse = se / (w * h) as f64;
        let psnr = 10.0 * (255.0 * 255.0 / mse).log10();
        assert!(psnr > 30.0, "psnr {:.2}", psnr);
        assert!(blob.len() > HDR);
        let _ = PER_PLANE;
    }
}
