# -*- coding: utf-8 -*-
"""H.264 backend for the MTC video container.

The in-house DCT + arithmetic-coding path encodes one frame at ~210 KB at
quality 85, roughly five times the size of x264 at comparable fidelity, and
decompresses at six frames per second. Motion compensation would have to be
followed by loop filters, sub-pixel search, B frames and CABAC before it came
close, which is not something to reimplement from scratch.

So the container keeps its job - one file holding video, audio and stills -
and the video payload is produced by x264 through ffmpeg, which is already on
this machine. Frames go over a pipe as raw RGB, the compressed Annex-B stream
comes back.
"""
import os
import shutil
import subprocess
import threading

import numpy as np

_FFMPEG = None


def ffmpeg_bin():
    global _FFMPEG
    if _FFMPEG is None:
        found = shutil.which("ffmpeg")
        if found:
            _FFMPEG = found
        else:
            cand = r"D:\ffmpeg-2026-11-05-git-0893feba65-essentials_build\bin\ffmpeg.exe"
            _FFMPEG = cand if os.path.exists(cand) else "ffmpeg"
    return _FFMPEG


def available():
    try:
        out = subprocess.run([ffmpeg_bin(), "-version"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=20)
        return out.returncode == 0
    except Exception:
        return False


def crf_for(quality):
    """Map the container's 0-100 quality onto an x264 CRF."""
    q = max(1, min(100, int(quality)))
    crf = int(round(18 + (100 - q) * 0.27))
    return max(16, min(40, crf))


def encode(frames, w, h, fps, quality=85, preset="veryfast", keyint=250):
    """Encode an iterable of RGB uint8 frames into an Annex-B H.264 stream."""
    crf = crf_for(quality)
    cmd = [
        ffmpeg_bin(), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h),
        "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-g", str(max(1, int(keyint))), "-pix_fmt", "yuv420p",
        "-f", "h264", "-",
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    chunks = []

    def drain():
        while True:
            data = proc.stdout.read(1 << 16)
            if not data:
                break
            chunks.append(data)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        for frame in frames:
            arr = np.ascontiguousarray(np.asarray(frame, dtype=np.uint8))
            if arr.shape[0] != h or arr.shape[1] != w:
                raise ValueError("frame is %dx%d, expected %dx%d"
                                 % (arr.shape[1], arr.shape[0], w, h))
            proc.stdin.write(arr.tobytes())
        proc.stdin.close()
    finally:
        proc.wait()
    reader.join(timeout=5)
    if proc.returncode not in (0, None):
        raise RuntimeError("ffmpeg encode failed (rc=%s)" % proc.returncode)
    return b"".join(chunks)


def decode(stream, w, h, fps, limit=None):
    """Decode an Annex-B stream back into RGB uint8 frames."""
    cmd = [
        ffmpeg_bin(), "-loglevel", "error",
        "-f", "h264", "-i", "-",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    frame_bytes = w * h * 3

    def feed():
        try:
            proc.stdin.write(stream)
            proc.stdin.close()
        except Exception:
            pass

    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    n = 0
    try:
        while True:
            if limit is not None and n >= limit:
                break
            raw = proc.stdout.read(frame_bytes)
            if not raw or len(raw) < frame_bytes:
                break
            yield np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3).copy()
            n += 1
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        writer.join(timeout=2)
