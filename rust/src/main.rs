//! MTC image codec — Rust-only implementation.
//!
//! The Python package is being replaced; this binary owns the container and,
//! in the next steps, the DCT, quantiser, arithmetic coder and viewer.

use std::env;
use std::fs;
use std::process::ExitCode;

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

fn usage() -> ExitCode {
    eprintln!("mtcodec — MTC image codec (Rust)");
    eprintln!();
    eprintln!("usage:");
    eprintln!("  mtcodec info <file.mtc>");
    ExitCode::from(2)
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        return usage();
    }
    match args[1].as_str() {
        "info" if args.len() == 3 => match cmd_info(&args[2]) {
            Ok(()) => ExitCode::SUCCESS,
            Err(e) => {
                eprintln!("error: {}", e);
                ExitCode::from(1)
            }
        },
        "-h" | "--help" => usage(),
        other => {
            eprintln!("unknown command: {}", other);
            usage()
        }
    }
}
