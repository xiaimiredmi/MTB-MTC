import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from mtcodec import decode_image, encode_image, psnr

SRC = [
    (r"C:\Windows\Web\Screen\img100.jpg", "photo_a"),
    (r"C:\Windows\Web\Wallpaper\Theme1\img13.jpg", "photo_b"),
    (r"C:\Windows\Web\Wallpaper\Theme1\img3.jpg", "photo_c"),
    (r"C:\Windows\Web\4K\Wallpaper\Windows\img0_3840x2160.jpg", "render_d"),
]
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")
SIZE = 512

os.makedirs(OUT, exist_ok=True)
for path, name in SRC:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    crop = img.crop((left, top, left + side, top + side)).resize((SIZE, SIZE), Image.LANCZOS)
    out = os.path.join(OUT, f"{name}.png")
    crop.save(out)
    arr = np.array(crop)
    for q, sub in ((90, "420"), (60, "420"), (90, "444"), (60, "444")):
        t0 = time.perf_counter()
        blob = encode_image(arr, quality=q, subsample=sub)
        t1 = time.perf_counter()
        back = decode_image(blob)
        t2 = time.perf_counter()
        print(f"{name} q{q} {sub}: {len(blob)} bytes  bpp {len(blob) * 8 / arr.size:.3f}"
              f"  psnr {psnr(arr, back):.2f}  enc {t1 - t0:.2f}s dec {t2 - t1:.2f}s")
    t0 = time.perf_counter()
    blob = encode_image(arr, lossless=True)
    t1 = time.perf_counter()
    back = decode_image(blob)
    t2 = time.perf_counter()
    print(f"{name} lossless: {len(blob)} bytes  bpp {len(blob) * 8 / arr.size:.3f}"
          f"  exact {np.array_equal(arr, back)}  enc {t1 - t0:.2f}s dec {t2 - t1:.2f}s")
