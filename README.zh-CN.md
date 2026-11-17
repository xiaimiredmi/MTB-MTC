# MTC —— 自己写的图片编解码器

MTC 是从零实现的静态图片编解码器。不链接 JPEG、WebP、PNG、HEIC 的库：变换、
量化、算术编码、颜色空间、容器格式全部是自己的。PNG/JPEG/WebP/BMP 只用来
读写普通图片文件。

一个格式，一个后缀：**`.mtc`**。有损与无损共用一个容器，可选 alpha 与
4:2:0 / 4:4:4 色度。

## 特性

- 8×8 DCT，频率倾斜的量化表，交流系数带零区。
- YCoCg 颜色，可选 4:2:0，色度压得更狠。
- 直流系数用左/上/左上做中值边缘检测预测。
- 按 zig-zag 频带分组的自适应二元算术编码。
- 无损模式（空间预测 + 同一个算术编码器），逐像素精确。
- alpha 通道精确，走无损通路，有损 RGB 也能配无损 alpha。
- 可选逐瓦片自适应量化（实测见下）。
- 白色查看器：滚轮缩放、拖动平移、双击复位。

## 安装

```powershell
cd rust
cargo build --release                      # mtcodec + mtbench
cargo build --release --features viewer    # 再加 mtview

copy target\release\mtcodec.exe,target\release\mtbench.exe,target\release\mtview.exe ..\bin\
powershell -ExecutionPolicy Bypass -File ..\deploy\register.ps1
```

最后一步把 `.mtc` 关联到 `mtview`、清掉旧视频容器的注册、并把 `bin\` 放到
用户 `Path` 最前面（不需要管理员）。`deploy\register.ps1 -Unregister` 全部撤销。

## 用法

```powershell
# PNG / JPG / WEBP / BMP -> .mtc
mtcodec encode photo.jpg photo.mtc -q 85

# .mtc -> PNG / JPG / WEBP（按输出后缀决定）
mtcodec decode photo.mtc out.jpg

# 只看头
mtcodec info photo.mtc

# 查看器（PNG/JPEG/WebP/BMP 也能直接开）
mtview photo.mtc
```

无损，以及 4:4:4 色度：

```powershell
mtcodec encode scan.png scan.mtc --lossless
mtcodec encode photo.jpg photo.mtc -q 90 -s 444
```

## 实测

- 2048×1152 实拍，`-q 85`，4:2:0，版本 2：397 KB、33.63 dB，编码约 115 ms、
  解码约 130 ms（单核，release）。
- 同 PSNR 下版本 2 比版本 1 少 11.3% 字节（四张 512×512 实拍 × 六档质量）。
- 无损：512×512 实拍 367 KB（11.2 bpp），解码逐位精确。
- 自适应量化是选开项：固定 `-q` 下约 +0.3 dB 换 +15% 字节，同 PSNR 下不划算。

数字、基准工具和比较脚本都在 `rust/` 里。

## 目录

```
rust/src/container.rs  头、模式、颜色、alpha、编解码入口
rust/src/codec.rs      8×8 DCT 平面、量化、重建
rust/src/entropy.rs    系数块编码与残差模型
rust/src/aq.rs         自适应量化，每 16×16 瓦片一个倍率
rust/src/lossless.rs   无损通路与 alpha 的空间预测
rust/src/arith.rs      二元算术编码器
rust/src/transform.rs  DCT 矩阵、zig-zag 扫描、量化表
rust/src/bin/          mtbench（测量）与 mtview（egui 查看器）
deploy/register.ps1    按用户写文件关联与 PATH
samples/               .mtc 样本，包括被删掉的 Python 编码器写的那些
```

版本 1 码流（被移除的 Python 编码器写的布局）仍然逐位正确解码，
`rust/tests/data/` 里留了三个样本做夹具测试。

## 状态

图片是产品方向，格式现在由 `rust/` 里的 Rust 编解码器接手。Python 实现已经
删除，迁移完成。下一步是体积和速度：同 PSNR 下还没压过 WebP，那是要打的靶子。

## 许可

MIT，见 `LICENSE`。
