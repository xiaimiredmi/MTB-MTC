//! Reading and writing ordinary image files, through the `image` crate.

use crate::container::Image;

/// Load PNG/JPEG/WebP/BMP into one of the three MTC pixel layouts.
pub fn load(path: &str) -> Result<Image, String> {
    let img = image::open(path).map_err(|e| format!("{}: {}", path, e))?;
    let (w, h) = (img.width() as usize, img.height() as usize);
    if img.color().has_alpha() {
        let rgba = img.to_rgba8();
        Image::new(w, h, 4, rgba.into_raw())
    } else if img.color().has_color() {
        let rgb = img.to_rgb8();
        Image::new(w, h, 3, rgb.into_raw())
    } else {
        let luma = img.to_luma8();
        Image::new(w, h, 1, luma.into_raw())
    }
}

/// Load any file as RGBA, for the viewer (no channel-count surprises).
pub fn load_rgba(path: &str) -> Result<Image, String> {
    let img = image::open(path).map_err(|e| format!("{}: {}", path, e))?;
    let (w, h) = (img.width() as usize, img.height() as usize);
    let rgba = img.to_rgba8();
    Image::new(w, h, 4, rgba.into_raw())
}

/// Write an image; the format follows the file extension.
pub fn save(path: &str, img: &Image) -> Result<(), String> {
    let (w, h) = (img.width as u32, img.height as u32);
    let dynimg = match img.channels {
        1 => {
            let buf = image::GrayImage::from_raw(w, h, img.data.clone())
                .ok_or_else(|| "bad gray buffer".to_string())?;
            image::DynamicImage::ImageLuma8(buf)
        }
        4 => {
            let buf = image::RgbaImage::from_raw(w, h, img.data.clone())
                .ok_or_else(|| "bad rgba buffer".to_string())?;
            image::DynamicImage::ImageRgba8(buf)
        }
        _ => {
            let buf = image::RgbImage::from_raw(w, h, img.data.clone())
                .ok_or_else(|| "bad rgb buffer".to_string())?;
            image::DynamicImage::ImageRgb8(buf)
        }
    };
    dynimg.save(path).map_err(|e| format!("{}: {}", path, e))
}
