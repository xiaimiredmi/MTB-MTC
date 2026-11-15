import numpy as np


def rgb_to_ycocg(rgb):
    r = rgb[:, :, 0].astype(np.int32)
    g = rgb[:, :, 1].astype(np.int32)
    b = rgb[:, :, 2].astype(np.int32)
    co = r - b
    t = b + (co >> 1)
    cg = g - t
    y = t + (cg >> 1)
    return y, co, cg


def ycocg_to_rgb(y, co, cg):
    t = y - (cg >> 1)
    g = cg + t
    b = t - (co >> 1)
    r = co + b
    return r, g, b


def down2(plane):
    return (
        plane[0::2, 0::2] + plane[1::2, 0::2] + plane[0::2, 1::2] + plane[1::2, 1::2]
    ) // 4


def up2(plane, height, width):
    return np.repeat(np.repeat(plane, 2, axis=0), 2, axis=1)[:height, :width]


CLIP = {0: (0, 255), 1: (-300, 300), 2: (-300, 300)}


def clip_plane(plane, index):
    lo, hi = CLIP[index]
    return np.clip(plane, lo, hi)


def to_uint8(rgb):
    return np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
