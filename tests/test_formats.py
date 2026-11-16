import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
from PIL import Image

from mtcodec import decode_image, encode_image, probe
from mtcodec import io_bridge


def _photo(w=240, h=180, alpha=False):
    y, x = np.mgrid[0:h, 0:w]
    r = (x * 255 // max(1, w - 1)).astype(np.uint8)
    g = (y * 255 // max(1, h - 1)).astype(np.uint8)
    b = ((x + y) * 255 // max(1, w + h - 2)).astype(np.uint8)
    arr = np.stack([r, g, b], axis=2)
    if alpha:
        a = (x * 255 // max(1, w - 1)).astype(np.uint8)
        arr = np.dstack([arr, a])
    return arr


def test_formats():
    tmp = tempfile.mkdtemp(prefix="mtc_fmt_")
    arr = _photo()
    try:
        for ext, kw in ((".png", {}), (".jpg", {"quality": 95}),
                        (".bmp", {}), (".webp", {"quality": 95})):
            p = os.path.join(tmp, "in" + ext)
            Image.fromarray(arr).save(p, **kw)
            frames, has_alpha, src = io_bridge.load_image_frames(p)
            assert frames[0].shape[:2] == arr.shape[:2]
            blob = encode_image(frames[0], quality=80, subsample="420")
            back = decode_image(blob)
            assert back.shape[:2] == arr.shape[:2]
            print("%-5s -> mtc  %d bytes  %dx%d" % (ext, len(blob), src[0], src[1]))

        rgba = _photo(alpha=True)
        p = os.path.join(tmp, "a.png")
        Image.fromarray(rgba).save(p)
        frames, has_alpha, _ = io_bridge.load_image_frames(p)
        assert has_alpha
        blob = encode_image(frames[0], quality=85, subsample="420")
        back = decode_image(blob)
        assert np.array_equal(back[:, :, 3], rgba[:, :, 3])
        print("rgba -> mtc  %d bytes  alpha exact" % len(blob))

        imgs = [Image.fromarray(_photo()).rotate(90 * i) for i in range(2)]
        p = os.path.join(tmp, "anim.png")
        imgs[0].save(p, save_all=True, append_images=imgs[1:], duration=80, loop=0)
        frames, _, _ = io_bridge.load_image_frames(p)
        assert len(frames) == 2
        print("apng frames", len(frames))
    finally:
        for name in os.listdir(tmp):
            os.remove(os.path.join(tmp, name))
        os.rmdir(tmp)


def test_probe():
    arr = _photo()
    blob = encode_image(arr, quality=70, subsample="420")
    info = probe(blob)
    assert info["magic"] == "MTB1"
    assert info["width"] == arr.shape[1]
    assert info["height"] == arr.shape[0]
    assert info["quality"] == 70
    print("probe ok", info["width"], "x", info["height"])


if __name__ == "__main__":
    test_formats()
    test_probe()
    print("format tests passed")
