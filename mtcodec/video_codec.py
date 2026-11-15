import itertools
import struct
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import arithmetic as ac
from . import color
from . import fastdec
from . import fastenc
from . import h264
from . import motion
from . import transform as tf
from .entropy import Model, ModeModel, dec_block, dec_skip, enc_block, enc_skip
from .image_codec import _plane_step, _pad

VID_MAGIC = b"MTC1"
VID_VERSION = 4
VHDR = struct.Struct("<4sBBBBHHI")
VHDR2 = struct.Struct("<4sBBBBHHII")

# version 2: co-located prediction only. version 3: adds a per-frame motion
# vector table. version 4: the video payload is an H.264 stream.
ME_VERSION = 3
H264_VERSION = 4
VERSIONS_HEAD2 = (2, 3, 4)

SCENE_CUT_SAD = 24.0
DEFAULT_FPS = 24.0
# 关掉这一项就退回旧的同位预测。实测块级 ME 在这类素材上只省 3.5%
# 体积，PSNR 反而掉 1.7 dB，编码还慢 4.8 倍，所以默认关闭，代码留作
# 以后换成原生实现时参考。
ME_ON = False

# 三个平面彼此独立，交给 Rust 后 GIL 已释放，可以真并行跑。
_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="mtc-enc")
# 熵编码是单一比特流、只能一帧一帧串行；放后台线程，好让它与下一帧的
# 预处理/量化/重建重叠。
_ENT_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mtc-ent")


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


def _predict_from(ref, mvs):
    """Rebuild the prediction planes from a reference frame and a vector table."""
    chroma = motion.scale(mvs, 2)
    return [
        motion.predict(ref[0], mvs, motion.BLOCK),
        motion.predict(ref[1], chroma, motion.BLOCK // 2),
        motion.predict(ref[2], chroma, motion.BLOCK // 2),
    ]


def _predict_planes(planes, ref):
    """Motion-compensated prediction planes plus the vector table.

    Both the quantiser and the reconstruction use the planes returned here, and
    the decoder rebuilds them from the same table, so the two sides stay in
    lockstep.
    """
    if not ME_ON:
        return [ref[i] for i in range(3)], None
    if planes[0].shape != ref[0].shape:
        return [ref[i] for i in range(3)], None
    mvs = motion.search(planes[0], ref[0])
    return _predict_from(ref, mvs), mvs


def _encode_h264(frames, quality, fps, audio, gop, collect, progress):
    """Wrap an x264 stream in the MTC container."""
    it = iter(frames)
    try:
        first = np.asarray(next(it))
    except StopIteration:
        raise ValueError("empty frame list")
    h, w = first.shape[:2]
    count = [0]

    def wrapped():
        for frame in itertools.chain((first,), it):
            count[0] += 1
            if progress is not None and count[0] % 100 == 0:
                progress(count[0])
            yield frame

    if fps:
        stream = h264.encode(wrapped(), w, h, fps, quality,
                             keyint=(gop * 12) if gop else 250)
    else:
        stream = h264.encode(wrapped(), w, h, DEFAULT_FPS, quality,
                             keyint=(gop * 12) if gop else 250)
    fps100 = int(round(float(fps) * 100)) if fps else 0
    head = VHDR2.pack(VID_MAGIC, H264_VERSION, 1, int(quality), int(gop), w, h,
                      count[0], fps100)
    audio = audio or b""
    head += struct.pack("<I", len(audio)) + audio
    if collect is not None:
        collect["frames"] = list(h264.decode(stream, w, h, fps or DEFAULT_FPS))
        collect["stats"] = []
    return head + stream


def encode_video(frames, quality=85, subsample="420", gop=12, collect=None,
                 fps=DEFAULT_FPS, audio=None, progress=None, codec="h264"):
    """Encode a stream of frames.

    ``codec`` selects the video backend: ``"h264"`` (the default, through
    ffmpeg/x264) or ``"dct"`` (the original in-house transform coder).

    ``frames`` may be any iterable — a list, or a generator that pulls one
    frame at a time from ffmpeg. Only the frames still needed for prediction
    are kept alive, so multi-minute clips do not need tens of gigabytes of
    RAM.
    """
    if codec == "h264" and h264.available():
        return _encode_h264(frames, quality, fps, audio, gop, collect, progress)

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
    fprep = fastenc.prep_available()
    parts = []
    stats = []
    ref = None
    recon_frames = []
    count = 0
    pending = None  # (future, intra, idx) — 上一帧的熵编码在后台跑
    for idx, frame in enumerate(itertools.chain((first,), it)):
        if fprep:
            planes = fastenc.prep_frame(frame, mult, flag)
        else:
            planes = _prep_frame(frame, mult, flag)
        intra = True
        if ref is not None and gop and idx % gop:
            if all(a.shape == b.shape for a, b in zip(planes, ref)):
                sad = float(np.mean(np.abs(planes[0] - ref[0])))
                intra = sad > SCENE_CUT_SAD
        recon = []
        mvs = None
        if fe is not None:
            steps = [_plane_step(step, i) for i in range(3)]
            if intra:
                qzs = list(_POOL.map(
                    lambda i: fastenc.quantize_plane(planes[i], steps[i]), range(3)))
                recon = list(_POOL.map(
                    lambda i: fastenc.recon_plane(qzs[i], steps[i], None, color.CLIP[i]),
                    range(3)))
            else:
                preds_i, mvs = _predict_planes(planes, ref)
                preds = [p.astype(np.float64) for p in preds_i]
                qzs = list(_POOL.map(
                    lambda i: fastenc.quantize_plane(planes[i], steps[i], preds[i]),
                    range(3)))
                qz_effs = []
                for qz in qzs:
                    flat = (qz == 0).all(axis=2)
                    qz_effs.append(qz * (1 - flat[:, :, None]))
                recon = list(_POOL.map(
                    lambda i: fastenc.recon_plane(qz_effs[i], steps[i], preds_i[i],
                                                  color.CLIP[i]),
                    range(3)))
            if pending is not None:
                fut, p_intra, p_idx, p_mv = pending
                payload = p_mv + fut.result()
                parts.append(struct.pack("<BI", 0 if p_intra else 1, len(payload)) + payload)
                stats.append({"frame": p_idx, "type": "i" if p_intra else "p",
                              "bytes": len(payload) + 5})
                pending = None
            mv_blob = motion.pack(mvs) if mvs is not None else b""
            pending = (_ENT_POOL.submit(fe.encode, qzs, not intra), intra, idx, mv_blob)
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
            stats.append({"frame": idx, "type": "i" if intra else "p",
                          "bytes": len(payload) + 5})
        ref = recon
        count += 1
        if collect is not None:
            if fe is not None:
                recon_frames.append(fastdec.planes_to_rgb(recon, bool(flag), h, w))
            else:
                recon_frames.append(_planes_to_rgb(recon, bool(flag), h, w))
        if progress is not None and count % 100 == 0:
            progress(count)

    if pending is not None:
        fut, p_intra, p_idx, p_mv = pending
        payload = p_mv + fut.result()
        parts.append(struct.pack("<BI", 0 if p_intra else 1, len(payload)) + payload)
        stats.append({"frame": p_idx, "type": "i" if p_intra else "p",
                      "bytes": len(payload) + 5})
        pending = None

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
        "me": False, "codec": "dct",
    }
    if ver in VERSIONS_HEAD2:
        magic, ver, flag, quality, gop, w, h, nframes, fps100 = VHDR2.unpack(data[: VHDR2.size])
        pos = VHDR2.size
        alen = struct.unpack("<I", data[pos : pos + 4])[0]
        info.update({
            "flag": flag, "quality": quality, "gop": gop,
            "w": w, "h": h, "nframes": nframes,
            "audio": data[pos + 4 : pos + 4 + alen],
            "fps": (fps100 / 100.0) if fps100 else DEFAULT_FPS,
            "pos": pos + 4 + alen,
            "me": ver == ME_VERSION,
            "codec": "h264" if ver >= H264_VERSION else "dct",
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
    if info.get("codec") == "h264":
        fps = info.get("fps") or DEFAULT_FPS
        n = 0
        for n, rgb in enumerate(h264.decode(data[pos:], w, h, fps, limit), 1):
            if stat_sink is not None:
                stat_sink.append({"frame": n - 1, "type": "x", "bytes": 0})
            if progress is not None:
                progress(n, nframes, rgb)
            yield rgb
            if limit is not None and n >= limit:
                break
        return
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
        intra = ftype == 0
        mvs = None
        if not intra and info.get("me") and ref is not None:
            nbh = ref[0].shape[0] // motion.BLOCK
            nbw = ref[0].shape[1] // motion.BLOCK
            need = nbh * nbw * 2
            if len(payload) >= need:
                mvs = motion.unpack(payload[:need], nbh, nbw)
                payload = payload[need:]
        dec = ac.Decoder(payload)
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
        preds_i = None
        if not intra and mvs is not None and ref is not None:
            preds_i = _predict_from(ref, mvs)
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
                if mvs is not None and fast is None:
                    raise RuntimeError(
                        "this stream uses motion compensation and needs the "
                        "native decoder")
                pred = preds_i[i] if preds_i is not None else ref[i]
                if fast is not None:
                    recon.append(fast.decode_plane_pixels(
                        i, ref[i].shape[0] // 8, ref[i].shape[1] // 8, True,
                        s, pred, color.CLIP[i]))
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
    if ver in VERSIONS_HEAD2:
        magic, ver, flag, quality, gop, w, h, nframes, fps100 = VHDR2.unpack(data[: VHDR2.size])
        alen = struct.unpack("<I", data[VHDR2.size : VHDR2.size + 4])[0]
        info["quality"] = quality
        info["gop"] = gop
        info["width"] = w
        info["height"] = h
        info["frames"] = nframes
        info["subsample_420"] = bool(flag)
        info["version"] = ver
        info["codec"] = "h264" if ver >= H264_VERSION else "dct"
        info["fps"] = (fps100 / 100.0) if fps100 else DEFAULT_FPS
        info["has_audio"] = alen > 0
        info["audio_bytes"] = alen
        info["bytes"] = len(data)
    else:
        info["fps"] = DEFAULT_FPS
        info["has_audio"] = False
        info["audio_bytes"] = 0
    return info
