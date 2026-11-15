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
    def _build_ui(self, title):
        import tkinter as tk

        for child in self.root.winfo_children():
            child.destroy()
        self.root.title(title)
        self.root.configure(bg=BG)
        self.root.minsize(480, 320)

        self.image_label = tk.Label(self.root, bg=BG, bd=0, highlightthickness=0)
        self.image_label.pack(fill="both", expand=True)

        bar = tk.Frame(self.root, bg=BAR_BG, padx=10, pady=6)
        bar.pack(side="bottom", fill="x")

        self.scale = tk.Scale(
            bar, from_=0.0, to=self.duration, orient="horizontal",
            resolution=0.01, showvalue=False, bg=BAR_BG, fg=FG,
            troughcolor="#2B3039", highlightthickness=0, bd=0,
            activebackground=ACCENT,
        )
        self.scale.pack(fill="x")
        self.scale.bind("<ButtonPress-1>", self._seek_press)
        self.scale.bind("<ButtonRelease-1>", self._seek_release)
        self.scale.bind("<B1-Motion>", self._seek_press)

        row = tk.Frame(bar, bg=BAR_BG)
        row.pack(fill="x", pady=(4, 0))

        self.btn_play = tk.Button(
            row, text="暂停", width=6, command=self.toggle,
            bg="#2B3039", fg=FG, activebackground="#3A414C",
            activeforeground=FG, bd=0, highlightthickness=0,
        )
        self.btn_play.pack(side="left")

        tk.Label(row, text="倍速", bg=BAR_BG, fg="#9BA3AE").pack(side="left", padx=(10, 4))
        self.speed_var = tk.StringVar(value="1x")
        menu = tk.OptionMenu(row, self.speed_var, *SPEEDS, command=self._on_speed)
        menu.configure(bg="#2B3039", fg=FG, activebackground="#3A414C",
                       activeforeground=FG, bd=0, highlightthickness=0, width=4)
        menu["menu"].configure(bg="#2B3039", fg=FG)
        menu.pack(side="left")

        tk.Label(row, text="音量", bg=BAR_BG, fg="#9BA3AE").pack(side="left", padx=(12, 4))
        self.vol = tk.Scale(
            row, from_=0, to=100, orient="horizontal", length=110,
            showvalue=False, command=self._on_volume,
            bg=BAR_BG, fg=FG, troughcolor="#2B3039",
            highlightthickness=0, bd=0, activebackground=ACCENT,
        )
        self.vol.set(100)
        self.vol.pack(side="left")

        self.loop_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text="循环", variable=self.loop_var,
                       command=self._on_loop, bg=BAR_BG, fg=FG,
                       selectcolor="#2B3039", activebackground=BAR_BG,
                       activeforeground=FG, bd=0, highlightthickness=0
                       ).pack(side="left", padx=(12, 0))

        self.end_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text="播完关闭", variable=self.end_var,
                       command=self._on_end_close, bg=BAR_BG, fg=FG,
                       selectcolor="#2B3039", activebackground=BAR_BG,
                       activeforeground=FG, bd=0, highlightthickness=0
                       ).pack(side="left", padx=(8, 0))

        self.time_label = tk.Label(row, text="0.0 / 0.0 s", bg=BAR_BG, fg="#9BA3AE")
        self.time_label.pack(side="right")

        note = "" if self.audio.available() else "（当前系统没有找到音频后端，仅静音播放）"
        if not self.track.ok():
            note = "（这个文件没有音轨）"
        if note:
            tk.Label(bar, text=note, bg=BAR_BG, fg="#A85B12",
                     anchor="w").pack(fill="x", pady=(2, 0))

        self.root.bind("<space>", self.toggle)
        self.root.bind("<Escape>", lambda e: self.close())
        self.root.bind("<Left>", lambda e: self.nudge(-1.0))
        self.root.bind("<Right>", lambda e: self.nudge(1.0))
        self.root.bind("<Up>", lambda e: self.volume_step(10))
        self.root.bind("<Down>", lambda e: self.volume_step(-10))

    # ---------- 帧 ----------
    def _photo(self, idx):
        ph = self._cache.get(idx)
        if ph is None:
            ph = ImageTk.PhotoImage(Image.fromarray(self.frames[idx]))
            self._cache[idx] = ph
            self._order.append(idx)
            while len(self._order) > CACHE_LIMIT:
                old = self._order.pop(0)
                self._cache.pop(old, None)
        return ph

    def show(self, idx):
        if self.count == 0:
            return
        idx = int(max(0, min(self.count - 1, idx)))
        self.image_label.configure(image=self._photo(idx))

    def _update_bar(self, t):
        if not self._dragging:
            self._syncing = True
            try:
                self.scale.set(min(self.duration, max(0.0, t)))
            finally:
                self._syncing = False
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
        self.btn_play.configure(text="暂停")
        self._play_audio(self.pos)
        self._schedule(0.0)

    def pause(self):
        self.pos = min(self.duration, self.elapsed())
        self.playing = False
        self.btn_play.configure(text="播放")
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

    def _play_audio(self, start_sec):
        if not self.track.ok() or not self.audio.available():
            return
        self.audio.play(self.track.build(start_sec, self.speed, self.gain))

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
        self.btn_play.configure(text="播放")
        self.audio.stop()
        self.show(self.count - 1)
        self._update_bar(self.duration)

    # ---------- 交互 ----------
    def _seek_press(self, _event=None):
        self._dragging = True

    def _seek_release(self, _event=None):
        self._dragging = False
        self.seek(float(self.scale.get()))

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

    def _on_speed(self, _value=None):
        label = self.speed_var.get()
        self.speed = float(label.replace("x", ""))
        if self.playing:
            self.pos = self.elapsed()
            self.base_pos = self.pos
            self.base_wall = time.monotonic()
            self._play_audio(self.pos)

    def _on_volume(self, value):
        if self._syncing:
            return
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

    def _on_end_close(self):
        self.close_at_end = bool(self.end_var.get())

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
