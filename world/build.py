"""Step 2: 360 panorama -> one splat world made of per-view chunks.

    python world/build.py room3      # reads world/worlds/room3/pano.jpg, writes view_XX.ply + world.json

Each view is cut from the panorama, turned into splats by SHARP, scaled so neighbours agree where
they overlap, trimmed to the directions it owns, and rotated into world space
(+x right, +y up, -z forward: three.js axes, so the viewer needs no flip).
"""
import sys, os, json, time
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import view_basis, extend_pano, pano_to_view

name = sys.argv[1]
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worlds", name)
WORK = os.path.join(ROOT, ".work")
os.makedirs(WORK, exist_ok=True)

S, FOV = 1536, 90.0
F_PX = (S / 2) / np.tan(np.radians(FOV) / 2)
EDGE = 0.96  # ignore the outer 4% of every view, SHARP is weakest there
# (yaw, pitch) in degrees; order = reveal order in the viewer
VIEWS = [(0, 0), (60, 0), (-60, 0), (120, 0), (-120, 0), (180, 0),
         (0, -55), (120, -55), (-120, -55), (60, 55), (180, 55), (-60, 55)]
if len(sys.argv) > 2:
    VIEWS = VIEWS[: int(sys.argv[2])]
K = len(VIEWS)
R = [view_basis(y, p) for y, p in VIEWS]

# ---- 1. cut views ---------------------------------------------------------------------------
pano = np.asarray(Image.open(os.path.join(ROOT, "pano.jpg")).convert("RGB"), np.float32)
full = extend_pano(pano)
views = []
for k, (yaw, pitch) in enumerate(VIEWS):
    v = pano_to_view(full, yaw, pitch, FOV, S).clip(0, 255).astype(np.uint8)
    Image.fromarray(v).save(os.path.join(WORK, f"view_{k:02d}.jpg"), quality=92)
    views.append(v)
print("cut", K, "views from pano", pano.shape[1], "x", pano.shape[0], flush=True)

# ---- 2. SHARP per view (cached) ---------------------------------------------------------------
todo = [k for k in range(K) if not os.path.exists(os.path.join(WORK, f"view_{k:02d}.npz"))]
if todo:
    import torch
    from sharp.models import PredictorParams, create_predictor
    from sharp.cli.predict import predict_image
    from sharp.utils import color_space as cs_utils

    sd = torch.load(os.path.expanduser("~/.cache/torch/hub/checkpoints/sharp_2572gikvuh.pt"), weights_only=True)
    predictor = create_predictor(PredictorParams())
    predictor.load_state_dict(sd)
    dev = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    predictor.eval().to(dev)
    for k in todo:
        t0 = time.time()
        g = predict_image(predictor, views[k], F_PX, torch.device(dev))
        np.savez(
            os.path.join(WORK, f"view_{k:02d}.npz"),
            xyz=g.mean_vectors[0].cpu().numpy().astype(np.float32),
            scale=g.singular_values[0].cpu().numpy().astype(np.float32),
            quat=g.quaternions[0].cpu().numpy().astype(np.float32),
            rgb=cs_utils.linearRGB2sRGB(g.colors[0]).cpu().numpy().astype(np.float32),
            opac=g.opacities[0].cpu().numpy().astype(np.float32),
        )
        del g
        if dev == "mps":
            torch.mps.empty_cache()  # without this the process grows past 13 GB over a dozen views
        print(f"sharp view {k:02d} yaw {VIEWS[k][0]} pitch {VIEWS[k][1]}  {time.time() - t0:.0f}s", flush=True)
    del predictor

# ---- 3. one depth scale per view, fitted where views overlap ----------------------------------
G = [dict(np.load(os.path.join(WORK, f"view_{k:02d}.npz"))) for k in range(K)]
CW, CH = 180, 90  # 2 degree cells


def inside(d, Rk):
    p = d @ Rk  # world direction -> that camera
    z = np.maximum(p[:, 2], 1e-6)
    return (p[:, 2] > 0.05) & (np.abs(p[:, 0] / z) < EDGE) & (np.abs(p[:, 1] / z) < EDGE)


logr, wsum = [], []
for k in range(K):
    g = G[k]
    r = np.linalg.norm(g["xyz"], axis=1)
    d = (g["xyz"] / r[:, None]) @ R[k].T
    g["dir"], g["r"] = d, r
    m = inside(d, R[k]) & (g["opac"] > 0.2)
    lon, lat = np.arctan2(d[m, 0], -d[m, 2]), np.arcsin(np.clip(d[m, 1], -1, 1))
    cell = (np.clip(((0.5 - lat / np.pi) * CH).astype(int), 0, CH - 1) * CW
            + np.clip(((lon / (2 * np.pi) + 0.5) * CW).astype(int), 0, CW - 1))
    w = np.bincount(cell, g["opac"][m], CW * CH)
    s = np.bincount(cell, g["opac"][m] * np.log(r[m]), CW * CH)
    logr.append(np.where(w > 0, s / np.maximum(w, 1e-9), 0))
    wsum.append(w)

rows, rhs = [], []
for i in range(K):
    for j in range(i + 1, K):
        both = (wsum[i] > 3) & (wsum[j] > 3)
        if both.sum() < 60:
            continue
        diff = (logr[i] - logr[j])[both]
        delta = np.median(diff)
        mad = np.median(np.abs(diff - delta))
        wt = np.sqrt(both.sum()) / (0.02 + mad)
        row = np.zeros(K)
        row[i], row[j] = wt, -wt
        rows.append(row)
        rhs.append(-delta * wt)
        print(f"overlap {i:02d}-{j:02d} cells {both.sum():4d}  ratio {np.exp(delta):.3f}  spread {100 * mad:.1f}%")
anchor = np.zeros(K)
anchor[0] = 1e3
x = np.linalg.lstsq(np.array(rows + [anchor]), np.array(rhs + [0.0]), rcond=None)[0]
scale = np.exp(x)
print("scales", np.round(scale, 3), flush=True)

# ---- 4. trim each view to the directions it owns, move to world space, write -------------------
fwd = np.stack([Rk[:, 2] for Rk in R])  # K x 3


def qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    return np.stack([aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw], 1)


PROPS = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
         "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
pf = os.path.join(ROOT, "prompt.txt")
manifest = {"name": name, "prompt": open(pf).read().strip() if os.path.exists(pf) else "", "fov": FOV, "panoW": int(pano.shape[1]), "panoH": int(pano.shape[0]), "views": []}
Image.fromarray(pano.astype(np.uint8)).resize((736, round(736 * pano.shape[0] / pano.shape[1]))).save(os.path.join(ROOT, "pano_small.jpg"), quality=85)
total = 0
for k in range(K):
    g = G[k]
    d = g["dir"]
    score = np.full((len(d), K), -2.0, np.float32)
    for j in range(K):
        mj = inside(d, R[j])
        score[mj, j] = (d[mj] @ fwd[j]).astype(np.float32)
    keep = (score[:, k] > -1) & (score[:, k] >= score.max(1) - 0.01) & (g["opac"] > 0.02)
    xyz = scale[k] * (g["xyz"][keep] @ R[k].T)
    qx, qy, qz, qw = Rotation.from_matrix(R[k]).as_quat()
    quat = qmul((qw, qx, qy, qz), g["quat"][keep])
    quat /= np.linalg.norm(quat, axis=1, keepdims=True)
    o = np.clip(g["opac"][keep], 1e-4, 1 - 1e-4)
    arr = np.empty((keep.sum(), 14), np.float32)
    arr[:, 0:3] = xyz
    arr[:, 3:6] = (g["rgb"][keep] - 0.5) / 0.28209479177387814
    arr[:, 6] = np.log(o / (1 - o))
    arr[:, 7:10] = np.log(np.maximum(scale[k] * g["scale"][keep], 1e-7))
    arr[:, 10:14] = quat
    fn = f"view_{k:02d}.ply"
    with open(os.path.join(ROOT, fn), "wb") as f:
        f.write(("ply\nformat binary_little_endian 1.0\nelement vertex %d\n" % len(arr)
                 + "".join(f"property float {p}\n" for p in PROPS) + "end_header\n").encode())
        f.write(arr.tobytes())
    Image.fromarray(views[k]).resize((384, 384)).save(os.path.join(ROOT, f"view_{k:02d}.jpg"), quality=85)
    dist = float(np.median(g["r"][keep]) * scale[k])
    manifest["views"].append({"file": fn, "thumb": f"view_{k:02d}.jpg", "yaw": VIEWS[k][0], "pitch": VIEWS[k][1],
                              "scale": round(float(scale[k]), 4), "count": int(keep.sum()), "dist": round(dist, 2)})
    total += int(keep.sum())
    print(f"wrote {fn}  {keep.sum():8d} splats  median range {dist:.2f} m", flush=True)
manifest["total"] = total
json.dump(manifest, open(os.path.join(ROOT, "world.json"), "w"), indent=1)
idx = os.path.join(os.path.dirname(ROOT), "index.json")
names = json.load(open(idx)) if os.path.exists(idx) else []
if name not in names:
    json.dump(names + [name], open(idx, "w"))
print("world", name, "total splats", total)
