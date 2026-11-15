# Changelog

All notable changes to this project. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
`MAJOR.MINOR.PATCH`. Two languages per release, English first, 中文在后。

---

## [1.2.1] — 2026-11-15

### Added

* **Full player controls.** Speed 0.5× / 1× / 1.5× / 2×, a draggable seek bar,
  volume 0–100, loop, and close-when-finished. Space toggles play/pause, ←/→
  seek one second, ↑/↓ change volume, Esc closes.
* **Native Rust decoder.** The whole decode pipeline — entropy decoding,
  dequantisation, inverse DCT, prediction, clipping, YCoCg → RGB — runs in a
  Rust cdylib called through a C ABI, four FFI crossings per frame instead of
  hundreds of millions per clip. Measured on this machine: `demo.mtc`
  64.6 → 2.5 ms per frame (26×), `q_360p.mtc` (120 frames, 638×360)
  21.28 s → 0.90 s (24×), `q_720p.mtc` (120 frames, 1278×720) 64.84 s →
  2.43 s (27×). Entropy decoding stays serial (one bitstream, one adaptive
  context chain); the IDCT and RGB pack fan out across cores. Output is
  unchanged: `demo.mtc` is bit-for-bit equal, the longer clips differ on
  0.004 % of samples by one grey level. Missing `mtfastdec.dll` (or
  `MTCODEC_NO_NATIVE=1`) falls back to pure Python with no behaviour change.
* **Real audio speed and volume.** The embedded PCM is resampled and scaled
  with numpy, written to a temporary WAV and handed to the OS player
  (`winsound` on Windows, `aplay` on Linux, `afplay` on macOS), so speed and
  gain need no extra dependency (no pygame, no sounddevice).
* **Pitch-preserving speed.** Speed now runs through ffmpeg's `atempo` filter
  on the whole track, so 0.5× / 1.5× / 2× change tempo without touching the
  pitch. Verified with a 440 Hz tone: the spectral peak stays at 440 Hz at all
  four speeds (0.5× 1.97 s, 1.5× 0.67 s, 2× 0.50 s). Without ffmpeg the player
  falls back to linear interpolation and the window says the pitch will move.
  Speed WAVs are built on a worker thread and cached per speed, so switching
  speed never blocks the UI.
* **Live decode progress bar.** Opening a clip shows a progress bar, a
  percentage, and the frame currently being decoded; when decoding finishes
  that same window becomes the player, so the bar hands over to the playback
  seek bar. `decode_video` gained a `progress(i, nframes, frame)` callback.

### Changed

* **Playback clock is monotonic.** Frame timing is derived from
  `time.monotonic()` and scheduled to the next frame boundary, instead of
  chaining a fixed `after(1000/fps)`, so a long clip no longer drifts slower
  and slower.
* **Resolution-preserving display.** Frames keep their decoded size (only
  scaled down once above 1600 px) and are fitted to the window with LANCZOS,
  so the window can be dragged larger or smaller and zooming in no longer
  turns detail into mush. Still images do the same and open at their native
  resolution.
* **Redrawn player UI.** Dark flat skin with hand-drawn chips for speed, loop
  and close-when-finished, a self-drawn seek bar with a round handle, and a
  fixed-width time readout.
* `tools/build_exe.py --onedir` builds a folder bundle. Measured on the dev
  machine, start-to-close on the same sample: onefile 6.1–9.2 s, onedir
  4.1–6.1 s (both include a 1.2 s auto-close timer plus the decode step).

## [1.2.0] — 2026-11-15

### Added

* **Image alpha plane.** `MTB1` gains `FLAG_ALPHA` and an independent lossless
  alpha stream written before the main payload, so RGBA images round-trip
  byte-exactly while RGB stays lossy. Pixels with `alpha < 8` are forced to
  RGB 0 to remove colour fringing.
* **MTC v2.** New 20-byte header (`<4sBBBBHHII`) carries `fps × 100` plus an
  embedded 44.1 kHz stereo PCM WAV segment. v1 files still decode.
* **`convert` and `export`.** One command in (PNG/JPG/WebP/GIF/APNG/MP4/MOV/MKV →
  `.mtb`/`.mtc`), one command out (`.mtb` → PNG/JPG/WebP, `.mtc` → MP4 or PNG
  sequence + WAV).
* **Size presets.** `360p / 480p / 540p / 720p / 1080p / 1440p / 2k / 4k / 4x4k / 8k`
  or any explicit `WxH`; images are fitted without stretching and portrait sizes
  swap the box automatically.
* **`tools/batch_convert.py`.** Folder-level batch conversion in both directions,
  one line per file, per-file failure isolation, `--overwrite`, `--quiet`.
* **Icons.** `tools/make_icons.py` draws the red `#C62828` M (image) and blue
  `#1565C0` M (video) PNG/ICO set from scratch.
* **Viewer without overlays.** All on-screen technical text removed — no frame
  counter, fps, gop or byte size. A still image looks like a still image; the
  window title is the file name.
* **Docs.** `README.md` (English), `README.zh-CN.md`, `docs/FORMAT.md`,
  `docs/CONVERT.md`, `docs/BUILD.md`, `docs/PUBLISH.md` — each bilingual where it
  describes behaviour.
* **Release engineering.** `pyproject.toml`, `requirements.txt`, `.gitignore`,
  `LICENSE` (MIT), `.github/workflows/release.yml`, `tools/make_zip.py`.

### Changed

* `threshold` in the alpha path: an image is now reported as `alpha=True` by
  `info` instead of silently flattening.
* `--fps` now also drives playback rate, not just frame sampling.
* Rebuilt `MTBViewer.exe` (29.4 MB) and verified on the alpha, audio and 8K samples
  (exit code 0 for all three).

### Fixed

* Odd `width × height` no longer produce a broken MP4 export
  (`scale=trunc(iw/2)*2:trunc(ih/2)*2` in the ffmpeg call).
* `decode_video` on a v1 stream no longer divides by an absent fps field.

### Measured (not a guarantee)

* 7680×4320 at q80: 1.58 MB, PSNR 38.83 dB, encode 16.6 s, decode 18.0 s.
* 5.56 MB MP4 → 371.6 KB `.mtc` (172.3 KB of it audio), export back to MP4 with sound.
* 1080×1080 RGBA → 128.7 KB `.mtb` → PNG, alpha bit-exact.

---

## [1.1.0] — 2026-11-11

### Added

* `MTC1` v1 container: I/P frames, `gop` with automatic scene-cut detection
  (`SCENE_CUT_SAD = 24.0`), full decode.
* CLI subcommands `encode`, `decode`, `open`, `video-encode`, `video-decode`,
  `video-info`.
* tkinter viewer with space-to-pause and Esc-to-close.

### Changed

* DCT coefficient coding switched to per-plane, per-position context models,
  about 8 % smaller files at the same quality.

---

## [1.0.0] — 2026-11-09

### Added

* `MTB1` container: gray / YCoCg 4:4:4 / 4:2:0 lossy modes (0–2), gray and RGB
  lossless modes (3–4).
* 8×8 DCT, zig-zag scan, DC prediction, arithmetic coder with adaptive models.
* `encode` / `decode` / `info` for images.
* First benchmark run: 2048×2048 photo at 350 KB, 32.6 dB.

---

# 中文

## [1.2.1] — 2026-11-15

### 新增

* **完整播放控件。** 倍速 0.5× / 1× / 1.5× / 2×、可拖动进度条、音量 0–100、
  循环播放、播完关闭。空格播放/暂停，←/→ 前后跳 1 秒，↑/↓ 调音量，Esc 关闭。
* **真正的音频变速与音量。** 内嵌 PCM 用 numpy 重采样并做增益，写成临时 WAV
  交给系统播放器（Windows 用 `winsound`，Linux 用 `aplay`，macOS 用 `afplay`），
  所以变速和音量不需要 pygame / sounddevice 这类额外依赖。
* **解码进度条。** 打开片子时窗口里就是一根进度条加百分比，还会显示正在解码的
  那一帧；解码完成后同一个窗口直接变成播放器，这根进度条交给播放进度条接着用。
  `decode_video` 新增 `progress(i, nframes, frame)` 回调。

### 变更

* **播放时钟改为单调时钟。** 帧时刻由 `time.monotonic()` 推出并排到下一帧边界，
  不再用固定 `after(1000/fps)` 接力，长片不会越播越慢。
* **内存更省、贴图更顺。** 解码后先把帧缩到不超过 960×720，再按需生成
  `PhotoImage` 并做 32 帧 LRU 缓存，不再一次性预生成全部原尺寸帧。
* `tools/build_exe.py --onedir` 可产出目录版。本机实测同一样本从启动到关闭：
  onefile 6.1–9.2 秒，onedir 4.1–6.1 秒（都含 1.2 秒自动关闭与解码）。

## [1.2.0] — 2026-11-15

### 新增

* **图片透明平面。** `MTB1` 增加 `FLAG_ALPHA` 和一个独立无损 alpha 流，写在
  主数据前面；RGBA 图往返逐位一致，RGB 仍可有损。`alpha < 8` 的像素 RGB 置 0，
  消掉半透明边缘脏色。
* **MTC v2。** 新的 20 字节头（`<4sBBBBHHII`）带 `fps × 100`，并内嵌
  44.1 kHz 立体声 PCM WAV。v1 文件仍能解码。
* **`convert` 与 `export`。** 一条命令进（PNG/JPG/WebP/GIF/APNG/MP4/MOV/MKV →
  `.mtb`/`.mtc`），一条命令出（`.mtb` → PNG/JPG/WebP，`.mtc` → MP4 或
  PNG 序列 + WAV）。
* **尺寸预设。** `360p / 480p / 540p / 720p / 1080p / 1440p / 2k / 4k / 4x4k / 8k`
  或任意 `WxH`；等比装框不拉伸，竖图自动对调宽高。
* **`tools/batch_convert.py`。** 目录级双向批量转换，每文件一行，单文件失败隔离，
  支持 `--overwrite`、`--quiet`。
* **图标。** `tools/make_icons.py` 从零画红色 `#C62828` M（图片）与蓝色
  `#1565C0` M（视频）的 PNG/ICO 一套。
* **查看器去掉叠加信息。** 屏幕上所有技术文字全部移除——没有帧号、帧率、
  gop、字节数。单张图片就是单张图片，窗口标题只有文件名。
* **文档。** `README.md`（英文）、`README.zh-CN.md`、`docs/FORMAT.md`、
  `docs/CONVERT.md`、`docs/BUILD.md`、`docs/PUBLISH.md`，凡描述行为处均双语。
* **发布工程。** `pyproject.toml`、`requirements.txt`、`.gitignore`、`LICENSE`（MIT）、
  `.github/workflows/release.yml`、`tools/make_zip.py`。

### 变更

* `info` 现在正确报告 `has_alpha=True`，不再静默扁平化。
* `--fps` 同时决定播放帧率，不只是抽帧率。
* 重打 `MTBViewer.exe`（29.4 MB），alpha、音频、8K 三个样本全部 exit code 0。

### 修复

* 奇数宽高不再导出损坏的 MP4（ffmpeg 调用里加了
  `scale=trunc(iw/2)*2:trunc(ih/2)*2`）。
* v1 流解码不再除一个不存在的 fps 字段。

### 实测（不是承诺）

* 7680×4320 q80：1.58 MB，PSNR 38.83 dB，编码 16.6 s，解码 18.0 s。
* 5.56 MB MP4 → 371.6 KB `.mtc`（其中音频 172.3 KB），导回 MP4 带声音。
* 1080×1080 RGBA → 128.7 KB `.mtb` → PNG，alpha 逐位相等。

## [1.1.0] — 2026-11-11

### 新增

* `MTC1` v1 容器：I/P 帧、`gop` 与自动场景切换检测（`SCENE_CUT_SAD = 24.0`）、完整解码。
* CLI 子命令 `encode`、`decode`、`open`、`video-encode`、`video-decode`、`video-info`。
* tkinter 查看器，空格暂停、Esc 关闭。

### 变更

* DCT 系数编码改为"按平面 × 按位置"的上下文模型，同质量下体积约小 8%。

## [1.0.0] — 2026-11-09

### 新增

* `MTB1` 容器：灰度 / YCoCg 4:4:4 / 4:2:0 有损模式（0–2），灰度与 RGB 无损模式（3–4）。
* 8×8 DCT、zig-zag、DC 预测、带自适应模型的算术编码器。
* 图片的 `encode` / `decode` / `info`。
* 首次基准：2048×2048 照片 350 KB，32.6 dB。
