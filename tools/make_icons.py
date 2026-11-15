import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "icons")
ICO_OUT = os.path.join(ROOT, "deploy", "icons")
CANON = 1024
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\seguisb.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw(color):
    img = Image.new("RGBA", (CANON, CANON), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        [0, 0, CANON - 1, CANON - 1], radius=int(CANON * 0.17), fill=color
    )
    font = load_font(int(CANON * 0.70))
    d.text((CANON / 2, CANON / 2 - CANON * 0.02), "M", font=font, anchor="mm",
           fill=(255, 255, 255, 255))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(ICO_OUT, exist_ok=True)
    specs = [
        ("mtb", (198, 40, 40, 255)),
        ("mtc", (21, 101, 192, 255)),
    ]
    for name, color in specs:
        master = draw(color)
        master.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, name + ".png"))
        master.save(os.path.join(ICO_OUT, name + ".ico"), format="ICO", sizes=ICO_SIZES)
        print("wrote", name, "png 512 (assets/icons) + ico (deploy/icons)", ICO_SIZES)


if __name__ == "__main__":
    main()
