# -*- coding: utf-8 -*-
"""MTB / MTC 播放器。

功能：播放 / 暂停、进度拖动、倍速（0.5x / 1x / 1.5x / 2x）、音量、
循环播放、播完关闭。只依赖标准库 + numpy + Pillow：

- 音频在 Windows 走 winsound，Linux 走 aplay，macOS 走 afplay；
- 倍速与音量通过把 PCM 重采样 / 加增益后重写临时 WAV 实现，
  所以不需要 pygame、sounddevice 这类额外依赖；
- 画面用单调时钟排程（不是每帧 after(fixed)），长时间播放不会越走越慢；
- 帧图按需生成 PhotoImage 并做 LRU 缓存，避免一次占几百 MB。
"""
import io
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave

import numpy as np
from PIL import Image, ImageTk

from .image_codec import MAGIC as IMAGE_MAGIC
from .image_codec import decode_image
from .video_codec import VID_MAGIC as VIDEO_MAGIC
from .video_codec import _parse_heads, decode_video, iter_frames

MAX_W = int(os.environ.get("MTCODEC_VIEWER_MAX_W", "0") or 0)
MAX_H = int(os.environ.get("MTCODEC_VIEWER_MAX_H", "0") or 0)
# 0 keeps decoded frames at native size, which is what sharp zoom needs.
# A positive value still caps the stored frames for very large clips.
MAX_SIDE = int(os.environ.get("MTCODEC_VIEWER_MAX_SIDE", "0") or 0)
DEFAULT_FPS = 24.0
CACHE_LIMIT = 24

# Light theme: every surface is white or near-white, including the letterbox
# around the picture. Text is a dark neutral; the single accent is a warm pink
# that reads against white without turning the window colourless.
BG = "#FFFFFF"
BAR_BG = "#F7F7F8"
CANVAS_BG = "#FFFFFF"
FG = "#1A1A1A"
DIM = "#6B6B6B"
TRACK = "#E6E6E9"
CHIP_BG = "#F1F1F3"
CHIP_HI = "#E5E5E9"
ACCENT = "#E8476B"
ACCENT_HI = "#F25C7C"
ACCENT_DARK = "#C22B4E"
ACCENT_SOFT = "#FDECF0"
ON_ACCENT = "#FFFFFF"
FONT = "Microsoft YaHei"
MONO = "Consolas"

SPEEDS = (0.5, 1.0, 1.5, 2.0)
FFMPEG = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def fmt_time(sec):
    """1:23 / 1:02:03 这样的读数，和网页播放器一致。"""
    try:
        total = int(max(0.0, float(sec)))
    except Exception:
        total = 0
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    """Tk 没有圆角矩形，用平滑多边形近似。"""
    r = min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def light_title_bar(root):
    """Force a light Windows caption so the window has no black chrome."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        if not hwnd:
            hwnd = root.winfo_id()
        off = ctypes.c_int(0)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(off), ctypes.sizeof(off))
        white = ctypes.c_int(0x00FFFFFF)
        ink = ctypes.c_int(0x001A1A1A)
        for attr, col in ((35, white), (36, ink)):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(col), ctypes.sizeof(col))
    except Exception:
        pass


def sniff(blob):
    magic = blob[:4]
    if magic == IMAGE_MAGIC:
        return "image"
    if magic == VIDEO_MAGIC:
        return "video"
    return None


def read_container(path):
    with open(path, "rb") as f:
        blob = f.read()
    kind = sniff(blob)
    if kind is None:
        raise ValueError("not an MTB or MTC container: %s" % path)
    return kind, blob


def display_frames(frames):
    """Keep decoded frames at native size unless MAX_SIDE asks for a cap.

    Zoom renders from these frames, so downscaling them here would make every
    zoomed-in view soft. MAX_SIDE=0 (the default) leaves them untouched.
    """
    if not frames or MAX_SIDE <= 0:
        return list(frames)
    h0, w0 = frames[0].shape[:2]
    cap = MAX_SIDE
    if MAX_W and MAX_H:
        cap = min(cap, max(MAX_W, MAX_H))
    scale = min(cap / float(max(w0, h0)), 1.0)
    if scale >= 1.0:
        return list(frames)
    w = max(1, int(round(w0 * scale)))
    h = max(1, int(round(h0 * scale)))
    return [np.asarray(Image.fromarray(arr).resize((w, h), Image.LANCZOS))
            for arr in frames]


class AudioTrack(object):
    """44.1k / 16bit PCM 音轨。倍速用 ffmpeg 的 atempo 滤镜做变速不变调。"""

    def __init__(self, wav_bytes=b""):
        self.rate = 44100
        self.channels = 2
        self.samples = None
        self._wav = wav_bytes
        self._cache = {}
        self._dir = None
        self._lock = threading.Lock()
        if not wav_bytes or len(wav_bytes) < 44:
            return
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                self.rate = wf.getframerate() or 44100
                self.channels = wf.getnchannels() or 1
                width = wf.getsampwidth()
                raw = wf.readframes(wf.getnframes())
            if width != 2 or not raw:
                return
            data = np.frombuffer(raw, dtype="<i2")
            if self.channels > 1:
                data = data.reshape(-1, self.channels)
            self.samples = data
        except Exception:
            self.samples = None

    def ok(self):
        return self.samples is not None and len(self.samples) > 0

    def duration(self):
        if not self.ok():
            return 0.0
        return len(self.samples) / float(self.rate)

    def stretched(self):
        """是否能用 atempo 做到不变调。"""
        return bool(FFMPEG) and self.ok()

    def _workdir(self):
        if self._dir is None:
            self._dir = tempfile.mkdtemp(prefix="mtcodec_audio_")
        return self._dir

    def _atempo(self, speed):
        """整条音轨变速不变调，返回 wav 路径；不可用时返回 None。"""
        if not FFMPEG or not self._wav:
            return None
        tag = ("%.3f" % speed).replace(".", "_")
        out = os.path.join(self._workdir(), "tempo_%s.wav" % tag)
        if os.path.isfile(out) and os.path.getsize(out) > 44:
            return out
        src = os.path.join(self._workdir(), "src.wav")
        if not os.path.isfile(src):
            with open(src, "wb") as f:
                f.write(self._wav)
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
               "-i", src, "-filter:a", "atempo=%.4f" % speed,
               "-ac", str(self.channels), "-ar", str(self.rate),
               "-f", "wav", out]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=600)
        except Exception:
            return None
        if proc.returncode != 0 or not os.path.isfile(out):
            return None
        return out

    def _linear(self, speed):
        """没有 ffmpeg 时的回退：线性插值，音调会跟着变。"""
        n = len(self.samples)
        count = max(1, int(round(n / float(speed))))
        pos = np.linspace(0, n - 1, count)
        base = np.floor(pos).astype(np.int64)
        nxt = np.clip(base + 1, 0, n - 1)
        frac = (pos - base).astype(np.float32)
        if self.samples.ndim == 2:
            frac = frac[:, None]
        a = self.samples[base].astype(np.float32)
        b = self.samples[nxt].astype(np.float32)
        return a + (b - a) * frac

    def _stretched(self, speed):
        key = round(float(speed), 3)
        got = self._cache.get(key)
        if got is not None:
            return got
        with self._lock:
            got = self._cache.get(key)
            if got is not None:
                return got
            if abs(key - 1.0) < 1e-6:
                arr = self.samples.astype(np.float32)
            else:
                arr = None
                path = self._atempo(key)
                if path:
                    try:
                        with wave.open(path, "rb") as wf:
                            raw = wf.readframes(wf.getnframes())
                        got = np.frombuffer(raw, dtype="<i2")
                        if self.channels > 1:
                            got = got.reshape(-1, self.channels)
                        arr = got.astype(np.float32)
                    except Exception:
                        arr = None
                if arr is None:
                    arr = self._linear(key)
            self._cache[key] = arr
            return arr

    def build(self, start_sec=0.0, speed=1.0, gain=1.0):
        if not self.ok():
            return b""
        arr = self._stretched(speed)
        if arr is None or len(arr) == 0:
            return b""
        i0 = int(max(0.0, start_sec) * self.rate)
        if i0 >= len(arr):
            return b""
        seg = arr[i0:]
        if gain is not None and abs(gain - 1.0) > 1e-6:
            seg = seg * float(gain)
        seg = np.clip(seg, -32768, 32767).astype("<i2")

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.rate)
            wf.writeframes(seg.tobytes())
        return buf.getvalue()

    def cleanup(self):
        self._cache = {}
        if self._dir and os.path.isdir(self._dir):
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None


class AudioPlayer(object):
    """把 WAV 片段交给系统播放器，异步播放，可随时停止。"""

    def __init__(self):
        self.backend = None
        self.proc = None
        self.path = None
        self._winsound = None
        self._dir = None
        if sys.platform == "win32":
            try:
                import winsound
                self._winsound = winsound
                self.backend = "winsound"
            except Exception:
                self.backend = None
        elif sys.platform.startswith("linux"):
            if shutil.which("aplay"):
                self.backend = "aplay"
        elif sys.platform == "darwin":
            if shutil.which("afplay"):
                self.backend = "afplay"

    def available(self):
        return self.backend is not None

    def play(self, wav_bytes):
        self.stop()
        if not wav_bytes or self.backend is None:
            return False
        try:
            if self._dir is None:
                self._dir = tempfile.mkdtemp(prefix="mtcodec_play_")
            self.path = os.path.join(self._dir, "seg.wav")
            with open(self.path, "wb") as f:
                f.write(wav_bytes)
            if self.backend == "winsound":
                self._winsound.PlaySound(
                    self.path,
                    self._winsound.SND_FILENAME
                    | self._winsound.SND_ASYNC
                    | self._winsound.SND_NODEFAULT,
                )
            elif self.backend == "aplay":
                self.proc = subprocess.Popen(
                    ["aplay", "-q", self.path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                self.proc = subprocess.Popen(
                    ["afplay", self.path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            self.proc = None
            return False

    def stop(self):
        try:
            if self.backend == "winsound":
                self._winsound.PlaySound(None, self._winsound.SND_PURGE)
            elif self.proc is not None:
                self.proc.terminate()
                self.proc.wait(timeout=2)
        except Exception:
            pass
        self.proc = None

    def cleanup(self):
        self.stop()
        if self._dir and os.path.isdir(self._dir):
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None


class StreamFrames(object):
    """长片用：后台顺序解码，只留最近 window 帧，边解边放不爆内存。"""

    def __init__(self, blob, total, shape, fps, audio, window=24,
                 max_side=None, ready=6):
        self.count = int(total)
        self.shape = shape
        self.fps = float(fps or DEFAULT_FPS)
        self.audio = audio
        self.window = int(window)
        self.max_side = int(MAX_SIDE if max_side is None else max_side)
        self._frames = {}
        self._lock = threading.Lock()
        self.decoded = 0
        self.err = None
        self._ready = int(ready)
        self._pos = 0
        self._blob = blob
        self._th = threading.Thread(target=self._run)
        self._th.daemon = True
        self._th.start()

    def _shrink(self, rgb):
        side = self.max_side
        h, w = rgb.shape[:2]
        if side and max(h, w) > side:
            s = side / float(max(h, w))
            tw = max(1, int(round(w * s)))
            th = max(1, int(round(h * s)))
            return np.asarray(Image.fromarray(rgb).resize((tw, th), Image.BILINEAR))
        return rgb

    def _run(self):
        try:
            for i, rgb in enumerate(iter_frames(self._blob)):
                # 别跑得比播放位置快太多，否则刚解出来的帧马上被淘汰掉。
                while True:
                    with self._lock:
                        if i - self._pos <= self.window:
                            break
                    time.sleep(0.02)
                arr = self._shrink(rgb)
                with self._lock:
                    self._frames[i] = arr
                    self.decoded = i + 1
                    drop = i - self.window
                    if drop > self._pos:
                        drop = self._pos
                    for k in [k for k in self._frames if k < drop]:
                        del self._frames[k]
        except Exception as exc:
            self.err = exc

    def note_pos(self, idx):
        """播放器告诉解码线程自己播到哪了，淘汰线不能越过它。"""
        with self._lock:
            self._pos = int(idx)

    def resolve(self, idx):
        """返回 idx 本身，或能顶上的最近一帧（解码掉队时用）。"""
        with self._lock:
            idx = int(idx)
            if idx in self._frames:
                return idx
            if not self._frames:
                return None
            older = [k for k in self._frames if k <= idx]
            if older:
                return max(older)
            return min(self._frames)

    def ready(self, n=None):
        with self._lock:
            return self.decoded >= (self._ready if n is None else n)

    def get(self, idx):
        with self._lock:
            return self._frames.get(int(idx))


class Player(object):
    def __init__(self, root, frames, fps, audio_bytes, title):
        self.root = root
        self.frames = frames
        if isinstance(frames, StreamFrames):
            self._prov = frames
            self.count = int(frames.count)
            self._shape = frames.shape
            self.fps = float(frames.fps or DEFAULT_FPS)
        else:
            self._prov = None
            self.count = len(frames)
            self._shape = frames[0].shape[:2]
            self.fps = float(fps or DEFAULT_FPS)
        if self.fps <= 0:
            self.fps = DEFAULT_FPS
        self.duration = self.count / self.fps
        self.track = AudioTrack(audio_bytes)
        self.audio = AudioPlayer()

        self.pos = 0.0
        self.speed = 1.0
        self.gain = 1.0
        self.loop = False
        self.close_at_end = False
        self.playing = False
        self.job = None
        self.base_wall = time.monotonic()
        self.base_pos = 0.0
        self._dragging = False
        self._syncing = False
        self._cache = {}
        self._order = []
        self._mips = {}
        self._mip_order = []
        self._probe_idx = None
        self._photo_ref = None
        self.scale = 1.0
        self.pan = [0.0, 0.0]
        self._fit_mode = True
        self._drag = None
        self.volume = 100

        self._build_ui(title)
        self.show(0)
        self.start()

    # ---------- 界面 ----------
    def _play_button(self, parent, cmd, d=36):
        import tkinter as tk
        c = tk.Canvas(parent, width=d, height=d, bg=BAR_BG,
                      highlightthickness=0, cursor="hand2")
        ring = c.create_oval(0, 0, d, d, fill=ACCENT, outline="")
        c.bind("<Button-1>", lambda e: cmd())
        c.bind("<Enter>", lambda e: c.itemconfigure(ring, fill=ACCENT_HI))
        c.bind("<Leave>", lambda e: c.itemconfigure(ring, fill=ACCENT))
        self._play_cv = c
        self._play_d = d
        self._play_ico = []
        self._paint_play(True)
        return c

    def _paint_play(self, playing):
        c = getattr(self, "_play_cv", None)
        if c is None:
            return
        for it in getattr(self, "_play_ico", []):
            try:
                c.delete(it)
            except Exception:
                pass
        d = self._play_d
        cx = cy = d / 2.0
        self._play_ico = []
        if playing:
            self._play_ico.append(
                c.create_rectangle(cx - 7, cy - 7.5, cx - 2.4, cy + 7.5,
                                   fill=ON_ACCENT, outline=""))
            self._play_ico.append(
                c.create_rectangle(cx + 2.4, cy - 7.5, cx + 7, cy + 7.5,
                                   fill=ON_ACCENT, outline=""))
        else:
            self._play_ico.append(
                c.create_polygon(cx - 4.6, cy - 7.8, cx - 4.6, cy + 7.8,
                                 cx + 7.4, cy, fill=ON_ACCENT, outline=""))

    def _hover_pb(self, on):
        self._pb_hot = bool(on)
        self._draw_progress(self._shown_time())

    def _chip_hover(self, c, box, label, on):
        if getattr(c, "_on", False):
            return
        c.itemconfigure(box, fill=(CHIP_HI if on else CHIP_BG))
        c.itemconfigure(label, fill=(FG if on else DIM))

    def _chip(self, parent, text, cmd, w=54, h=26, primary=False):
        import tkinter as tk
        c = tk.Canvas(parent, width=w, height=h, bg=BAR_BG, highlightthickness=0,
                      cursor="hand2")
        box = round_rect(c, 0, 0, w, h, h / 2.0, fill=CHIP_BG,
                         outline=(ACCENT if primary else ""), width=1)
        label = c.create_text(w / 2.0, h / 2.0, text=text,
                              fill=(ACCENT_DARK if primary else DIM),
                              font=(FONT, 9, "bold" if primary else "normal"))
        c._on = bool(primary)
        c.bind("<Button-1>", lambda e: cmd())
        c.bind("<Enter>", lambda e: self._chip_hover(c, box, label, True))
        c.bind("<Leave>", lambda e: self._chip_hover(c, box, label, False))
        return c, box, label

    def _build_ui(self, title):
        import tkinter as tk

        for child in self.root.winfo_children():
            child.destroy()
        self.root.title(title)
        self.root.configure(bg=BG)
        self.root.minsize(780, 420)
        self._chips = []
        self._togs = []
        self._cur = 0
        self._pb_hot = False
        self._cache = {}
        self._order = []
        self._mips = {}
        self._mip_order = []
        self._probe_idx = None
        self._photo_ref = None
        self.scale = 1.0
        self.pan = [0.0, 0.0]
        self._fit_mode = True
        self._drag = None
        self.volume = 100

        hf, wf = self._shape
        try:
            sw = min(max(880, wf + 40), 1120)
            sh = int(round(sw * hf / float(wf))) + 170
            sw = min(sw, self.root.winfo_screenwidth() - 80)
            sh = min(sh, self.root.winfo_screenheight() - 130)
            self.root.geometry("%dx%d" % (sw, sh))
        except Exception:
            pass

        head = tk.Frame(self.root, bg=BG)
        head.pack(side="top", fill="x", padx=20, pady=(12, 2))

        mark = tk.Canvas(head, width=5, height=22, bg=BG, highlightthickness=0)
        round_rect(mark, 0, 1, 5, 21, 2.5, fill=ACCENT, outline="")
        mark.pack(side="left")

        tk.Label(head, text=title, bg=BG, fg=FG, anchor="w",
                 font=(FONT, 12, "bold")).pack(side="left", padx=(10, 0))
        meta = "%d×%d  ·  %d fps" % (wf, hf, int(round(self.fps)))
        tk.Label(head, text=meta, bg=BG, fg=DIM,
                 font=(FONT, 9)).pack(side="right", padx=(12, 0))
        self.zoom_label = tk.Label(head, text="适应 100%", bg=BG, fg=DIM,
                                   font=(MONO, 9), cursor="hand2")
        self.zoom_label.pack(side="right", padx=(12, 0))
        self.zoom_label.bind("<Button-1>", self.fit)

        # 控制条先 pack：pack 顺序决定空间分配，画面先占就会把控件挤没。
        bar = tk.Frame(self.root, bg=BAR_BG)
        bar.pack(side="bottom", fill="x")

        self.canvas = tk.Canvas(self.root, bg=CANVAS_BG, bd=0,
                                highlightthickness=0, cursor="arrow")
        self.canvas.pack(fill="both", expand=True)
        self._img_item = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<Double-Button-1>", self.fit)
        self.canvas.bind("<ButtonPress-1>", self._pan_start)
        self.canvas.bind("<B1-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-1>", self._pan_end)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._wheel_step(1, e))
        self.canvas.bind("<Button-5>", lambda e: self._wheel_step(-1, e))

        self.pb = tk.Canvas(bar, height=26, bg=BAR_BG, highlightthickness=0,
                            cursor="hand2")
        self.pb.pack(fill="x", padx=20, pady=(2, 0))
        self.pb.bind("<Button-1>", self._pb_press)
        self.pb.bind("<B1-Motion>", self._pb_drag)
        self.pb.bind("<ButtonRelease-1>", self._pb_release)
        self.pb.bind("<Configure>", lambda e: self._draw_progress(self._shown_time()))
        self.pb.bind("<Enter>", lambda e: self._hover_pb(True))
        self.pb.bind("<Leave>", lambda e: self._hover_pb(False))

        row = tk.Frame(bar, bg=BAR_BG)
        row.pack(fill="x", padx=20, pady=(8, 16))

        self.btn_play = self._play_button(row, self.toggle, 38)
        self.btn_play.pack(side="left")

        self.time_label = tk.Label(row, text="0:00 / %s" % fmt_time(self.duration),
                                   bg=BAR_BG, fg=FG, font=(MONO, 10))
        self.time_label.pack(side="left", padx=(12, 0))

        self.end_var = tk.BooleanVar(value=False)
        self.loop_var = tk.BooleanVar(value=False)
        self._toggle_chip(row, "播完关闭", self.end_var, self._on_end_close,
                          78).pack(side="right")
        self._toggle_chip(row, "循环", self.loop_var, self._on_loop,
                          52).pack(side="right", padx=(0, 6))

        self.vol_cv = tk.Canvas(row, width=84, height=24, bg=BAR_BG,
                                highlightthickness=0, cursor="hand2")
        self.vol_cv.pack(side="right", padx=(6, 12))
        self.vol_cv.bind("<Button-1>", self._vol_press)
        self.vol_cv.bind("<B1-Motion>", self._vol_drag)
        self.vol_cv.bind("<ButtonRelease-1>", self._vol_release)

        tk.Label(row, text="音量", bg=BAR_BG, fg=DIM,
                 font=(FONT, 9)).pack(side="right")

        tk.Frame(row, width=1, height=18, bg=TRACK).pack(side="right", padx=(0, 14))

        for sp in SPEEDS:
            self._speed_chip(row, sp).pack(side="left", padx=(3, 0))

        note = ""
        if not self.audio.available():
            note = "当前系统没有音频后端，只能静音播放"
        elif not self.track.ok():
            note = "这个文件没有音轨"
        elif not self.track.stretched():
            note = "没有找到 ffmpeg，倍速会连音调一起变"
        if note:
            tk.Label(bar, text=note, bg=BAR_BG, fg="#B26A00", anchor="w",
                     font=(FONT, 9)).pack(fill="x", padx=14, pady=(0, 8))

        self._paint_speeds()
        self._paint_toggles()
        self._draw_volume()

        self.root.bind("<space>", self.toggle)
        self.root.bind("<Escape>", lambda e: self.close())
        self.root.bind("<Left>", lambda e: self.nudge(-1.0))
        self.root.bind("<Right>", lambda e: self.nudge(1.0))
        self.root.bind("<Up>", lambda e: self.volume_step(10))
        self.root.bind("<Down>", lambda e: self.volume_step(-10))

    def _speed_chip(self, parent, speed):
        text = ("%gx" % speed)
        c, box, label = self._chip(
            parent, text, lambda s=speed: self._set_speed(s), 52, 26)
        self._chips.append((speed, c, box, label))
        return c

    def _paint_speeds(self):
        for speed, c, box, label in self._chips:
            on = abs(self.speed - speed) < 1e-6
            c._on = on
            c.itemconfigure(box, fill=(ACCENT_SOFT if on else CHIP_BG),
                            outline=(ACCENT if on else ""), width=(1 if on else 0))
            c.itemconfigure(label, fill=(ACCENT_DARK if on else DIM))

    def _toggle_chip(self, parent, text, var, cmd, w=52):
        def _hit():
            var.set(not var.get())
            cmd()

        c, box, label = self._chip(parent, text, _hit, w, 26)
        self._togs.append((c, box, var))
        return c

    def _paint_toggles(self):
        for c, box, var in self._togs:
            on = bool(var.get())
            c._on = on
            c.itemconfigure(box, fill=(ACCENT_SOFT if on else CHIP_BG),
                            outline=(ACCENT if on else ""), width=(1 if on else 0))
            for it in c.find_all():
                if c.type(it) == "text":
                    c.itemconfigure(it, fill=(ACCENT_DARK if on else DIM))

    # ---------- 画面与缩放 ----------
    def _viewport(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 8 or h <= 8:
            return (self._shape[1], self._shape[0])
        return (w, h)

    def _fit_scale(self):
        cw, ch = self._viewport()
        h0, w0 = self._shape
        if w0 <= 0 or h0 <= 0:
            return 1.0
        return min(cw / float(w0), ch / float(h0))

    def _clamp_pan(self):
        cw, ch = self._viewport()
        h0, w0 = self._shape
        sw = w0 * self.scale
        sh = h0 * self.scale
        if sw <= cw:
            self.pan[0] = (cw - sw) / 2.0
        else:
            self.pan[0] = min(0.0, max(cw - sw, self.pan[0]))
        if sh <= ch:
            self.pan[1] = (ch - sh) / 2.0
        else:
            self.pan[1] = min(0.0, max(ch - sh, self.pan[1]))

    def fit(self, _event=None):
        """把画面缩到窗口大小并居中。"""
        self.scale = self._fit_scale()
        self._fit_mode = True
        self._clamp_pan()
        self._render(force=True)
        return "break"

    def _zoom_at(self, cx, cy, factor):
        """以 (cx, cy) 为锚点缩放，光标下的像素保持不动。"""
        lo = self._fit_scale()
        hi = max(8.0, lo)
        old = self.scale if self.scale > 0 else lo
        new = min(max(old * factor, lo), hi)
        if abs(new - old) <= 1e-9:
            return
        sx = (cx - self.pan[0]) / old
        sy = (cy - self.pan[1]) / old
        self.scale = new
        self.pan[0] = cx - sx * new
        self.pan[1] = cy - sy * new
        self._fit_mode = False
        self._clamp_pan()
        self._render(force=True)

    def _on_wheel(self, event):
        if self.count == 0:
            return "break"
        d = int(event.delta)
        n = int(d / 120.0)
        if n == 0:
            n = 1 if d > 0 else -1
        self._zoom_at(event.x, event.y, 1.25 ** n)
        return "break"

    def _wheel_step(self, n, event):
        if self.count == 0:
            return "break"
        self._zoom_at(event.x, event.y, 1.25 ** n)
        return "break"

    def _pan_start(self, event):
        self._drag = (event.x, event.y)

    def _pan_move(self, event):
        if self._drag is None:
            return
        dx = event.x - self._drag[0]
        dy = event.y - self._drag[1]
        self._drag = (event.x, event.y)
        if not dx and not dy:
            return
        self.pan[0] += dx
        self.pan[1] += dy
        self._fit_mode = False
        self._clamp_pan()
        self._render()

    def _pan_end(self, _event=None):
        self._drag = None

    def _source(self, idx):
        if self._prov is not None:
            return self._prov.get(idx)
        try:
            return self.frames[idx]
        except Exception:
            return None

    def _trim_cache(self):
        while len(self._order) > CACHE_LIMIT:
            old = self._order.pop(0)
            self._cache.pop(old, None)

    def _mip(self, idx, arr):
        """Half-size copy of a frame, built once and kept for playback.

        A 1080p downscale to about 60% costs tens of milliseconds from the
        original; resizing this half-size copy instead is roughly three times
        cheaper and still sharp, because it is built by 2x2 area averaging.
        """
        got = self._mips.get(idx)
        if got is not None:
            return got
        img = Image.fromarray(arr).reduce(2)
        self._mips[idx] = img
        self._mip_order.append(idx)
        while len(self._mip_order) > CACHE_LIMIT:
            old = self._mip_order.pop(0)
            self._mips.pop(old, None)
        return img

    def _render(self, force=False):
        """按当前缩放画出可见区域。

        只裁出看得见的那一块再缩放，结果按 (帧, 目标矩形) 缓存。适应窗口
        播放时每帧仍然只生成一张 PhotoImage，缩放状态不会被每帧重建。
        """
        if self._probe_idx is None:
            return
        cw, ch = self._viewport()
        arr = self._source(self._probe_idx)
        if arr is None:
            return
        h0, w0 = arr.shape[:2]
        s = self.scale if self.scale > 0 else self._fit_scale()
        self.scale = s
        x0 = max(0, int(math.floor(-self.pan[0] / s)))
        y0 = max(0, int(math.floor(-self.pan[1] / s)))
        x1 = min(w0, int(math.ceil((cw - self.pan[0]) / s)))
        y1 = min(h0, int(math.ceil((ch - self.pan[1]) / s)))
        if x1 <= x0 or y1 <= y0:
            return
        tx0 = int(round(self.pan[0] + x0 * s))
        ty0 = int(round(self.pan[1] + y0 * s))
        tx1 = int(round(self.pan[0] + x1 * s))
        ty1 = int(round(self.pan[1] + y1 * s))
        tw = max(1, tx1 - tx0)
        th = max(1, ty1 - ty0)
        use_mip = 0.35 <= s <= 0.65 and w0 >= 64 and h0 >= 64
        key = (self._probe_idx, x0, y0, x1, y1, tw, th, use_mip)
        ph = self._cache.get(key)
        if ph is None or force:
            img = None
            resample = Image.BOX
            if use_mip:
                mip = self._mip(self._probe_idx, arr)
                mw, mh = mip.size
                mx0 = min(mw, x0 // 2)
                my0 = min(mh, y0 // 2)
                mx1 = min(mw, (x1 + 1) // 2)
                my1 = min(mh, (y1 + 1) // 2)
                mx1 = max(mx0 + 1, mx1)
                my1 = max(my0 + 1, my1)
                img = mip.crop((mx0, my0, mx1, my1))
                ratio = s / 0.5
                resample = Image.BOX if ratio <= 1.2 else Image.BICUBIC
            else:
                img = Image.fromarray(arr[y0:y1, x0:x1])
                # BOX is an area average, so shrinking stays clean and costs
                # about half of LANCZOS; zoomed-in frames keep their pixels.
                resample = Image.BILINEAR if s >= 1.0 else Image.BOX
            if img.size != (tw, th):
                img = img.resize((tw, th), resample)
            ph = ImageTk.PhotoImage(img)
            self._cache[key] = ph
            if key in self._order:
                self._order.remove(key)
            self._order.append(key)
            self._trim_cache()
        self._photo_ref = ph
        self.canvas.itemconfigure(self._img_item, image=ph)
        self.canvas.coords(self._img_item, tx0, ty0)
        self._cur = self._probe_idx
        pct = int(round(s * 100.0))
        if self._fit_mode:
            self.zoom_label.configure(text="适应 %d%%" % pct)
        else:
            self.zoom_label.configure(text="缩放 %d%%" % pct)

    def _prefetch(self, idx):
        """Build the next half-size copy while the current frame is on screen."""
        if idx < 0 or idx >= self.count or idx in self._mips:
            return
        arr = self._source(idx)
        if arr is not None:
            try:
                self._mip(idx, arr)
            except Exception:
                pass

    def show(self, idx):
        if self.count == 0:
            return False
        idx = int(max(0, min(self.count - 1, idx)))
        got = idx
        if self._prov is not None:
            got = self._prov.resolve(idx)
            if got is None:
                return False
        self._probe_idx = got
        self._render()
        return True

    def _on_canvas_resize(self, _event=None):
        if not self.count or self._probe_idx is None:
            return
        if self._fit_mode:
            self.scale = self._fit_scale()
        else:
            self.scale = max(self.scale, self._fit_scale())
        self._clamp_pan()
        self._render()

    def _shown_time(self):
        return self.pos if not self.playing else self.elapsed()

    def _draw_progress(self, t):
        c = self.pb
        W = c.winfo_width() or 600
        H = 26
        mid = H / 2.0
        c.delete("all")
        x0, x1 = 6, W - 6
        if x1 <= x0:
            return
        round_rect(c, x0, mid - 1.5, x1, mid + 1.5, 1.5, fill=TRACK, outline="")
        frac = 0.0 if not self.duration else min(1.0, max(0.0, t / self.duration))
        x = x0 + (x1 - x0) * frac
        if frac > 0.002:
            round_rect(c, x0, mid - 1.5, x, mid + 1.5, 1.5,
                       fill=ACCENT, outline="")
        r = 7.0 if getattr(self, "_pb_hot", False) else 5.0
        c.create_oval(x - r, mid - r, x + r, mid + r, fill=ACCENT,
                      outline=ON_ACCENT, width=2)

    def _update_bar(self, t):
        self._draw_progress(t)
        self.time_label.configure(
            text="%s / %s" % (fmt_time(t), fmt_time(self.duration)))

    # ---------- 时钟 ----------
    def elapsed(self):
        if not self.playing:
            return self.pos
        return self.base_pos + (time.monotonic() - self.base_wall) * self.speed

    def _schedule(self, delay):
        if self.job is not None:
            self.root.after_cancel(self.job)
        self.job = self.root.after(max(1, int(delay * 1000)), self._tick)

    def _tick(self):
        self.job = None
        if not self.playing:
            return
        t = self.elapsed()
        if t >= self.duration:
            self._on_end()
            return
        idx = int(t * self.fps)
        if self._prov is not None:
            self._prov.note_pos(idx)
        if not self.show(idx):
            # 解码还没追上：时间照走，画面等下一次补上，别把时钟卡住。
            self._update_bar(t)
            self._schedule(0.05)
            return
        self._update_bar(t)
        if self._prov is None:
            self.root.after_idle(self._prefetch, idx + 1)
        nxt = (idx + 1) / self.fps
        delay = (nxt - t) / self.speed
        if delay < 0.001:
            delay = 0.001
        self._schedule(delay)

    def start(self):
        self.playing = True
        self.base_pos = self.pos
        self.base_wall = time.monotonic()
        self._set_play_label("暂停")
        self._play_audio(self.pos)
        self._schedule(0.0)

    def pause(self):
        self.pos = min(self.duration, self.elapsed())
        self.playing = False
        self._set_play_label("播放")
        if self.job is not None:
            try:
                self.root.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        self.audio.stop()
        self._update_bar(self.pos)

    def toggle(self, _event=None):
        if self.playing:
            self.pause()
        else:
            if self.pos >= self.duration:
                self.pos = 0.0
                self.show(0)
            self.start()
        return "break"

    def _set_play_label(self, text):
        self._paint_play(str(text).startswith("暂停"))

    def _play_audio(self, start_sec):
        if not self.track.ok() or not self.audio.available():
            return
        self._audio_seq = getattr(self, "_audio_seq", 0) + 1
        seq = self._audio_seq
        speed, gain = self.speed, self.gain

        def _worker():
            try:
                wav = self.track.build(start_sec, speed, gain)
            except Exception:
                return
            if seq != self._audio_seq:
                return
            try:
                self.audio.play(wav)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _on_end(self):
        if self.loop:
            self.pos = 0.0
            self.show(0)
            self.base_pos = 0.0
            self.base_wall = time.monotonic()
            self._play_audio(0.0)
            self._update_bar(0.0)
            self._schedule(0.0)
            return
        if self.close_at_end:
            self.close()
            return
        self.playing = False
        self.pos = self.duration
        self._set_play_label("播放")
        self.audio.stop()
        self.show(self.count - 1)
        self._update_bar(self.duration)

    # ---------- 进度条与交互 ----------
    def _pb_time(self, event):
        W = self.pb.winfo_width() or 600
        frac = min(1.0, max(0.0, (float(event.x) - 2.0) / max(1.0, W - 4.0)))
        return frac * self.duration

    def _pb_press(self, event):
        self._dragging = True
        t = self._pb_time(event)
        self._draw_progress(t)
        self.time_label.configure(
            text="%s / %s" % (fmt_time(t), fmt_time(self.duration)))
        return "break"

    def _pb_drag(self, event):
        t = self._pb_time(event)
        self._draw_progress(t)
        self.time_label.configure(
            text="%s / %s" % (fmt_time(t), fmt_time(self.duration)))
        return "break"

    def _pb_release(self, event):
        self._dragging = False
        self.seek(self._pb_time(event))
        return "break"

    def seek(self, sec):
        self.pos = min(self.duration, max(0.0, float(sec)))
        self.show(int(self.pos * self.fps))
        self._update_bar(self.pos)
        if self.playing:
            self.base_pos = self.pos
            self.base_wall = time.monotonic()
            self._play_audio(self.pos)
            self._schedule(0.0)

    def nudge(self, delta):
        self.seek(self.elapsed() + delta)
        return "break"

    def _set_speed(self, speed):
        self.speed = float(speed)
        self._paint_speeds()
        if self.playing:
            self.pos = self.elapsed()
            self.base_pos = self.pos
            self.base_wall = time.monotonic()
            self._play_audio(self.pos)

    def _draw_volume(self):
        c = getattr(self, "vol_cv", None)
        if c is None:
            return
        c.delete("all")
        W = int(c["width"])
        H = int(c["height"])
        mid = H / 2.0
        x0, x1 = 7, W - 7
        round_rect(c, x0, mid - 1.5, x1, mid + 1.5, 1.5, fill=TRACK, outline="")
        frac = max(0.0, min(1.0, self.volume / 100.0))
        x = x0 + (x1 - x0) * frac
        if frac > 0.002:
            round_rect(c, x0, mid - 1.5, x, mid + 1.5, 1.5,
                       fill=ACCENT, outline="")
        r = 5.5
        c.create_oval(x - r, mid - r, x + r, mid + r, fill=ACCENT,
                      outline=ON_ACCENT, width=2)

    def _vol_from_x(self, x):
        W = int(self.vol_cv["width"])
        f = (float(x) - 7.0) / max(1.0, W - 14)
        return int(round(min(1.0, max(0.0, f)) * 100.0))

    def _set_volume(self, value, restart=True):
        self.volume = int(max(0, min(100, int(value))))
        self.gain = self.volume / 100.0
        self._draw_volume()
        if restart and self.playing:
            self.pos = self.elapsed()
            self.base_pos = self.pos
            self.base_wall = time.monotonic()
            self._play_audio(self.pos)

    def _vol_press(self, event):
        self._set_volume(self._vol_from_x(event.x), restart=False)
        return "break"

    def _vol_drag(self, event):
        self._set_volume(self._vol_from_x(event.x), restart=False)
        return "break"

    def _vol_release(self, event):
        self._set_volume(self._vol_from_x(event.x), restart=True)
        return "break"

    def volume_step(self, delta):
        self._set_volume(self.volume + delta)
        return "break"

    def _on_loop(self):
        self.loop = bool(self.loop_var.get())
        self._paint_toggles()

    def _on_end_close(self):
        self.close_at_end = bool(self.end_var.get())
        self._paint_toggles()

    def close(self):
        self.playing = False
        if self.job is not None:
            try:
                self.root.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        self.audio.cleanup()
        try:
            self.track.cleanup()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


def open_path(path):
    import tkinter as tk
    from tkinter import messagebox

    try:
        kind, blob = read_container(path)
    except Exception as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("MTB / MTC", str(exc))
            root.destroy()
        except Exception:
            print(exc, file=sys.stderr)
        return 1

    root = tk.Tk()
    light_title_bar(root)
    auto = int(os.environ.get("MTCODEC_VIEWER_AUTOCLOSE_MS", "0") or 0)

    if kind == "image":
        root.title(os.path.basename(path) + "  —  MTB")
        root.configure(bg=BG)
        root.minsize(320, 240)
        label = tk.Label(root, bg=CANVAS_BG, bd=0, highlightthickness=0)
        label.pack(fill="both", expand=True)
        src = Image.fromarray(decode_image(blob))
        w0, h0 = src.size
        holder = {"img": src, "photo": None}

        def _paint(_event=None):
            ax = label.winfo_width()
            ay = label.winfo_height()
            if ax <= 8 or ay <= 8:
                ax, ay = w0, h0
            s = min(ax / float(src.width), ay / float(src.height))
            tw = max(1, int(round(src.width * s)))
            th = max(1, int(round(src.height * s)))
            if tw > src.width * 3:
                tw, th = src.width, src.height
            img = src if (tw, th) == src.size else src.resize((tw, th), Image.LANCZOS)
            holder["photo"] = ImageTk.PhotoImage(img)
            label.configure(image=holder["photo"])

        label.bind("<Configure>", _paint)
        root.bind("<Escape>", lambda e: root.destroy())
        root.after(50, _paint)

        def _close_img():
            try:
                root.destroy()
            except Exception:
                pass

        if auto > 0:
            root.after(auto, _close_img)
        root.mainloop()
        if auto > 0:
            print("viewer ok kind=%s file=%s" % (kind, os.path.basename(path)))
        return 0

    name = os.path.basename(path)
    root.title(name)
    root.configure(bg=BG)

    # 默认静默启动：先把窗口藏住，解码走完再露出来，中间不显示任何提示。
    want_splash = bool(os.environ.get("MTCODEC_VIEWER_SPLASH", ""))
    splash = hint = bar = fill = pct = preview = None
    if want_splash:
        splash = tk.Frame(root, bg=BG)
        splash.pack(fill="both", expand=True)
        hint = tk.Label(splash, text="正在解码…", bg=BG, fg=FG,
                        font=("Microsoft YaHei", 12))
        hint.pack(pady=(20, 8))
        bar = tk.Canvas(splash, height=10, bg=TRACK, highlightthickness=0)
        bar.pack(fill="x", padx=32)
        fill = bar.create_rectangle(0, 0, 0, 10, fill=ACCENT, width=0)
        pct = tk.Label(splash, text="0%", bg=BG, fg=DIM)
        pct.pack(pady=(6, 20))
        preview = tk.Label(splash, bg=CANVAS_BG, bd=0, highlightthickness=0)
        preview.pack(expand=True, pady=(0, 12))
    else:
        root.withdraw()
    root.bind("<Escape>", lambda e: root.destroy())

    state = {"cur": 0, "total": 0, "frames": None, "audio": b"",
             "fps": 0.0, "err": None, "frame": None, "shown": None}
    t_app = time.monotonic()

    # 长片走流式：边解码边播放，内存恒定；短片照旧全解，拖到哪都即时。
    head = _parse_heads(blob)
    total_n = int(head.get("nframes") or 0)
    vfps = float(head.get("fps") or DEFAULT_FPS)
    vaudio = head.get("audio") or b""
    stream = None
    pix = total_n * int(head.get("w") or 0) * int(head.get("h") or 0)
    # H.264 数据解码只要二十来毫秒一帧，全解纯属白等；一律流式，窗口立刻出来。
    if head.get("codec") == "h264" or pix > 900000000:
        stream = StreamFrames(blob, total_n, (head["h"], head["w"]), vfps, vaudio)

    def worker():
        try:
            got = {}

            def _prog(i, n, frame=None):
                state["cur"] = i
                state["total"] = n
                state["frame"] = frame

            frames, _stats = decode_video(blob, collect=got, progress=_prog)
            state["frames"] = display_frames(frames)
            state["total"] = len(state["frames"])
            state["audio"] = got.get("audio", b"")
            state["fps"] = got.get("fps") or DEFAULT_FPS
        except Exception as exc:
            state["err"] = exc

    th = None
    if stream is None:
        th = threading.Thread(target=worker)
        th.daemon = True
        th.start()

    def draw_bar(fraction):
        if bar is None:
            return
        width = bar.winfo_width()
        if width <= 1:
            width = 560
        bar.coords(fill, 0, 0, int(width * min(1.0, max(0.0, fraction))), 10)

    def draw_preview(arr):
        if preview is None:
            return
        thumb = Image.fromarray(arr)
        target = 360
        if thumb.width > target:
            thumb = thumb.resize(
                (target, max(1, int(thumb.height * target / float(thumb.width)))),
                Image.BILINEAR)
        ph = ImageTk.PhotoImage(thumb)
        preview.configure(image=ph)
        preview.image = ph

    def poll():
        if stream is not None:
            if stream.err is not None:
                try:
                    if splash is not None:
                        splash.destroy()
                except Exception:
                    pass
                messagebox.showerror("MTB / MTC", str(stream.err))
                root.destroy()
                return
            if not stream.ready():
                root.after(80, poll)
                return
            player = Player(root, stream, vfps, vaudio, name)
            try:
                root.deiconify()
                root.lift()
            except Exception:
                pass
            if auto > 0:
                used = (time.monotonic() - t_app) * 1000.0
                root.after(int(max(300, auto - used)), player.close)
            return
        if state["err"] is not None:
            try:
                if splash is not None:
                    splash.destroy()
            except Exception:
                pass
            messagebox.showerror("MTB / MTC", str(state["err"]))
            root.destroy()
            return
        if state["frames"] is None:
            if hint is not None:
                cur = state["cur"]
                total = state["total"] or 0
                fraction = (cur / float(total)) if total else 0.0
                hint.configure(text="正在解码 %d / %d 帧" % (cur, total))
                pct.configure(text="%d%%" % int(100.0 * fraction))
                draw_bar(fraction)
                arr = state.get("frame")
                if arr is not None and arr is not state["shown"]:
                    state["shown"] = arr
                    try:
                        draw_preview(arr)
                    except Exception:
                        pass
            root.after(250, poll)
            return
        if splash is not None:
            draw_bar(1.0)
            pct.configure(text="100%")
            try:
                splash.destroy()
            except Exception:
                pass
        player = Player(root, state["frames"], state["fps"], state["audio"], name)
        try:
            root.deiconify()
            root.lift()
        except Exception:
            pass
        if auto > 0:
            used = (time.monotonic() - t_app) * 1000.0
            root.after(int(max(300, auto - used)), player.close)

    root.after(200, poll)
    root.mainloop()
    if auto > 0:
        print("viewer ok kind=%s file=%s" % (kind, name))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m mtcodec.viewer <file.mtb|file.mtc>")
        raise SystemExit(2)
    raise SystemExit(open_path(sys.argv[1]))
