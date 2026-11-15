# Build guide — Windows, Linux, macOS, Android

How to turn the source tree into something you can hand to another person.
中文版在下半部分。

---

## 0. Environment first

| Need | Why |
| --- | --- |
| Python 3.10 – 3.12, 64-bit, with **Tcl/Tk** | the viewer is tkinter; python.org installers and `conda` both include it |
| `numpy`, `pillow` | codec core |
| `imageio-ffmpeg` *or* ffmpeg on PATH | video import/export only |
| `pyinstaller` | single-file build |
| ffmpeg binary | not needed for a GUI-only build, only for video |

Check the Tk situation before you build anything:

```bash
python -c "import tkinter; tkinter.Tk().destroy(); print('tk ok')"
```

If this raises `Can't find a usable init.tcl`, that interpreter cannot run the
viewer. Ubuntu/Debian fix: `sudo apt install python3-tk`. Embedded/portable
Python builds (the ones without `tcl/` next to `python.exe`) never include it —
use a full python.org installer.

---

## 1. Windows — PyInstaller (this is what ships)

```bash
python tools/build_exe.py
```

`tools/build_exe.py` runs exactly this:

```text
python -m PyInstaller --noconfirm --clean --onefile --windowed
    --name MTBViewer
    --icon deploy/icons/mtb.ico
    --paths .
    --hidden-import mtcodec.viewer
    --hidden-import PIL.ImageTk
    deploy/mtb_app.py
```

Why each flag matters:

| Flag | Reason |
| --- | --- |
| `--onefile` | one artifact, no `_internal` folder to explain |
| `--windowed` | no console window; a console build flashes black on launch |
| `--icon deploy/icons/mtb.ico` | Explorer shows the red M on the exe itself |
| `--hidden-import mtcodec.viewer` | the viewer is imported via `-m`, static analysis misses it |
| `--hidden-import PIL.ImageTk` | Pillow loads ImageTk lazily; without this the exe dies at first image |
| `--noconfirm --clean` | reproducible builds, no stale cache prompts |

Result on Windows 11 / Python 3.12: `dist\MTBViewer.exe`, about **30 MB**;
a onefile launch unpacks numpy, Pillow and Tcl/Tk into `%TEMP%` first, which is
the bulk of the startup cost.

Use the wrapper instead of calling PyInstaller by hand:

```bash
python tools/build_exe.py            # onefile -> dist\MTBViewer.exe
python tools/build_exe.py --onedir   # folder  -> dist\MTBViewer\MTBViewer.exe
```

Measured on the dev machine, same sample, start to close (both include a 1.2 s
auto-close timer and the decode step): **onefile 6.1–9.2 s, onedir 4.1–6.1 s**.
The folder build is also easier to code-sign and smaller to update: ship the
onefile in releases, install the folder locally.

`deploy/mtb_app.py` is the entry point: when Windows passes a file path, it opens
that file; with no argument it shows the file picker.

### Icon

```bash
python tools/make_icons.py
```

Regenerates `assets/icons/mtb.png`, `assets/icons/mtc.png` and the `.ico` files
in `deploy/icons/` from scratch with Pillow — red `#C62828` square with a white
M for images, blue `#1565C0` for video. No external assets required.

### File association

```bash
python deploy/windows_register.py --exe "D:/MTB-MTC/release/viewer/MTBViewer.exe"
python deploy/windows_register.py --unregister
```

Writes under `HKCU\Software\Classes` (no admin rights needed):

| Key | Value |
| --- | --- |
| `.mtb` | `MTB.Image`, Content Type `image/x-mtb` |
| `.mtc` | `MTB.Video`, Content Type `video/x-mtc` |
| `MTB.Image\shell\open\command` | `"…\MTBViewer.exe" "%1"` |
| `MTB.Image\DefaultIcon` | `deploy\icons\mtb.ico` |

Windows 10/11 deliberately block a program from silently becoming the default
handler. After registering, the file gets the icon and appears under
"Open with"; the user ticks *Always use this app* once and it stays.
That is a platform decision, not a bug in the script.

---

## 2. Windows — Nuitka (smaller, slower to build)

```bash
pip install nuitka
python -m nuitka --standalone --onefile --enable-plugin=tk-inter ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=deploy/icons/mtb.ico ^
    --include-package=mtcodec ^
    deploy/mtb_app.py
```

* C-compiled, so startup is noticeably faster than onefile PyInstaller.
* Needs a C compiler (MSVC Build Tools or MinGW64).
* Build time is minutes, output is usually 15–25 MB.
* `--enable-plugin=tk-inter` is mandatory — without it Tk data files are missing
  and the exe starts then dies silently.

Not measured on the author's machine; the PyInstaller path above is the tested one.

---

## 3. Linux

```bash
sudo apt install python3-tk ffmpeg          # Debian/Ubuntu
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pyinstaller
python -m mtcodec open samples/photo_c.mtb  # run from source first
python -m PyInstaller --noconfirm --clean --onefile --windowed \
    --name mtbviewer --paths . \
    --hidden-import mtcodec.viewer --hidden-import PIL.ImageTk \
    deploy/mtb_app.py
```

Desktop integration:

```ini
# ~/.local/share/applications/mtbviewer.desktop
[Desktop Entry]
Type=Application
Name=MTB Viewer
Exec=/home/user/MTB-MTC/dist/mtbviewer %f
Icon=/home/user/MTB-MTC/assets/icons/mtb.png
MimeType=image/x-mtb;video/x-mtc;
Terminal=false
Categories=Graphics;Viewer;
```

```bash
xdg-mime default mtbviewer.desktop image/x-mtb
xdg-mime default mtbviewer.desktop video/x-mtc
update-desktop-database ~/.local/share/applications
```

Known limitation: there is no audio playback on Linux or macOS. `winsound` is
Windows-only and the code deliberately does not fake it. The picture plays.

For a distro-independent binary, an AppImage or a plain `tar.gz` of the
`--onefile` output both work; nothing in the codec links against system paths.

---

## 4. macOS

```bash
brew install python-tk        # or use the python.org installer, which bundles Tk
pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name "MTB Viewer" \
    --icon deploy/icons/mtb.icns --paths . \
    --hidden-import mtcodec.viewer --hidden-import PIL.ImageTk \
    deploy/mtb_app.py
```

* `--windowed` on macOS produces `dist/MTB Viewer.app`.
* Homebrew's `python3` often ships **without** Tk; the python.org framework build
  is the safe choice. Symptom is the same `init.tcl` error.
* Add document types to `dist/MTB Viewer.app/Contents/Info.plist` so Finder
  offers the app for `.mtb` / `.mtc`:

```xml
<key>CFBundleDocumentTypes</key>
<array>
  <dict>
    <key>CFBundleTypeExtensions</key><array><string>mtb</string></array>
    <key>CFBundleTypeName</key><string>MTB Image</string>
    <key>CFBundleTypeRole</key><string>Viewer</string>
  </dict>
  <dict>
    <key>CFBundleTypeExtensions</key><array><string>mtc</string></array>
    <key>CFBundleTypeName</key><string>MTC Video</string>
    <key>CFBundleTypeRole</key><string>Viewer</string>
  </dict>
</array>
```

* Gatekeeper: unsigned apps need one right-click → Open, or
  `xattr -dr com.apple.quarantine "MTB Viewer.app"`.
* Audio is silent here too, same reason as Linux.

---

## 5. Android — three realistic routes

Android has no Tk. Decide what you actually need before picking a route:

| Route | GUI | Effort | Best for |
| --- | --- | --- | --- |
| **Termux** (CLI only) | none | lowest | converting files on-device from a terminal |
| **Chaquopy** inside a normal Android app | native Android | medium | a real app with an Open button, shipped as APK |
| **Kivy / Buildozer** | Kivy widgets | medium-high | keeping one Python codebase and getting an APK |

### 5.1 Termux — the pragmatic one

```bash
pkg install python ffmpeg
pip install numpy pillow
cd ~/MTB-MTC
python -m mtcodec convert DCIM/photo.jpg out.mtb -q 80
python -m mtcodec export out.mtb back.png
```

This works today with no code change, because the CLI and the codec never touch
Tk. `python -m mtcodec open` will fail (`no display` / no tkinter) — skip the
viewer on Termux. Also note `imageio-ffmpeg`'s wheels do not cover every
Termux arch, so `pkg install ffmpeg` is the reliable path.

### 5.2 Chaquopy — codec inside a real APK

Keep `mtcodec/` as-is (pure numpy), drop the tkinter viewer, and call it from
Kotlin/Java:

```gradle
// app/build.gradle
plugins { id "com.chaquo.python" version "15.0.1" }
android { defaultConfig { ndk { abiFilters "arm64-v8a", "armeabi-v7a" } } }
chaquopy {
  defaultConfig { pip { install "numpy" ; install "pillow" } }
  sourceSets { getByName("main") { srcDir("$rootDir/../MTB-MTC") } }
}
```

```kotlin
val py = Python.getInstance()
val mod = py.getModule("mtcodec")
val blob = mod.callAttr("encode_image", bitmapArg, 80).toJava(ByteArray::class.java)
```

Changes required in the code:

* nothing in `image_codec.py` / `video_codec.py` — they are display-agnostic;
* do **not** import `mtcodec.viewer` (it imports tkinter);
* video import needs ffmpeg: either bundle `ffmpeg-kit-android` and pass frames in,
  or stay image-only on Android. `io_bridge` shells out to `ffmpeg`, which does not
  exist in an APK sandbox — this is the one real blocker.

### 5.3 Kivy / Buildozer — Python GUI on Android

Replace `viewer.py` with a Kivy `App` that shows the decoded numpy array via
`kivy.core.image`, keep the codec unchanged, then:

```bash
pip install buildozer
buildozer init
# buildozer.spec: requirements = python3,numpy,pillow,kivy
buildozer -v android debug
```

Expect a large APK (~60 MB with numpy) and a slow first import. Worth it only if
you truly want one Python codebase everywhere.

### 5.4 Why HarmonyOS and iOS are out of scope

* HarmonyOS next-gen apps need ArkTS or native C++ plus a DevEco toolchain; there
  is no supported path to run this Python package as a viewer.
* iOS requires macOS + Xcode to sign anything, and Python's GUI story there
  (Kivy or Briefcase) is a separate research project.

Stated here so nobody wastes a weekend. The codec still *works* on those
platforms if someone builds a wrapper — the container format has no OS dependency.

---

## 6. What to ship

| Target | Files | Size |
| --- | --- | --- |
| Windows, no Python | `MTBViewer.exe` + `README.txt` | ~29 MB |
| Windows, with Python | sdist/wheel or the zip of the tree | ~40 MB (samples included) |
| Linux | `mtbviewer` + `.desktop` + icon | ~20–30 MB |
| macOS | `MTB Viewer.app` (zip it) | ~25–35 MB |
| Android | APK from 5.2 or 5.3 | 25–60 MB |

Keep `release/` out of git — see [PUBLISH.md](PUBLISH.md) for attaching binaries
to a GitHub Release instead.

---

## 7. Build checklist

1. `python -c "import tkinter; tkinter.Tk().destroy()"` prints `tk ok`.
2. `python tests/test_codec.py` and `python tests/test_formats.py` pass.
3. `python -m mtcodec open samples/photo_c.mtb` opens a window with no overlay.
4. `python -m mtcodec open samples/mtc_audio.mtc` plays with sound (Windows).
5. `python -m mtcodec export samples/photo_c.mtb out.png` writes a valid PNG.
6. Build the exe, then run it on a machine without Python.
7. Register association, double-click a `.mtb`, confirm icon + viewer.

---

# 中文版

## 0. 先看环境

| 需要 | 原因 |
| --- | --- |
| Python 3.10–3.12，64 位，**带 Tcl/Tk** | 查看器是 tkinter；python.org 安装包和 conda 都自带 |
| `numpy`、`pillow` | 编解码核心 |
| `imageio-ffmpeg` 或 PATH 里有 ffmpeg | 只有视频导入/导出需要 |
| `pyinstaller` | 打单文件 |
| ffmpeg 可执行文件 | 纯看图程序不需要 |

打包前先验证 Tk：

```bash
python -c "import tkinter; tkinter.Tk().destroy(); print('tk ok')"
```

如果报 `Can't find a usable init.tcl`，这个解释器跑不了查看器。
Debian/Ubuntu 补 `sudo apt install python3-tk`。嵌入式/便携版 Python
（`python.exe` 旁边没有 `tcl/` 目录的那种）永远没有 Tk，换 python.org 官方安装包。

## 1. Windows —— PyInstaller（当前发布的走法）

```bash
python tools/build_exe.py
```

脚本等价于：

```text
python -m PyInstaller --noconfirm --clean --onefile --windowed
    --name MTBViewer
    --icon deploy/icons/mtb.ico
    --paths .
    --hidden-import mtcodec.viewer
    --hidden-import PIL.ImageTk
    deploy/mtb_app.py
```

每个参数为什么必须有：

| 参数 | 原因 |
| --- | --- |
| `--onefile` | 只出一个文件，不用向别人解释 `_internal` 目录 |
| `--windowed` | 不带控制台窗口；带控制台的版本启动时会闪一下黑框 |
| `--icon deploy/icons/mtb.ico` | 资源管理器里 exe 本身就是红色 M |
| `--hidden-import mtcodec.viewer` | 查看器是动态导入的，静态分析扫不到 |
| `--hidden-import PIL.ImageTk` | Pillow 延迟加载 ImageTk，漏了它程序在显示第一张图时崩 |
| `--noconfirm --clean` | 可重复构建，不被缓存卡住 |

Windows 11 / Python 3.12 实测：`dist\MTBViewer.exe`，约 **30 MB**；onefile 每次
启动都要先把 numpy、Pillow、Tcl/Tk 解包到 `%TEMP%`，这就是启动慢的大头。

不要手敲 PyInstaller，直接用封装脚本：

```bash
python tools/build_exe.py            # onefile -> dist\MTBViewer.exe
python tools/build_exe.py --onedir   # 目录版 -> dist\MTBViewer\MTBViewer.exe
```

本机同一样本从启动到关闭实测（都含 1.2 秒自动关闭与解码）：
**onefile 6.1–9.2 秒，onedir 4.1–6.1 秒**。目录版还更好做代码签名、增量更新也小：
发布给别人用 onefile，自己日常用目录版。

`deploy/mtb_app.py` 是入口：Windows 传文件路径进来就打开那个文件，
没有参数就弹文件选择框。

### 图标

```bash
python tools/make_icons.py
```

用 Pillow 从零重画 `assets/icons/mtb.png`、`assets/icons/mtc.png` 和
`deploy/icons/` 里的 `.ico`：图片是红色 `#C62828` 圆角方块配白色 M，
视频是蓝色 `#1565C0`。不依赖任何外部素材。

### 文件关联

```bash
python deploy/windows_register.py --exe "D:/MTB-MTC/release/viewer/MTBViewer.exe"
python deploy/windows_register.py --unregister
```

写到 `HKCU\Software\Classes`（不需要管理员权限）：

| 键 | 值 |
| --- | --- |
| `.mtb` | `MTB.Image`，Content Type `image/x-mtb` |
| `.mtc` | `MTB.Video`，Content Type `video/x-mtc` |
| `MTB.Image\shell\open\command` | `"…\MTBViewer.exe" "%1"` |
| `MTB.Image\DefaultIcon` | `deploy\icons\mtb.ico` |

Windows 10/11 不允许程序静默把自己设成默认打开方式。注册之后文件有了图标、
出现在"打开方式"里，用户勾一次"始终使用此应用"就固定下来。这是系统策略，
不是脚本写错了。

## 2. Windows —— Nuitka（体积更小，编译更久）

```bash
pip install nuitka
python -m nuitka --standalone --onefile --enable-plugin=tk-inter --windows-console-mode=disable --windows-icon-from-ico=deploy/icons/mtb.ico --include-package=mtcodec deploy/mtb_app.py
```

* 编译成 C，启动明显快于 PyInstaller onefile。
* 需要 C 编译器（MSVC Build Tools 或 MinGW64）。
* 构建要几分钟，产物体积一般 15–25 MB。
* `--enable-plugin=tk-inter` 必须加，否则 Tk 的数据文件缺失，程序启动后无声退出。

这条路径作者机器上没有实测，上面 PyInstaller 那条是验证过的。

## 3. Linux

```bash
sudo apt install python3-tk ffmpeg
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pyinstaller
python -m mtcodec open samples/photo_c.mtb
python -m PyInstaller --noconfirm --clean --onefile --windowed --name mtbviewer --paths . --hidden-import mtcodec.viewer --hidden-import PIL.ImageTk deploy/mtb_app.py
```

桌面集成：

```ini
# ~/.local/share/applications/mtbviewer.desktop
[Desktop Entry]
Type=Application
Name=MTB Viewer
Exec=/home/user/MTB-MTC/dist/mtbviewer %f
Icon=/home/user/MTB-MTC/assets/icons/mtb.png
MimeType=image/x-mtb;video/x-mtc;
Terminal=false
Categories=Graphics;Viewer;
```

```bash
xdg-mime default mtbviewer.desktop image/x-mtb
xdg-mime default mtbviewer.desktop video/x-mtc
update-desktop-database ~/.local/share/applications
```

已知限制：Linux 和 macOS 都没有声音。`winsound` 是 Windows 专有，代码没有假装
能响。画面正常播。

要跨发行版分发，AppImage 或者把 `--onefile` 产物打个 `tar.gz` 都行，
编解码器不依赖任何系统路径。

## 4. macOS

```bash
brew install python-tk        # 或者直接用 python.org 安装包（自带 Tk）
pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name "MTB Viewer" --icon deploy/icons/mtb.icns --paths . --hidden-import mtcodec.viewer --hidden-import PIL.ImageTk deploy/mtb_app.py
```

* `--windowed` 在 macOS 上产出 `dist/MTB Viewer.app`。
* Homebrew 的 `python3` 经常**不带** Tk，用 python.org 的 framework 版本最稳。
  症状同样是 `init.tcl` 报错。
* 把文档类型写进 `Info.plist`，Finder 才会用这个 app 打开 `.mtb`/`.mtc`：

```xml
<key>CFBundleDocumentTypes</key>
<array>
  <dict>
    <key>CFBundleTypeExtensions</key><array><string>mtb</string></array>
    <key>CFBundleTypeName</key><string>MTB Image</string>
    <key>CFBundleTypeRole</key><string>Viewer</string>
  </dict>
</array>
```

* Gatekeeper：未签名应用要右键 → 打开一次，或者
  `xattr -dr com.apple.quarantine "MTB Viewer.app"`。
* 这里同样没声音，原因和 Linux 一样。

## 5. 安卓 —— 三条现实路线

安卓没有 Tk。先想清楚要什么再选：

| 路线 | 界面 | 工作量 | 适合 |
| --- | --- | --- | --- |
| **Termux**（纯命令行） | 无 | 最低 | 在手机上用终端转换文件 |
| **Chaquopy** 嵌进正常安卓应用 | 原生安卓 | 中 | 要真正带"打开"按钮的 APK |
| **Kivy / Buildozer** | Kivy 控件 | 中高 | 想保留一套 Python 代码并拿到 APK |

### 5.1 Termux —— 最省事

```bash
pkg install python ffmpeg
pip install numpy pillow
cd ~/MTB-MTC
python -m mtcodec convert DCIM/photo.jpg out.mtb -q 80
python -m mtcodec export out.mtb back.png
```

今天就能用，不用改一行代码，因为 CLI 和编解码器都不碰 Tk。
`python -m mtcodec open` 会失败（没有显示服务器），Termux 上不看图就不用管。
另外 `imageio-ffmpeg` 的轮子不覆盖所有 Termux 架构，`pkg install ffmpeg` 更稳。

### 5.2 Chaquopy —— 把编解码器塞进真正的 APK

`mtcodec/` 原样保留（纯 numpy），去掉 tkinter 查看器，从 Kotlin/Java 里调：

```gradle
plugins { id "com.chaquo.python" version "15.0.1" }
android { defaultConfig { ndk { abiFilters "arm64-v8a", "armeabi-v7a" } } }
chaquopy {
  defaultConfig { pip { install "numpy" ; install "pillow" } }
}
```

```kotlin
val py = Python.getInstance()
val mod = py.getModule("mtcodec")
val blob = mod.callAttr("encode_image", bitmapArg, 80).toJava(ByteArray::class.java)
```

需要改动的地方：

* `image_codec.py` / `video_codec.py` **完全不动**——它们与显示无关；
* 绝对不要 import `mtcodec.viewer`（它 import tkinter）；
* 视频导入要 ffmpeg：要么集成 `ffmpeg-kit-android` 自己把帧传进来，
  要么安卓上只做图片。`io_bridge` 是调外部 `ffmpeg` 的，APK 沙箱里没有，
  这是唯一真正的硬阻碍。

### 5.3 Kivy / Buildozer —— 安卓上的 Python GUI

把 `viewer.py` 换成 Kivy `App`，用 `kivy.core.image` 显示解码出的 numpy 数组，
编解码器不动，然后：

```bash
pip install buildozer
buildozer init
# buildozer.spec: requirements = python3,numpy,pillow,kivy
buildozer -v android debug
```

APK 会比较大（带 numpy 约 60 MB），首次 import 也慢。只有确实想"一套 Python
代码全平台"才值得走这条。

### 5.4 鸿蒙和 iOS 为什么不做

* 鸿蒙原生应用要 ArkTS 或 C++ 加 DevEco 工具链，没有把这个 Python 包当查看器
  跑起来的可行路径。
* iOS 必须 Mac + Xcode 才能签名，而 Python 在 iOS 上的 GUI（Kivy 或 Briefcase）
  是另一个独立课题。

写在这里是为了别人别白花一个周末。容器格式本身没有任何操作系统依赖，
真有人做壳子，那两个平台理论上也能跑。

## 6. 该发什么

| 目标 | 文件 | 体积 |
| --- | --- | --- |
| Windows，对方没 Python | `MTBViewer.exe` + `README.txt` | 约 29 MB |
| Windows，对方有 Python | sdist/wheel 或整棵树的 zip | 约 40 MB（含示例） |
| Linux | `mtbviewer` + `.desktop` + 图标 | 约 20–30 MB |
| macOS | `MTB Viewer.app`（打包成 zip） | 约 25–35 MB |
| 安卓 | 5.2 或 5.3 产出的 APK | 25–60 MB |

`release/` 不入 git，二进制放到 GitHub Release 里，
见 [PUBLISH.md](PUBLISH.md)。

## 7. 打包检查清单

1. `python -c "import tkinter; tkinter.Tk().destroy()"` 输出 `tk ok`。
2. `python tests/test_codec.py` 和 `python tests/test_formats.py` 通过。
3. `python -m mtcodec open samples/photo_c.mtb` 出窗口，且没有技术指标叠加。
4. `python -m mtcodec open samples/mtc_audio.mtc` 有画面且有声音（Windows）。
5. `python -m mtcodec export samples/photo_c.mtb out.png` 产出合法 PNG。
6. 打包后在一台没装 Python 的机器上跑一次。
7. 注册关联，双击一个 `.mtb`，确认图标和查看器都对。
