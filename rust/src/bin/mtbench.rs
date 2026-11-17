//! Rate/distortion measurement for the codec.
//!
//! ```text
//! mtbench bench/data/*.png -q 50,60,70,80,85,90,95 -o results/rd.csv
//! ```
//!
//! Modes are the three stream shapes the encoder can write: `flat` (version 1,
//! no adaptive quantisation), `ctx` (version 2, context model) and `aq`
//! (version 2 plus adaptive quantisation). `auto` is the shipped default, which
//! picks between the last two per file.

use std::env;
use std::fmt::Write as _;
use std::time::Instant;

use mtc::container::{self, AqMode, Options, VERSION, VERSION_LEGACY};
use mtc::imgio;

struct Mode {
    label: &'static str,
    opts: Options,
}

fn modes() -> Vec<Mode> {
    vec![
        Mode {
            label: "flat",
            opts: Options {
                version: VERSION_LEGACY,
                aq: AqMode::Off,
                ..Options::default()
            },
        },
        Mode {
            label: "ctx",
            opts: Options {
                version: VERSION,
                aq: AqMode::Off,
                ..Options::default()
            },
        },
        Mode {
            label: "aq",
            opts: Options {
                version: VERSION,
                aq: AqMode::On,
                ..Options::default()
            },
        },
        Mode {
            label: "auto",
            opts: Options {
                version: VERSION,
                aq: AqMode::Auto,
                ..Options::default()
            },
        },
    ]
}

struct Row {
    image: String,
    quality: u8,
    mode: &'static str,
    bytes: usize,
    bpp: f64,
    psnr: f64,
    enc_ms: f64,
    dec_ms: f64,
}

fn best_ms(reps: usize, mut f: impl FnMut() -> f64) -> f64 {
    let mut best = f64::MAX;
    for _ in 0..reps.max(1) {
        let v = f();
        if v < best {
            best = v;
        }
    }
    best
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    if args.is_empty() {
        eprintln!("usage: mtbench <image...> [-q 50,60,85] [-o out.csv] [--modes flat,ctx,aq,auto]");
        std::process::exit(2);
    }
    let mut images: Vec<String> = Vec::new();
    let mut qualities: Vec<u8> = vec![50, 60, 70, 80, 85, 90, 95];
    let mut csv_path: Option<String> = None;
    let mut wanted: Vec<String> = vec![
        "flat".to_string(),
        "ctx".to_string(),
        "aq".to_string(),
        "auto".to_string(),
    ];
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "-q" if i + 1 < args.len() => {
                qualities = args[i + 1]
                    .split(',')
                    .filter_map(|s| s.trim().parse::<u8>().ok())
                    .collect();
                i += 2;
            }
            "-o" if i + 1 < args.len() => {
                csv_path = Some(args[i + 1].clone());
                i += 2;
            }
            "--modes" if i + 1 < args.len() => {
                wanted = args[i + 1].split(',').map(|s| s.trim().to_string()).collect();
                i += 2;
            }
            other => {
                images.push(other.to_string());
                i += 1;
            }
        }
    }
    if images.is_empty() {
        eprintln!("no input images");
        std::process::exit(2);
    }

    let selected: Vec<Mode> = modes()
        .into_iter()
        .filter(|m| wanted.iter().any(|w| w == m.label))
        .collect();

    let mut rows: Vec<Row> = Vec::new();
    println!(
        "{:<12} {:>4} {:>5} {:>9} {:>7} {:>8} {:>8} {:>8}",
        "image", "q", "mode", "bytes", "bpp", "psnr", "enc ms", "dec ms"
    );
    for path in &images {
        let name = std::path::Path::new(path)
            .file_stem()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_else(|| path.clone());
        let img = match imgio::load(path) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("skip {}: {}", path, e);
                continue;
            }
        };
        let pixels = (img.width * img.height) as f64;
        for &q in &qualities {
            for m in &selected {
                let mut opts = m.opts;
                opts.quality = q;
                let mut blob = Vec::new();
                let enc_ms = best_ms(3, || {
                    let t = Instant::now();
                    blob = container::encode(&img, &opts).expect("encode");
                    t.elapsed().as_secs_f64() * 1000.0
                });
                let mut back = None;
                let dec_ms = best_ms(3, || {
                    let t = Instant::now();
                    back = Some(container::decode(&blob).expect("decode"));
                    t.elapsed().as_secs_f64() * 1000.0
                });
                let back = back.expect("decode");
                let row = Row {
                    image: name.clone(),
                    quality: q,
                    mode: m.label,
                    bytes: blob.len(),
                    bpp: blob.len() as f64 * 8.0 / pixels,
                    psnr: img.psnr_visible(&back),
                    enc_ms,
                    dec_ms,
                };
                println!(
                    "{:<12} {:>4} {:>5} {:>9} {:>7.3} {:>8.2} {:>8.1} {:>8.1}",
                    row.image,
                    row.quality,
                    row.mode,
                    row.bytes,
                    row.bpp,
                    row.psnr,
                    row.enc_ms,
                    row.dec_ms
                );
                rows.push(row);
            }
        }
    }

    if let Some(path) = csv_path {
        let mut text = String::from("image,quality,mode,bytes,bpp,psnr,enc_ms,dec_ms\n");
        for r in &rows {
            writeln!(
                &mut text,
                "{},{},{},{},{:.4},{:.3},{:.2},{:.2}",
                r.image, r.quality, r.mode, r.bytes, r.bpp, r.psnr, r.enc_ms, r.dec_ms
            )
            .unwrap();
        }
        if let Some(dir) = std::path::Path::new(&path).parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        match std::fs::write(&path, text) {
            Ok(()) => println!("\nwrote {} ({} rows)", path, rows.len()),
            Err(e) => eprintln!("could not write {}: {}", path, e),
        }
    }
}
