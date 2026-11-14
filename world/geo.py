"""Shared geometry: world = three.js axes (+x right, +y up, -z forward at yaw 0)."""
import numpy as np
from scipy.ndimage import map_coordinates, gaussian_filter1d


def view_basis(yaw_deg, pitch_deg):
    """3x3 whose columns are the camera's x (right), y (down), z (forward) in world axes."""
    y, p = np.radians(yaw_deg), np.radians(pitch_deg)
    f = np.array([np.sin(y) * np.cos(p), np.sin(p), -np.cos(y) * np.cos(p)])
    r = np.array([np.cos(y), 0.0, np.sin(y)])
    up = np.cross(r, f)
    return np.stack([r, -up, f], axis=1)


def sample(img, u, v, wrap):
    """Bilinear lookup of img (H,W,C float32) at pixel coords u (x), v (y)."""
    H, W = img.shape[:2]
    if wrap:
        img = np.concatenate([img, img[:, :1]], axis=1)
        u = np.mod(u, W)
    v = np.clip(v, 0, H - 1)
    return np.stack(
        [map_coordinates(img[..., c], [v, u], order=1, mode="nearest") for c in range(img.shape[2])], -1
    )


def photo_to_guide(photo, hfov_deg, W, H):
    """Paint a normal photo into the middle of an equirect canvas W x H (360 deg wide, same deg/px vertically)."""
    h, w = photo.shape[:2]
    f = (w / 2) / np.tan(np.radians(hfov_deg) / 2)
    latmax = np.pi * H / W
    lon = ((np.arange(W) + 0.5) / W - 0.5) * 2 * np.pi
    lat = (0.5 - (np.arange(H) + 0.5) / H) * 2 * latmax
    lon, lat = np.meshgrid(lon, lat)
    x, y, z = np.sin(lon) * np.cos(lat), np.sin(lat), np.cos(lon) * np.cos(lat)
    ok = z > 1e-3
    zs = np.where(ok, z, 1)
    px, py = f * x / zs + w / 2 - 0.5, -f * y / zs + h / 2 - 0.5
    ok &= (px >= 0) & (px <= w - 1) & (py >= 0) & (py <= h - 1)
    out = sample(photo, px, py, wrap=False)
    out[~ok] = 0
    return out, ok


def extend_pano(pano):
    """Pad a 360-wide pano (any height) to a full 2:1 equirect; the caps get a blurred copy of the edge rows."""
    H, W = pano.shape[:2]
    n = (W // 2 - H) // 2
    if n <= 0:
        return pano

    def cap(edge):
        rows = []
        for k in range(n):
            t = (k + 1) / n
            b = gaussian_filter1d(edge, sigma=max(2.0, t * W * 0.08), axis=0, mode="wrap")
            rows.append(b * (1 - 0.6 * t) + edge.mean(0) * 0.6 * t)
        return np.stack(rows)

    top = cap(pano[:12].mean(0))[::-1]
    bot = cap(pano[-12:].mean(0))
    return np.concatenate([top, pano, bot], axis=0)


def pano_to_view(pano_full, yaw_deg, pitch_deg, fov_deg, S):
    """Cut a square perspective view out of a full 2:1 equirect."""
    R = view_basis(yaw_deg, pitch_deg)
    f = (S / 2) / np.tan(np.radians(fov_deg) / 2)
    j, i = np.meshgrid(np.arange(S) + 0.5 - S / 2, np.arange(S) + 0.5 - S / 2)
    d = np.stack([j / f, i / f, np.ones_like(j)], -1) @ R.T
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    lon = np.arctan2(d[..., 0], -d[..., 2])
    lat = np.arcsin(np.clip(d[..., 1], -1, 1))
    H, W = pano_full.shape[:2]
    return sample(pano_full, (lon / (2 * np.pi) + 0.5) * W - 0.5, (0.5 - lat / np.pi) * H - 0.5, wrap=True)
