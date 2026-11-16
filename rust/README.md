# mtc — Rust image codec

Self-contained MTC image codec in Rust. PNG/JPEG/WebP/BMP are read and written
with the `image` crate; the `.mtc` container, DCT, quantiser, arithmetic coder
and coefficient model are ours.

## Build

```powershell
cargo build --release
```

The binary is `target/release/mtcodec.exe`.

## Commands

```powershell
mtcodec encode photo.png photo.mtc -q 85      # 4:2:0, alpha kept if present
mtcodec encode photo.png photo.mtc -q 85 -s 444
mtcodec decode photo.mtc out.png               # format from the output extension
mtcodec info photo.mtc
```

## Status

- gray / RGB 4:4:4 / RGB 4:2:0 lossy, exact alpha (stored as a PNG blob)
- 2048x1152 photo: ~130 ms encode, ~93 ms decode, ~34.8 KB at q85
- lossless, adaptive quantisation, viewer and Python removal are still pending
- tests: `cargo test` (8 tests: arithmetic coder, DCT, quantiser, block coder,
  gray and colour round trips)
