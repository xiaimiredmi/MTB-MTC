import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mtcodec import decode_image, decode_video, encode_image, encode_video, psnr
from mtcodec.arithmetic import PROB_INIT, Decoder, Encoder, dec_bits, dec_tree, enc_bits, enc_tree


def test_arithmetic():
    rng = np.random.default_rng(0)
    probs = [PROB_INIT] * 4
    bits = rng.integers(0, 2, 200000)
    enc = Encoder()
    for b in bits:
        enc.encode(probs, 0, int(b))
    blob = enc.flush()
    probs = [PROB_INIT] * 4
    dec = Decoder(blob)
    out = [dec.decode(probs, 0) for _ in bits]
    assert out == bits.tolist(), "arithmetic coder mismatch"
    print(f"arithmetic ok  200000 bits -> {len(blob)} bytes")


def test_tree_bits():
    rng = np.random.default_rng(1)
    values = rng.integers(0, 16, 5000)
    probs = [PROB_INIT] * 32
    enc = Encoder()
    for v in values:
        enc_tree(enc, probs, 0, 4, int(v))
    blob = enc.flush()
    probs = [PROB_INIT] * 32
    dec = Decoder(blob)
    out = [dec_tree(dec, probs, 0, 4) for _ in values]
    assert out == values.tolist()
    print("tree ok")

    probs2 = [PROB_INIT] * 64
    vals = rng.integers(0, 1024, 3000)
    enc = Encoder()
    for v in vals:
        enc_bits(enc, probs2, 16, 10, int(v))
    blob = enc.flush()
    probs2 = [PROB_INIT] * 64
    dec = Decoder(blob)
    got = [dec_bits(dec, probs2, 16, 10) for _ in vals]
    assert got == vals.tolist()
    print("bits ok")


def _photo(h, w):
    y = np.linspace(0, 1, h)[:, None]
    x = np.linspace(0, 1, w)[None, :]
    r = 128 + 80 * np.sin(6.2 * x + 1.1) * np.cos(3.4 * y)
    g = 128 + 70 * np.sin(4.4 * y + 2.0) + 40 * x
    b = 128 + 60 * np.cos(5.5 * (x + y))
    img = np.stack([r, g, b], axis=2)
    img[h // 4 : h // 2, w // 4 : w // 2] = 240
    img[h // 2 :, : w // 3] = np.linspace(10, 200, w // 3)[None, :, None]
    return np.clip(img, 0, 255).astype(np.uint8)


def test_lossless():
    img = _photo(200, 240)
    blob = encode_image(img, lossless=True)
    back = decode_image(blob)
    assert np.array_equal(img, back), "lossless round trip mismatch"
    print(f"lossless exact  {len(blob)} bytes for {img.size} samples ({img.size / len(blob):.2f}x)")

    gray = img[:, :, 0].copy()
    blob = encode_image(gray, lossless=True)
    back = decode_image(blob)
    assert np.array_equal(gray, back)
    print("lossless gray exact")


def test_lossy_coefficients():
    img = _photo(128, 160)
    for sub in ("420", "444"):
        for q in (30, 60, 85):
            got = {}
            blob = encode_image(img, quality=q, subsample=sub, collect=got)
            other = {}
            back = decode_image(blob, collect=other)
            for a, b in zip(got["qz"], other["qz"]):
                assert np.array_equal(a, b), f"coeff mismatch q={q} sub={sub}"
            print(f"lossy {sub} q={q}  ratio {img.size * 1 / len(blob):.2f}x  psnr {psnr(img, back):.2f}")
    gray = img[:, :, 1].copy()
    blob = encode_image(gray, quality=70)
    back = decode_image(blob)
    print(f"lossy gray ratio {gray.size / len(blob):.2f}x psnr {psnr(gray, back):.2f}")


def test_video():
    base = _photo(144, 176)
    frames = []
    for i in range(8):
        dx = i * 2
        frames.append(np.roll(np.roll(base, dx, axis=1), i % 3, axis=0))
    col = {}
    blob = encode_video(frames, quality=80, subsample="420", gop=12, collect=col)
    stats = col["stats"]
    out, dstat = decode_video(blob)
    assert len(out) == len(frames)
    assert [s["type"] for s in stats] == [s["type"] for s in dstat]
    raw = sum(f.size for f in frames)
    print(f"video {len(frames)} frames  {len(blob)} bytes  ratio {raw / len(blob):.2f}x")
    print("types", [s["type"] for s in stats])
    print(f"psnr first {psnr(frames[0], out[0]):.2f}  last {psnr(frames[-1], out[-1]):.2f}")
    intra_only = encode_video(frames, quality=80, subsample="420", gop=0)
    print(f"all-intra bytes {len(intra_only)}  inter bytes {len(blob)}")


if __name__ == "__main__":
    test_arithmetic()
    test_tree_bits()
    test_lossless()
    test_lossy_coefficients()
    test_video()
    print("all tests passed")
