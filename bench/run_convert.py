import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from mtcodec import decode_image, decode_video, encode_image, encode_video, probe, probe_video
from mtcodec import io_bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL = r"C:\Users\Administrator\Downloads"
OUT = os.path.join(ROOT, "results", "convert_results.json")
OUTDIR = os.path.join(ROOT, "samples", "converted")
SIZES = ["orig", "1080p", "720p", "480p", "360p", "4k", "4x4k"]


def _psnr_rgb(a, b):
    a = a[:, :, :3].astype(np.float64) if a.ndim == 3 else a.astype(np.float64)
    b = b[:, :, :3].astype(np.float64) if b.ndim == 3 else b.astype(np.float64)
    mse = float(np.mean((a - b) ** 2))
    return 99.0 if mse == 0 else 10.0 * np.log10(255.0 ** 2 / mse)


def log(*a):
    print(*a)
    sys.stdout.flush()


def run_images():
    rows = []
    pics = sorted(f for f in os.listdir(DL)
                  if f.lower().startswith("w") and f.lower().endswith(".png"))
    log("=== images: %d ===" % len(pics))
    for name in pics:
        path = os.path.join(DL, name)
        frames, has_alpha, src = io_bridge.load_image_frames(path)
        t0 = time.perf_counter()
        blob = encode_image(frames[0], quality=80)
        enc = time.perf_counter() - t0
        t0 = time.perf_counter()
        back = decode_image(blob)
        dec = time.perf_counter() - t0
        raw = frames[0].size * frames[0].dtype.itemsize
        row = {
            "file": name,
            "size": list(src),
            "alpha_in": bool(has_alpha),
            "alpha_out": probe(blob)["has_alpha"],
            "bytes": len(blob),
            "ratio": raw / len(blob),
            "psnr": _psnr_rgb(frames[0], back),
            "enc_s": enc,
            "dec_s": dec,
            "png_bytes": os.path.getsize(path),
        }
        rows.append(row)
        log("%-52s %5dx%-5d png %6.2fMB -> mtb %7.1fKB  %.2f:1  psnr %.1f  enc %.2fs dec %.2fs"
            % (name, src[0], src[1], row["png_bytes"] / 1e6, len(blob) / 1024.0,
               row["ratio"], row["psnr"], enc, dec))
    return rows


def run_sizes():
    """一张最大的图，跑全部尺寸档，验证"各种分辨率各种大小"。"""
    pics = sorted((f for f in os.listdir(DL) if f.lower().startswith("w")), key=lambda n: 0)
    big = max(pics, key=lambda n: os.path.getsize(os.path.join(DL, n)))
    log("=== size ladder on %s ===" % big)
    rows = []
    for spec in SIZES:
        frames, has_alpha, src = io_bridge.load_image_frames(os.path.join(DL, big), spec)
        t0 = time.perf_counter()
        blob = encode_image(frames[0], quality=80)
        enc = time.perf_counter() - t0
        back = decode_image(blob)
        out_size = [frames[0].shape[1], frames[0].shape[0]]
        raw = frames[0].size * frames[0].dtype.itemsize
        rows.append({
            "spec": spec, "out": out_size, "bytes": len(blob),
            "ratio": raw / len(blob), "psnr": _psnr_rgb(frames[0], back), "enc_s": enc,
        })
        log("%-7s -> %5dx%-5d  %7.1fKB  %.2f:1  psnr %.1f  enc %.2fs"
            % (spec, out_size[0], out_size[1], len(blob) / 1024.0,
               raw / len(blob), rows[-1]["psnr"], enc))
    return big, rows


def run_apng(src_path):
    """PNG 动图（APNG）：本机生成一个 8 帧 APNG，再转 .mtc。"""
    log("=== APNG ===")
    frames, has_alpha, src = io_bridge.load_image_frames(src_path, "720p")
    base = Image.fromarray(frames[0][:, :, :3]).resize((320, 180), Image.LANCZOS)
    seq = []
    for i in range(8):
        f = base.copy()
        arr = np.array(f)
        arr[:, int(i * 40): int(i * 40) + 6] = [230, 60, 60]
        f = Image.fromarray(arr, mode="RGB")
        seq.append(f)
    tmp = os.path.join(os.environ.get("TEMP", "."), "mtcodec_w.apng")
    seq[0].save(tmp, save_all=True, append_images=seq[1:], duration=90, loop=0)
    loaded, alpha, ssz = io_bridge.load_image_frames(tmp)
    t0 = time.perf_counter()
    blob = encode_video([f[:, :, :3] for f in loaded], quality=80, fps=11, gop=8)
    enc = time.perf_counter() - t0
    out, stats = decode_video(blob)
    info = probe_video(blob)
    log("apng %dx%d %d frames -> mtc %d frames %d bytes  %.2fs"
        % (ssz[0], ssz[1], len(loaded), len(out), len(blob), enc))
    os.remove(tmp)
    return {"apng_frames": len(loaded), "mtc_frames": len(out), "bytes": len(blob),
            "size": list(ssz), "enc_s": enc, "has_audio": info["has_audio"]}


def run_videos():
    rows = []
    vids = sorted(f for f in os.listdir(DL)
                  if os.path.splitext(f)[1].lower() in io_bridge.VIDEO_EXTS)
    log("=== videos: %d ===" % len(vids))
    for name in vids:
        path = os.path.join(DL, name)
        t0 = time.perf_counter()
        frames, size = io_bridge.load_video_frames(path, fps=12, size_spec="720p",
                                                   max_frames=12, start=0)
        audio = io_bridge.load_audio_wav(path, seconds=1.0)
        blob = encode_video(frames, quality=80, fps=12, gop=12, audio=audio)
        enc = time.perf_counter() - t0
        got = {}
        t0 = time.perf_counter()
        out, stats = decode_video(blob, collect=got)
        dec = time.perf_counter() - t0
        info = probe_video(blob)
        mtc = os.path.join(OUTDIR, os.path.splitext(name)[0][:40] + ".mtc")
        with open(mtc, "wb") as f:
            f.write(blob)
        raw = sum(f.size for f in frames)
        row = {
            "file": name,
            "src_bytes": os.path.getsize(path),
            "frames": len(frames),
            "size": list(size),
            "mtc_bytes": len(blob),
            "ratio": raw / len(blob),
            "audio_bytes": len(got.get("audio", b"")),
            "has_audio": info["has_audio"],
            "enc_s": enc,
            "dec_s": dec,
            "mtc_path": os.path.relpath(mtc, ROOT),
            "psnr_first": _psnr_rgb(frames[0], out[0]),
        }
        # 反向验证：MTC -> MP4（带音轨）
        mp4 = os.path.join(OUTDIR, os.path.splitext(name)[0][:40] + "_back.mp4")
        io_bridge.export_mp4(out, mp4, fps=got.get("fps") or 12.0,
                             wav_bytes=got.get("audio", b""))
        row["mp4_bytes"] = os.path.getsize(mp4)
        row["mp4_path"] = os.path.relpath(mp4, ROOT)
        back_size = io_bridge.probe_video(mp4)
        row["mp4_size"] = list(back_size)
        rows.append(row)
        log("%-46s %5.1fMB -> %d frames %dx%d  mtc %7.1fKB (%.2f:1) audio %5d  enc %.1fs dec %.1fs  -> mp4 %.1fKB %dx%d"
            % (name, row["src_bytes"] / 1e6, len(frames), size[0], size[1],
               len(blob) / 1024.0, row["ratio"], len(got.get("audio", b"")), enc, dec,
               row["mp4_bytes"] / 1024.0, back_size[0], back_size[1]))
    return rows


def run_alpha(src_path):
    """图片透明：从实拍壁纸抠一个圆形透明区，转 MTB 再导回 PNG，验证 alpha 保真。"""
    log("=== alpha ===")
    frames, has_alpha, src = io_bridge.load_image_frames(src_path, "1080p")
    rgb = frames[0][:, :, :3]
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    r = min(h, w) / 3.0
    dist = np.sqrt((yy - h / 2.0) ** 2 + (xx - w / 2.0) ** 2)
    a = np.clip((r - dist) / 2.0, 0, 255).astype(np.uint8)
    rgba = np.dstack([rgb, a])
    blob = encode_image(rgba, quality=80)
    back = decode_image(blob)
    png = os.path.join(OUTDIR, "alpha_roundtrip.png")
    io_bridge.save_image(back, png)
    reload = np.array(Image.open(png).convert("RGBA"))
    exact = np.array_equal(reload[:, :, 3], back[:, :, 3])
    info = probe(blob)
    log("rgba %dx%d -> mtb %d bytes  alpha flag=%s  png back %d bytes  alpha exact=%s"
        % (w, h, len(blob), info["has_alpha"], os.path.getsize(png), exact))
    return {"size": [w, h], "mtb_bytes": len(blob), "png_bytes": os.path.getsize(png),
            "has_alpha": info["has_alpha"], "alpha_exact": bool(exact),
            "png": os.path.relpath(png, ROOT)}


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    data = {}
    data["images"] = run_images()
    big, ladder = run_sizes()
    data["size_ladder"] = {"source": big, "rows": ladder}
    data["apng"] = run_apng(os.path.join(DL, big))
    data["videos"] = run_videos()
    data["alpha"] = run_alpha(os.path.join(DL, big))
    data["env"] = {"ffmpeg": io_bridge.ffmpeg_exe()}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log("wrote %s" % OUT)


if __name__ == "__main__":
    main()
