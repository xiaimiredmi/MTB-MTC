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
from .video_codec import decode_video

MAX_W = int(os.environ.get("MTCODEC_VIEWER_MAX_W", "0") or 0)
MAX_H = int(os.environ.get("MTCODEC_VIEWER_MAX_H", "0") or 0)
MAX_SIDE = int(os.environ.get("MTCODEC_VIEWER_MAX_SIDE", "1600") or 1600)
DEFAULT_FPS = 24.0
CACHE_LIMIT = 24

BG = "#101317"
FG = "#E8E6E1"
DIM = "#8F98A4"
BAR_BG = "#171B21"
CHIP_BG = "#20242C"
CHIP_HI = "#2B3240"
TRACK = "#2A303A"
ACCENT = "#0E717C"
FONT = "Microsoft YaHei"
MONO = "Consolas"

SPEEDS = (0.5, 1.0, 1.5, 2.0)
FFMPEG = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


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
    """只在帧超过 MAX_SIDE 时做一次高质量缩放，其余保留原始分辨率。"""
    if not frames:
        return frames
    h0, w0 = frames[0].shape[:2]
    cap = MAX_SIDE if MAX_SIDE > 0 else max(w0, h0)
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


class Player(object):
    def __init__(self, root, frames, fps, audio_bytes, title):
        self.root = root
        self.frames = frames
        self.count = len(frames)
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

        self._build_ui(title)
        self.show(0)
        self.start()

    # ---------- 界面 ----------
    def _chip(self, parent, text, cmd, w=54, h=28):
        import tkinter as tk
        c = tk.Canvas(parent, width=w, height=h, bg=BAR_BG,
                      highlightthickness=0, cursor="hand2")
        box = c.create_rectangle(0, 0, w, h, fill=CHIP_BG, outline="")
        label = c.create_text(w / 2.0, h / 2.0, text=text, fill=FG,
                              font=(FONT, 10))
        c.bind("<Button-1>", lambda e: cmd())
        c.bind("<Enter>", lambda e: c.itemconfigure(box, fill=CHIP_HI)
               if not c.itemcget(box, "fill") in (ACCENT,) else None)
        c.bind("<Leave>", lambda e: c.itemconfigure(box, fill=CHIP_BG)
               if not c.itemcget(box, "fill") in (ACCENT,) else None)
        return c, box, label

    def _build_ui(self, title):
        import tkinter as tk

        for child in self.root.winfo_children():
            child.destroy()
        self.root.title(title)
        self.root.configure(bg=BG)
        self.root.minsize(560, 380)
        self._chips = []
        self._togs = []
        self._cur = 0

        self.image_label = tk.Label(self.root, bg="#0B0D10", bd=0,
                                    highlightthickness=0)
        self.image_label.pack(fill="both", expand=True)
        self.image_label.bind("<Configure>", self._on_canvas_resize)
        self.image_label.bind("<Double-Button-1>", lambda e: self.toggle())

        bar = tk.Frame(self.root, bg=BAR_BG)
        bar.pack(side="bottom", fill="x")

        self.pb = tk.Canvas(bar, height=18, bg=BAR_BG, highlightthickness=0,
                            cursor="hand2")
        self.pb.pack(fill="x", padx=14, pady=(10, 0))
        self.pb.bind("<Button-1>", self._pb_press)
        self.pb.bind("<B1-Motion>", self._pb_drag)
        self.pb.bind("<ButtonRelease-1>", self._pb_release)
        self.pb.bind("<Configure>", lambda e: self._draw_progress(self._shown_time()))

        row = tk.Frame(bar, bg=BAR_BG)
        row.pack(fill="x", padx=14, pady=(8, 10))

        self.btn_play, self._play_box, self._play_text = self._chip(
            row, "暂停", self.toggle, 54)
        self.btn_play.pack(side="left")

        self.time_label = tk.Label(row, text="0.0 / 0.0 s", bg=BAR_BG, fg=DIM,
                                   font=(MONO, 10))
        self.time_label.pack(side="left", padx=(12, 0))

        self.end_var = tk.BooleanVar(value=False)
        self.loop_var = tk.BooleanVar(value=False)
        self._toggle_chip(row, "播完关闭", self.end_var, self._on_end_close,
                          78).pack(side="right")
        self._toggle_chip(row, "循环", self.loop_var, self._on_loop,
                          52).pack(side="right", padx=(0, 6))

        self.vol = tk.Scale(row, from_=0, to=100, orient="horizontal", length=84,
                            showvalue=False, command=self._on_volume,
                            bg=BAR_BG, fg=FG, troughcolor=TRACK,
                            highlightthickness=0, bd=0, sliderrelief="flat",
                            sliderlength=14, width=8, activebackground=ACCENT)
        self.vol.set(100)
        self.vol.pack(side="right", padx=(6, 12))

        tk.Label(row, text="音量", bg=BAR_BG, fg=DIM,
                 font=(FONT, 9)).pack(side="right")

        for sp in reversed(SPEEDS):
            self._speed_chip(row, sp).pack(side="right", padx=2)

        note = ""
        if not self.audio.available():
            note = "当前系统没有音频后端，只能静音播放"
        elif not self.track.ok():
            note = "这个文件没有音轨"
        elif not self.track.stretched():
            note = "没有找到 ffmpeg，倍速会连音调一起变"
        if note:
            tk.Label(bar, text=note, bg=BAR_BG, fg="#C07A2A", anchor="w",
                     font=(FONT, 9)).pack(fill="x", padx=14, pady=(0, 8))

        self._paint_speeds()
        self._paint_toggles()

        self.root.bind("<space>", self.toggle)
        self.root.bind("<Escape>", lambda e: self.close())
        self.root.bind("<Left>", lambda e: self.nudge(-1.0))
        self.root.bind("<Right>", lambda e: self.nudge(1.0))
        self.root.bind("<Up>", lambda e: self.volume_step(10))
        self.root.bind("<Down>", lambda e: self.volume_step(-10))

    def _speed_chip(self, parent, speed):
        text = ("%gx" % speed)
        c, box, label = self._chip(
            parent, text, lambda s=speed: self._set_speed(s), 46, 26)
        self._chips.append((speed, c, box, label))
        return c

    def _paint_speeds(self):
        for speed, c, box, label in self._chips:
            on = abs(self.speed - speed) < 1e-6
            c.itemconfigure(box, fill=(ACCENT if on else CHIP_BG))
            c.itemconfigure(label, fill=("#FFFFFF" if on else FG))

    def _toggle_chip(self, parent, text, var, cmd, w=52):
        def _hit():
            var.set(not var.get())
            cmd()

        c, box, label = self._chip(parent, text, _hit, w, 26)
        self._togs.append((c, box, var))
        return c

    def _paint_toggles(self):
        for c, box, var in self._togs:
            c.itemconfigure(box, fill=(ACCENT if var.get() else CHIP_BG))

    # ---------- 帧 ----------
    def _fit_size(self):
        ax = self.image_label.winfo_width()
        ay = self.image_label.winfo_height()
        h0, w0 = self.frames[0].shape[:2]
        if ax <= 8 or ay <= 8:
            return (w0, h0)
        s = min(ax / float(w0), ay / float(h0))
        return (max(1, int(round(w0 * s))), max(1, int(round(h0 * s))))

    def _photo(self, idx, size):
        key = (idx, size)
        ph = self._cache.get(key)
        if ph is None:
            img = Image.fromarray(self.frames[idx])
            if size and img.size != size:
                img = img.resize(size, Image.LANCZOS)
            ph = ImageTk.PhotoImage(img)
            self._cache[key] = ph
            self._order.append(key)
            while len(self._order) > CACHE_LIMIT:
                old = self._order.pop(0)
                self._cache.pop(old, None)
        return ph

    def show(self, idx):
        if self.count == 0:
            return
        idx = int(max(0, min(self.count - 1, idx)))
        self._cur = idx
        self.image_label.configure(image=self._photo(idx, self._fit_size()))

    def _on_canvas_resize(self, _event=None):
        if self.count:
            self.show(self._cur)

    def _shown_time(self):
        return self.pos if not self.playing else self.elapsed()

    def _draw_progress(self, t):
        c = self.pb
        W = c.winfo_width() or 600
        H = 18
        mid = H / 2.0
        c.delete("all")
        c.create_line(0, mid, W, mid, fill=TRACK, width=4)
        frac = 0.0 if not self.duration else min(1.0, max(0.0, t / self.duration))
        x = W * frac
        if frac > 0:
            c.create_line(0, mid, x, mid, fill=ACCENT, width=4)
        c.create_oval(x - 5, mid - 5, x + 5, mid + 5, fill=FG, outline="")

    def _update_bar(self, t):
        self._draw_progress(t)
        self.time_label.configure(text="%.1f / %.1f s" % (t, self.duration))

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
        self.show(idx)
        self._update_bar(t)
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
        try:
            self.btn_play.itemconfigure(self._play_text, text=text)
        except Exception:
            pass

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
        frac = min(1.0, max(0.0, float(event.x) / W))
        return frac * self.duration

    def _pb_press(self, event):
        self._dragging = True
        t = self._pb_time(event)
        self._draw_progress(t)
        self.time_label.configure(text="%.1f / %.1f s" % (t, self.duration))
        return "break"

    def _pb_drag(self, event):
        t = self._pb_time(event)
        self._draw_progress(t)
        self.time_label.configure(text="%.1f / %.1f s" % (t, self.duration))
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

    def _on_volume(self, value):
        try:
            self.gain = float(value) / 100.0
        except Exception:
            self.gain = 1.0
        if self.playing:
            self.pos = self.elapsed()
            self.base_pos = self.pos
            self.base_wall = time.monotonic()
            self._play_audio(self.pos)

    def volume_step(self, delta):
        self.vol.set(max(0, min(100, int(self.vol.get()) + delta)))
        self._on_volume(self.vol.get())
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
    auto = int(os.environ.get("MTCODEC_VIEWER_AUTOCLOSE_MS", "0") or 0)

    if kind == "image":
        root.title(os.path.basename(path))
        root.configure(bg=BG)
        label = tk.Label(root, bg=BG, bd=0, highlightthickness=0)
        label.pack(fill="both", expand=True)
        img = Image.fromarray(decode_image(blob))
        scale = min(MAX_W / float(img.width), MAX_H / float(img.height), 1.0)
        if scale < 1.0:
            img = img.resize((int(img.width * scale), int(img.height * scale)),
                             Image.LANCZOS)
        ph = ImageTk.PhotoImage(img)
        label.configure(image=ph)
        label.image = ph
        root.bind("<Escape>", lambda e: root.destroy())

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

    splash = tk.Frame(root, bg=BG)
    splash.pack(fill="both", expand=True)
    hint = tk.Label(splash, text="正在解码…", bg=BG, fg=FG,
                    font=("Microsoft YaHei", 12))
    hint.pack(pady=(20, 8))
    bar = tk.Canvas(splash, height=10, bg="#2B3039", highlightthickness=0)
    bar.pack(fill="x", padx=32)
    fill = bar.create_rectangle(0, 0, 0, 10, fill=ACCENT, width=0)
    pct = tk.Label(splash, text="0%", bg=BG, fg="#9BA3AE")
    pct.pack(pady=(6, 20))
    preview = tk.Label(splash, bg=BG, bd=0, highlightthickness=0)
    preview.pack(expand=True, pady=(0, 12))
    root.bind("<Escape>", lambda e: root.destroy())

    state = {"cur": 0, "total": 0, "frames": None, "audio": b"",
             "fps": 0.0, "err": None, "frame": None, "shown": None}
    t_app = time.monotonic()

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

    th = threading.Thread(target=worker)
    th.daemon = True
    th.start()

    def draw_bar(fraction):
        width = bar.winfo_width()
        if width <= 1:
            width = 560
        bar.coords(fill, 0, 0, int(width * min(1.0, max(0.0, fraction))), 10)

    def draw_preview(arr):
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
        if state["err"] is not None:
            try:
                splash.destroy()
            except Exception:
                pass
            messagebox.showerror("MTB / MTC", str(state["err"]))
            root.destroy()
            return
        if state["frames"] is None:
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
        draw_bar(1.0)
        pct.configure(text="100%")
        try:
            splash.destroy()
        except Exception:
            pass
        player = Player(root, state["frames"], state["fps"], state["audio"], name)
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
