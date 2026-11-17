"""Crop the Windows wallpapers into the fixed test set used for measurements.

Run once on the build machine; the PNGs land in rust/bench/data and are the
same 512x512 crops the Python bench used, plus one wide 2048x1152 frame for
timing.
"""

import os

from PIL import Image

SRC = [
    (r"C:\Windows\Web\Screen\img100.jpg", "photo_a"),
    (r"C:\Windows\Web\Wallpaper\Theme1\img13.jpg", "photo_b"),
    (r"C:\Windows\Web\Wallpaper\Theme1\img3.jpg", "photo_c"),
    (r"C:\Windows\Web\4K\Wallpaper\Windows\img0_3840x2160.jpg", "render_d"),
]

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def main():
    os.makedirs(OUT, exist_ok=True)
    for path, name in SRC:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        crop = img.crop((left, top, left + side, top + side)).resize((512, 512), Image.LANCZOS)
        crop.save(os.path.join(OUT, name + ".png"))
        print(name, crop.size)
    img = Image.open(SRC[2][0]).convert("RGB").resize((2048, 1152), Image.LANCZOS)
    img.save(os.path.join(OUT, "wide_2048.png"))
    print("wide_2048", img.size)


if __name__ == "__main__":
    main()
