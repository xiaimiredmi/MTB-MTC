import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from mtcodec import decode_image, decode_video, encode_image, encode_video, probe, probe_video
from mtcodec import io_bridge


def _photo(h, w, channels=3):
    y = np.linspace(0, 1, h)[:, None]
    x = np.linspace(0, 1, w)[None, :]
    r = 128 + 80 * np.sin(6.2 * x + 1.1) * np.cos(3.4 * y)
    g = 128 + 70 * np.sin(4.4 * y + 2.0) + 40 * x
    b = 128 + 60 * np.cos(5.5 * (x + y))
    img = np.stack([r, g, b], axis=2)
    if channels == 4:
        a = np.zeros((h, w))
        a[:, : w // 2] = 255
        a[:, w // 2 :] = np.linspace(0, 255, w - w // 2)[None, :]
        img = np.dstack([img, a])
    return np.clip(img, 0, 255).astype(np.uint8)


def test_alpha_lossless():
    img = _photo(120, 140, 4)
    blob = encode_image(img, lossless=True)
    info = probe(blob)
    assert info["has_alpha"], "alpha flag missing"
    back = decode_image(blob)
    assert back.shape == img.shape, back.shape
    assert np.array_equal(back[:, :, 3], img[:, :, 3]), "alpha not exact"
    mask = img[:, :, 3] >= 8
    assert np.array_equal(back[:, :, :3][mask], img[:, :, :3][mask]), "visible rgb not exact"
    print("alpha lossless ok  %d bytes  alpha exact, rgb exact where alpha>=8" % len(blob))


def test_alpha_lossy():
    img = _photo(120, 140, 4)
    for q in (50, 85):
        blob = encode_image(img, quality=q)
        back = decode_image(blob)
        assert np.array_equal(back[:, :, 3], img[:, :, 3]), "alpha not exact q=%d" % q
        print("alpha lossy q=%d %d bytes alpha exact" % (q, len(blob)))


def test_apng_roundtrip():
    frames = [_photo(64, 64, 4) for _ in range(6)]
    for i, f in enumerate(frames):
        f[:, :, 3] = 255 if i % 2 == 0 else 128
    tmp = os.path.join(os.environ.get("TEMP", "."), "mtcodec_test.apng")
    imgs = [Image.fromarray(f, mode="RGBA") for f in frames]
    imgs[0].save(tmp, save_all=True, append_images=imgs[1:], duration=80, loop=0, format="PNG")
    loaded, has_alpha, src = io_bridge.load_image_frames(tmp)
    assert len(loaded) == len(frames), "apng frame count %d" % len(loaded)
    assert has_alpha
    blob = encode_video([f[:, :, :3] for f in loaded], quality=80, fps=12, gop=12)
    out, stats = decode_video(blob)
    assert len(out) == len(loaded)
    print("apng -> mtc ok  %d frames  %d bytes" % (len(out), len(blob)))
    os.remove(tmp)


def test_video_audio():
    base = _photo(96, 128)
    frames = [np.roll(base, i * 2, axis=1) for i in range(5)]
    fake_wav = b"RIFF" + b"\x24\x00\x00\x00WAVEfmt " + b"\x00" * 100
    blob = encode_video(frames, quality=80, fps=12.5, audio=fake_wav)
    info = probe_video(blob)
    assert info["has_audio"] and info["audio_bytes"] == len(fake_wav), info
    assert abs(info["fps"] - 12.5) < 1e-6, info["fps"]
    got = {}
    out, stats = decode_video(blob, collect=got)
    assert got["audio"] == fake_wav, "audio not preserved"
    assert abs(got["fps"] - 12.5) < 1e-6
    print("video v2 ok  fps=%.2f audio=%d bytes frames=%d" % (
        got["fps"], len(got["audio"]), len(out)))


def test_v1_compat():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "samples", "demo.mtc")
    with open(path, "rb") as f:
        blob = f.read()
    info = probe_video(blob)
    frames, stats = decode_video(blob)
    print("v1 sample ok  version=%d frames=%d" % (info["version"], len(frames)))


if __name__ == "__main__":
    test_alpha_lossless()
    test_alpha_lossy()
    test_apng_roundtrip()
    test_video_audio()
    test_v1_compat()
    print("format tests passed")
