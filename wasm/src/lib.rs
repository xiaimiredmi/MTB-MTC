//! The codec, compiled to WebAssembly, for the project site.
//!
//! No wasm-bindgen: the module exports a handful of C functions and the page
//! reads results out of linear memory, so the build needs nothing beyond
//! `rustup target add wasm32-unknown-unknown`.
//!
//! The calling convention is deliberately boring: write the input into memory
//! obtained from [`mtc_alloc`], call encode or decode, then read the result from
//! [`mtc_out_ptr`] with the length that was returned.

use std::sync::Mutex;

use mtc::container::{self, AqMode, Image, Options};

/// Result of the last call: `.mtc` bytes after an encode, RGBA after a decode.
static OUT: Mutex<Vec<u8>> = Mutex::new(Vec::new());
/// Size of the picture in `OUT` (only meaningful after a decode).
static DIMS: Mutex<(u32, u32)> = Mutex::new((0, 0));

fn options(quality: u32, lossless: bool, aq: bool) -> Options {
    Options {
        quality: quality.clamp(1, 100) as u8,
        subsample_420: true,
        aq: if aq { AqMode::On } else { AqMode::Off },
        version: container::VERSION,
        lossless,
    }
}

/// Memory for the caller to write into; give it back with [`mtc_free`].
#[no_mangle]
pub extern "C" fn mtc_alloc(len: usize) -> *mut u8 {
    let mut buf = vec![0u8; len];
    let ptr = buf.as_mut_ptr();
    std::mem::forget(buf);
    ptr
}

/// Release a buffer from [`mtc_alloc`].
#[no_mangle]
pub unsafe extern "C" fn mtc_free(ptr: *mut u8, len: usize) {
    if !ptr.is_null() && len > 0 {
        drop(Vec::from_raw_parts(ptr, len, len));
    }
}

/// Encode `len` bytes of `w * h * channels` pixels; returns the `.mtc` length.
///
/// `channels` is 1 (grey), 3 (RGB) or 4 (RGBA, alpha kept exactly). Returns 0 on
/// failure, and the caller should treat the contents of `OUT` as undefined then.
#[no_mangle]
pub unsafe extern "C" fn mtc_encode(
    ptr: *const u8,
    len: usize,
    w: usize,
    h: usize,
    channels: usize,
    quality: u32,
    lossless: u32,
    aq: u32,
) -> usize {
    if ptr.is_null() || w == 0 || h == 0 || len != w * h * channels {
        return 0;
    }
    let pixels = std::slice::from_raw_parts(ptr, len).to_vec();
    let img = match Image::new(w, h, channels, pixels) {
        Ok(v) => v,
        Err(_) => return 0,
    };
    match container::encode(&img, &options(quality, lossless != 0, aq != 0)) {
        Ok(blob) => {
            let mut out = OUT.lock().unwrap();
            *out = blob;
            out.len()
        }
        Err(_) => 0,
    }
}

/// Decode a `.mtc` file; returns the RGBA length, with the size in `mtc_out_w/h`.
///
/// `max_side > 0` decodes straight to at most that size, so a thumbnail never
/// costs a full-size buffer.
#[no_mangle]
pub unsafe extern "C" fn mtc_decode(ptr: *const u8, len: usize, max_side: usize) -> usize {
    if ptr.is_null() || len < container::HDR {
        return 0;
    }
    let blob = std::slice::from_raw_parts(ptr, len);
    let decoded = if max_side > 0 {
        container::decode_downsized(blob, max_side)
    } else {
        container::decode(blob)
    };
    match decoded {
        Ok(img) => {
            let rgba = img.to_rgba();
            {
                let mut dims = DIMS.lock().unwrap();
                *dims = (img.width as u32, img.height as u32);
            }
            let mut out = OUT.lock().unwrap();
            *out = rgba;
            out.len()
        }
        Err(_) => 0,
    }
}

/// Where the last result starts.
#[no_mangle]
pub extern "C" fn mtc_out_ptr() -> *const u8 {
    let out = OUT.lock().unwrap();
    if out.is_empty() {
        std::ptr::null()
    } else {
        out.as_ptr()
    }
}

#[no_mangle]
pub extern "C" fn mtc_out_w() -> u32 {
    DIMS.lock().unwrap().0
}

#[no_mangle]
pub extern "C" fn mtc_out_h() -> u32 {
    DIMS.lock().unwrap().1
}

/// Container version this build writes, for the page to display.
#[no_mangle]
pub extern "C" fn mtc_version() -> u32 {
    container::VERSION as u32
}
