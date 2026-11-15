import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, "tests", "_tmp_smoke")


def run(*args):
    cmd = [sys.executable, "-m", "mtcodec"] + list(args)
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        print("FAIL", " ".join(args))
        print(p.stdout.strip())
        print(p.stderr.strip())
        raise SystemExit(1)
    return p.stdout.strip()


def main():
    if os.path.isdir(TMP):
        shutil.rmtree(TMP)
    os.makedirs(TMP)

    src = os.path.join(ROOT, "testdata", "photo_b.png")
    arr = np.array(Image.open(src).convert("RGB"))

    pic = os.path.join(TMP, "out.mtb")
    print(run("encode", src, pic, "--quality", "80"))
    print(run("info", pic))
    back = os.path.join(TMP, "back.png")
    print(run("decode", pic, back))
    dec = np.array(Image.open(back).convert("RGB"))
    assert dec.shape == arr.shape, "shape mismatch"
    mse = float(np.mean((arr.astype(np.float64) - dec.astype(np.float64)) ** 2))
    psnr = 99.0 if mse == 0 else 10 * np.log10(255 ** 2 / mse)
    print("roundtrip psnr %.2f dB" % psnr)
    assert psnr > 30.0, "quality too low"

    loss = os.path.join(TMP, "loss.mtb")
    print(run("encode", src, loss, "--lossless"))
    back2 = os.path.join(TMP, "back_loss.png")
    print(run("decode", loss, back2))
    assert np.array_equal(arr, np.array(Image.open(back2).convert("RGB"))), "lossless mismatch"
    print("lossless bit-exact")

    frames = os.path.join(TMP, "frames")
    os.makedirs(frames)
    base = np.array(Image.open(os.path.join(ROOT, "testdata", "photo_a.png")).convert("RGB"))
    for i in range(8):
        dx = i * 3
        frames_arr = base[100:356, 100 + dx:356 + dx]
        Image.fromarray(frames_arr.copy()).save(os.path.join(frames, "frame_%04d.png" % i))

    vid = os.path.join(TMP, "out.mtc")
    print(run("video-encode", frames, vid, "--quality", "80", "--gop", "4"))
    print(run("video-info", vid))
    out_frames = os.path.join(TMP, "frames_out")
    print(run("video-decode", vid, out_frames))
    got = sorted(f for f in os.listdir(out_frames) if f.endswith(".png"))
    assert len(got) == 8, "frame count mismatch %d" % len(got)
    print("video frames decoded", len(got))
    print("PASS")


if __name__ == "__main__":
    main()
