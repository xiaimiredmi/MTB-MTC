//! JNI surface between the Android app and the MTC codec.
//!
//! Everything the app needs is a handful of calls: turn a camera frame into
//! `.mtc` bytes, turn `.mtc` bytes back into pixels, and say how big a file is
//! without decoding it. Pixel buffers are passed as `jbyteArray` of RGBA so the
//! Java side never has to think about the container.
//!
//! The decoded buffer carries its own size in the first eight bytes (two
//! big-endian `u32`), which saves a second JNI round trip per image.

use jni::objects::{JByteArray, JClass};
use jni::sys::{jbyteArray, jint};
use jni::JNIEnv;

use mtc::container::{self, AqMode, Image, Options};

/// Everything the app asks for is 4:2:0 at a fixed quality unless it says
/// otherwise; photos are the only thing this build is for.
fn options(quality: i32) -> Options {
    Options {
        quality: quality.clamp(1, 100) as u8,
        subsample_420: true,
        aq: AqMode::Off,
        version: container::VERSION,
        lossless: false,
    }
}

fn take_bytes(env: &mut JNIEnv, array: JByteArray) -> Result<Vec<u8>, String> {
    env.convert_byte_array(&array)
        .map_err(|e| format!("reading byte array: {}", e))
}

fn give_bytes(env: &mut JNIEnv, data: &[u8]) -> jbyteArray {
    match env.byte_array_from_slice(data) {
        Ok(a) => a.into_raw(),
        Err(_) => std::ptr::null_mut(),
    }
}

/// `encodeRgba(rgba, width, height, quality) -> byte[] | null`
///
/// `rgba` is `width * height * 4` bytes, row major.
#[no_mangle]
pub extern "system" fn Java_dev_mtc_Mtc_encodeRgba(
    mut env: JNIEnv,
    _class: JClass,
    rgba: JByteArray,
    width: jint,
    height: jint,
    quality: jint,
) -> jbyteArray {
    let px = match take_bytes(&mut env, rgba) {
        Ok(v) => v,
        Err(_) => return std::ptr::null_mut(),
    };
    let (w, h) = (width.max(0) as usize, height.max(0) as usize);
    if w == 0 || h == 0 || px.len() != w * h * 4 {
        return std::ptr::null_mut();
    }
    let img = match Image::new(w, h, 4, px) {
        Ok(v) => v,
        Err(_) => return std::ptr::null_mut(),
    };
    match container::encode(&img, &options(quality)) {
        Ok(blob) => give_bytes(&mut env, &blob),
        Err(_) => std::ptr::null_mut(),
    }
}

/// `encodeYuv(y, u, v, width, height, yRowStride, uvRowStride, uvPixelStride, quality)`
///
/// Camera2 hands out `YUV_420_888` with arbitrary strides; converting here keeps
/// the pixel loop in Rust, where the encoder already lives. Returns `.mtc` bytes
/// or null.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub extern "system" fn Java_dev_mtc_Mtc_encodeYuv(
    mut env: JNIEnv,
    _class: JClass,
    y: JByteArray,
    u: JByteArray,
    v: JByteArray,
    width: jint,
    height: jint,
    y_row_stride: jint,
    uv_row_stride: jint,
    uv_pixel_stride: jint,
    quality: jint,
) -> jbyteArray {
    let (py, pu, pv) = match (
        take_bytes(&mut env, y),
        take_bytes(&mut env, u),
        take_bytes(&mut env, v),
    ) {
        (Ok(a), Ok(b), Ok(c)) => (a, b, c),
        _ => return std::ptr::null_mut(),
    };
    let (w, h) = (width.max(0) as usize, height.max(0) as usize);
    if w == 0 || h == 0 {
        return std::ptr::null_mut();
    }
    let y_stride = y_row_stride.max(width) as usize;
    let uv_stride = uv_row_stride.max(width / 2) as usize;
    let uv_pixel = uv_pixel_stride.max(1) as usize;
    if py.len() < y_stride * h {
        return std::ptr::null_mut();
    }

    let rgba = yuv_to_rgba(&py, &pu, &pv, w, h, y_stride, uv_stride, uv_pixel);

    let img = match Image::new(w, h, 4, rgba) {
        Ok(v) => v,
        Err(_) => return std::ptr::null_mut(),
    };
    match container::encode(&img, &options(quality)) {
        Ok(blob) => give_bytes(&mut env, &blob),
        Err(_) => std::ptr::null_mut(),
    }
}

/// `decodeRgba(data, maxSide) -> byte[] | null`
///
/// Returns an 8-byte big-endian `width`, `height` header followed by RGBA.
/// `maxSide > 0` decodes and downsamples in one pass, which is what thumbnails
/// and the on-screen viewer want; `0` means the full picture.
#[no_mangle]
pub extern "system" fn Java_dev_mtc_Mtc_decodeRgba(
    mut env: JNIEnv,
    _class: JClass,
    data: JByteArray,
    max_side: jint,
) -> jbyteArray {
    let blob = match take_bytes(&mut env, data) {
        Ok(v) => v,
        Err(_) => return std::ptr::null_mut(),
    };
    let img = match container::decode(&blob) {
        Ok(v) => v,
        Err(_) => return std::ptr::null_mut(),
    };
    let rgba = img.to_rgba();
    let (w, h) = (img.width, img.height);
    let limit = max_side.max(0) as usize;
    let out = if limit > 0 && (w > limit || h > limit) {
        let step = ((w.max(h) + limit - 1) / limit).max(1);
        downsample(&rgba, w, h, step)
    } else {
        pack(w, h, &rgba)
    };
    give_bytes(&mut env, &out)
}

fn downsample(rgba: &[u8], w: usize, h: usize, step: usize) -> Vec<u8> {
    let (ow, oh) = ((w + step - 1) / step, (h + step - 1) / step);
    let mut out = Vec::with_capacity(8 + ow * oh * 4);
    out.extend_from_slice(&(ow as u32).to_be_bytes());
    out.extend_from_slice(&(oh as u32).to_be_bytes());
    for y in (0..h).step_by(step) {
        for x in (0..w).step_by(step) {
            let o = (y * w + x) * 4;
            out.extend_from_slice(&rgba[o..o + 4]);
        }
    }
    out
}

/// `info(data) -> String` — a one-line summary for the gallery header, or null.
#[no_mangle]
pub extern "system" fn Java_dev_mtc_Mtc_info(
    mut env: JNIEnv,
    _class: JClass,
    data: JByteArray,
) -> jni::sys::jstring {
    let blob = match take_bytes(&mut env, data) {
        Ok(v) => v,
        Err(_) => return std::ptr::null_mut(),
    };
    let text = match container::probe(&blob) {
        Ok(h) => format!(
            "{}x{} {} q{} v{}",
            h.width,
            h.height,
            h.mode_name(),
            h.quality,
            h.version
        ),
        Err(_) => return std::ptr::null_mut(),
    };
    match env.new_string(text) {
        Ok(s) => s.into_raw(),
        Err(_) => std::ptr::null_mut(),
    }
}

/// `YUV_420_888` to RGBA, BT.601 full range.
///
/// Camera2 hands out the same sampling grid for U and V with arbitrary strides,
/// so one pair of strides describes both planes.
pub fn yuv_to_rgba(
    py: &[u8],
    pu: &[u8],
    pv: &[u8],
    w: usize,
    h: usize,
    y_stride: usize,
    uv_stride: usize,
    uv_pixel: usize,
) -> Vec<u8> {
    let mut rgba = vec![0u8; w * h * 4];
    for row in 0..h {
        for col in 0..w {
            let yv = py[row * y_stride + col] as i32;
            let c_row = row / 2;
            let c_col = col / 2;
            let idx = c_row * uv_stride + c_col * uv_pixel;
            let (uu, vv) = if idx < pu.len() && idx < pv.len() {
                (pu[idx] as i32 - 128, pv[idx] as i32 - 128)
            } else {
                (0, 0)
            };
            let r = yv + (91881 * vv >> 16);
            let g = yv - (22554 * uu + 46802 * vv >> 16);
            let b = yv + (116130 * uu >> 16);
            let o = (row * w + col) * 4;
            rgba[o] = r.clamp(0, 255) as u8;
            rgba[o + 1] = g.clamp(0, 255) as u8;
            rgba[o + 2] = b.clamp(0, 255) as u8;
            rgba[o + 3] = 255;
        }
    }
    rgba
}

/// A decoded picture with its size in front, which is what Java reads back.
pub fn pack(w: usize, h: usize, rgba: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(8 + rgba.len());
    out.extend_from_slice(&(w as u32).to_be_bytes());
    out.extend_from_slice(&(h as u32).to_be_bytes());
    out.extend_from_slice(rgba);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn grey_frame(w: usize, h: usize, luma: u8) -> (Vec<u8>, Vec<u8>, Vec<u8>) {
        (vec![luma; w * h], vec![128; (w / 2) * (h / 2)], vec![128; (w / 2) * (h / 2)])
    }

    #[test]
    fn neutral_chroma_is_grey() {
        let (y, u, v) = grey_frame(8, 8, 180);
        let rgba = yuv_to_rgba(&y, &u, &v, 8, 8, 8, 4, 1);
        assert_eq!(&rgba[0..4], &[180, 180, 180, 255]);
        assert_eq!(&rgba[4..8], &[180, 180, 180, 255]);
    }

    #[test]
    fn chroma_shifts_the_channels_the_right_way() {
        // Pure blue in BT.601: Y=41, U=240, V=110.
        let w = 4;
        let h = 4;
        let y = vec![41u8; w * h];
        let u = vec![240u8; (w / 2) * (h / 2)];
        let v = vec![110u8; (w / 2) * (h / 2)];
        let rgba = yuv_to_rgba(&y, &u, &v, w, h, w, w / 2, 1);
        let (r, g, b) = (rgba[0] as i32, rgba[1] as i32, rgba[2] as i32);
        assert!(b > 200, "blue {} {} {}", r, g, b);
        assert!(r < 60, "red {} {} {}", r, g, b);
        assert!(g < 80, "green {} {} {}", r, g, b);
    }

    #[test]
    fn strided_rows_are_walked_correctly() {
        // 2x1 visible pixels in a 3-wide row: the padding must be skipped.
        let y = vec![10u8, 20, 99, 30, 40, 99];
        let u = vec![128u8, 128];
        let v = vec![128u8, 128];
        let rgba = yuv_to_rgba(&y, &u, &v, 2, 2, 3, 1, 1);
        assert_eq!(rgba[0], 10);
        assert_eq!(rgba[4], 20);
        assert_eq!(rgba[8], 30);
        assert_eq!(rgba[12], 40);
    }

    #[test]
    fn pack_puts_the_size_first() {
        let rgba = vec![1u8; 3 * 2 * 4];
        let packed = pack(3, 2, &rgba);
        assert_eq!(&packed[0..4], &[0, 0, 0, 3]);
        assert_eq!(&packed[4..8], &[0, 0, 0, 2]);
        assert_eq!(packed.len(), 8 + rgba.len());
        assert_eq!(&packed[8..], &rgba[..]);
    }
    #[test]
    fn camera_frame_round_trips_through_the_codec() {
        // The whole phone path, minus the phone: YUV frame -> RGBA -> .mtc -> RGBA.
        let (w, h) = (64usize, 48usize);
        let mut y = vec![0u8; w * h];
        for row in 0..h {
            for col in 0..w {
                y[row * w + col] = (80 + col * 2) as u8;
            }
        }
        let u = vec![110u8; (w / 2) * (h / 2)];
        let v = vec![140u8; (w / 2) * (h / 2)];
        let rgba = yuv_to_rgba(&y, &u, &v, w, h, w, w / 2, 1);

        let img = mtc::container::Image::new(w, h, 4, rgba).unwrap();
        let blob = mtc::container::encode(&img, &mtc::container::Options::default()).unwrap();
        let back = mtc::container::decode(&blob).unwrap();
        let psnr = back.psnr_visible(&img);
        assert!(psnr > 30.0, "psnr {:.2}, {} bytes", psnr, blob.len());

        let packed = pack(w, h, &back.to_rgba());
        assert_eq!(&packed[0..4], &(w as u32).to_be_bytes());
        assert_eq!(packed.len(), 8 + w * h * 4);
    }
}