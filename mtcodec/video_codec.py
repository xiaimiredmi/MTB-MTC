import itertools
import struct

import numpy as np

from . import arithmetic as ac
from . import color
from . import fastdec
from . import fastenc
from . import transform as tf
from .entropy import Model, ModeModel, dec_block, dec_skip, enc_block, enc_skip
from .image_codec import _plane_step, _pad

VID_MAGIC = b"MTC1"
VID_VERSION = 2
VHDR = struct.Struct("<4sBBBBHHI")
VHDR2 = struct.Struct("<4sBBBBHHII")

SCENE_CUT_SAD = 24.0
DEFAULT_FPS = 24.0


def _prep_frame(frame, mult, subsample):
    rgb = _pad(frame.astype(np.int32), mult)
    y, co, cg = color.rgb_to_ycocg(rgb)
    if subsample:
        co = color.down2(co)
        cg = color.down2(cg)
    return [_pad(y, 8), _pad(co, 8), _pad(cg, 8)]


def _recon(qz, step, pred, index):
    hb, wb = qz.shape[0], qz.shape[1]
    q8 = np.zeros((hb, wb, 8, 8), np.float64)
    q8[:, :, tf.ZZ_U, tf.ZZ_V] = qz
    blocks = tf.idct(q8 * step)
    if pred is not None:
        blocks = blocks + pred
    plane = np.rint(tf.plane_of(blocks)).astype(np.int32)
    return color.clip_plane(plane, index)


def _quantize(plane, step, pred=None):
    source = tf.blocks_of(plane.astype(np.float64))
    if pred is not None:
        source = source - pred
    q = np.rint(tf.fdct(source) / step).astype(np.int32)
    return np.ascontiguousarray(q[:, :, tf.ZZ_U, tf.ZZ_V])


def _enc_intra(enc, m, pl, plane, step):
    qz = _quantize(plane, step)
    hb, wb = qz.shape[0], qz.shape[1]
    for r in range(hb):
        prev = 0
        row = qz[r]
        for c in range(wb):
            blk = row[c].tolist()
            enc_block(enc, m, pl, blk, prev)
            prev = blk[0]
    return qz, _recon(qz, step, None, pl)


def _dec_intra(dec, m, pl, shape, step):
    h, w = shape
    hb, wb = h // 8, w // 8
    qz = np.zeros((hb, wb, 64), np.int32)
    for r in range(hb):
        prev = 0
        for c in range(wb):
            blk = dec_block(dec, m, pl, prev)
            qz[r, c] = blk
            prev = blk[0]
    return qz, _recon(qz, step, None, pl)


def _enc_inter(enc, mm, m, pl, plane, ref, step):
    pred = tf.blocks_of(ref.astype(np.float64))
    qz = _quantize(plane, step, pred)
    hb, wb = qz.shape[0], qz.shape[1]
    flags = np.zeros((hb, wb), np.int8)
    for r in range(hb):
        prev = 0
        left_skip = 0
        row = qz[r]
        for c in range(wb):
            blk = row[c].tolist()
            skip = not any(blk)
            if skip:
                enc_skip(enc, mm, pl, left_skip, 1)
                flags[r, c] = 1
            else:
                enc_skip(enc, mm, pl, left_skip, 0)
                enc_block(enc, m, pl, blk, prev)
                prev = blk[0]
            left_skip = 1 if skip else 0
    qz_eff = qz * (1 - flags[:, :, None])
    return qz_eff, _recon(qz_eff, step, pred, pl)


def _dec_inter(dec, mm, m, pl, shape, ref, step):
    h, w = shape
    hb, wb = h // 8, w // 8
    pred = tf.blocks_of(ref.astype(np.float64))
    qz = np.zeros((hb, wb, 64), np.int32)
    for r in range(hb):
        prev = 0
        left_skip = 0
        for c in range(wb):
            if dec_skip(dec, mm, pl, left_skip):
                left_skip = 1
                continue
            blk = dec_block(dec, m, pl, prev)
            qz[r, c] = blk
            prev = blk[0]
            left_skip = 0
    return qz, _recon(qz, step, pred, pl)


def _planes_to_rgb(planes, subsample, out_h, out_w):
    ph = planes[0].shape[0]
    pw = planes[0].shape[1]
    if subsample:
        co = color.up2(planes[1], ph, pw)
        cg = color.up2(planes[2], ph, pw)
    else:
        co = planes[1]
        cg = planes[2]
    r, g, b = color.ycocg_to_rgb(planes[0], co, cg)
    return color.to_uint8(np.stack([r, g, b], axis=2)[:out_h, :out_w])


def encode_video(frames, quality=85, subsample="420", gop=12, collect=None,
                 fps=DEFAULT_FPS, audio=None, progress=None):
    """Encode a stream of frames.

    ``frames`` may be any iterable — a list, or a generator that pulls one
    frame at a time from ffmpeg. Only the frames still needed for prediction
    are kept alive, so multi-minute clips do not need tens of gigabytes of
    RAM.
    """
    it = iter(frames)
    try:
        first = np.asarray(next(it))
    except StopIteration:
        raise ValueError("empty frame list")
    h, w = first.shape[:2]
    flag = 1 if subsample == "420" else 0
    mult = 16 if flag else 8
    step = tf.step_table(tf.quality_scale(quality))
    m = Model(3)
    mm = ModeModel(3)
    fe = fastenc.PlaneEncoder(m, mm, 3) if fastenc.available() else None
    parts = []
    stats = []
    ref = None
    recon_frames = []
    count = 0
    for idx, frame in enumerate(itertools.chain((first,), it)):
        planes = _prep_frame(frame, mult, flag)
        intra = True
        if ref is not None and gop and idx % gop:
            if all(a.shape == b.shape for a, b in zip(planes, ref)):
                sad = float(np.mean(np.abs(planes[0] - ref[0])))
                intra = sad > SCENE_CUT_SAD
        recon = []
        if fe is not None:
            qzs = []
            for i in range(3):
                s = _plane_step(step, i)
                if intra:
                    qz = fastenc.quantize_plane(planes[i], s)
                    qzs.append(qz)
                    recon.append(fastenc.recon_plane(qz, s, None, color.CLIP[i]))
                else:
                    qz = fastenc.quantize_plane(planes[i], s, ref[i].astype(np.float64))
                    qzs.append(qz)
                    flat = (qz == 0).all(axis=2)
                    qz_eff = qz * (1 - flat[:, :, None])
                    recon.append(fastenc.recon_plane(qz_eff, s, ref[i], color.CLIP[i]))
            payload = fe.encode(qzs, not intra)
        else:
            enc = ac.Encoder()
            for i in range(3):
                s = _plane_step(step, i)
                if intra:
                    recon.append(_enc_intra(enc, m, i, planes[i], s)[1])
                else:
                    recon.append(_enc_inter(enc, mm, m, i, planes[i], ref[i], s)[1])
            payload = enc.flush()
        parts.append(struct.pack("<BI", 0 if intra else 1, len(payload)) + payload)
        stats.append({"frame": idx, "type": "i" if intra else "p", "bytes": len(payload) + 5})
        ref = recon
        count += 1
        if collect is not None:
            if fe is not None:
                recon_frames.append(fastdec.planes_to_rgb(recon, bool(flag), h, w))
            else:
                recon_frames.append(_planes_to_rgb(recon, bool(flag), h, w))
        if progress is not None and count % 100 == 0:
            progress(count)

    audio = audio or b""
    fps100 = int(round(float(fps) * 100)) if fps else 0
    head = VHDR2.pack(VID_MAGIC, VID_VERSION, flag, int(quality), int(gop), w, h,
                      count, fps100)
    head += struct.pack("<I", len(audio)) + audio
    if collect is not None:
        collect["frames"] = recon_frames
        collect["stats"] = stats
    return head + b"".join(parts)


def _parse_heads(data):
    if len(data) < VHDR.size:
        raise ValueError("truncated header")
    magic, ver, flag, quality, gop, w, h, nframes = VHDR.unpack(data[: VHDR.size])
    if magic != VID_MAGIC:
        raise ValueError("not an MTC stream")
    info = {
        "flag": flag, "quality": quality, "gop": gop,
        "w": w, "h": h, "nframes": nframes,
        "audio": b"", "fps": DEFAULT_FPS, "pos": VHDR.size,
    }
    if ver == VID_VERSION:
        magic, ver, flag, quality, gop, w, h, nframes, fps100 = VHDR2.unpack(data[: VHDR2.size])
        pos = VHDR2.size
        alen = struct.unpack("<I", data[pos : pos + 4])[0]
        info.update({
            "flag": flag, "quality": quality, "gop": gop,
            "w": w, "h": h, "nframes": nframes,
            "audio": data[pos + 4 : pos + 4 + alen],
            "fps": (fps100 / 100.0) if fps100 else DEFAULT_FPS,
            "pos": pos + 4 + alen,
        })
    elif ver != 1:
        raise ValueError("unsupported version")
    return info


def iter_frames(data, progress=None, limit=None, stat_sink=None, head=None):
    info = _parse_heads(data)
    if head is not None:
        head.update(info)
    flag = info["flag"]
    w = info["w"]
    h = info["h"]
    nframes = info["nframes"]
    pos = info["pos"]
    step = tf.step_table(tf.quality_scale(info["quality"]))
    m = Model(3)
    mm = ModeModel(3)
    fast = fastdec.PlaneDecoder(m, mm, 3) if fastdec.available() else None
    ref = None
    n = 0
    while pos < len(data) and n < nframes:
        if limit is not None and n >= limit:
            break
        ftype, size = struct.unpack("<BI", data[pos : pos + 5])
        pos += 5
        payload = data[pos : pos + size]
        pos += size
        dec = ac.Decoder(payload)
        intra = ftype == 0
        shapes = None
        if intra:
            if flag:
                ph = -(-h // 16) * 16
                pw = -(-w // 16) * 16
                shapes = [(ph, pw), (ph // 2, pw // 2), (ph // 2, pw // 2)]
            else:
                ph = -(-h // 8) * 8
                pw = -(-w // 8) * 8
                shapes = [(ph, pw)] * 3
        recon = []
        if fast is not None:
            fast.attach(dec)
        for i in range(3):
            s = _plane_step(step, i)
            if intra:
                shape = shapes[i]
                if fast is not None:
                    recon.append(fast.decode_plane_pixels(
                        i, shape[0] // 8, shape[1] // 8, False, s, None,
                        color.CLIP[i]))
                else:
                    recon.append(_dec_intra(dec, m, i, shape, s)[1])
            else:
                if fast is not None:
                    recon.append(fast.decode_plane_pixels(
                        i, ref[i].shape[0] // 8, ref[i].shape[1] // 8, True,
                        s, ref[i], color.CLIP[i]))
                else:
                    recon.append(_dec_inter(dec, mm, m, i, ref[i].shape, ref[i], s)[1])
        if fast is not None:
            rgb = fast.planes_to_rgb(recon, bool(flag), h, w)
        else:
            rgb = _planes_to_rgb(recon, bool(flag), h, w)
        if stat_sink is not None:
            stat_sink.append({"frame": n, "type": "i" if intra else "p", "bytes": size + 5})
        ref = recon
        n += 1
        if progress is not None:
            progress(n, nframes, rgb)
        yield rgb


def decode_video(data, collect=None, progress=None, limit=None, on_frame=None):
    head = {}
    stats = []
    frames = []
    for rgb in iter_frames(data, progress=progress, limit=limit,
                           stat_sink=stats, head=head):
        if on_frame is not None:
            on_frame(rgb)
        else:
            frames.append(rgb)
    if collect is not None:
        collect["stats"] = stats
        collect["audio"] = head.get("audio", b"")
        collect["fps"] = head.get("fps") or DEFAULT_FPS
    return frames, stats


def probe_video(data):
    magic, ver, flag, quality, gop, w, h, nframes = VHDR.unpack(data[: VHDR.size])
    info = {
        "magic": magic.decode("ascii", "replace"),
        "version": ver,
        "subsample_420": bool(flag),
        "quality": quality,
        "gop": gop,
        "width": w,
        "height": h,
        "frames": nframes,
    }
    if ver == VID_VERSION:
        magic, ver, flag, quality, gop, w, h, nframes, fps100 = VHDR2.unpack(data[: VHDR2.size])
        alen = struct.unpack("<I", data[VHDR2.size : VHDR2.size + 4])[0]
        info["fps"] = (fps100 / 100.0) if fps100 else DEFAULT_FPS
        info["has_audio"] = alen > 0
        info["audio_bytes"] = alen
        info["bytes"] = len(data)
    else:
        info["fps"] = DEFAULT_FPS
        info["has_audio"] = False
        info["audio_bytes"] = 0
    return info
