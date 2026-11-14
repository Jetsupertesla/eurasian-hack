"""Viewer server with a generate button: serves the repo, and POST /generate repaints the framed camera view
with the image model, turns it into splats with SHARP and fits it into the world in place of what was there.

    .sharp/venv/bin/python world/serve.py [port]      # then open http://localhost:3095/world/
Needs FAL_KEY in .env at the repo root (one image call per press, about $0.03) and SHARP (see DEMO_README).
"""
import sys, os, io, json, time, base64, glob, threading, traceback, subprocess, socket
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import numpy as np
import requests
from PIL import Image
from scipy.spatial.transform import Rotation
from urllib.parse import unquote, urlsplit, parse_qs
from config import fal_key, require_fal_key
import history as world_history
import library

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MODEL = os.environ.get("GEN_MODEL", "minimax/h3-image/edit")
S = 1536
PROPS = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
         "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
PROMPT = ("This image is a rough render of a real place from a 3D scan, seen from a new camera position. Some parts are "
          "smeared, stretched, blurry or torn, and black areas are parts the scan has not captured yet. Repaint it as one "
          "clean, sharp photograph taken from exactly this camera position: keep every wall, window, piece of furniture "
          "and plant exactly where it is, with the same perspective, colours and lighting; repair the smeared and torn "
          "areas; fill the black areas with a natural continuation of the same place{scene}. Photorealistic, "
          "no borders, nothing black left.")
LOCK = threading.Lock()
_pred = None
_sharp_error = None
_sharp_device = None


def generation_prompt(scene, additional=""):
    if not isinstance(additional, str) or len(additional) > 2000:
        raise ValueError("Additional prompt must be text of at most 2000 characters.")
    prompt = PROMPT.format(scene=f", which is {scene}" if scene else "")
    additional = additional.strip()
    if additional:
        return (prompt + "\nRequested change: " + additional
                + "\nApply the requested change even when it changes an existing object or adds people or text. "
                  "Keep the camera position, framing and perspective fixed, and preserve everything not mentioned in the request.")
    return prompt + " No people or text."


def network_error(error):
    if isinstance(error, requests.Timeout):
        return "fal timed out. The request may still be processing; do not immediately submit it again."
    return ("Cannot reach fal (queue.fal.run). Check Wi-Fi/internet. If internet works, restart the app "
            "from Terminal with npm run serve or double-click Start.command; this server may have restricted network access.")


def check_fal():
    """Read-only authentication/connectivity check; never submits a model request."""
    key = fal_key()
    if not key:
        return {"fal_authenticated": False, "fal_error": "FAL_KEY missing: run npm run setup:fal"}
    try:
        socket.getaddrinfo("queue.fal.run", 443)
        response = requests.get("https://api.fal.ai/v1/models/requests/by-endpoint",
                                params={"endpoint_id": MODEL, "limit": 1},
                                headers={"Authorization": f"Key {key}"}, timeout=15)
        if response.status_code == 200:
            return {"fal_authenticated": True, "fal_error": None}
        if response.status_code == 401:
            error = "fal rejected the API key. Save a valid key with npm run setup:fal."
        elif response.status_code == 403:
            error = "This fal key cannot read model requests. Use a key with the API permission preset."
        else:
            error = f"fal connectivity check returned HTTP {response.status_code}."
        return {"fal_authenticated": False, "fal_error": error}
    except (OSError, requests.RequestException) as error:
        return {"fal_authenticated": False, "fal_error": network_error(error)}


def paint(im, prompt):
    key = require_fal_key()
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    data = buf.getvalue()
    body = {"prompt": prompt, "output_format": "jpeg", "num_images": 1}
    body.update({"image_size": {"width": 2048, "height": 2048}} if "minimax" in MODEL else {"aspect_ratio": "1:1", "resolution": "2K"})
    h = {"Authorization": f"Key {key}", "Content-Type": "application/json"}

    def call(url, body=None):
        try:
            r = requests.post(url, json=body, headers=h, timeout=120) if body else requests.get(url, headers=h, timeout=120)
        except requests.RequestException as error:
            raise RuntimeError(network_error(error)) from None
        if r.status_code >= 400:
            error = RuntimeError(f"fal answered {r.status_code}: {r.text[:300]}")
            error.status_code = r.status_code
            raise error
        return r.json()

    submit = lambda image: call(f"https://queue.fal.run/{MODEL}", dict(body, image_urls=[image]))
    try:
        sub = submit("data:image/jpeg;base64," + base64.b64encode(data).decode())
    except RuntimeError as error:
        # Retry only a definite input rejection, never auth, billing, or server errors.
        if getattr(error, "status_code", None) != 422 or "image_urls" not in str(error):
            raise
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
    global _pred, _sharp_device
    import torch
    from sharp.models import PredictorParams, create_predictor
    from sharp.cli.predict import predict_image
    from sharp.utils import color_space as cs_utils
    if _sharp_device is None:
        dev = os.environ.get("SHARP_DEVICE") or ("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
        if dev == "mps":
            # Availability alone can be true when macOS denies Metal compiler access.
            # Probe in a child: that native abort must not take down the HTTP server.
            try:
                probe = subprocess.run([sys.executable, "-c", "import torch; torch.ones(1, device='mps').cpu()"],
                                       capture_output=True, timeout=20)
                gpu_ok = probe.returncode == 0
            except subprocess.TimeoutExpired:
                gpu_ok = False
            if not gpu_ok:
                print("Metal GPU unavailable in this session; using CPU for SHARP (slower).", flush=True)
                dev = "cpu"
        _sharp_device = dev
    dev = _sharp_device
    if _pred is None:
        sd = torch.load(os.path.expanduser("~/.cache/torch/hub/checkpoints/sharp_2572gikvuh.pt"), weights_only=True, mmap=True)
        predictor = create_predictor(PredictorParams())
        predictor.load_state_dict(sd, assign=True)
        predictor.eval().to(dev)
        _pred = predictor
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
    b = Path(path).read_bytes()
    return np.frombuffer(b, np.float32, offset=b.index(b"end_header\n") + 11).reshape(-1, 14)


def write_ply(path, arr):
    with open(path, "wb") as f:
        f.write(("ply\nformat binary_little_endian 1.0\nelement vertex %d\n" % len(arr)
                 + "".join(f"property float {p}\n" for p in PROPS) + "end_header\n").encode())
        f.write(np.ascontiguousarray(arr, np.float32).tobytes())


def in_view(xyz, c, R, k, edge, aspect=1.0):
    """Which points fall inside the square view at c with basis R (columns right, down, forward); also their camera coords."""
    p = (xyz - c) @ R
    z = np.maximum(p[:, 2], 1e-6)
    return (p[:, 2] > 0.02) & (np.abs(p[:, 0] / z) < k * edge * aspect) & (np.abs(p[:, 1] / z) < k * edge), p


def front_depth(p, k, G=48, aspect=1.0):
    """Depth of the nearest surface (20th percentile) per cell of a GxG grid over the view."""
    z = p[:, 2]
    ix = lambda a: np.clip(((a / z / k + 1) / 2 * G).astype(int), 0, G - 1)
    cell = ix(p[:, 1]) * G + ix(p[:, 0] / aspect)
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


def world_context(req):
    name = req.get("world", "")
    if not isinstance(name, str) or name in ("", ".", "..") or name != os.path.basename(name):
        raise ValueError("Choose a valid world.")
    root = str(Path(HERE, "worlds", name))
    if not Path(root, "world.json").is_file():
        raise ValueError("That world does not exist.")
    world = json.loads(Path(root, "world.json").read_text())
    single = req.get("mode") == "single"
    if single:
        world["views"] = world["views"][:1]
    prefix = "gen_single" if single else "gen"
    gp = os.path.join(root, prefix + ".json")
    doc = world_history.load_history(gp, world["views"], prefix, single)
    return root, world, single, prefix, gp, doc


def get_history(req):
    return world_history.active_state(world_context(req)[-1])


def select_history(req):
    *_, gp, doc = world_context(req)
    world_history.seek(doc, req.get("cursor"))
    world_history.save_history(gp, doc)
    return world_history.active_state(doc)


def camera_pose(matrix, level=False):
    e = np.asarray(matrix, np.float64)
    if e.size != 16 or not np.all(np.isfinite(e)):
        raise ValueError("Camera matrix must contain 16 finite numbers.")
    e = e.reshape(4, 4).T
    c = e[:3, 3]
    if not level:
        return c, np.stack([e[:3, 0], -e[:3, 1], -e[:3, 2]], 1)
    forward = -e[:3, 2].copy()
    forward[1] = 0
    if np.linalg.norm(forward) < 1e-6:
        right = e[:3, 0].copy()
        right[1] = 0
        forward = np.cross([0, 1, 0], right)
    if np.linalg.norm(forward) < 1e-6:
        forward = np.array([0.0, 0.0, -1.0])
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0, 1, 0])
    return c, np.stack([right, [0, -1, 0], forward], 1)


def generate(req):
    placed = bool(req.get("asset_id"))
    if not placed and not req.get("painted_url"):
        require_fal_key()
    if _sharp_error:
        raise RuntimeError("SHARP could not load: " + _sharp_error)
    root, world, single, prefix, gp, doc = world_context(req)
    st = world_history.active_state(doc)
    if (("history_cursor" in req and req["history_cursor"] != doc["cursor"])
            or ("history_n" in req and req["history_n"] != doc["n"])):
        raise ValueError("The world changed in another window. Reload before adding a view.")
    n = doc["n"] + 1
    c, R = camera_pose(req["matrix"], level=placed)
    fov = float(req["fov"])
    if not np.isfinite(fov) or not 10 <= fov <= 120:
        raise ValueError("Camera field of view must be between 10 and 120 degrees.")
    k = np.tan(np.radians(fov) / 2)
    t0 = time.time()
    asset = None
    if placed:
        source, asset = library.resolve_asset(REPO, req["asset_id"])
        out = library.read_image(source)
        out.thumbnail((S, S), Image.Resampling.LANCZOS)
    else:
        prompt = generation_prompt(world.get("prompt") or "", req.get("prompt", ""))
        im = Image.open(io.BytesIO(base64.b64decode(req["image"].split(",", 1)[1]))).convert("RGB").resize((S, S), Image.LANCZOS)
        im.save(os.path.join(root, f"{prefix}_{n:02d}_in.jpg"), quality=92)
        url = req.get("painted_url") or paint(im, prompt)
        downloaded = requests.get(url, timeout=300)
        downloaded.raise_for_status()
        out = Image.open(io.BytesIO(downloaded.content)).convert("RGB").resize((S, S), Image.LANCZOS)
    out.save(os.path.join(root, f"{prefix}_{n:02d}.jpg"), quality=92)
    aspect = out.width / out.height
    t1 = time.time()
    g = sharp(np.asarray(out), (out.height / 2) / k)
    t2 = time.time()

    # one depth scale for the new view, fitted to the surfaces the world already has in this frame
    xyz = g["xyz"]
    z = np.maximum(xyz[:, 2], 1e-6)
    own = (xyz[:, 2] > 0.02) & (np.abs(xyz[:, 0] / z) < k * aspect * 0.97) & (np.abs(xyz[:, 1] / z) < k * 0.97) & (g["opac"] > 0.02)
    if not np.any(own):
        raise RuntimeError("No usable 3D points were found. The world has not been changed.")
    files = [st["replace"].get(v["file"], v["file"]) for v in world["views"]] + [x["file"] for x in st["gens"]]
    olds = {f: read_ply(os.path.join(root, f)) for f in files}
    P = np.concatenate([a[a[:, 6] > -1.386, :3] for a in olds.values()])   # opacity above 0.2
    m, p = in_view(P, c, R, k, 1.0, aspect)
    d_old, d_new = front_depth(p[m], k, aspect=aspect), front_depth(xyz[own & (g["opac"] > 0.2)], k, aspect=aspect)
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
    write_ply(os.path.join(root, f"{prefix}_{n:02d}.ply"), arr)

    # what the world had inside this frame is replaced: write each touched chunk again without those splats
    cut = 0
    for f, a in olds.items():
        m, _ = in_view(a[:, :3], c, R, k, 0.93, aspect)
        if m.sum() < 200:
            continue
        suffix = "single-c" if single else "c"
        nf = f"{f.split('.')[0]}.{suffix}{n:02d}.ply"
        write_ply(os.path.join(root, nf), a[~m])
        cut += int(m.sum())
        for v in world["views"]:
            if st["replace"].get(v["file"], v["file"]) == f:
                st["replace"][v["file"]] = nf
        for x in st["gens"]:
            if x["file"] == f:
                x["file"] = nf
    st["gens"].append({"id": n, "file": f"{prefix}_{n:02d}.ply", "pos": c.tolist(), "R": R.tolist(), "fov": fov,
                       "aspect": aspect, "dist": float(np.median(s * xyz[own, 2])),
                       "scale": round(s, 4), "count": int(own.sum()), "prompt": "" if placed else req.get("prompt", "").strip(),
                       "image": f"{prefix}_{n:02d}.jpg", "kind": "placement" if placed else "generation",
                       "asset_id": req.get("asset_id"), "label": f"Placed {asset['name']}" if placed else f"Generation {n}"})
    world_history.append_step(doc, st["replace"], st["gens"], n)
    world_history.save_history(gp, doc)
    secs = {"paint": round(t1 - t0, 1), "sharp": round(t2 - t1, 1), "fit": round(time.time() - t2, 1)}
    print(f"view {world.get('name', Path(root).name)} #{n}: {own.sum()} splats in, {cut} out, scale {s:.3f} over {both.sum()} cells, {secs}", flush=True)
    return dict(world_history.active_state(doc), secs=secs)


def reset(req):
    return select_history(dict(req, cursor=0))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=REPO, **kw)

    def log_message(self, *a):
        pass

    def send_json(self, out, code=200):
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        if any(part.startswith(".") for part in path.split("/")):
            self.send_error(404)
            return None
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/world/")
            self.end_headers()
            return None
        return super().send_head()

    def do_GET(self):
        path = urlsplit(self.path).path
        query = {key: values[0] for key, values in parse_qs(urlsplit(self.path).query).items()}
        if path in ("/history", "/library", "/library/thumbnail"):
            try:
                if path == "/history":
                    with LOCK:
                        out = get_history(query)
                elif path == "/library":
                    out = {"assets": library.assets(REPO)}
                else:
                    data = library.thumbnail(REPO, query.get("id"))
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                return self.send_json(out)
            except (ValueError, OSError) as error:
                return self.send_json({"error": str(error)}, 400)
        if path == "/health":
            status = {"fal_configured": bool(fal_key()), "sharp_ready": _pred is not None, "sharp_device": _sharp_device,
                      "sharp_error": _sharp_error, "model": MODEL, "editor_version": 2}
            if query.get("check_fal") == "1":
                status.update(check_fal())
            return self.send_json(status)
        super().do_GET()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 30_000_000:
                return self.send_json({"error": "Request is too large (maximum 20 MB image)."}, 413)
            body = json.loads(self.rfile.read(length))
            if self.path == "/generate":
                with LOCK:
                    out = generate(body)
            elif self.path == "/history":
                with LOCK:
                    out = select_history(body)
            elif self.path == "/library/upload":
                out = library.upload(REPO, body)
            elif self.path == "/reset":
                with LOCK:
                    out = reset(body)
            else:
                return self.send_error(404)
            code = 200
        except Exception as e:
            traceback.print_exc()
            message = network_error(e) if isinstance(e, requests.RequestException) else str(e)
            out, code = {"error": message}, 400 if isinstance(e, ValueError) else 500
        self.send_json(out, code)


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 3095))
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    def warm():
        global _sharp_error
        with LOCK:
            try:
                sharp(None, 0)
                print("SHARP loaded", flush=True)
            except Exception as error:
                _sharp_error = str(error)
                print("SHARP failed to load: " + _sharp_error, flush=True)
    threading.Thread(target=warm, daemon=True).start()
    print(f"http://localhost:{PORT}/world/   (fal key: {'found' if fal_key() else 'MISSING, generate will fail'}; model {MODEL})", flush=True)
    server.serve_forever()
