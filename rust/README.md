# mtc — Rust image codec

Self-contained MTC image codec in Rust. PNG/JPEG/WebP/BMP are read and written
with the `image` crate; the `.mtc` container, DCT, quantiser, adaptive
quantisation, arithmetic coder and coefficient model are ours.

## Build

```powershell
cargo build --release                      # mtcodec + mtbench
cargo build --release --features viewer    # + mtview, the egui viewer
```

The binaries are `target/release/mtcodec.exe`, `mtbench.exe` and `mtview.exe`.

## Install

`D:\MTB-MTC\bin` is on the user `Path` and holds the three binaries, so the bare
names resolve to these builds:

```powershell
copy target\release\mtcodec.exe,target\release\mtbench.exe,target\release\mtview.exe ..\bin\
powershell -ExecutionPolicy Bypass -File ..\deploy\register.ps1
mtcodec info photo.mtc
```

`deploy\register.ps1` registers `.mtc` to open with `mtview`, points the icon at
`deploy\mtc.ico`, clears the old video-container registrations, puts `bin\` first
on the user `Path` and tells Explorer the environment changed. It is per-user
(`HKCU`), needs no administrator, and `-Unregister` undoes all of it.

## Commands

```powershell
mtcodec encode photo.png photo.mtc -q 85      # 4:2:0, alpha kept if present
mtcodec encode photo.png photo.mtc -q 85 -s 444
mtcodec encode photo.png photo.mtc -q 85 --aq on
mtcodec encode scan.png scan.mtc --lossless    # spatial prediction, exact
mtcodec encode photo.png photo.mtc --v1       # legacy version 1 stream
mtcodec decode photo.mtc out.png              # format from the output extension
mtcodec info photo.mtc
mtview photo.mtc                              # or any PNG/JPEG/WebP/BMP
```

`mtbench` measures rate and distortion:

```powershell
mtbench bench/data/*.png -q 55,65,75,82,88,93,97 --modes flat,ctx,aq -o results/rd.csv
python bench/rd_compare.py results/rd.csv results/rd.csv --mode flat --alt-mode ctx
```

`rd_compare.py` compares two runs **at matched PSNR**. Two encoder settings
cannot be compared at the same `-q`, because whichever spends more bits scores
higher and looks better than it is.

## What the codec does

- 8×8 DCT with a frequency-tilted quantiser and an AC dead zone.
- YCoCg colour, 4:2:0 (default) or 4:4:4, chroma quantised 1.35× harder.
- DC predicted from the block above and the block to the left by a median edge
  detector, so smooth pictures stop paying for a per-block brightness value.
- Adaptive binary arithmetic coding over zig-zag coefficients, with the
  previous block's sparsity conditioning the `last` symbol.
- Lossless mode (spatial prediction instead of the DCT), pixel-exact.
- Exact alpha, coded with the lossless path, so lossy RGB can carry lossless
  alpha.
- Version 1 streams written by the Python encoder decode bit-exactly; there is
  a fixture test for it.

## Adaptive quantisation and contexts

Both were measured against the encoder as it was, one change at a time, on four
512×512 photographs at seven quality settings, compared at matched PSNR.

| change | effect on bytes at matched PSNR |
| --- | --- |
| AC dead zone (0.65 of a step) | −7.8% |
| 2-D DC prediction (median edge detector) | −3.1% |
| `last` conditioned on the previous block | −0.45% |
| band context on significance / magnitude | +1.4% |
| DC-class context | −0.1% (dropped) |
| per-tile adaptive quantisation | +8.5% (opt-in) |
| **version 2 as shipped** | **−11.35%** |

The dead zone is the surprise only in size: rounding small AC coefficients to
zero costs nothing to code them and buys back much more than the tiny error it
adds, and the DC coefficient is deliberately left at plain round-to-nearest.

Adaptive quantisation is a per-16×16-tile quantiser multiplier in seven levels
(0.70× to 1.40×), chosen by the encoder from tile activity against the picture
median and **signalled**, because an intra frame gives the decoder no reference
plane to derive it from. Levels are delta-coded against the previous tile and
the multiplier is tapered towards the low frequencies. It spends more bits on
busy tiles, which is what a fixed `-q` benchmark rewards: about +0.3 dB for
+15% bytes. At matched PSNR that trade loses, so it is off by default and
`--aq auto` — which encodes both and keeps the smaller file that does not lose
quality — rejects it on all four test pictures. It stays in the format for
perceptual work.

Two other contexts were tried and removed: significance conditioned on the
previous block's non-zero pattern, and the DC class conditioned on the previous
block's DC. Both dilute the per-band probabilities and make files larger.

## Measured

2048×1152 photograph, `-q 85`, 4:2:0, version 2: **397 KB at 33.63 dB, ~115 ms
encode, ~130 ms decode** (one core, release build). Version 1 for the same file
and `-q` gives 457 KB at 34.22 dB.

Rate/distortion against the version 1 stream, four 512×512 pictures, six
quality settings each (`results/rd_final.csv`):

| image | v1 bytes | v2 bytes | delta |
| --- | --- | --- | --- |
| photo_a | 21115 | 20041 | −5.3% |
| photo_b | 15747 | 13085 | −15.3% |
| photo_c | 50610 | 46571 | −8.5% |
| render_d | 4175 | 3433 | −15.8% |

The byte counts are the two curves evaluated at the same PSNR, not two files at
the same `-q`.

## Viewer

`mtview` is an egui window: white background, the picture at fit-to-window,
mouse wheel zooms around the cursor between fit and 8×, drag pans, double-click
or `1` returns to fit, Esc closes. `.mtc` files show their mode, quality, size
and version in the header bar; other image files open too, which makes it
usable for eyeballing a decode against its source.

Above 1:1 the texture switches to nearest-neighbour, so block edges and ringing
are visible as they are, not blurred by interpolation. egui ships no CJK glyphs,
so the viewer loads a system font (YaHei, DengXian, SimHei or SimSun) as the
fallback face; without it a Chinese file name is a row of empty boxes.

Environment variables for scripted checks: `MTCODEC_VIEWER_AUTOCLOSE_MS` closes
the window and prints `viewer ok`, `MTCODEC_VIEWER_ZOOM` opens at a fixed zoom.

## Tests

```powershell
cargo test                                  # 32 unit + 5 compatibility tests
cargo test --release --features viewer      # + 9 viewer geometry tests
```

`tests/compat.rs` decodes `tests/data/legacy_v1.mtc` — a file the Python encoder
wrote — and checks the decoded pixels against a hash taken from the Python
decoder. It exists because the Rust port originally transposed each block's
axes, so every Python file decoded rotated by 90° inside every 8×8 block while
still round-tripping against itself.

## Status

- lossy gray / RGB 4:4:4 / RGB 4:2:0, exact alpha
- lossless gray / RGB, pixel-exact, verified against the reference encoder both
  ways (identical bytes for the same input)
- version 1 and version 2 streams both decode; version 2 is what we write
- the Python implementation is gone; `tests/data/` keeps three of its files as
  fixtures so the legacy streams stay decodable
