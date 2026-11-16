"""MTC 图片查看器：白色界面、滚轮缩放、拖动平移。

只依赖标准库 + numpy + Pillow。解码后的图片保留原始像素，缩放时按可见
区域裁切再缩放；适应窗口时用缓存，滚轮/拖动时只重算当前视口。
"""

import math
import os
import sys

import numpy as np
from PIL import Image, ImageTk

from .image_codec import MAGIC, decode_image

BG = "#FFFFFF"
BAR_BG = "#F7F7F8"
FG = "#1A1A1A"
DIM = "#6B6B6B"
TRACK = "#E6E6E9"
ACCENT = "#E8476B"
ACCENT_HI = "#F25C7C"
ACCENT_DARK = "#C22B4E"
ACCENT_SOFT = "#FDECF0"
ON_ACCENT = "#FFFFFF"
FONT = "Microsoft YaHei"
MONO = "Consolas"
CACHE_LIMIT = 12


def fmt_bytes(n):
    if n >= 1048576:
        return "%.2f MB" % (n / 1048576.0)
    if n >= 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%d B" % n


class Viewer(object):
    def __init__(self, root, img, title, raw_size):
        self.root = root
        self.img = img
        self.iw, self.ih = img.size
        self.raw_size = raw_size
        self.scale = 1.0
        self.pan = [0.0, 0.0]
        self.fit_mode = True
        self._drag = None
        self._cache = {}
        self._order = []
        self._photo = None
        self._build(title)
        self.root.after(30, self.fit)

    # ---------- 界面 ----------
    def _build(self, title):
        import tkinter as tk

        self.root.title(title)
        self.root.configure(bg=BG)
        self.root.minsize(480, 360)
        try:
            sw = min(self.iw + 80, self.root.winfo_screenwidth() - 120)
            sh = min(self.ih + 170, self.root.winfo_screenheight() - 140)
            self.root.geometry("%dx%d" % (max(480, sw), max(360, sh)))
        except Exception:
            pass

        head = tk.Frame(self.root, bg=BG)
        head.pack(side="top", fill="x", padx=20, pady=(12, 6))
        mark = tk.Canvas(head, width=5, height=22, bg=BG, highlightthickness=0)
        mark.create_rectangle(0, 1, 5, 21, fill=ACCENT, outline="")
        mark.pack(side="left")
        tk.Label(head, text=title, bg=BG, fg=FG, anchor="w",
                 font=(FONT, 12, "bold")).pack(side="left", padx=(10, 0))
        meta = "%d×%d  ·  %s" % (self.iw, self.ih, fmt_bytes(self.raw_size))
        tk.Label(head, text=meta, bg=BG, fg=DIM,
                 font=(FONT, 9)).pack(side="right")
        self.zoom_label = tk.Label(head, text="适应 100%", bg=BG, fg=DIM,
                                   font=(MONO, 9), cursor="hand2")
        self.zoom_label.pack(side="right", padx=(12, 0))
        self.zoom_label.bind("<Button-1>", self.fit)

        foot = tk.Frame(self.root, bg=BAR_BG)
        foot.pack(side="bottom", fill="x")
        tk.Label(foot, text="滚轮缩放  ·  拖动平移  ·  双击复位  ·  Esc 关闭",
                 bg=BAR_BG, fg=DIM, font=(FONT, 9)).pack(side="left", padx=20,
                                                         pady=10)
        close = tk.Label(foot, text="关闭", bg=BAR_BG, fg=DIM,
                         font=(FONT, 9), cursor="hand2", padx=10)
        close.pack(side="right", padx=14)
        close.bind("<Button-1>", lambda e: self.close())

        self.canvas = tk.Canvas(self.root, bg=BG, bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._item = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Double-Button-1>", self.fit)
        self.canvas.bind("<ButtonPress-1>", self._pan_start)
        self.canvas.bind("<B1-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-1>", self._pan_end)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._wheel_step(1, e))
        self.canvas.bind("<Button-5>", lambda e: self._wheel_step(-1, e))
        self.root.bind("<Escape>", lambda e: self.close())

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    # ---------- 几何 ----------
    def _viewport(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 8 or h <= 8:
            return (max(1, self.iw), max(1, self.ih))
        return (w, h)

    def _fit_scale(self):
        cw, ch = self._viewport()
        return min(cw / float(self.iw), ch / float(self.ih))

    def _clamp_pan(self):
        cw, ch = self._viewport()
        sw = self.iw * self.scale
        sh = self.ih * self.scale
        if sw <= cw:
            self.pan[0] = (cw - sw) / 2.0
        else:
            self.pan[0] = min(0.0, max(cw - sw, self.pan[0]))
        if sh <= ch:
            self.pan[1] = (ch - sh) / 2.0
        else:
            self.pan[1] = min(0.0, max(ch - sh, self.pan[1]))

    def fit(self, _event=None):
        self.scale = self._fit_scale()
        self.fit_mode = True
        self._clamp_pan()
        self._render(force=True)
        return "break"

    def _zoom_at(self, cx, cy, factor):
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
        self.fit_mode = False
        self._clamp_pan()
        self._render(force=True)

    def _on_wheel(self, event):
        d = int(event.delta)
        n = int(d / 120.0)
        if n == 0:
            n = 1 if d > 0 else -1
        self._zoom_at(event.x, event.y, 1.25 ** n)
        return "break"

    def _wheel_step(self, n, event):
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
        self.fit_mode = False
        self._clamp_pan()
        self._render()

    def _pan_end(self, _event=None):
        self._drag = None

    # ---------- 绘制 ----------
    def _render(self, force=False):
        cw, ch = self._viewport()
        s = self.scale if self.scale > 0 else self._fit_scale()
        self.scale = s
        x0 = max(0, int(math.floor(-self.pan[0] / s)))
        y0 = max(0, int(math.floor(-self.pan[1] / s)))
        x1 = min(self.iw, int(math.ceil((cw - self.pan[0]) / s)))
        y1 = min(self.ih, int(math.ceil((ch - self.pan[1]) / s)))
        if x1 <= x0 or y1 <= y0:
            return
        tx0 = int(round(self.pan[0] + x0 * s))
        ty0 = int(round(self.pan[1] + y0 * s))
        tx1 = int(round(self.pan[0] + x1 * s))
        ty1 = int(round(self.pan[1] + y1 * s))
        tw = max(1, tx1 - tx0)
        th = max(1, ty1 - ty0)
        key = (x0, y0, x1, y1, tw, th)
        ph = self._cache.get(key)
        if ph is None or force:
            part = self.img.crop((x0, y0, x1, y1))
            if part.size != (tw, th):
                resample = Image.BOX if s < 1.0 else Image.BILINEAR
                part = part.resize((tw, th), resample)
            ph = ImageTk.PhotoImage(part)
            self._cache[key] = ph
            if key in self._order:
                self._order.remove(key)
            self._order.append(key)
            while len(self._order) > CACHE_LIMIT:
                self._cache.pop(self._order.pop(0), None)
        self._photo = ph
        self.canvas.itemconfigure(self._item, image=ph)
        self.canvas.coords(self._item, tx0, ty0)
        pct = int(round(s * 100.0))
        self.zoom_label.configure(
            text=("适应 %d%%" if self.fit_mode else "缩放 %d%%") % pct)

    def _on_resize(self, _event=None):
        if self.fit_mode:
            self.scale = self._fit_scale()
        else:
            self.scale = max(self.scale, self._fit_scale())
        self._clamp_pan()
        self._render()


def open_path(path):
    import tkinter as tk
    from tkinter import messagebox

    try:
        with open(path, "rb") as f:
            blob = f.read()
        if blob[:4] != MAGIC:
            raise ValueError("不是 MTC 图片文件：%s" % os.path.basename(path))
        arr = decode_image(blob)
        img = Image.fromarray(arr)
    except Exception as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("MTC", str(exc))
            root.destroy()
        except Exception:
            print(exc, file=sys.stderr)
        return 1

    root = tk.Tk()
    viewer = Viewer(root, img, os.path.basename(path), len(blob))
    auto = int(os.environ.get("MTCODEC_VIEWER_AUTOCLOSE_MS", "0") or 0)
    if auto > 0:
        root.after(max(300, auto), viewer.close)
    root.mainloop()
    if auto > 0:
        print("viewer ok file=%s" % os.path.basename(path))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m mtcodec.viewer <file.mtc>")
        raise SystemExit(2)
    raise SystemExit(open_path(sys.argv[1]))
