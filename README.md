# MTC — a self-built image codec

MTC is a from-scratch still-image codec. No JPEG, WebP, PNG or HEIC library is
linked in: the transform, quantiser, arithmetic coder and colour conversion are
our own, and the container is ours.

One format, one extension: **`.mtc`**. Lossy and lossless share the container,
with optional alpha and 4:2:0 / 4:4:4 chroma.

## What it does

- 8×8 DCT with a frequency-tilted quantiser, YCoCg colour, optional 4:2:0.
- Adaptive binary arithmetic coding over zig-zag coefficients.
- Exact alpha channel, stored losslessly alongside the RGB payload.
- Lossless mode (spatial predictor + arithmetic coding) for pixel-perfect work.
- White player with mouse-wheel zoom (fit to 8×), drag to pan, double-click to
  reset.

The video codec that used to live in this repository has been removed. `.mtc`
is now the image format; `.mtb` is no longer produced.

## Install

```powershell
D:\python\python.exe -m pip install -e D:\MTB-MTC
```

The package is pure Python plus numpy and Pillow. It runs from the source tree
without any build step.

## Use

```powershell
# PNG / JPG / WEBP / BMP / GIF / APNG -> .mtc
D:\python\python.exe -m mtcodec encode photo.jpg photo.mtc -q 85

# .mtc -> PNG / JPG / WEBP by output extension
D:\python\python.exe -m mtcodec decode photo.mtc out.jpg

# header only
D:\python\python.exe -m mtcodec info photo.mtc

# open the player
D:\python\python.exe -m mtcodec open photo.mtc
```

Lossless:

```powershell
D:\python\python.exe -m mtcodec encode scan.png scan.mtc --lossless
```

## Player

`mtcodec.viewer` opens `.mtc` in a white window. Mouse wheel zooms around the
cursor between fit-to-window and 8×, dragging pans, double-click or clicking the
zoom readout returns to fit, Esc closes.

`rust/target/release/mtview.exe` is the same player on egui, and it also opens
PNG/JPEG/WebP/BMP, which makes it the quickest way to put a decode beside its
source.

## Repository layout

```
mtcodec/image_codec.py   container and pixel pipeline
mtcodec/entropy.py       coefficient model and block coder
mtcodec/arithmetic.py    arithmetic coder
mtcodec/transform.py     DCT / quantiser tables
mtcodec/color.py         YCoCg and clipping
mtcodec/io_bridge.py     PNG/JPG/WEBP/GIF/APNG bridge
mtcodec/viewer.py        image player
mtcodec/cli.py           command line
rust/                    Rust codec, bench harness and egui viewer
native/                  early Rust helpers (dormant)
deploy/                  Windows registration and PATH setup
tests/                   image codec tests
```

## Status

The image path is the product, and the format now belongs to the Rust codec in
`rust/`: it writes a version 2 stream that is 11% smaller than the Python
encoder's at matched PSNR, decodes every existing `.mtc` bit-exactly, and comes
with its own egui viewer (`mtview`). What is left is lossless mode, an
arithmetic-coded alpha channel, and taking the Python package out. The
rate/distortion numbers live in `rust/results/` and are reproducible with
`rust/bench/rd_compare.py`.
