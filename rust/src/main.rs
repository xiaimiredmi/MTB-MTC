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

fn read_pgm(path: &str) -> Result<(usize, usize, Vec<u8>), String> {
    let data = fs::read(path).map_err(|e| format!("{}: {}", path, e))?;
    if data.len() < 2 || &data[0..2] != b"P5" {
        return Err("only binary PGM (P5) input is supported for now".into());
    }
    let mut i = 2usize;
    let mut nums = Vec::new();
    while nums.len() < 3 {
        while i < data.len() && (data[i] as char).is_whitespace() {
            i += 1;
        }
        if i < data.len() && data[i] == b'#' {
            while i < data.len() && data[i] != b'\n' {
                i += 1;
            }
            continue;
        }
        let start = i;
        while i < data.len() && data[i].is_ascii_digit() {
            i += 1;
        }
        if start == i {
            return Err("bad PGM header".into());
        }
        nums.push(
            std::str::from_utf8(&data[start..i])
                .unwrap()
                .parse::<usize>()
                .map_err(|_| "bad PGM header".to_string())?,
        );
    }
    i += 1; // single whitespace byte after maxval
    let (w, h) = (nums[0], nums[1]);
    if data.len() < i + w * h {
        return Err("truncated PGM body".into());
    }
    Ok((w, h, data[i..i + w * h].to_vec()))
}

fn write_pgm(path: &str, w: usize, h: usize, px: &[u8]) -> Result<(), String> {
    let mut out = format!("P5\n{} {}\n255\n", w, h).into_bytes();
    out.extend_from_slice(px);
    fs::write(path, out).map_err(|e| format!("{}: {}", path, e))
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
    let mut i = 4;
    while i < args.len() {
        if args[i] == "-q" && i + 1 < args.len() {
            q = args[i + 1].parse().map_err(|_| "bad -q".to_string())?;
            i += 2;
        } else {
            return Err(format!("unknown argument: {}", args[i]));
        }
    }
    let (w, h, px) = read_pgm(input)?;
    let blob = codec::encode_gray(w, h, &px, q);
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
    let img = codec::decode_gray(&data)?;
    write_pgm(output, img.width, img.height, &img.pixels)?;
    println!("decoded {}x{} -> {}", img.width, img.height, output);
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
