# MTB / MTC —— 纯 Python 图像与视频编码器

一套自带容器格式的纯 Python 编解码器：`.mtb` 存静态图片，`.mtc` 存短视频。
带 Tk 查看器、命令行工具，以及可选的 Windows 单文件程序。没有 C 扩展、
不需要编译器，只有 `numpy` + `Pillow`，所以同一份代码在 Windows、Linux、
macOS 上都能跑（只要装了 Python）。

> English version: [README.md](README.md)

---

## 它是什么

| | 静态图片 | 视频 |
| --- | --- | --- |
| 扩展名 | `.mtb` | `.mtc` |
| 魔数 | `MTB1` | `MTC1` |
| 容器版本 | 1 | 2 |
| 色彩 | 灰度 / YCoCg 4:4:4 / 4:2:0 / 无损 | YCoCg 4:2:0 或 4:4:4 |
| 透明 | alpha 平面，无损，逐位一致 | 不支持 |
| 音频 | — | 内嵌 WAV（44.1 kHz 立体声 PCM） |
| 帧率 | — | 存在头里（`fps × 100`） |
| 内核 | 8×8 DCT + 算术编码 | 8×8 DCT + I/P 帧 + 算术编码 |

这个项目不打算打赢 JPEG 或 H.264。它的意义是：一个下午就能从头读到尾的
编解码器，同时保住透明和声音，并且随时能转回普通格式。

---

## 安装

```bash
git clone <你的仓库地址>
cd MTB-MTC
pip install -r requirements.txt        # numpy + pillow
```

视频导入/导出还需要 ffmpeg（装到 PATH 即可；没有的话会自动退到
`imageio-ffmpeg`）：

```bash
pip install imageio-ffmpeg
```

想直接用 `mtcodec` 命令，做一次可编辑安装：

```bash
pip install -e .
mtcodec --help
```

---

## 快速开始

```bash
# 看：窗口里只有画面，没有任何帧率/码率之类的指标
python -m mtcodec open samples/photo_c.mtb
python -m mtcodec open samples/mtc_audio.mtc

# 查头
python -m mtcodec info samples/photo_c.mtb
python -m mtcodec video-info samples/mtc_audio.mtc
```

上面两条命令的真实输出：

```text
{'magic': 'MTB1', 'version': 1, 'mode': 2, 'quality': 80, 'has_alpha': False,
 'width': 512, 'height': 512, 'bytes': 46921}

{'magic': 'MTC1', 'version': 2, 'subsample_420': True, 'quality': 80, 'gop': 12,
 'width': 720, 'height': 1280, 'frames': 12, 'fps': 12.0, 'has_audio': True,
 'audio_bytes': 176478, 'bytes': 298280}
```

---

## 主流格式互转（重点）

`convert` 是"进"（主流格式 → MTB/MTC），`export` 是"出"（MTB/MTC → 主流格式）。
输出什么格式由你写的扩展名决定，不猜。

### 图片 → `.mtb`

```bash
python -m mtcodec convert 照片.png 照片.mtb -q 80
python -m mtcodec convert 照片.png 照片.mtb --size 1080p
python -m mtcodec convert 透明图.png 透明图.mtb -q 85      # 透明保留
python -m mtcodec convert 照片.png 照片.mtb --lossless     # 逐像素一致
```

支持的输入：PNG、JPG、JPEG、BMP、WEBP、TIF、GIF、APNG。

### 视频 → `.mtc`

```bash
python -m mtcodec convert 片子.mp4 片子.mtc
python -m mtcodec convert 片子.mp4 片子.mtc --size 720p --fps 12 --max-frames 24
python -m mtcodec convert 片子.mp4 片子.mtc --start 5 --max-frames 48 --gop 0
python -m mtcodec convert 片子.mp4 片子.mtc --no-audio
```

支持的输入：ffmpeg 能解的一切（MP4、MOV、MKV、AVI、WEBM、M4V…）。
音轨会被解成 44.1 kHz 立体声 PCM 塞进容器，所以导出的 MP4 是有声音的。

### 回到主流格式

```bash
python -m mtcodec export 照片.mtb 照片.png        # 透明保留
python -m mtcodec export 照片.mtb 照片.jpg        # 透明合到白底
python -m mtcodec export 片子.mtc 片子.mp4        # H.264 + AAC，带音轨
python -m mtcodec export 片子.mtc 帧目录/          # PNG 序列 + audio.wav
```

### 批量转换

```bash
# 整个目录：图片和视频一起扫，全部转成 .mtb / .mtc
python tools/batch_convert.py D:/图片 --out D:/图片/converted -q 80

# 反向导回
python tools/batch_convert.py D:/图片/converted --export --out D:/图片/back
```

批量工具每个文件打印一行，单个失败不影响整批，有失败时退出码非 0。

---

## 尺寸预设

| 预设 | 输出 | 预设 | 输出 |
| --- | --- | --- | --- |
| `360p` | 640×360 | `1080p` | 1920×1080 |
| `480p` | 854×480 | `1440p` | 2560×1440 |
| `540p` | 960×540 | `2k` | 2560×1440 |
| `720p` | 1280×720 | `4k` | 3840×2160 |
| `4x4k` | 7680×4320 | `8k` | 7680×4320 |

* 也可以写具体尺寸：`--size 1920x1080`
* 等比缩放到框内，不拉伸
* 竖图自动对调宽高：1080×1920 的图写 `--size 1080p` 仍然得到 1080×1920，不会被转成横图

### 实测代价（单线程、纯 Python、q80）

| 目标 | 尺寸 | 体积 | 压缩比 | PSNR | 编码 |
| --- | --- | --- | --- | --- | --- |
| 360p | 360×360 | 27.1 KB | 14.0 : 1 | 26.61 dB | 0.21 s |
| 720p | 720×720 | 77.5 KB | 19.6 : 1 | 28.73 dB | 0.61 s |
| 1080p | 1080×1080 | 143.4 KB | 23.8 : 1 | 30.04 dB | 1.18 s |
| 原尺寸 | 2048×2048 | 350.3 KB | 35.1 : 1 | 32.60 dB | 3.16 s |
| 4K | 2160×2160 | 370.9 KB | 36.9 : 1 | 33.08 dB | 3.39 s |
| 4 倍 4K | 7680×4320 | 1.58 MB | 61.4 : 1 | 38.83 dB | 16.6 s（解码 18.0 s） |

放大档的 PSNR 更高，是因为画面被放大后更平滑，不代表画质更好。
跨尺寸比 PSNR 没有意义。

---

## 压缩参数

| 参数 | 作用范围 | 默认 | 含义 |
| --- | --- | --- | --- |
| `-q/--quality` | 图 + 视频 | 80（`convert`）/ 85（`encode`） | 量化步长；越大越清晰也越大 |
| `-s/--subsample` | 图 + 视频 | `420` | `444` 保留全色度，体积大约多 30% |
| `--lossless` | 图片 | 关 | RGB 无损模式，往返逐像素一致 |
| `--gop` | 视频 | 12 | I 帧间隔；`0` 表示全帧内，可随意跳转但更大 |
| `--fps` | 视频 | 12 | 每秒抽几帧，同时决定播放帧率 |
| `--max-frames` | 视频 | 24 | 存帧数硬上限 |
| `--start` | 视频 | 0 | 从第几秒开始抽 |
| `--no-audio` | 视频 | 关 | 不写入音频段 |

`--fps` 和 `--max-frames` 一起决定存了多少内容：
`--fps 12 --max-frames 24` 覆盖前两秒。`.mtc` 是给实验和归档用的存储格式，
不是 MP4 的替代品。

---

## Python 接口

```python
import mtcodec

blob = mtcodec.encode_image(img, quality=80, subsample="420")   # RGBA 或 RGB
img2 = mtcodec.decode_image(blob)                                # 有 alpha 则返回 RGBA

frames = mtcodec.encode_video([f0, f1, f2], quality=80, gop=12,
                              fps=12.0, audio=wav_bytes)
out, stats = mtcodec.decode_video(frames)
```

需要桥接主流格式时用底层接口：

```python
from mtcodec import io_bridge

frames, has_alpha, src_size = io_bridge.load_image_frames("输入.apng", "1080p")
frames, src_size = io_bridge.load_video_frames("输入.mp4", fps=12, size_spec="720p",
                                               max_frames=24, start=0)
audio = io_bridge.load_audio_wav("输入.mp4", seconds=2.0)
io_bridge.export_mp4(解出来的帧, "输出.mp4", fps=12.0, wav_bytes=audio)
```

---

## 界面与 Windows 关联

```bash
python -m mtcodec open samples/photo_c.mtb
python deploy/windows_register.py --exe "D:/MTB-MTC/release/MTBViewer.exe"
python deploy/windows_register.py --unregister
```

查看器故意**不显示任何技术指标**：没有帧号、没有帧率、没有 gop、没有字节数。
单张图片就是单张图片，窗口标题只有文件名。空格暂停播放，Esc 关闭。

Windows 10/11 不允许程序静默把自己变成默认打开方式，所以注册只把
MTB/MTC 加进"打开方式"列表，并配好红色 M（图片）与蓝色 M（视频）图标。
用户在"打开方式"里勾一次"始终使用此应用"就永久生效。

---

## 打包成单文件程序

```bash
pip install pyinstaller
python tools/build_exe.py          # 产出 dist/MTBViewer.exe，约 29 MB，无控制台
```

完整流程（PyInstaller、Nuitka、Linux 的 `.desktop`、macOS 的 `.app`、
安卓的 Termux/Chaquopy）见 [docs/BUILD.md](docs/BUILD.md)。

---

## 各平台情况

| 平台 | 跑源码 | 单文件 | 说明 |
| --- | --- | --- | --- |
| Windows 10/11 | 支持 | `MTBViewer.exe` | 支持文件关联和图标 |
| Linux | 支持 | PyInstaller | 音频不响（winsound 是 Windows 专有） |
| macOS | 支持 | PyInstaller `.app` | 同样不响；要用 python.org 的 Python（Homebrew 不带 Tk） |
| 安卓 | Termux / Chaquopy | — | Tk 必须换成原生控件 |

鸿蒙与 iOS 明确不做：一个要学另一种语言，一个必须有苹果电脑才能编译。
这里写清楚是为了不留想象空间，不是漏了。

---

## 老实说明的短板

* **大图慢。** 7680×4320 编码 16.6 s；把一张小图放大到 8K 要 82 s。纯 Python 逐符号算术编码就是这个量级。
* **音频不压缩。** 每秒 172 KB，在测试用的 `.mtc` 里占 24%–59%。
* **音画只是粗同步。** 音频用系统播放器异步启动，没有逐帧时间戳。几秒钟没问题，长了会漂。
* **`.mtc` 没有透明。** 带透明的动图存成视频会丢透明（单帧用 `.mtb` 可保住）。
* **APNG 的每帧时长会丢。** `.mtc` 是恒定帧率。
* **视频要 ffmpeg。** 图片不需要。
* **非 Windows 构建没有声音。** 画面能放，音频不响。

---

## 实测结果（2026-11-15，Windows 11 / Python 3.12）

| 输入 | 源大小 | 输出 | 压缩比 | PSNR |
| --- | --- | --- | --- | --- |
| 壁纸 1080×1920 PNG | 2.08 MB | 179.5 KB | 33.8 : 1 | 32.29 dB |
| 壁纸 1920×1080 PNG | 2.64 MB | 300.5 KB | 20.2 : 1 | 28.84 dB |
| 壁纸 2048×2048 PNG | 4.28 MB | 350.3 KB | 35.1 : 1 | 32.60 dB |
| 壁纸 2058×1440 PNG | 3.42 MB | 358.7 KB | 24.2 : 1 | 29.81 dB |
| 壁纸 560×1440 PNG | 0.83 MB | 88.3 KB | 26.8 : 1 | 30.43 dB |
| 壁纸 800×450 RGBA PNG | 0.65 MB | 81.6 KB | 17.2 : 1 | 26.08 dB |
| 壁纸 800×800 PNG | 0.81 MB | 98.5 KB | 19.0 : 1 | 28.23 dB |
| 片段 5.56 MB MP4 → MTC | 5.56 MB | 371.6 KB（音频 172.3 KB） | 87.2 : 1 | — |
| 片段 35.5 MB MP4 → MTC | 35.5 MB | 357.4 KB（音频 172.3 KB） | 87.1 : 1 | — |
| APNG 8 帧 → MTC | — | 28 465 B | — | — |

透明往返：1080×1080 RGBA → `.mtb`（128.7 KB）→ PNG（625.9 KB），alpha 通道逐位相等。

完整表格与图表在仓库根目录的两份报告里：
`格式互转与多分辨率测试报告.html`、`编码器实验报告.html`。

---

## 目录结构

```text
mtcodec/          编解码核心（image_codec、video_codec、io_bridge、cli、viewer）
deploy/           exe 入口、Windows 关联注册、图标
tools/            打 exe、打 zip、批量转换、图标与 CLI 演示、
                  check_release.py（发布前自检）、make_release_zip.py
tests/            单元与格式测试（不依赖 pytest，直接 python 跑）
bench/            产出 results/ 的基准脚本
results/          实测 JSON 数据
samples/          示例 .mtb / .mtc，含透明与音轨样本
assets/           图标、MTB / JPEG / WebP 对比条
docs/             FORMAT.md、CONVERT.md、BUILD.md、PUBLISH.md（英文 + 中文）
release/          预打包的 exe 与两个 zip（不入 git，发布时作为 Release 附件）
```

---

## 文档

| 文件 | 内容 |
| --- | --- |
| [docs/FORMAT.md](docs/FORMAT.md) | 容器字节级规范（英文 + 中文） |
| [docs/CONVERT.md](docs/CONVERT.md) | 转换指南、每个参数、常见故障 |
| [docs/BUILD.md](docs/BUILD.md) | PyInstaller / Nuitka / Linux / macOS / 安卓 |
| [docs/PUBLISH.md](docs/PUBLISH.md) | 怎么发布到 GitHub，一步一步 |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史 |

---

## 许可

MIT，见 [LICENSE](LICENSE)。
