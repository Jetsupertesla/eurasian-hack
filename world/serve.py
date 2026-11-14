"""Viewer server with a generate button: serves the repo, and POST /generate repaints the framed camera view
with the image model, turns it into splats with SHARP and fits it into the world in place of what was there.

    .sharp/venv/bin/python world/serve.py [port]      # then open http://localhost:3095/world/
Needs FAL_KEY in .env at the repo root (one image call per press, about $0.03) and SHARP (see DEMO_README).
"""
import sys, os, io, json, time, base64, glob, threading, traceback
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import numpy as np
import requests
from PIL import Image
from scipy.spatial.transform import Rotation

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3095
MODEL = os.environ.get("GEN_MODEL", "minimax/h3-image/edit")
S = 1536
PROPS = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
         "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
PROMPT = ("This image is a rough render of a real place from a 3D scan, seen from a new camera position. Some parts are "
          "smeared, stretched, blurry or torn, and black areas are parts the scan has not captured yet. Repaint it as one "
          "clean, sharp photograph taken from exactly this camera position: keep every wall, window, piece of furniture "
          "and plant exactly where it is, with the same perspective, colours and lighting; repair the smeared and torn "
          "areas; fill the black areas with a natural continuation of the same place{scene}. Photorealistic, no people, "
          "no text, no borders, nothing black left.")
LOCK = threading.Lock()
_pred = None


def fal_key():
    env = os.path.join(REPO, ".env")
    return os.environ.get("FAL_KEY") or (next(
        (l.split("=", 1)[1].strip() for l in open(env) if l.startswith("FAL_KEY=")), "") if os.path.exists(env) else "")


def paint(im, prompt):
    key = fal_key()
    if not key:
        raise RuntimeError("FAL_KEY missing: put FAL_KEY=... in .env at the repo root")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    data = buf.getvalue()
    body = {"prompt": prompt, "output_format": "jpeg", "num_images": 1}
    body.update({"image_size": {"width": 2048, "height": 2048}} if "minimax" in MODEL else {"aspect_ratio": "1:1", "resolution": "2K"})
    h = {"Authorization": f"Key {key}", "Content-Type": "application/json"}

    def call(url, body=None):
        r = requests.post(url, json=body, headers=h, timeout=120) if body else requests.get(url, headers=h, timeout=120)
        if r.status_code >= 400:
            raise RuntimeError(f"fal answered {r.status_code}: {r.text[:300]}")
        return r.json()

    submit = lambda image: call(f"https://queue.fal.run/{MODEL}", dict(body, image_urls=[image]))
    try:
        sub = submit("data:image/jpeg;base64," + base64.b64encode(data).decode())
    except RuntimeError:                                  # endpoint wants a hosted file: put it in fal storage first
        up = call("https://rest.alpha.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3",
                  {"file_name": "view.jpg", "content_type": "image/jpeg"})
        requests.put(up["upload_url"], data=data, headers={"Content-Type": "image/jpeg"}, timeout=120).raise_for_status()
        sub = submit(up["file_url"])
    while True:
        time.sleep(1.5)
        st = call(sub["status_url"])["status"]
        if st == "COMPLETED":
            return call(sub["response_url"])["images"][0]["url"]
        if st not in ("IN_QUEUE", "IN_PROGRESS"):
            raise RuntimeError("fal job failed: " + st)


def sharp(img, f_px):
    global _pred
    import torch
    from sharp.models import PredictorParams, create_predictor
    from sharp.cli.predict import predict_image
    from sharp.utils import color_space as cs_utils
    dev = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    if _pred is None:
        sd = torch.load(os.path.expanduser("~/.cache/torch/hub/checkpoints/sharp_2572gikvuh.pt"), weights_only=True)
        _pred = create_predictor(PredictorParams())
        _pred.load_state_dict(sd)
        _pred.eval().to(dev)
    if img is None:
        return None
    g = predict_image(_pred, img, f_px, torch.device(dev))
    out = dict(xyz=g.mean_vectors[0].cpu().numpy().astype(np.float32), scale=g.singular_values[0].cpu().numpy().astype(np.float32),
               quat=g.quaternions[0].cpu().numpy().astype(np.float32), opac=g.opacities[0].cpu().numpy().astype(np.float32),
               rgb=cs_utils.linearRGB2sRGB(g.colors[0]).cpu().numpy().astype(np.float32))
    del g
    if dev == "mps":
        torch.mps.empty_cache()
    return out


def read_ply(path):
    b = open(path, "rb").read()
    return np.frombuffer(b, np.float32, offset=b.index(b"end_header\n") + 11).reshape(-1, 14)


def write_ply(path, arr):
    with open(path, "wb") as f:
        f.write(("ply\nformat binary_little_endian 1.0\nelement vertex %d\n" % len(arr)
                 + "".join(f"property float {p}\n" for p in PROPS) + "end_header\n").encode())
        f.write(np.ascontiguousarray(arr, np.float32).tobytes())


def in_view(xyz, c, R, k, edge):
    """Which points fall inside the square view at c with basis R (columns right, down, forward); also their camera coords."""
    p = (xyz - c) @ R
    z = np.maximum(p[:, 2], 1e-6)
    return (p[:, 2] > 0.02) & (np.abs(p[:, 0] / z) < k * edge) & (np.abs(p[:, 1] / z) < k * edge), p


def front_depth(p, k, G=48):
    """Depth of the nearest surface (20th percentile) per cell of a GxG grid over the view."""
    z = p[:, 2]
    ix = lambda a: np.clip(((a / z / k + 1) / 2 * G).astype(int), 0, G - 1)
    cell = ix(p[:, 1]) * G + ix(p[:, 0])
    o = np.lexsort((z, cell))
    cell, z = cell[o], z[o]
    start = np.searchsorted(cell, np.arange(G * G))
    n = np.diff(np.append(start, len(cell)))
    d = np.full(G * G, np.nan)
    ok = n >= 8
    d[ok] = z[(start + (n * 0.2).astype(int))[ok]]
    return d


def qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    return np.stack([aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw], 1)


def generate(req):
    name = os.path.basename(req["world"])
    root = os.path.join(HERE, "worlds", name)
    world = json.load(open(os.path.join(root, "world.json")))
    gp = os.path.join(root, "gen.json")
    st = json.load(open(gp)) if os.path.exists(gp) else {"n": 0, "replace": {}, "gens": []}
    n = st["n"] + 1
    e = np.array(req["matrix"], np.float64).reshape(4, 4).T          # three.js stores matrices column by column
    c, R = e[:3, 3], np.stack([e[:3, 0], -e[:3, 1], -e[:3, 2]], 1)   # camera right, down, forward in world axes
    k = np.tan(np.radians(req["fov"]) / 2)
    t0 = time.time()
    im = Image.open(io.BytesIO(base64.b64decode(req["image"].split(",", 1)[1]))).convert("RGB").resize((S, S), Image.LANCZOS)
    im.save(os.path.join(root, f"gen_{n:02d}_in.jpg"), quality=92)
    scene = world.get("prompt") or ""
    url = req.get("painted_url") or paint(im, PROMPT.format(scene=f", which is {scene}" if scene else ""))
    out = Image.open(io.BytesIO(requests.get(url, timeout=300).content)).convert("RGB").resize((S, S), Image.LANCZOS)
    out.save(os.path.join(root, f"gen_{n:02d}.jpg"), quality=92)
    t1 = time.time()
    g = sharp(np.asarray(out), (S / 2) / k)
    t2 = time.time()

    # one depth scale for the new view, fitted to the surfaces the world already has in this frame
    xyz = g["xyz"]
    z = np.maximum(xyz[:, 2], 1e-6)
    own = (xyz[:, 2] > 0.02) & (np.abs(xyz[:, 0] / z) < k * 0.97) & (np.abs(xyz[:, 1] / z) < k * 0.97) & (g["opac"] > 0.02)
    files = [st["replace"].get(v["file"], v["file"]) for v in world["views"]] + [x["file"] for x in st["gens"]]
    olds = {f: read_ply(os.path.join(root, f)) for f in files}
    P = np.concatenate([a[a[:, 6] > -1.386, :3] for a in olds.values()])   # opacity above 0.2
    m, p = in_view(P, c, R, k, 1.0)
    d_old, d_new = front_depth(p[m], k), front_depth(xyz[own & (g["opac"] > 0.2)], k)
    both = np.isfinite(d_old) & np.isfinite(d_new)
    s = float(np.exp(np.median(np.log(d_old[both]) - np.log(d_new[both])))) if both.sum() > 50 else 1.0

    qx, qy, qz, qw = Rotation.from_matrix(R).as_quat()
    quat = qmul((qw, qx, qy, qz), g["quat"][own])
    quat /= np.linalg.norm(quat, axis=1, keepdims=True)
    o = np.clip(g["opac"][own], 1e-4, 1 - 1e-4)
    arr = np.empty((own.sum(), 14), np.float32)
    arr[:, 0:3] = s * (xyz[own] @ R.T) + c
    arr[:, 3:6] = (g["rgb"][own] - 0.5) / 0.28209479177387814
    arr[:, 6] = np.log(o / (1 - o))
    arr[:, 7:10] = np.log(np.maximum(s * g["scale"][own], 1e-7))
    arr[:, 10:14] = quat
    write_ply(os.path.join(root, f"gen_{n:02d}.ply"), arr)

    # what the world had inside this frame is replaced: write each touched chunk again without those splats
    cut = 0
    for f, a in olds.items():
        m, _ = in_view(a[:, :3], c, R, k, 0.93)
        if m.sum() < 200:
            continue
        nf = f"{f.split('.')[0]}.c{n:02d}.ply"
        write_ply(os.path.join(root, nf), a[~m])
        cut += int(m.sum())
        for v in world["views"]:
            if st["replace"].get(v["file"], v["file"]) == f:
                st["replace"][v["file"]] = nf
        for x in st["gens"]:
            if x["file"] == f:
                x["file"] = nf
    st["n"] = n
    st["gens"].append({"id": n, "file": f"gen_{n:02d}.ply", "pos": c.tolist(), "R": R.tolist(), "fov": req["fov"],
                       "scale": round(s, 4), "count": int(own.sum())})
    json.dump(st, open(gp, "w"))
    secs = {"paint": round(t1 - t0, 1), "sharp": round(t2 - t1, 1), "fit": round(time.time() - t2, 1)}
    print(f"gen {name} #{n}: {own.sum()} splats in, {cut} out, scale {s:.3f} over {both.sum()} cells, {secs}", flush=True)
    return dict(st, secs=secs)


def reset(req):
    root = os.path.join(HERE, "worlds", os.path.basename(req["world"]))
    for f in glob.glob(os.path.join(root, "gen.json")) + glob.glob(os.path.join(root, "gen_[0-9][0-9]*")) \
            + glob.glob(os.path.join(root, "*.c[0-9][0-9].ply")):
        os.remove(f)
    return {"ok": True}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=REPO, **kw)

    def log_message(self, *a):
        pass

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/generate":
                with LOCK:
                    out = generate(body)
            elif self.path == "/reset":
                with LOCK:
                    out = reset(body)
            else:
                return self.send_error(404)
            code = 200
        except Exception as e:
            traceback.print_exc()
            out, code = {"error": str(e)}, 500
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    def warm():
        with LOCK:
            sharp(None, 0)
            print("SHARP loaded", flush=True)
    threading.Thread(target=warm, daemon=True).start()
    print(f"http://localhost:{PORT}/world/   (fal key: {'found' if fal_key() else 'MISSING, generate will fail'}; model {MODEL})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
