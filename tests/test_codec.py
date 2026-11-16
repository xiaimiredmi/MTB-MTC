import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np

from mtcodec import decode_image, encode_image, psnr


def photo(w=640, h=480, alpha=False):
    rng = np.random.default_rng(7)
    y, x = np.mgrid[0:h, 0:w]
    r = (x * 255 // max(1, w - 1)).astype(np.int16)
    g = (y * 255 // max(1, h - 1)).astype(np.int16)
    b = ((x + y) * 255 // max(1, w + h - 2)).astype(np.int16)
    base = np.stack([r, g, b], axis=2)
    base = np.clip(base + rng.integers(-6, 7, base.shape), 0, 255).astype(np.uint8)
    if alpha:
        a = np.clip((x * 255 // max(1, w - 1)), 0, 255).astype(np.uint8)
        return np.dstack([base, a])
    return base


def test_lossless():
    arr = photo(320, 240, alpha=True)
    blob = encode_image(arr, lossless=True)
    back = decode_image(blob)
    mask = arr[:, :, 3] >= 8
    assert np.array_equal(back[:, :, 3], arr[:, :, 3]), "alpha must be exact"
    assert np.array_equal(back[mask], arr[mask]), "visible rgb must be exact"
    print("lossless exact  %d bytes for %d samples (%.2fx)"
          % (len(blob), arr.size, arr.size / float(len(blob))))


def test_lossy():
    arr = photo(640, 480)
    for sub in ("420", "444"):
        blob = encode_image(arr, quality=80, subsample=sub)
        back = decode_image(blob)
        p = psnr(arr, back)
        ratio = arr.size / float(len(blob))
        assert blob[:4] == b"MTB1"
        assert p > 30.0, "psnr too low: %.2f" % p
        assert ratio > 15.0, "ratio too low: %.2f" % ratio
        print("lossy %s q80  %.2f:1  psnr %.2f" % (sub, ratio, p))


def test_alpha():
    arr = photo(200, 150, alpha=True)
    blob = encode_image(arr, quality=85, subsample="420")
    back = decode_image(blob)
    assert back.shape == arr.shape
    assert np.array_equal(back[:, :, 3], arr[:, :, 3]), "alpha must be exact"
    print("alpha exact  %d bytes" % len(blob))


def test_gray():
    gray = photo(160, 120)[:, :, 0]
    blob = encode_image(gray, quality=85)
    back = decode_image(blob)
    assert back.shape == gray.shape
    print("gray ok  %.2f:1  psnr %.2f" % (gray.size / float(len(blob)),
                                          psnr(gray, back)))


if __name__ == "__main__":
    test_lossless()
    test_lossy()
    test_alpha()
    test_gray()
    print("all tests passed")
