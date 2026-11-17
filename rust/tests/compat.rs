//! Compatibility with files the Python encoder wrote.
//!
//! `tests/data/legacy_v1.mtc` is a 128x96 crop of `bench/data/photo_c.png`
//! encoded at `-q 80 -s 420` by `mtcodec/image_codec.py` (container version 1,
//! flat probability model, no dead zone). The expected hash is what the Python
//! decoder produced, so this test fails if the Rust decoder ever drifts from the
//! reference bitstream - including through the block-transpose bug that once
//! made every Python file decode rotated by 90 degrees inside each block.

use mtc::container::{self, probe};

fn fnv1a64(data: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in data {
        h ^= *b as u64;
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    h
}

#[test]
fn decodes_a_python_written_v1_stream() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/data/legacy_v1.mtc");
    let data = std::fs::read(path).expect("fixture");
    let head = probe(&data).expect("header");
    assert_eq!(head.version, 1);
    assert_eq!(head.mode, container::mode::RGB420_LOSSY);
    assert_eq!(head.quality, 80);
    assert!(!head.aq());
    assert_eq!((head.width, head.height), (128, 96));

    let img = container::decode(&data).expect("decode");
    assert_eq!((img.width, img.height, img.channels), (128, 96, 3));
    assert_eq!(fnv1a64(&img.data), 0x1931_9d14_bd4d_5e49);
}

#[test]
fn decodes_a_python_written_lossless_stream() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/data/legacy_v1_lossless.mtc");
    let data = std::fs::read(path).expect("fixture");
    let head = probe(&data).expect("header");
    assert_eq!(head.version, 1);
    assert_eq!(head.mode, container::mode::RGB_LOSSLESS);
    assert_eq!((head.width, head.height), (64, 48));

    let img = container::decode(&data).expect("decode");
    assert_eq!(fnv1a64(&img.data), 0x6bfe_3ae8_b2c4_4a19);
}

#[test]
fn decodes_a_python_written_alpha_stream() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/data/legacy_v1_alpha.mtc");
    let data = std::fs::read(path).expect("fixture");
    let head = probe(&data).expect("header");
    assert_eq!(head.mode, container::mode::RGB420_LOSSY);
    assert!(head.has_alpha());

    let img = container::decode(&data).expect("decode");
    assert_eq!(img.channels, 4);
    assert_eq!(fnv1a64(&img.data), 0x5132_2c9a_721a_7b61);
}

#[test]
fn lossless_round_trip_is_pixel_exact() {
    let (w, h) = (48usize, 40usize);
    let mut px = Vec::with_capacity(w * h * 3);
    for y in 0..h {
        for x in 0..w {
            px.push(((x * 5 + y * 3) % 256) as u8);
            px.push(((x * 11 + y) % 256) as u8);
            px.push(((x + y * 13) % 256) as u8);
        }
    }
    let img = mtc::container::Image::new(w, h, 3, px).unwrap();
    for version in [container::VERSION, container::VERSION_LEGACY] {
        let blob = container::encode(
            &img,
            &container::Options {
                lossless: true,
                version,
                ..container::Options::default()
            },
        )
        .unwrap();
        let head = probe(&blob).unwrap();
        assert_eq!(head.mode, container::mode::RGB_LOSSLESS);
        let back = container::decode(&blob).unwrap();
        assert_eq!(back.data, img.data, "version {}", version);
    }
}

#[test]
fn v2_round_trip_reports_the_new_stream() {
    let (w, h) = (64usize, 48usize);
    let mut px = Vec::with_capacity(w * h * 3);
    for y in 0..h {
        for x in 0..w {
            px.push((x * 4) as u8);
            px.push((y * 5) as u8);
            px.push(((x + y) * 2) as u8);
        }
    }
    let img = mtc::container::Image::new(w, h, 3, px).unwrap();
    let blob = container::encode(&img, &container::Options::default()).unwrap();
    let head = probe(&blob).unwrap();
    assert_eq!(head.version, 2);
    assert!(!head.aq(), "adaptive quantisation is opt-in");
    let back = container::decode(&blob).unwrap();
    let psnr = img.psnr(&back);
    assert!(psnr > 30.0, "psnr {:.2}", psnr);
}
