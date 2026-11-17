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
| `ViewerActivity` | one picture full screen, pinch to zoom, double-tap; also handles `VIEW` intents for `image/x-mtc` |

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
encodeYuv(y, u, v, w, h, yRowStride, uvRowStride, uvPixelStride, q) -> byte[]
decodeRgba(mtc, maxSide) -> byte[]      // 8-byte w/h header, then RGBA
info(mtc) -> String
```

`decodeRgba` takes a `maxSide`, so a thumbnail decodes to thumbnail size instead
of materialising a 12 MP bitmap; that is what keeps the grid cheap.

The pixel maths (`yuv_to_rgba`, `pack`) is plain Rust with unit tests, so the
conversion, the stride walking and the header format are verified on the host:

```powershell
cd android\jni
cargo test --release                      # 5 tests, including a full frame round trip
```

## Known unknowns

Nothing here has run on a phone yet — no device was attached while it was built,
so what is verified is the APK's structure (`aapt2 dump badging`, signature) and
the codec path on the host. The first things to check on real hardware:

* **Colour.** `yuv_to_rgba` assumes BT.601 full range. Plenty of devices deliver
  limited range (16–235), which shows up as washed-out or crushed images; if that
  happens, the conversion needs a range flag from the Java side.
* **Orientation.** The activity is portrait and the still comes out in sensor
  orientation; `CaptureRequest.JPEG_ORIENTATION` only applies to JPEG, so a
  rotation step will be needed in the app or in the encoder.
* **Encode time** on a large sensor, and whether 12 MP at quality 88 is a
  sensible default on a mid-range phone.
