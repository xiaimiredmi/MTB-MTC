import numpy as np

def _dct_matrix():
    u = np.arange(8)[:, None]
    x = np.arange(8)[None, :]
    m = np.cos((2 * x + 1) * u * np.pi / 16.0) * 0.5
    m[0, :] = np.sqrt(1.0 / 8.0)
    return np.ascontiguousarray(m)


M = _dct_matrix()


def fdct(blocks):
    return np.einsum("ux,ijxy,vy->ijuv", M, blocks, M, optimize=True)


def idct(coeffs):
    return np.einsum("ux,ijuv,vy->ijxy", M, coeffs, M, optimize=True)


def _zigzag():
    order = []
    for s in range(15):
        seq = [(s - v, v) for v in range(8) if 0 <= s - v < 8]
        if s % 2:
            seq.reverse()
        order.extend(seq)
    assert len(order) == 64 and len(set(order)) == 64
    return order


ZZ = _zigzag()
ZZ_U = np.array([p[0] for p in ZZ], dtype=np.intp)
ZZ_V = np.array([p[1] for p in ZZ], dtype=np.intp)


def base_weight():
    u = np.arange(8, dtype=np.float64)
    f = np.sqrt(u[:, None] ** 2 + u[None, :] ** 2)
    return 1.0 + 0.30 * np.power(f, 1.15)


W_BASE = base_weight()


def step_table(scale):
    return np.ascontiguousarray(W_BASE * float(scale))


def quality_scale(quality):
    q = min(100, max(1, int(quality)))
    return 0.85 + (100 - q) * 0.40


def blocks_of(plane):
    h, w = plane.shape
    return plane.reshape(h // 8, 8, w // 8, 8).transpose(0, 2, 1, 3)


def plane_of(blocks):
    hb, wb = blocks.shape[:2]
    return blocks.transpose(0, 2, 1, 3).reshape(hb * 8, wb * 8)
