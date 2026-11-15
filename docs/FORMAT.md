# MTB / MTC container format

Byte-level specification. Everything here is implemented in
`mtcodec/image_codec.py` and `mtcodec/video_codec.py`.
中文版在同一文件的下半部分。

---

## 1. MTB — still image

### 1.1 Header (12 bytes)

```text
struct "<4sBBBBHH"   (little endian)

offset  size  field    meaning
0       4     magic    b"MTB1"
4       1     version  always 1
5       1     mode     see 1.2
6       1     quality  1..100, the -q value that was used
7       1     flags    bit0 = FLAG_ALPHA (alpha plane present), other bits reserved
8       2     width    pixels, 1..65535
10      2     height   pixels, 1..65535
```

### 1.2 Mode

| value | name | payload |
| --- | --- | --- |
| 0 | MODE_GRAY_LOSSY | 1 plane, 8×8 DCT |
| 1 | MODE_RGB444_LOSSY | 3 planes (Y, Co, Cg), 4:4:4 |
| 2 | MODE_RGB420_LOSSY | 3 planes, Co/Cg half resolution |
| 3 | MODE_GRAY_LOSSLESS | 1 plane, spatial prediction, no DCT |
| 4 | MODE_RGB_LOSSLESS | 3 planes, spatial prediction, YCoCg reversible |

Alpha never uses a mode number; it always travels as a separate lossless plane
flagged in `flags`, so an RGBA image can still be lossy for RGB while alpha stays
byte-exact.

### 1.3 File layout

```text
+-----------------------------+
| header (12 bytes)           |
+-----------------------------+
| <I alpha_len>  (only if FLAG_ALPHA) |
| alpha_payload  (alpha_len bytes)    |
+-----------------------------+
| main payload                |
+-----------------------------+
```

`alpha_payload` and `main_payload` are each one complete arithmetic-coded stream,
so a decoder can skip alpha entirely if it does not need it.

### 1.4 Lossy payload

* Planes come from `YCoCg` (`color.rgb_to_ycocg`, reversible integer transform).
* Each plane is padded to a multiple of 16 (4:2:0) or 8 (4:4:4 / gray) by replicating
  the edge; the padded size is recomputed from `width/height` by the decoder.
* Blocks are 8×8, forward DCT, then divided by the quantiser step and rounded.
* Coefficients are reordered zig-zag; the DC coefficient of the previous block
  in the same row is used as predictor.
* Chroma planes use `step * 1.35` so chroma is quantised slightly harder.
* Every coefficient goes through the arithmetic coder with a per-plane,
  per-coefficient-position context model.
* `quality` maps to a quantiser step through `transform.quality_scale()` /
  `tf.step_table()`; larger quality = smaller step = bigger file.

### 1.5 Lossless payload

* Gray: the plane itself. RGB: reversible YCoCg, three planes.
* Each plane is coded with a left/up spatial predictor, residuals stored with the
  same arithmetic coder; clipping ranges come from `color.CLIP`.

### 1.6 Transparency rule

Before coding, any pixel with `alpha < 8` has its RGB set to 0. Alpha itself is
coded losslessly. This kills the colour fringing that semi-transparent edges
otherwise produce, and costs nothing visually because those pixels are invisible.

`decode_image` returns `H×W×4` when alpha is present, otherwise `H×W×3`
(or `H×W` for gray).

---

## 2. MTC — video

### 2.1 Header

Two layouts exist. Both start with the same magic.

```text
v1: struct "<4sBBBBHHI"  (16 bytes)
    0 4 magic b"MTC1", 4 1 version=1, 5 1 flag420, 6 1 quality,
    7 1 gop, 8 2 width, 10 2 height, 12 4 nframes
    (no audio, no fps — playback assumes 24 fps)

v2: struct "<4sBBBBHHII" (20 bytes)
    0 4 magic, 4 1 version=2, 5 1 flag420, 6 1 quality, 7 1 gop,
    8 2 width, 10 2 height, 12 4 nframes, 16 4 fps × 100
    followed by  <I audio_len> + audio bytes (WAV, 44.1 kHz stereo PCM)
```

`fps × 100` keeps 12.50 fps and 23.976 fps representable without floats in the
header. v1 files still decode; the viewer falls back to 24 fps and no audio.

### 2.2 File layout (v2)

```text
header (20 bytes)
+I audio_len
audio (WAV bytes, may be 0)
frame 0: <BI ftype, size> + payload
frame 1: <BI ftype, size> + payload
...
frame n-1
```

`ftype` is 0 for an I frame, 1 for a P frame. `size` is the payload length in bytes.

### 2.3 Frames

* I frame: independent, same DCT + arithmetic scheme as a single MTB plane set,
  but grayscale-free (always 3 planes).
* P frame: each plane is quantised on the difference against the previous
  reconstructed frame (`_quantize(plane, step, pred)`), predicted blocks are
  flagged per block with a `ModeModel` so skipped blocks cost almost nothing.
* `gop = 0` means every frame is intra. Otherwise a frame becomes intra when
  `idx % gop != 0` fails, and also when the mean absolute difference of the Y plane
  against the reference exceeds `SCENE_CUT_SAD = 24.0` (automatic scene cut).
* No motion vectors: P frames use a zero-motion predictor. Simple on purpose.

### 2.4 Audio

The audio segment is a complete RIFF/WAVE byte string extracted by ffmpeg
(`-vn -ac 2 -ar 44100 -f wav`), stored verbatim. No re-encoding, no container
fragmentation, no per-frame sync. Length is `--max-frames / --fps` seconds.

---

## 3. Reading a file by hand

```python
import struct
data = open("x.mtc", "rb").read()
print(data[:4])                                  # b'MTC1'
print(struct.unpack("<4sBBBBHHII", data[:24]))   # full v2 header
```

---

# 中文版

## 1. MTB —— 静态图片

### 1.1 头（12 字节）

```text
struct "<4sBBBBHH"   （小端）

偏移  长度  字段     含义
0     4     magic    b"MTB1"
4     1     version  固定 1
5     1     mode     见 1.2
6     1     quality  1..100，编码时用的 -q
7     1     flags    bit0 = FLAG_ALPHA（有 alpha 平面），其余位保留
8     2     width    像素宽
10    2     height   像素高
```

### 1.2 mode 取值

| 值 | 名称 | 数据段 |
| --- | --- | --- |
| 0 | 灰度有损 | 1 个平面，8×8 DCT |
| 1 | RGB444 有损 | 3 个平面（Y、Co、Cg），4:4:4 |
| 2 | RGB420 有损 | 3 个平面，Co/Cg 半分辨率 |
| 3 | 灰度无损 | 1 个平面，空间预测，不做 DCT |
| 4 | RGB 无损 | 3 个平面，可逆 YCoCg + 空间预测 |

alpha 不占 mode 编号，永远作为独立无损平面跟在头后面、由 flags 标记。
所以 RGBA 图可以"RGB 有损、alpha 逐位精确"。

### 1.3 文件布局

```text
头（12 字节）
<I alpha_len> + alpha_payload      （仅当 FLAG_ALPHA）
main_payload
```

两段各自是一个完整的算术编码流，解码器可以整体跳过 alpha。

### 1.4 有损数据段

* 平面来自 YCoCg（`color.rgb_to_ycocg`，可逆整数变换）。
* 每平面按 16（4:2:0）或 8（4:4:4/灰度）对齐，边缘复制填充；解码端按
  `width/height` 重算填充尺寸，不写入文件。
* 8×8 块做正变换，再除量化步长后取整。
* 系数按 zig-zag 重排；同行前一块的 DC 作为预测值。
* 色度平面的步长乘 1.35，色度压得更狠一点。
* 每个系数都进算术编码器，上下文模型按"平面 × 系数位置"分开。
* `quality` 通过 `transform.quality_scale()` / `tf.step_table()` 映射成步长，
  quality 越大步长越小、文件越大。

### 1.5 无损数据段

* 灰度：平面本身；RGB：可逆 YCoCg 三个平面。
* 每平面用左/上空间预测，残差走同一个算术编码器，裁剪范围来自 `color.CLIP`。

### 1.6 透明规则

编码前把 `alpha < 8` 的像素 RGB 置 0，alpha 本身无损编码。这样能消掉半透明
边缘的脏色，而这些像素本来就看不见，视觉上零代价。

`decode_image` 在有 alpha 时返回 `H×W×4`，否则返回 `H×W×3`（灰度是 `H×W`）。

## 2. MTC —— 视频

### 2.1 头

两套布局，魔数相同。

```text
v1: struct "<4sBBBBHHI"（16 字节）
    magic、version=1、flag420、quality、gop、width、height、nframes
    （没有音频、没有帧率，播放时按 24 fps 处理）

v2: struct "<4sBBBBHHII"（20 字节）
    magic、version=2、flag420、quality、gop、width、height、nframes、fps×100
    后面紧跟 <I audio_len> + 音频字节（WAV，44.1 kHz 立体声 PCM）
```

`fps × 100` 让 12.50、23.976 这类帧率在头里用整数表示，不必引入浮点。
v1 文件仍能解码：播放器退到 24 fps、无音频。

### 2.2 文件布局（v2）

```text
头（20 字节）
+I audio_len
音频（WAV 字节，可为 0 字节）
帧 0：<BI ftype, size> + payload
帧 1：…
```

`ftype` 为 0 是 I 帧，1 是 P 帧；`size` 是该帧 payload 的字节数。

### 2.3 帧

* I 帧：独立可解，和 MTB 的平面组合同一套 DCT + 算术编码，只是固定 3 个平面。
* P 帧：每个平面都按"与上一帧重建结果的差"量化，预测块用 `ModeModel`
  逐块标记，"跳过块"几乎不占字节。
* `gop = 0` 表示全帧内；否则每 `gop` 帧强制一个 I 帧，另外当 Y 平面的平均
  绝对差超过 `SCENE_CUT_SAD = 24.0` 时自动切 I 帧（场景切换）。
* 没有运动矢量：P 帧是零运动预测，故意做简单。

### 2.4 音频

音频段是 ffmpeg 用 `-vn -ac 2 -ar 44100 -f wav` 抽出来的完整 RIFF/WAVE 字节，
原样存进去：不重编码、不切片、不做逐帧同步。长度是
`--max-frames / --fps` 秒。

## 3. 手动读一个文件

```python
import struct
data = open("x.mtc", "rb").read()
print(data[:4])                                  # b'MTC1'
print(struct.unpack("<4sBBBBHHII", data[:24]))   # v2 完整头
```
