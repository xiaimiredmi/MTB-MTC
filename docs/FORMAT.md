# MTC container format

Byte-level specification of the still-image container. Implemented by the Rust
codec in `rust/`; the Python encoder in `mtcodec/` writes version 1.

The video container (`MTC1`) and everything that produced `.mtb` were removed
from this repository; `.mtc` is the image format.

中文版在同一文件的下半部分。

---

## 1. MTC — still image

### 1.1 Header (12 bytes)

```text
struct "<4sBBBBHH"   (little endian)

offset  size  field    meaning
0       4     magic    b"MTB1"
4       1     version  1 or 2, see 1.5
5       1     mode     see 1.2
6       1     quality  1..100, the -q value that was used
7       1     flags    bit0 = FLAG_ALPHA, bit1 = FLAG_AQ, other bits reserved
8       2     width    pixels, 1..65535
10      2     height   pixels, 1..65535
```

A decoder must reject a version it does not know rather than guess. Version 1
and version 2 differ in the lossy payload only (1.5); the header, the modes and
the alpha segment are identical.

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

`alpha_payload` is a complete PNG file holding the 8-bit alpha plane at the
picture size. `main_payload` is one complete arithmetic-coded stream. A decoder
that does not need alpha can skip it entirely.

### 1.4 Lossy payload

* Planes come from `YCoCg` (`rgb_to_ycocg`, reversible integer transform).
* Each plane is padded to a multiple of 16 (4:2:0) or 8 (4:4:4 / gray) by
  replicating the edge; the padded size is recomputed from `width/height` by the
  decoder and never written.
* Blocks are 8×8 and stored row-major: `blk[y][x]` is row `y`, column `x`. The
  coefficient `[u][v]` therefore has `u` as the vertical frequency and `v` as the
  horizontal one. **Getting these two axes the wrong way round produces a stream
  that round-trips against itself and is unreadable by everyone else** — the
  original Rust port had that bug.
* Forward DCT is orthonormal, so the DC coefficient of the mean `m` block is
  `8*m`.
* The quantiser step for coefficient `[u][v]` is
  `(1 + 0.30 * (u² + v²)^0.575) * (0.85 + (100 - quality) * 0.40)`, multiplied
  by `1.35` on both chroma planes.
* Quantisation of version 2:

  ```text
  q = floor(|c| / step + 1 - t)      t = 0.65 for the AC coefficients
                                     t = 0.50 for the DC coefficient
  q carries the sign of c
  ```

  `t` is the half-width of the zero bin in units of a step; 0.5 is ordinary
  round-to-nearest. A decoder only sees `q`, so this is an encoder-side choice
  and needs no signalling.
* Coefficients are scanned zig-zag. `u + v = 0, 1, 2, …`, even diagonals
  descending, odd diagonals ascending.
* The DC coefficient is predicted from already-decoded neighbours: the block to
  the left on the first block row, and afterwards a median edge detector over
  the left, top and top-left quantised DC values. Only `dc - prediction` is
  coded.
* The `last` symbol (highest non-zero zig-zag index) is coded with an adaptive
  6-bit tree whose context is the previous block's `last` bucketed by 8
  (`last >> 3`, 0..7).
* Every other coefficient goes through the arithmetic coder with a per-plane,
  per-band context model: significance, magnitude class (bit length), sign and
  raw magnitude bits are separate adaptive models.

### 1.5 Version 1 versus version 2

Version 1 is what the Python encoder writes and what every file produced before
the Rust port contains. Version 2 is what the Rust encoder writes.

| | version 1 | version 2 |
| --- | --- | --- |
| quantisation | `round(c / step)` to nearest even | dead zone, `t = 0.65` AC / `0.50` DC |
| DC prediction | left block only, reset every block row | median edge detector over left/top/top-left |
| `last` context | none, one model per plane | previous block's `last`, 8 buckets |
| adaptive quantisation | never | flag `FLAG_AQ` in `flags` |

Both versions use the same arithmetic coder, the same zig-zag scan, the same
step table, the same YCoCg transform and the same alpha segment.

### 1.6 Adaptive quantisation (version 2 only)

Set `FLAG_AQ` in `flags` and the payload starts each group of two block rows
with one multiplier per tile, before any coefficient of those rows.

* A tile is 2×2 blocks, i.e. 16×16 plane pixels.
* There are seven multipliers, one per level:

  | level | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | multiplier | 0.70 | 0.80 | 0.90 | 1.00 | 1.12 | 1.25 | 1.40 |

* Tiles are visited in raster order per plane; the previous level starts at 3
  (neutral) on the first tile of each plane.
* Each level is coded as `delta = level - previous_level`, clamped to `[-3, 3]`,
  as a 3-bit adaptive tree over `delta + 3`. The context has two states: whether
  the previous delta was zero.
* The decoder reconstructs `level = clamp(previous_level + delta, 0, 6)`.
* The multiplier scales the step of coefficients with `u + v <= 5`; higher
  frequencies always use the base step.

An encoder is free to signal level 3 everywhere; that is a valid, slightly
larger stream.

### 1.7 Lossless payload

* Gray: the plane itself. RGB: reversible YCoCg, three planes.
* Each plane is coded with a left/up spatial predictor, residuals stored with the
  same arithmetic coder; clipping ranges are `[0,255]` for luma and `[-300,300]`
  for chroma.

The Rust codec does not implement this mode yet; it reports the mode as
unsupported instead of guessing.

### 1.8 Transparency rule

Before coding, any pixel with `alpha < 8` has its RGB set to 0. This kills the
colour fringing that semi-transparent edges otherwise produce, and costs
nothing visually because those pixels are invisible.

A decoded RGBA picture is `H×W×4`; without alpha it is `H×W×3` (`H×W` for gray).

### 1.9 Arithmetic coder

Binary arithmetic coder with 11-bit probabilities, an adaptation shift of 5 and
24-bit renormalisation, following the LZMA conventions: `bound = (range >> 11) *
p`, and a bit of 1 narrows `range` to `range - bound` and moves `low` up by
`bound`. Probabilities move towards 0 for a 1 (`p -= p >> 5`) and towards 2048
for a 0 (`p += (2048 - p) >> 5`). Five flush bytes terminate the stream.

### 1.10 Reading a file by hand

```python
import struct
data = open("x.mtc", "rb").read()
magic, version, mode, quality, flags, w, h = struct.unpack("<4sBBBBHH", data[:12])
print(magic, version, mode, quality, flags, w, h)
```

---

# 中文版

## 1. MTC —— 静态图片

容器格式的字节级说明。由 `rust/` 里的 Rust 编解码器实现；`mtcodec/` 里的
Python 编码器写的是版本 1。

视频容器（`MTC1`）以及所有产出 `.mtb` 的东西已经从仓库里删掉了，`.mtc`
就是图片格式。

### 1.1 头（12 字节）

```text
struct "<4sBBBBHH"   （小端）

偏移  长度  字段     含义
0     4     magic    b"MTB1"
4     1     version  1 或 2，见 1.5
5     1     mode     见 1.2
6     1     quality  1..100，编码时用的 -q
7     1     flags    bit0 = FLAG_ALPHA，bit1 = FLAG_AQ，其余保留
8     2     width    像素宽
10    2     height   像素高
```

解码器必须拒绝不认识的版本，不能靠猜。版本 1 和版本 2 只有有损数据段不同
（1.5），头、mode 和 alpha 段完全一样。

### 1.2 mode 取值

| 值 | 名称 | 数据段 |
| --- | --- | --- |
| 0 | 灰度有损 | 1 个平面，8×8 DCT |
| 1 | RGB444 有损 | 3 个平面（Y、Co、Cg），4:4:4 |
| 2 | RGB420 有损 | 3 个平面，Co/Cg 半分辨率 |
| 3 | 灰度无损 | 1 个平面，空间预测，不做 DCT |
| 4 | RGB 无损 | 3 个平面，可逆 YCoCg + 空间预测 |

alpha 不占 mode 编号，永远作为独立无损平面由 `flags` 标记，所以 RGBA 图可以
"RGB 有损、alpha 逐位精确"。

### 1.3 文件布局

```text
头（12 字节）
<I alpha_len> + alpha_payload      （仅当 FLAG_ALPHA）
main_payload
```

`alpha_payload` 是一个完整的 PNG 文件，装原图尺寸的 8 位 alpha 平面。
`main_payload` 是一整条算术编码流。不需要 alpha 的解码器可以整段跳过。

### 1.4 有损数据段

* 平面来自 YCoCg（`rgb_to_ycocg`，可逆整数变换）。
* 每平面按 16（4:2:0）或 8（4:4:4/灰度）对齐，边缘复制填充；填充尺寸由解码端
  按 `width/height` 重算，不写进文件。
* 8×8 块按行主序存放：`blk[y][x]` 是第 `y` 行第 `x` 列。于是系数 `[u][v]`
  的 `u` 是竖直频率、`v` 是水平频率。**这两个轴弄反的话，码流自己编自己解
  一点问题都没有，但别人全都读不了**——Rust 移植的第一版就踩了这个坑。
* 正变换是正交的，所以均值为 `m` 的块，直流系数等于 `8*m`。
* 系数 `[u][v]` 的量化步长是
  `(1 + 0.30 * (u² + v²)^0.575) * (0.85 + (100 - quality) * 0.40)`，两个色度
  平面再乘 `1.35`。
* 版本 2 的量化：

  ```text
  q = floor(|c| / step + 1 - t)      t = 0.65（交流系数）
                                     t = 0.50（直流系数）
  q 取 c 的符号
  ```

  `t` 是以步长为单位的零区半宽，0.5 就是普通的四舍五入。解码端只看得到 `q`，
  所以这是编码端的自由选择，不需要任何信令。
* 系数按 zig-zag 扫描：`u + v = 0, 1, 2, …`，偶对角线向下、奇对角线向上。
* 直流系数用已经解出来的邻居预测：第一块行用左边块，之后用左、上、左上三个
  量化直流值做中值边缘检测（MED）。码流里只放 `dc - 预测值`。
* `last`（最后一个非零的 zig-zag 下标）走自适应 6 位树，上下文取前一块的
  `last` 除以 8（`last >> 3`，0..7）。
* 其余每个系数都进算术编码器，上下文按"平面 × 频带"分开：显著性、幅度类别
  （比特长度）、符号、幅度原始位各用一套自适应模型。

### 1.5 版本 1 与版本 2

版本 1 是 Python 编码器写的，也是 Rust 移植之前所有文件的内容；版本 2 是
Rust 编码器写的。

| | 版本 1 | 版本 2 |
| --- | --- | --- |
| 量化 | `round(c / step)`，四舍六入五取偶 | 零区，`t = 0.65`（交流）/ `0.50`（直流） |
| 直流预测 | 只用左边块，每块行重置 | 左/上/左上做中值边缘检测 |
| `last` 上下文 | 没有，每平面一套模型 | 前一块的 `last`，8 个桶 |
| 自适应量化 | 从不 | `flags` 里的 `FLAG_AQ` |

两个版本共用同一个算术编码器、同一张 zig-zag 表、同一张量化步长表、同一个
YCoCg 变换和同一段 alpha。

### 1.6 自适应量化（仅版本 2）

在 `flags` 里置 `FLAG_AQ`，数据段就会在每两行块之前先给每个瓦片一个量化
倍率。

* 一个瓦片是 2×2 个块，也就是 16×16 个平面像素。
* 倍率共七档：

  | 档位 | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | 倍率 | 0.70 | 0.80 | 0.90 | 1.00 | 1.12 | 1.25 | 1.40 |

* 每个平面内瓦片按光栅顺序走；每个平面的第一个瓦片的前一档取 3（中性）。
* 每档编成 `delta = 当前档 - 前一档`，夹到 `[-3, 3]`，再作为 `delta + 3` 走
  自适应 3 位树。上下文两个状态：上一个 delta 是不是 0。
* 解码端重建 `档位 = clamp(前一档 + delta, 0, 6)`。
* 倍率只作用于 `u + v <= 5` 的系数，更高的频率永远用基础步长。

编码器可以一路只发第 3 档，那同样合法，只是文件略大。

### 1.7 无损数据段

* 灰度：平面本身；RGB：可逆 YCoCg 三个平面。
* 每平面用左/上空间预测，残差走同一个算术编码器；裁剪范围亮度是 `[0,255]`，
  色度是 `[-300,300]`。

Rust 编解码器还没实现这个模式，遇到它会明确报"不支持"，而不是硬猜。

### 1.8 透明规则

编码前把 `alpha < 8` 的像素 RGB 置 0。这样能消掉半透明边缘的脏色，而这些像素
本来就看不见，视觉上零代价。

解出来的图有 alpha 就是 `H×W×4`，没有就是 `H×W×3`（灰度是 `H×W`）。

### 1.9 算术编码器

二进制算术编码器，11 位概率、5 位自适应、24 位重归一化，沿用 LZMA 的写法：
`bound = (range >> 11) * p`，编码 1 时 `range -= bound` 且 `low += bound`。
概率在编 1 时向 0 靠（`p -= p >> 5`），编 0 时向 2048 靠
（`p += (2048 - p) >> 5`）。结尾补 5 个字节。

### 1.10 手动读一个文件

```python
import struct
data = open("x.mtc", "rb").read()
magic, version, mode, quality, flags, w, h = struct.unpack("<4sBBBBHH", data[:12])
print(magic, version, mode, quality, flags, w, h)
```
