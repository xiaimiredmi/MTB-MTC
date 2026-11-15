# MTB / MTC

A self-contained image and video codec written in pure Python. It ships its own
container formats (`.mtb` for still images, `.mtc` for short videos), a Tk viewer,
a CLI, and an optional single-file Windows build.

No native extensions, no C toolchain: everything is `numpy` + `Pillow`, so the same
source runs on Windows, Linux and macOS once Python is present.

> 中文说明见 [README.zh-CN.md](README.zh-CN.md)。

---

## What it is

| | Still image | Video |
| --- | --- | --- |
| Extension | `.mtb` | `.mtc` |
| Magic | `MTB1` | `MTC1` |
| Container version | 1 | 2 |
| Colour | gray / YCoCg 4:4:4 / 4:2:0 / lossless | YCoCg 4:2:0 or 4:4:4 |
| Transparency | alpha plane, lossless, byte-exact | not supported |
| Audio | — | embedded WAV (44.1 kHz stereo PCM) |
| Frame rate | — | stored in the header (`fps × 100`) |
| Codec core | 8×8 DCT + arithmetic coding | 8×8 DCT + I/P frames + arithmetic coding |

The point of the project is not to beat JPEG or H.264. It is a codec you can
read end to end in one afternoon, that keeps alpha, keeps audio, and can be
converted back to ordinary formats at any time.

---

## Install

```bash
git clone <your-repo-url>
cd MTB-MTC
pip install -r requirements.txt        # numpy + pillow
```

Optional, only needed for video import/export:

```bash
# any ffmpeg on PATH works; imageio-ffmpeg is a zero-config fallback
pip install imageio-ffmpeg
```

Editable install, which also gives you the `mtcodec` command:

```bash
pip install -e .
mtcodec --help
```

---

## Quick start

```bash
# open a file in the viewer (window shows only the picture, no fps/bitrate overlays)
python -m mtcodec open samples/photo_c.mtb
python -m mtcodec open samples/mtc_audio.mtc

# print the header
python -m mtcodec info samples/photo_c.mtb
python -m mtcodec video-info samples/mtc_audio.mtc
```

Real output from the two commands above:

```text
{'magic': 'MTB1', 'version': 1, 'mode': 2, 'quality': 80, 'has_alpha': False,
 'width': 512, 'height': 512, 'bytes': 46921}

{'magic': 'MTC1', 'version': 2, 'subsample_420': True, 'quality': 80, 'gop': 12,
 'width': 720, 'height': 1280, 'frames': 12, 'fps': 12.0, 'has_audio': True,
 'audio_bytes': 176478, 'bytes': 298280}
```

---

## Converting mainstream formats

This is the part most people need. `convert` goes **into** the codec,
`export` goes **out of** it. The output type is decided by the extension you
write — no guessing.

### Images → `.mtb`

```bash
python -m mtcodec convert photo.png photo.mtb -q 80
python -m mtcodec convert photo.png photo.mtb --size 1080p
python -m mtcodec convert transparent.png transparent.mtb -q 85   # alpha kept
python -m mtcodec convert photo.png photo.mtb --lossless           # byte-exact
```

Accepted input: PNG, JPG, JPEG, BMP, WEBP, TIF, GIF, APNG.

### Video → `.mtc`

```bash
python -m mtcodec convert clip.mp4 clip.mtc
python -m mtcodec convert clip.mp4 clip.mtc --size 720p --fps 12 --max-frames 24
python -m mtcodec convert clip.mp4 clip.mtc --start 5 --max-frames 48 --gop 0
python -m mtcodec convert clip.mp4 clip.mtc --no-audio
```

Accepted input: anything ffmpeg can decode (MP4, MOV, MKV, AVI, WEBM, M4V…).
The audio track is extracted to 44.1 kHz stereo PCM and embedded in the container,
so an exported MP4 keeps its sound.

### Back to mainstream formats

```bash
python -m mtcodec export photo.mtb photo.png        # alpha preserved
python -m mtcodec export photo.mtb photo.jpg        # alpha flattened onto white
python -m mtcodec export clip.mtc clip.mp4          # H.264 + AAC, audio included
python -m mtcodec export clip.mtc frames/           # PNG sequence + audio.wav
```

### Batch conversion

```bash
# a whole folder of images and videos -> .mtb / .mtc
python tools/batch_convert.py D:/pictures --out D:/pictures/converted -q 80

# back out again
python tools/batch_convert.py D:/pictures/converted --export --out D:/pictures/back
```

The batch tool prints one line per file, keeps going when a single file fails,
and returns a non-zero exit code if anything failed.

---

## Size presets

| Preset | Output | Preset | Output |
| --- | --- | --- | --- |
| `360p` | 640×360 | `1080p` | 1920×1080 |
| `480p` | 854×480 | `1440p` | 2560×1440 |
| `540p` | 960×540 | `2k` | 2560×1440 |
| `720p` | 1280×720 | `4k` | 3840×2160 |
| `4x4k` | 7680×4320 | `8k` | 7680×4320 |

* Any explicit size also works: `--size 1920x1080`.
* Images are fitted inside the box and never stretched.
* Portrait images swap the box automatically: a 1080×1920 picture with
  `--size 1080p` stays 1080×1920 instead of being rotated into landscape.

### Measured cost (single thread, pure Python, q80)

| Target | Size | Output | Ratio | PSNR | Encode |
| --- | --- | --- | --- | --- | --- |
| 360p | 360×360 | 27.1 KB | 14.0 : 1 | 26.61 dB | 0.21 s |
| 720p | 720×720 | 77.5 KB | 19.6 : 1 | 28.73 dB | 0.61 s |
| 1080p | 1080×1080 | 143.4 KB | 23.8 : 1 | 30.04 dB | 1.18 s |
| source | 2048×2048 | 350.3 KB | 35.1 : 1 | 32.60 dB | 3.16 s |
| 4K | 2160×2160 | 370.9 KB | 36.9 : 1 | 33.08 dB | 3.39 s |
| 4×4K | 7680×4320 | 1.58 MB | 61.4 : 1 | 38.83 dB | 16.6 s (decode 18.0 s) |

PSNR rises with upscaled targets because the picture gets smoother, not because
the quality is better. Never compare PSNR across different sizes.

---

## Compression knobs

| Flag | Applies to | Default | What it does |
| --- | --- | --- | --- |
| `-q/--quality` | both | 80 (`convert`), 85 (`encode`) | quantiser scale; higher = bigger, cleaner |
| `-s/--subsample` | both | `420` | `444` keeps full chroma, costs ~30 % more |
| `--lossless` | images | off | RGB lossless mode, byte-exact round trip |
| `--gop` | video | 12 | I-frame interval; `0` = all intra, seekable, large |
| `--fps` | video | 12 | frames sampled per second *and* playback rate |
| `--max-frames` | video | 24 | hard cap on stored frames |
| `--start` | video | 0 | start offset in seconds |
| `--no-audio` | video | off | skip the audio segment |

`--fps` and `--max-frames` together decide how much of the clip is stored:
`--fps 12 --max-frames 24` covers the first two seconds. `.mtc` is a storage
format for experiments and archives, not a replacement for MP4.

---

## Python API

```python
import mtcodec

blob = mtcodec.encode_image(img, quality=80, subsample="420")   # RGBA or RGB
img2 = mtcodec.decode_image(blob)                                # RGBA if alpha present

frames = mtcodec.encode_video([f0, f1, f2], quality=80, gop=12,
                              fps=12.0, audio=wav_bytes)
out, stats = mtcodec.decode_video(frames)
```

Low level, when you need the bridging helpers:

```python
from mtcodec import io_bridge

frames, has_alpha, src_size = io_bridge.load_image_frames("in.apng", "1080p")
frames, src_size = io_bridge.load_video_frames("in.mp4", fps=12, size_spec="720p",
                                               max_frames=24, start=0)
audio = io_bridge.load_audio_wav("in.mp4", seconds=2.0)
io_bridge.export_mp4(decoded_frames, "out.mp4", fps=12.0, wav_bytes=audio)
```

---

## GUI and Windows integration

```bash
python -m mtcodec open samples/photo_c.mtb
python deploy/windows_register.py --exe "D:/MTB-MTC/release/MTBViewer.exe"
python deploy/windows_register.py --unregister
```

The viewer deliberately shows **no technical overlay**: no frame counter, no fps,
no gop, no byte count. A still image looks like a still image; the window title is
just the file name. Space pauses playback, Esc closes.

Windows 10/11 refuse to let a program silently become the default handler, so
registration only puts MTB/MTC into the "Open with" list with the red M (image)
and blue M (video) icons. Tick "Always use this app" once and it sticks.

---

## Build a single-file executable

```bash
pip install pyinstaller
python tools/build_exe.py          # -> dist/MTBViewer.exe, ~29 MB, windowed
```

Full instructions (PyInstaller, Nuitka, Linux `.desktop`, macOS `.app`,
Android via Termux/Chaquopy) are in [docs/BUILD.md](docs/BUILD.md).

---

## Platform notes

| Platform | Run source | Single file | Notes |
| --- | --- | --- | --- |
| Windows 10/11 | yes | `MTBViewer.exe` | file association + icons supported |
| Linux | yes | PyInstaller | audio playback is silent (winsound is Windows only) |
| macOS | yes | PyInstaller `.app` | same, silent; use python.org Python (Homebrew lacks Tk) |
| Android | via Termux / Chaquopy | — | Tk must be replaced by a native widget |

HarmonyOS and iOS are out of scope: they need a different language or a Mac build
chain. That is stated here on purpose, not forgotten.

---

## Honest limits

* **Large images are slow.** 7680×4320 takes 16.6 s to encode; a small picture
  upscaled to 8K took 82 s. Per-symbol arithmetic coding in pure Python.
* **Audio is stored uncompressed.** 172 KB per second, 24–59 % of a test `.mtc`.
* **Audio and video are only coarsely synced.** Playback uses an async system
  player; there are no per-frame timestamps. Fine for a few seconds, it drifts.
* **`.mtc` has no alpha.** Transparent animations lose transparency when stored
  as video (use `.mtb` for a single frame).
* **APNG frame durations are lost.** `.mtc` is constant frame rate.
* **Video needs ffmpeg.** Images work without it.
* **Non-Windows builds are silent.** Picture plays, audio does not.

---

## Measured results (2026-11-15, Windows 11 / Python 3.12)

| Input | Size | Output | Ratio | PSNR |
| --- | --- | --- | --- | --- |
| wall 1080×1920 PNG | 2.08 MB | 179.5 KB | 33.8 : 1 | 32.29 dB |
| wall 1920×1080 PNG | 2.64 MB | 300.5 KB | 20.2 : 1 | 28.84 dB |
| wall 2048×2048 PNG | 4.28 MB | 350.3 KB | 35.1 : 1 | 32.60 dB |
| wall 2058×1440 PNG | 3.42 MB | 358.7 KB | 24.2 : 1 | 29.81 dB |
| wall 560×1440 PNG | 0.83 MB | 88.3 KB | 26.8 : 1 | 30.43 dB |
| wall 800×450 RGBA PNG | 0.65 MB | 81.6 KB | 17.2 : 1 | 26.08 dB |
| wall 800×800 PNG | 0.81 MB | 98.5 KB | 19.0 : 1 | 28.23 dB |
| clip 5.56 MB MP4 → MTC | 5.56 MB | 371.6 KB (172.3 KB audio) | 87.2 : 1 | — |
| clip 35.5 MB MP4 → MTC | 35.5 MB | 357.4 KB (172.3 KB audio) | 87.1 : 1 | — |
| APNG 8 frames → MTC | — | 28 465 B | — | — |

Alpha round trip: 1080×1080 RGBA → `.mtb` (128.7 KB) → PNG (625.9 KB), alpha
channel bit-exact.

Two HTML reports with the full tables and charts live in the repository root:
`格式互转与多分辨率测试报告.html` and `编码器实验报告.html`.

---

## Repository layout

```text
mtcodec/          codec core (image_codec, video_codec, io_bridge, cli, viewer)
deploy/           exe entry point, Windows registration, icons
tools/            build exe, build zip, batch convert, icon and CLI demos,
                  check_release.py (pre-publish self-check), make_release_zip.py
tests/            unit and format tests (pytest-free, plain python)
bench/            benchmark scripts that produced results/
results/          measured JSON data
samples/          example .mtb / .mtc files, including alpha and audio samples
assets/           icons and the codec-vs-JPEG-vs-WebP comparison strip
docs/             FORMAT.md, CONVERT.md, BUILD.md, PUBLISH.md (EN + 中文)
release/          prebuilt exe + two zips (git-ignored; attach to a Release)
```

---

## Documentation

| File | Content |
| --- | --- |
| [docs/FORMAT.md](docs/FORMAT.md) | byte-level container spec, both EN and 中文 |
| [docs/CONVERT.md](docs/CONVERT.md) | conversion guide, every flag, troubleshooting |
| [docs/BUILD.md](docs/BUILD.md) | PyInstaller / Nuitka / Linux / macOS / Android |
| [docs/PUBLISH.md](docs/PUBLISH.md) | how to publish this on GitHub, step by step |
| [CHANGELOG.md](CHANGELOG.md) | version history |

---

## License

MIT. See [LICENSE](LICENSE).
