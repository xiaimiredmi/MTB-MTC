# Conversion guide

How to get files **into** MTB/MTC and **back out** again, with every flag,
the recommended combinations, and the errors you will actually hit.
中文版在下半部分。

---

## 1. Decide what you want first

| You have | You want | Command |
| --- | --- | --- |
| a photo, screenshot, wallpaper | one still image | `convert … .mtb` |
| a transparent PNG | keep the transparency | `convert … .mtb` (alpha is automatic) |
| a GIF / APNG | keep the motion | `convert … .mtc` |
| a GIF / APNG | just the first frame | `convert … .mtb` (warns, keeps frame 0) |
| an MP4/MOV/MKV | a compact, self-describing sample | `convert … .mtc` |
| an MP4/MOV/MKV | the same clip with sound | `convert … .mtc` (audio on by default) |
| a `.mtb` | a PNG/JPG for sharing | `export … .png` / `.jpg` |
| a `.mtc` | an MP4 that plays anywhere | `export … .mp4` |
| a whole folder | all of it | `tools/batch_convert.py` |

---

## 2. Images → `.mtb`

```bash
python -m mtcodec convert in.png out.mtb
python -m mtcodec convert in.png out.mtb -q 80 --size 1080p
python -m mtcodec convert in.png out.mtb -q 92 -s 444
python -m mtcodec convert in.png out.mtb --lossless
```

What happens inside:

1. Pillow opens the file (all frames are read for GIF/APNG).
2. Mode is inspected: `RGBA` / `LA` / `P`+transparency become alpha +
   RGB(A); everything else is converted to RGB or gray.
3. If `--size` is given, the frame is fitted into the box (no stretching,
   portrait sizes are swapped).
4. Pixels with `alpha < 8` get RGB = 0.
5. Encode, write the header, then the alpha stream (if any), then the main stream.

Notes:

* `.mtb` holds **one** frame. Feeding an animation prints
  `note: animated / video input has N frames, MTB keeps the first frame`.
* `--lossless` ignores `-q` and `-s` (mode 3/4 has no quantiser).
* JPG is fine as input; there is no extra loss beyond the JPEG you already have
  minus your own `-q`. Going PNG → MTB is the cleaner path.

---

## 3. Video → `.mtc`

```bash
python -m mtcodec convert clip.mp4 clip.mtc
python -m mtcodec convert clip.mp4 clip.mtc --size 720p --fps 12 --max-frames 24
python -m mtcodec convert clip.mp4 clip.mtc --start 3.5 --fps 24 --max-frames 48 --gop 0
python -m mtcodec convert clip.mp4 clip.mtc --no-audio
```

Inside:

1. `ffprobe`-free probing via ffmpeg to get width, height, duration.
2. Frames are streamed through a rawvideo pipe:
   `-vf fps=<fps>,scale=W:H:flags=lanczos` — so decoding never holds the whole clip.
3. Audio: `-vn -ac 2 -ar 44100 -f wav`, trimmed to `max_frames / fps` seconds.
4. Frames are encoded as I/P; audio is appended after the header.

Frame budget: `stored_seconds = max_frames / fps`. Defaults give 2 s at 12 fps.
Increasing `--fps` without raising `--max-frames` just shortens the clip.

---

## 4. Back out

```bash
python -m mtcodec export in.mtb out.png      # alpha preserved
python -m mtcodec export in.mtb out.webp
python -m mtcodec export in.mtb out.jpg      # alpha composited on white
python -m mtcodec export in.mtc out.mp4      # H.264 + AAC, audio included
python -m mtcodec export in.mtc outdir/      # PNG sequence + audio.wav
```

MP4 export goes through a temporary PNG sequence and the embedded WAV, then
ffmpeg with `libx264` + `aac`; the scale filter is
`scale=trunc(iw/2)*2:trunc(ih/2)*2` so odd sizes do not break H.264.

---

## 5. Flag reference

| Flag | Values | Default | Effect |
| --- | --- | --- | --- |
| `-q`, `--quality` | 1..100 | 80 (`convert`), 85 (`encode`/`video-encode`) | quantiser step |
| `-s`, `--subsample` | `420`, `444` | `420` | chroma resolution |
| `--lossless` | flag | off | images only, byte-exact |
| `--size` | preset or `WxH` | source | fit into box |
| `--fps` | float | 12 | sample rate = playback rate |
| `--gop` | int | 12 | I-frame spacing, 0 = all intra |
| `--max-frames` | int | 24 | stored frame cap |
| `--start` | float seconds | 0 | start offset |
| `--no-audio` | flag | off | skip audio |

Recommended presets:

| Goal | Settings |
| --- | --- |
| smallest file | `-q 60 -s 420 --size 480p` |
| balanced (default) | `-q 80 -s 420 --size 1080p` |
| good for photos with gradients | `-q 90 -s 444` |
| must be identical | `--lossless` |
| video you can scrub | `--gop 0` |
| very short clip, more frames | `--fps 24 --max-frames 48` |

---

## 6. Batch conversion

```bash
python tools/batch_convert.py <folder> --out <folder> [-q 80] [--size 1080p]
python tools/batch_convert.py <folder> --export --out <folder>   # reverse
```

* Scans only the top level (no recursion), skips non-media files.
* Output names keep the stem: `a.png` → `a.mtb`, `b.mp4` → `b.mtc`.
* `--overwrite` replaces existing outputs; otherwise they are skipped.
* One failing file does not stop the run; the exit code is 1 if anything failed.
* The reverse mode sniffs the magic (`MTB1` → `.png`, otherwise `.mp4`).

---

## 7. Python API

```python
import mtcodec
from mtcodec import io_bridge

# single image
frames, has_alpha, src = io_bridge.load_image_frames("a.png", "1080p")
blob = mtcodec.encode_image(frames[0], quality=80, subsample="420")
open("a.mtb", "wb").write(blob)

# video with audio
frames, src = io_bridge.load_video_frames("a.mp4", fps=12, size_spec="720p",
                                          max_frames=24, start=0)
audio = io_bridge.load_audio_wav("a.mp4", seconds=2.0)
open("a.mtc", "wb").write(mtcodec.encode_video(frames, quality=80, fps=12, audio=audio))

# read back
back, stats = mtcodec.decode_video(open("a.mtc", "rb").read())
io_bridge.export_mp4(back, "a_back.mp4", fps=12, wav_bytes=audio_from_collect)
```

`decode_video(..., collect=got)` fills `got["audio"]` and `got["fps"]`;
that is exactly what `export … .mp4` uses.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ffmpeg not found` | no ffmpeg on PATH | `pip install imageio-ffmpeg`, or put ffmpeg on PATH |
| `unsupported input type: .heic` | Pillow cannot read HEIC | convert to JPG first |
| JPEG export looks flat | alpha composited on white | expected; export PNG if you need the cut-out |
| `not an MTB stream` | wrong magic | file is not `.mtb`, or truncated |
| video plays too fast | fps in header differs from capture fps | re-encode with a matching `--fps` |
| 8K takes a minute | pure-Python coder | lower `--size`, or accept it |
| sound missing on Linux/macOS | winsound is Windows-only | picture only, by design |
| `mtb` from an APNG is static | MTB stores one frame | use `.mtc` for motion |

---

# 中文版

## 1. 先想清楚要什么

| 手上有什么 | 想要什么 | 命令 |
| --- | --- | --- |
| 照片、截图、壁纸 | 一张静态图 | `convert … .mtb` |
| 带透明的 PNG | 保住透明 | `convert … .mtb`（自动） |
| GIF / APNG | 保住动 | `convert … .mtc` |
| GIF / APNG | 只要第一帧 | `convert … .mtb`（会提示，保存第 0 帧） |
| MP4/MOV/MKV | 体积小、自带描述的样本 | `convert … .mtc` |
| MP4/MOV/MKV | 带声音的同一段 | `convert … .mtc`（默认带音轨） |
| `.mtb` | 能分享的 PNG/JPG | `export … .png` / `.jpg` |
| `.mtc` | 到处都能播的 MP4 | `export … .mp4` |
| 一整个目录 | 全都要 | `tools/batch_convert.py` |

## 2. 图片 → `.mtb`

```bash
python -m mtcodec convert 输入.png 输出.mtb
python -m mtcodec convert 输入.png 输出.mtb -q 80 --size 1080p
python -m mtcodec convert 输入.png 输出.mtb -q 92 -s 444
python -m mtcodec convert 输入.png 输出.mtb --lossless
```

内部做了这几步：

1. Pillow 打开文件（GIF/APNG 会把所有帧读出来）。
2. 判断模式：`RGBA` / `LA` / 带透明的 `P` 走 alpha + RGB；其余转 RGB 或灰度。
3. 有 `--size` 就等比装进框里（不拉伸，竖图自动对调宽高）。
4. `alpha < 8` 的像素 RGB 置 0。
5. 编码、写头、有 alpha 就写 alpha 流，再写主数据流。

要点：

* `.mtb` 只存**一帧**。喂动图会提示
  `note: animated / video input has N frames, MTB keeps the first frame`。
* `--lossless` 会忽略 `-q` 和 `-s`（mode 3/4 没有量化器）。
* JPG 也能当输入，但那是"在已有 JPEG 损失上再压一次"，PNG → MTB 更干净。

## 3. 视频 → `.mtc`

```bash
python -m mtcodec convert 片子.mp4 片子.mtc
python -m mtcodec convert 片子.mp4 片子.mtc --size 720p --fps 12 --max-frames 24
python -m mtcodec convert 片子.mp4 片子.mtc --start 3.5 --fps 24 --max-frames 48 --gop 0
python -m mtcodec convert 片子.mp4 片子.mtc --no-audio
```

内部：

1. 用 ffmpeg 探宽高与时长。
2. 帧通过 rawvideo 管道逐帧读：
   `-vf fps=<fps>,scale=W:H:flags=lanczos`，不会把整段视频读进内存。
3. 音频：`-vn -ac 2 -ar 44100 -f wav`，截到 `max_frames / fps` 秒。
4. 帧编码成 I/P；音频接在头后面。

存多少内容 = `max_frames / fps` 秒。默认是 12 fps 存 2 秒。
只加 `--fps` 不加 `--max-frames` 只会让存的内容变短。

## 4. 导回主流格式

```bash
python -m mtcodec export 输入.mtb 输出.png      # 透明保留
python -m mtcodec export 输入.mtb 输出.webp
python -m mtcodec export 输入.mtb 输出.jpg      # 透明合到白底
python -m mtcodec export 输入.mtc 输出.mp4      # H.264 + AAC，带音轨
python -m mtcodec export 输入.mtc 帧目录/        # PNG 序列 + audio.wav
```

MP4 导出的做法是：解码成临时 PNG 序列 + 内嵌 WAV，交给 ffmpeg 的
`libx264` + `aac`，缩放滤镜写成 `scale=trunc(iw/2)*2:trunc(ih/2)*2`，
保证奇数尺寸也不会让 H.264 报错。

## 5. 参数速查

| 参数 | 取值 | 默认 | 作用 |
| --- | --- | --- | --- |
| `-q/--quality` | 1..100 | 80（`convert`）/ 85（`encode`） | 量化步长 |
| `-s/--subsample` | `420`、`444` | `420` | 色度分辨率 |
| `--lossless` | 开关 | 关 | 仅图片，逐像素一致 |
| `--size` | 预设或 `WxH` | 原尺寸 | 装进框里 |
| `--fps` | 浮点 | 12 | 抽帧率 = 播放帧率 |
| `--gop` | 整数 | 12 | I 帧间隔，0 = 全帧内 |
| `--max-frames` | 整数 | 24 | 存帧上限 |
| `--start` | 秒 | 0 | 起始偏移 |
| `--no-audio` | 开关 | 关 | 不写音频段 |

推荐组合：

| 目标 | 参数 |
| --- | --- |
| 体积最小 | `-q 60 -s 420 --size 480p` |
| 平衡（默认） | `-q 80 -s 420 --size 1080p` |
| 渐变多的照片 | `-q 90 -s 444` |
| 必须一模一样 | `--lossless` |
| 视频要能随便拖 | `--gop 0` |
| 短片要多存几帧 | `--fps 24 --max-frames 48` |

## 6. 批量转换

```bash
python tools/batch_convert.py <目录> --out <目录> [-q 80] [--size 1080p]
python tools/batch_convert.py <目录> --export --out <目录>   # 反向
```

* 只扫当前一层，不递归；非媒体文件跳过。
* 输出保持主文件名：`a.png` → `a.mtb`，`b.mp4` → `b.mtc`。
* `--overwrite` 覆盖已有输出，否则跳过。
* 单个文件失败不会中断整批；有失败时退出码为 1。
* 反向模式按魔数判断：`MTB1` → `.png`，其余 → `.mp4`。

## 7. Python 接口

```python
import mtcodec
from mtcodec import io_bridge

# 单张图
frames, has_alpha, src = io_bridge.load_image_frames("a.png", "1080p")
blob = mtcodec.encode_image(frames[0], quality=80, subsample="420")
open("a.mtb", "wb").write(blob)

# 带音轨的视频
frames, src = io_bridge.load_video_frames("a.mp4", fps=12, size_spec="720p",
                                          max_frames=24, start=0)
audio = io_bridge.load_audio_wav("a.mp4", seconds=2.0)
open("a.mtc", "wb").write(mtcodec.encode_video(frames, quality=80, fps=12, audio=audio))

# 读回来
back, stats = mtcodec.decode_video(open("a.mtc", "rb").read(), collect=got)
```

`decode_video(..., collect=got)` 会把音频写进 `got["audio"]`、帧率写进
`got["fps"]`，`export … .mp4` 用的就是它。

## 8. 常见故障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `ffmpeg not found` | PATH 里没有 ffmpeg | `pip install imageio-ffmpeg` 或装到 PATH |
| `unsupported input type: .heic` | Pillow 读不了 HEIC | 先转成 JPG |
| 导出的 JPEG 一片平 | 透明被合到白底 | 正常；要抠图就导 PNG |
| `not an MTB stream` | 魔数不对 | 不是 `.mtb`，或文件被截断 |
| 视频播得太快 | 头里的 fps 与实际抽帧不符 | 用匹配的 `--fps` 重转 |
| 8K 要一分钟 | 纯 Python 编码器 | 降 `--size`，或者接受它 |
| Linux/macOS 没声音 | winsound 是 Windows 专有 | 只有画面，这是设计 |
| APNG 转 MTB 变成静态 | MTB 只存一帧 | 要动就转 `.mtc` |
