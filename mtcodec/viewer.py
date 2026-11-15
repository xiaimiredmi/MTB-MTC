import os
import sys
import tempfile

import numpy as np
from PIL import Image, ImageTk

from .image_codec import MAGIC as IMAGE_MAGIC
from .image_codec import decode_image
from .video_codec import VID_MAGIC as VIDEO_MAGIC
from .video_codec import decode_video

MAX_W = 960
MAX_H = 720
DEFAULT_FPS = 24.0


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


def _fit(arr):
    h, w = arr.shape[:2]
    scale = min(MAX_W / float(w), MAX_H / float(h), 1.0)
    if scale < 1.0:
        img = Image.fromarray(arr).resize(
            (max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS
        )
    else:
        img = Image.fromarray(arr)
    return img


def _play_audio(wav_bytes):
    """WAV 字节直接异步播放（Windows 用系统播放器，其它平台先静音）。"""
    if not wav_bytes:
        return None
    if sys.platform != "win32":
        return None
    try:
        import winsound

        tmp = os.path.join(tempfile.gettempdir(), "mtcodec_audio.wav")
        with open(tmp, "wb") as f:
            f.write(wav_bytes)
        winsound.PlaySound(tmp, winsound.SND_FILENAME | winsound.SND_ASYNC)
        return tmp
    except Exception:
        return None


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
    root.title(os.path.basename(path))
    root.configure(bg="#15181D")
    label = tk.Label(root, bg="#15181D", bd=0, highlightthickness=0)
    label.pack(fill="both", expand=True)

    state = {"i": 0, "playing": True, "job": None, "frames": None}

    if kind == "image":
        arr = decode_image(blob)
        img = _fit(arr)
        state["frames"] = [ImageTk.PhotoImage(img)]
        label.configure(image=state["frames"][0])
        root.bind("<Escape>", lambda e: root.destroy())
    else:
        got = {}
        frames, stats = decode_video(blob, collect=got)
        fps = got.get("fps") or DEFAULT_FPS
        audio = got.get("audio", b"")
        state["frames"] = [ImageTk.PhotoImage(_fit(f)) for f in frames]
        label.configure(image=state["frames"][0])

        def tick():
            if not state["playing"] or not state["frames"]:
                return
            try:
                state["i"] = (state["i"] + 1) % len(state["frames"])
                label.configure(image=state["frames"][state["i"]])
                state["job"] = root.after(int(1000 / fps), tick)
            except Exception:
                state["job"] = None

        def toggle(_event=None):
            state["playing"] = not state["playing"]
            if state["playing"]:
                tick()
                if audio:
                    _play_audio(audio)
            else:
                if state["job"] is not None:
                    root.after_cancel(state["job"])
                    state["job"] = None
                if sys.platform == "win32":
                    try:
                        import winsound

                        winsound.PlaySound(None, winsound.SND_PURGE)
                    except Exception:
                        pass

        root.bind("<space>", toggle)
        root.bind("<Escape>", lambda e: root.destroy())
        _play_audio(audio)
        tick()

    root.bind("<Escape>", lambda e: root.destroy())
    auto = int(os.environ.get("MTCODEC_VIEWER_AUTOCLOSE_MS", "0") or 0)

    def _finish():
        if state.get("job") is not None:
            try:
                root.after_cancel(state["job"])
            except Exception:
                pass
            state["job"] = None
        state["playing"] = False
        root.destroy()

    if auto > 0:
        root.after(auto, _finish)
    root.mainloop()
    if auto > 0:
        print("viewer ok kind=%s file=%s" % (kind, os.path.basename(path)))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m mtcodec.viewer <file.mtb|file.mtc>")
        raise SystemExit(2)
    raise SystemExit(open_path(sys.argv[1]))
