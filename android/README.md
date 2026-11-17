# MTC camera and gallery for Android

A camera that writes `.mtc` directly, and a gallery that reads it. No JPEG is
ever produced: the frame goes from Camera2 straight into the Rust codec through
JNI.

## Build

```powershell
powershell -ExecutionPolicy Bypass -File android\build.ps1            # arm64-v8a
powershell -ExecutionPolicy Bypass -File android\build.ps1 -Install    # + adb install -r
```

The output is `android/mtc-camera.apk`, signed with the debug key. The script
uses only what is already installed: `cargo-ndk` for the Rust shared library,
then `aapt2`, `javac`, `d8`, `zipalign` and `apksigner` from the SDK. No Gradle,
no Maven, no network — which also means the build cannot drift because a
repository moved.

Two environment details it works around, both worth knowing if it breaks:

* `--release` is not usable with the JDK on this machine, and lambdas do not
  compile against `android.jar` as a bootclasspath. The Java is therefore
  `-source 8` with anonymous inner classes, which needs no desugaring.
* `d8` from build-tools 34 crashes on this JDK; the script defaults to
  build-tools 36.

## What is in it

| screen | what it does |
| --- | --- |
| `GalleryActivity` | the launcher: a grid of `.mtc` files, thumbnails decoded at cell size by the codec, count and total size, one button to the camera |
| `CameraActivity` | Camera2 preview, one still per shutter, `YUV_420_888` → `.mtc` in Rust, saved with the milliseconds it took |
| `ViewerActivity` | one picture full screen, pinch to zoom, double-tap, **export to PNG** (so a photo can leave the app); also handles `VIEW` intents for `image/x-mtc` |

Long-press a thumbnail in the grid to delete it. The camera header carries a
colour-range switch (see below).

Pictures land in `Android/data/dev.mtc/files/Pictures`, which needs no storage
permission on any supported version and is reachable over USB. The camera asks
only for `CAMERA`.

The still is capped at 12 MP (`MAX_PIXELS`) and the encoder quality is 88; both
are constants at the top of `CameraActivity` and `jni/src/lib.rs` respectively.

## Rust side

`android/jni` is a `cdylib` that depends on the codec by path, so there is one
codec implementation and the phone gets whatever the desktop has. Four entry
points, all on `dev.mtc.Mtc`:

```
encodeRgba(rgba, w, h, q) -> byte[]
encodeYuv(y, u, v, w, h, yRowStride, uvRowStride, uvPixelStride,
          q, fullRange, rotation) -> byte[]
decodeRgba(mtc, maxSide) -> byte[]      // 8-byte w/h header, then RGBA
info(mtc) -> String
```

Two things that are camera facts rather than codec ones live in the Rust side
because the pixel loop is already there:

* **`rotation`** — a still arrives landscape in sensor orientation and
  `JPEG_ORIENTATION` only applies to JPEG, so the quarter turn happens while the
  pixels are converted. The app computes it from `SENSOR_ORIENTATION` and the
  display rotation.
* **`fullRange`** — devices disagree about whether `YUV_420_888` is BT.601 full
  (0–255) or limited (16–235) range. Guessing wrong shows up as a washed-out or a
  crushed picture, so the camera screen has a switch, remembered across runs.

`decodeRgba` takes a `maxSide`, so a thumbnail decodes to thumbnail size instead
of materialising a 12 MP bitmap; that is what keeps the grid cheap.

The pixel maths (`yuv_to_rgba`, `pack`) is plain Rust with unit tests, so the
conversion, the stride walking and the header format are verified on the host:

```powershell
cd android\jni
cargo test --release                      # 7 tests: range, rotation, strides, round trip
```

The JNI surface itself is checked on a desktop JVM, which is where a mismatched
symbol or a wrongly marshalled array would fail anyway:

```powershell
powershell -ExecutionPolicy Bypass -File android\jni\host\run.ps1
#   info: 64x48 rgb420-lossy q88 v2, 165 bytes
#   frame 64x48 -> 165 bytes, luma 61 -> 185
#   grey 128 -> 128,128,128
#   90 degree turn: 64x48 -> 48x64
#   thumbnail bounds 24 -> 22x16
#   rgba red -> 220,30,30 (54 bytes)
#   host JNI smoke: all checks passed
```

That covers the four entry points, the array marshalling, the `jboolean`/`jint`
widths, the rotation and the thumbnail bound — everything except the Android
camera itself.

## Known unknowns

Nothing here has run on a phone yet — no device was attached while it was built.
Verified so far: the APK's structure and signature, the exported JNI symbols in
the arm64 library, and the whole JNI surface on a desktop JVM (above). What is
left for real hardware:

* **Colour range.** Handled by a switch rather than by detection; the default is
  limited range. If the first capture looks washed out, tap the switch.
* **Preview framing.** `configureTransform` centre-crops with a quarter turn, the
  standard recipe, but it is the sort of thing that needs an eye on a real
  screen.
* **Encode time** on a large sensor, and whether 12 MP at quality 88 is a
  sensible default on a mid-range phone.
* **Front camera.** `pickBackCamera` falls back to whatever camera exists, and
  the rotation formula assumes a back-facing sensor; a selfie will probably come
  out mirrored or turned.
