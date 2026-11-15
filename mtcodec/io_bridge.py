"""主流图片 / 视频格式与本项目 MTB / MTC 之间的互转。

图片：PNG / JPG / BMP / WEBP / GIF / APNG  ->  numpy 帧（可带 alpha）
视频：MP4 / MKV / MOV / AVI / WEBM         <->  ffmpeg 抽帧与合流（含音轨）
"""

import io
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image

SIZE_PRESETS = {
    "360p": (640, 360),
    "480p": (854, 480),
    "540p": (960, 540),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "2k": (2560, 1440),
    "4k": (3840, 2160),
    "4x4k": (7680, 4320),
    "8k": (7680, 4320),
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".apng", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv"}


def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def has_ffmpeg():
    return ffmpeg_exe() is not None


def parse_size(spec):
    """'1080p' / '1920x1080' / 'orig' -> (w, h) 或 None。"""
    if spec is None:
        return None
    s = str(spec).strip().lower()
    if s in ("", "orig", "native", "none", "0"):
        return None
    if s in SIZE_PRESETS:
        return SIZE_PRESETS[s]
    if "x" in s:
        w, h = s.split("x", 1)
        return int(w), int(h)
    raise ValueError("unknown size spec: %s" % spec)


def target_size(w, h, spec):
    """按比例缩放（不拉伸），竖图自动把预设宽高对调。"""
    box = parse_size(spec)
    if box is None:
        return w, h
    tw, th = box
    if h > w:
        tw, th = th, tw
    scale = min(tw / float(w), th / float(h))
    return max(1, int(round(w * scale))), max(1, int(round(h * scale)))


def resize_arr(arr, size):
    if size is None or (arr.shape[1], arr.shape[0]) == tuple(size):
        return arr
    mode = "RGBA" if arr.ndim == 3 and arr.shape[2] == 4 else "RGB"
    img = Image.fromarray(arr, mode=mode)
    return np.array(img.resize(tuple(size), Image.LANCZOS))


def _pil_mode(img):
    if img.mode in ("RGBA", "LA", "PA"):
        return "RGBA"
    if img.mode == "P" and "transparency" in img.info:
        return "RGBA"
    return "RGB"


def load_image_frames(path, size_spec=None):
    """读 PNG / JPG / WEBP / GIF / APNG，返回 (frames, has_alpha, source_size)。"""
    img = Image.open(path)
    n = getattr(img, "n_frames", 1) or 1
    src = img.size
    out = []
    for i in range(n):
        img.seek(i)
        tw, th = target_size(src[0], src[1], size_spec)
        frame = img.convert(_pil_mode(img))
        if (tw, th) != src:
            frame = frame.resize((tw, th), Image.LANCZOS)
        out.append(np.array(frame))
    has_alpha = out[0].ndim == 3 and out[0].shape[2] == 4
    return out, has_alpha, src


def probe_video(path):
    ff = ffmpeg_exe()
    if ff is None:
        raise RuntimeError("需要 ffmpeg 才能处理视频：请把 ffmpeg 加进 PATH")
    res = subprocess.run(
        [ff, "-v", "error", "-i", path, "-frames:v", "1", "-f", "image2pipe",
         "-vcodec", "png", "-"],
        capture_output=True,
    )
    if not res.stdout:
        raise RuntimeError("ffmpeg 无法解码这个视频：%s" % res.stderr.decode("utf-8", "replace")[:200])
    img = Image.open(io.BytesIO(res.stdout))
    return img.size


def load_video_frames(path, fps=12, size_spec=None, max_frames=24, start=0):
    """用 ffmpeg 的 rawvideo 管道抽帧，返回 (frames, (w, h))。"""
    ff = ffmpeg_exe()
    if ff is None:
        raise RuntimeError("需要 ffmpeg 才能处理视频：请把 ffmpeg 加进 PATH")
    src_w, src_h = probe_video(path)
    tw, th = target_size(src_w, src_h, size_spec)
    tw, th = tw - tw % 2, th - th % 2
    vf = "fps=%s,scale=%d:%d:flags=lanczos" % (fps, tw, th)
    cmd = [ff, "-v", "error", "-ss", str(start), "-i", path, "-vf", vf,
           "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_bytes = tw * th * 3
    frames = []
    try:
        while len(frames) < max_frames:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            frames.append(np.frombuffer(buf, np.uint8).reshape((th, tw, 3)).copy())
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        err = proc.stderr.read()
        proc.stderr.close()
        proc.wait()
    if not frames:
        raise RuntimeError("抽帧失败：%s" % err.decode("utf-8", "replace")[:200])
    return frames, (tw, th)


def video_target_size(path, size_spec=None):
    """Even-rounded target size, identical to what the frame loaders use."""
    src_w, src_h = probe_video(path)
    tw, th = target_size(src_w, src_h, size_spec)
    return tw - tw % 2, th - th % 2


def iter_video_frames(path, fps=12, size_spec=None, max_frames=None, start=0):
    """Yield frames one at a time so a long clip never has to fit in RAM."""
    ff = ffmpeg_exe()
    if ff is None:
        raise RuntimeError("需要 ffmpeg 才能处理视频：请把 ffmpeg 加进 PATH")
    src_w, src_h = probe_video(path)
    tw, th = target_size(src_w, src_h, size_spec)
    tw, th = tw - tw % 2, th - th % 2
    if (tw, th) == (src_w, src_h):
        vf = "fps=%s" % fps
    else:
        vf = "fps=%s,scale=%d:%d:flags=lanczos" % (fps, tw, th)
    cmd = [ff, "-v", "error", "-ss", str(start), "-i", path, "-vf", vf,
           "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    frame_bytes = tw * th * 3
    n = 0
    try:
        while max_frames is None or max_frames <= 0 or n < max_frames:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            yield np.frombuffer(buf, np.uint8).reshape((th, tw, 3)).copy()
            n += 1
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass
        proc.wait()


def load_audio_wav(path, seconds=3.0):
    """抽音轨并统一成 44.1k 立体声 16bit WAV 字节；没有音轨返回 b''。"""
    ff = ffmpeg_exe()
    if ff is None:
        return b""
    cmd = [ff, "-v", "error", "-i", path, "-vn", "-t", str(seconds),
           "-ac", "2", "-ar", "44100", "-f", "wav", "-"]
    res = subprocess.run(cmd, capture_output=True)
    data = res.stdout
    if len(data) <= 44:
        return b""
    return data


def save_wav_file(wav_bytes, path):
    with open(path, "wb") as f:
        f.write(wav_bytes)


def save_image(arr, path, quality=95):
    ext = os.path.splitext(path)[1].lower()
    img = Image.fromarray(arr)
    if ext in (".jpg", ".jpeg") and img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    if ext in (".jpg", ".jpeg"):
        img.save(path, quality=quality, subsampling=0)
    else:
        img.save(path)


def export_mp4(frames, out_path, fps=12.0, wav_bytes=b"", quality_crf=23):
    ff = ffmpeg_exe()
    if ff is None:
        raise RuntimeError("需要 ffmpeg 才能导出 MP4：请把 ffmpeg 加进 PATH")
    tmp = tempfile.mkdtemp(prefix="mtexp_")
    try:
        for i, fr in enumerate(frames):
            rgb = fr[:, :, :3] if fr.ndim == 3 and fr.shape[2] == 4 else fr
            Image.fromarray(rgb).save(os.path.join(tmp, "f_%05d.png" % i))
        cmd = [ff, "-y", "-v", "error",
               "-framerate", str(fps), "-i", os.path.join(tmp, "f_%05d.png")]
        wavpath = None
        if wav_bytes:
            wavpath = os.path.join(tmp, "a.wav")
            save_wav_file(wav_bytes, wavpath)
            cmd += ["-i", wavpath]
        cmd += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v", "libx264", "-crf", str(quality_crf), "-pix_fmt", "yuv420p"]
        if wavpath:
            cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
        cmd += [out_path]
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode != 0:
            raise RuntimeError("ffmpeg 导出失败：%s" % res.stderr.decode("utf-8", "replace")[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def export_frames(frames, out_dir, prefix="frame"):
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for i, fr in enumerate(frames):
        p = os.path.join(out_dir, "%s_%04d.png" % (prefix, i))
        save_image(fr, p)
        paths.append(p)
    return paths
