"""The image model does not make the panorama's left and right edges meet. Fix: roll the panorama half a
turn so that join sits in the middle, have the model repaint the middle, keep only that band.

    python world/seam.py prep room3     # pano.jpg -> .work/pano_raw.jpg + .work/rolled.jpg  (send rolled.jpg to the model)
    python world/seam.py apply room3    # .work/rolled.jpg + .work/seamfix.jpg -> pano.jpg
    python world/seam.py level room3    # no model call: for panoramas whose edges already meet but differ slightly in tone
"""
import sys, os, shutil
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter1d

mode, name = sys.argv[1], sys.argv[2]
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worlds", name)
os.makedirs(os.path.join(ROOT, ".work"), exist_ok=True)
P = lambda f: os.path.join(ROOT, f if f == "pano.jpg" else os.path.join(".work", f))  # only the result stays in the world folder
BAND, FEATHER = 0.26, 0.07  # repainted share of the width, and the soft edge on each side

if mode == "prep":
    if not os.path.exists(P("pano_raw.jpg")):
        shutil.copy(P("pano.jpg"), P("pano_raw.jpg"))
    im = np.asarray(Image.open(P("pano_raw.jpg")).convert("RGB"))
    Image.fromarray(np.roll(im, im.shape[1] // 2, axis=1)).save(P("rolled.jpg"), quality=93)
    print(P("rolled.jpg"), os.path.getsize(P("rolled.jpg")))
elif mode == "level":
    if not os.path.exists(P("pano_raw.jpg")):
        shutil.copy(P("pano.jpg"), P("pano_raw.jpg"))
    a = np.asarray(Image.open(P("pano_raw.jpg")).convert("RGB"), np.float32).copy()
    H, W = a.shape[:2]
    d = gaussian_filter1d(a[:, :6].mean(1) - a[:, -6:].mean(1), sigma=H * 0.01, axis=0)  # tone step across the join, per row
    n = round(W * 0.05)
    w = np.linspace(0.5, 0, n)[None, :, None]
    a[:, :n] -= d[:, None] * w
    a[:, -n:] += d[:, None] * w[:, ::-1]
    Image.fromarray(a.clip(0, 255).astype(np.uint8)).save(P("pano.jpg"), quality=93)
    print("levelled; tone step at the join was", round(float(np.abs(d).mean()), 1), "/255 on average")
else:
    a = np.asarray(Image.open(P("rolled.jpg")).convert("RGB"), np.float32)
    H, W = a.shape[:2]
    b = np.asarray(Image.open(P("seamfix.jpg")).convert("RGB").resize((W, H), Image.LANCZOS), np.float32)
    x = np.abs((np.arange(W) + 0.5) / W - 0.5)
    m = np.clip((BAND / 2 + FEATHER - x) / FEATHER, 0, 1)
    m = (m * m * (3 - 2 * m))[None, :, None]
    drift = np.abs(a - b)[:, (x > BAND / 2 + FEATHER)].mean()
    out = a * (1 - m) + b * m
    Image.fromarray(np.roll(out, -(W // 2), axis=1).clip(0, 255).astype(np.uint8)).save(P("pano.jpg"), quality=93)
    print("applied; the model changed the untouched part by", round(float(drift), 1), "/255 on average")
