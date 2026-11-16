# MTC —— 自己写的图片编解码器

MTC 是从零实现的静态图片编解码器。不链接 JPEG、WebP、PNG、HEIC 的库：变换、
量化、算术编码、颜色空间全部是自己的，容器格式也是自己的。

一个格式，一个后缀：**`.mtc`**。有损与无损共用一个容器，可选 alpha 与
4:2:0 / 4:4:4 色度。

## 特性

- 8×8 DCT，频率倾斜的量化表，YCoCg 颜色，可选 4:2:0。
- 按 zig-zag 频带分组的自适应二元算术编码。
- alpha 通道精确保存，不参与有损。
- 无损模式（空间预测 + 算术编码），适合截图、扫描件。
- 白色播放器：滚轮缩放（适应窗口～8×）、拖动平移、双击复位。

原来的视频编解码已经从仓库删除。`.mtc` 现在是图片后缀，不再生成 `.mtb`。

## 安装

```powershell
D:\python\python.exe -m pip install -e D:\MTB-MTC
```

纯 Python + numpy + Pillow，不编译也能直接跑。

## 用法

```powershell
# PNG / JPG / WEBP / BMP / GIF / APNG -> .mtc
D:\python\python.exe -m mtcodec encode photo.jpg photo.mtc -q 85

# .mtc -> PNG / JPG / WEBP（按输出后缀决定）
D:\python\python.exe -m mtcodec decode photo.mtc out.jpg

# 只看头
D:\python\python.exe -m mtcodec info photo.mtc

# 打开播放器
D:\python\python.exe -m mtcodec open photo.mtc
```

无损：

```powershell
D:\python\python.exe -m mtcodec encode scan.png scan.mtc --lossless
```

## 播放器

`mtcodec.viewer` 用白色窗口打开 `.mtc`。滚轮以光标为中心缩放，范围从“适应
窗口”到 8×；按住拖动平移；双击或点缩放读数复位；Esc 关闭。

## 目录

```
mtcodec/image_codec.py   容器与像素流程
mtcodec/entropy.py       系数模型与块编码
mtcodec/arithmetic.py    算术编码器
mtcodec/transform.py     DCT / 量化表
mtcodec/color.py         YCoCg 与裁剪
mtcodec/io_bridge.py     PNG/JPG/WEBP/GIF/APNG 桥接
mtcodec/viewer.py        图片播放器
mtcodec/cli.py           命令行
native/                  Rust 辅助代码（下一轮图片提速用）
deploy/                  Windows 关联与 PATH
tests/                   图片测试
```

## 状态

图片是现在的产品方向。下一轮：大图 Rust 提速，以及同 PSNR 下体积压过 WebP
的画质/体积优化。测试和基准输出不放在仓库里。
