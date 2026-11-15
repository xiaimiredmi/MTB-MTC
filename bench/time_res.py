import os
import sys
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mtcodec import decode_image, encode_image, psnr

SRC = r"C:\Users\Administrator\Downloads\wallpaper_minecraft_bedrock_edition_1920x1080.png"


def run(arr, tag):
    t0 = time.perf_counter()
    blob = encode_image(arr, quality=80, subsample="420")
    enc = time.perf_counter() - t0
    t0 = time.perf_counter()
    back = decode_image(blob)
    dec = time.perf_counter() - t0
    bpp = len(blob) * 8.0 / arr[:, :, 0].size
    print("%-14s %5dx%-5d enc %6.2fs dec %6.2fs  %7.3f bpp  psnr %.2f  %.1f MB"
          % (tag, arr.shape[1], arr.shape[0], enc, dec, bpp, psnr(arr, back),
             len(blob) / 1024.0 / 1024.0))
    sys.stdout.flush()
    return blob


base = np.array(Image.open(SRC).convert("RGB"))
run(base, "1080p")

big = Image.open(SRC).convert("RGB").resize((3840, 2160), Image.LANCZOS)
run(np.array(big), "4K")

huge = Image.open(SRC).convert("RGB").resize((7680, 4320), Image.LANCZOS)
run(np.array(huge), "4x4K(8K)")
