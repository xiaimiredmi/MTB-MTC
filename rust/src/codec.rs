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

#[cfg(test)]
mod tests {
    use super::*;

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
