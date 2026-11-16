//! MTC image codec — Rust-only implementation.
//!
//! The Python package is being replaced; this binary owns the container and,
//! in the next steps, the DCT, quantiser, arithmetic coder and viewer.

use std::env;
use std::fs;
use std::process::ExitCode;

mod arith;
mod codec;
mod entropy;
mod transform;

const MAGIC: &[u8; 4] = b"MTB1";
const HDR: usize = 12;

const MODE_GRAY_LOSSY: u8 = 0;
const MODE_RGB444_LOSSY: u8 = 1;
const MODE_RGB420_LOSSY: u8 = 2;
const MODE_GRAY_LOSSLESS: u8 = 3;
const MODE_RGB_LOSSLESS: u8 = 4;

fn mode_name(mode: u8) -> &'static str {
    match mode {
        MODE_GRAY_LOSSY => "gray-lossy",
        MODE_RGB444_LOSSY => "rgb444-lossy",
        MODE_RGB420_LOSSY => "rgb420-lossy",
        MODE_GRAY_LOSSLESS => "gray-lossless",
        MODE_RGB_LOSSLESS => "rgb-lossless",
        _ => "unknown",
    }
}

struct Header {
    version: u8,
    mode: u8,
    quality: u8,
    flags: u8,
    width: u16,
    height: u16,
}

fn parse_header(data: &[u8]) -> Result<Header, String> {
    if data.len() < HDR {
        return Err("truncated header".into());
    }
    if &data[0..4] != MAGIC {
        return Err("not an MTC image (bad magic)".into());
    }
    Ok(Header {
        version: data[4],
        mode: data[5],
        quality: data[6],
        flags: data[7],
        width: u16::from_le_bytes([data[8], data[9]]),
        height: u16::from_le_bytes([data[10], data[11]]),
    })
}

fn cmd_info(path: &str) -> Result<(), String> {
    let data = fs::read(path).map_err(|e| format!("{}: {}", path, e))?;
    let h = parse_header(&data)?;
    println!("file    {}", path);
    println!("bytes   {}", data.len());
    println!("version {}", h.version);
    println!("mode    {} ({})", h.mode, mode_name(h.mode));
    println!("quality {}", h.quality);
    println!("alpha   {}", h.flags & 1 != 0);
    println!("size    {}x{}", h.width, h.height);
    Ok(())
}

fn read_ppm(path: &str) -> Result<(usize, usize, usize, Vec<u8>), String> {
    let img = image::open(path).map_err(|e| format!("{}: {}", path, e))?;
    let rgb = img.to_rgb8();
    let (w, h) = (rgb.width() as usize, rgb.height() as usize);
    Ok((w, h, 3, rgb.into_raw()))
}

fn write_ppm(path: &str, w: usize, h: usize, ch: usize, px: &[u8]) -> Result<(), String> {
    let img = if ch == 3 {
        let buf = image::RgbImage::from_raw(w as u32, h as u32, px.to_vec())
            .ok_or_else(|| "bad rgb buffer".to_string())?;
        image::DynamicImage::ImageRgb8(buf)
    } else {
        let buf = image::GrayImage::from_raw(w as u32, h as u32, px.to_vec())
            .ok_or_else(|| "bad gray buffer".to_string())?;
        image::DynamicImage::ImageLuma8(buf)
    };
    img.save(path).map_err(|e| format!("{}: {}", path, e))
}

fn usage() -> ExitCode {
    eprintln!("mtcodec — MTC image codec (Rust)");
    eprintln!();
    eprintln!("usage:");
    eprintln!("  mtcodec info <file.mtc>");
    eprintln!("  mtcodec encode <in.pgm> <out.mtc> [-q N]");
    eprintln!("  mtcodec decode <in.mtc> <out.pgm>");
    ExitCode::from(2)
}

fn cmd_encode(args: &[String]) -> Result<(), String> {
    if args.len() < 4 {
        return Err("encode needs <in.pgm> <out.mtc>".into());
    }
    let (input, output) = (&args[2], &args[3]);
    let mut q = 85u8;
    let mut sub = "420".to_string();
    let mut i = 4;
    while i < args.len() {
        if args[i] == "-q" && i + 1 < args.len() {
            q = args[i + 1].parse().map_err(|_| "bad -q".to_string())?;
            i += 2;
        } else if args[i] == "-s" && i + 1 < args.len() {
            sub = args[i + 1].clone();
            i += 2;
        } else {
            return Err(format!("unknown argument: {}", args[i]));
        }
    }
    let (w, h, ch, px) = read_ppm(input)?;
    let blob = if ch == 1 {
        codec::encode_gray(w, h, &px, q)
    } else if sub == "444" {
        codec::encode_rgb444(w, h, &px, q)
    } else {
        codec::encode_rgb420(w, h, &px, q)
    };
    fs::write(output, &blob).map_err(|e| format!("{}: {}", output, e))?;
    println!("encoded {}x{} -> {} ({} bytes)", w, h, output, blob.len());
    Ok(())
}

fn cmd_decode(args: &[String]) -> Result<(), String> {
    if args.len() < 4 {
        return Err("decode needs <in.mtc> <out.pgm>".into());
    }
    let (input, output) = (&args[2], &args[3]);
    let data = fs::read(input).map_err(|e| format!("{}: {}", input, e))?;
    if data.len() < 12 || &data[0..4] != b"MTB1" {
        return Err("not an MTC image".into());
    }
    match data[5] {
        0 => {
            let img = codec::decode_gray(&data)?;
            write_ppm(output, img.width, img.height, 1, &img.pixels)?;
            println!("decoded {}x{} -> {}", img.width, img.height, output);
        }
        1 => {
            let img = codec::decode_rgb444(&data)?;
            write_ppm(output, img.width, img.height, 3, &img.pixels)?;
            println!("decoded {}x{} -> {}", img.width, img.height, output);
        }
        2 => {
            let img = codec::decode_rgb420(&data)?;
            write_ppm(output, img.width, img.height, 3, &img.pixels)?;
            println!("decoded {}x{} -> {}", img.width, img.height, output);
        }
        mode => return Err(format!("mode {} is not implemented in Rust yet", mode)),
    }
    Ok(())
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        return usage();
    }
    let result = match args[1].as_str() {
        "info" if args.len() == 3 => cmd_info(&args[2]),
        "encode" => cmd_encode(&args),
        "decode" => cmd_decode(&args),
        "-h" | "--help" => return usage(),
        other => Err(format!("unknown command: {}", other)),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {}", e);
            ExitCode::from(1)
        }
    }
}
