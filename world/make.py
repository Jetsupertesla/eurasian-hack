"""One command: photo -> world you can look around in.

    python world/make.py originals/room3.jpg room3
    python world/make.py originals/room3.jpg overgrown "abandoned for decades and reclaimed by nature, ferns and
        tall grass through the floor boards, ivy on the brick, pools of still green water"

Needs FAL_KEY in .env at the repo root (one image-model call, about $0.14), then runs SHARP on this
machine (about 4 minutes on an M2). Open world/index.html?w=<name> when it finishes.
FILL_MODEL=fal-ai/nano-banana-pro/edit goes back to the old model, whose panoramas need the second, seam-repair call;
SEAM_REPAINT=1 forces that call for any model.
"""
import sys, os, json, time, base64, subprocess, io
import requests  # comes with the SHARP environment
from PIL import Image
from config import require_fal_key

HERE = os.path.dirname(os.path.abspath(__file__))
src, name = sys.argv[1], sys.argv[2]
scene = sys.argv[3] if len(sys.argv) > 3 else ""
ROOT = os.path.join(HERE, "worlds", name)
MODEL = os.environ.get("FILL_MODEL", "google/nano-banana-2.1/edit")
REPAINT = os.environ.get("SEAM_REPAINT", "1" if "nano-banana-pro" in MODEL else "0") == "1"

KEY = require_fal_key()

FILL = ("This is an unfinished 360-degree equirectangular panorama of one interior: the full image spans 360 degrees "
        "horizontally and its left and right edges are the same direction. The middle shows the part that has already "
        "been photographed. The black area is the rest of the same place, not captured yet. Extend the existing 3D scene: "
        "fill every black area with what you would see when turning around on the same spot: {scene}. Keep correct "
        "equirectangular perspective, with vertical lines staying vertical, the floor filling the bottom and the ceiling "
        "filling the top. Keep the photographed part exactly where it is, at the same size, unchanged. The left edge and "
        "the right edge must join seamlessly. Photorealistic, no people, no text, no black left anywhere, no borders.")
SAME = "the rest of this same room, with the same floor, the same ceiling, the same wall finishes and the same daylight"
SEAM = ("This is a 360-degree equirectangular panorama of one place. There is a hard vertical seam running down the exact "
        "centre of the image where the left half and the right half do not match: objects are cut off and the floor, walls "
        "and ceiling change abruptly. Repaint only the central part of the image so the place continues naturally across "
        "the centre as one coherent space: floor, ceiling and walls must flow across without any visible join, and cut-off "
        "objects are either completed or removed. Keep the outer left third and the outer right third of the image exactly "
        "as they are, pixel for pixel, same position and size. Photorealistic, same lighting, no people, no text.")


def http(url, body=None):
    h = {"Authorization": f"Key {KEY}", "Content-Type": "application/json"}
    r = requests.post(url, json=body, headers=h, timeout=120) if body else requests.get(url, headers=h, timeout=120)
    if r.status_code >= 400:
        sys.exit(f"fal answered {r.status_code} for {url.split('?')[0]}: {r.text[:300]}")
    return r.json()


def paint(image_path, prompt, out_path, max_w=4096):
    im = Image.open(image_path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(max_w * im.height / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    sub = http(f"https://queue.fal.run/{MODEL}", {"prompt": prompt, "image_urls": [uri], "aspect_ratio": "21:9",
                                                   "resolution": "4K", "output_format": "jpeg", "num_images": 1})
    if "request_id" not in sub:
        sys.exit("fal refused the job: " + json.dumps(sub)[:400])
    while True:
        time.sleep(3)
        st = http(sub["status_url"])["status"]
        if st == "COMPLETED":
            break
        if st not in ("IN_QUEUE", "IN_PROGRESS"):
            sys.exit("fal job failed: " + st)
    url = http(sub["response_url"])["images"][0]["url"]
    open(out_path, "wb").write(requests.get(url, timeout=300).content)
    print("painted", out_path, flush=True)


def run(script, *args):
    subprocess.run([sys.executable, os.path.join(HERE, script), *args], check=True)


t0 = time.time()
run("guide.py", src, name)
if scene:
    open(os.path.join(ROOT, "prompt.txt"), "w").write(scene)
paint(os.path.join(ROOT, "guide.jpg"), FILL.format(scene=f"the rest of this same place, but {scene}" if scene else SAME),
      os.path.join(ROOT, "pano.jpg"))
if REPAINT:
    run("seam.py", "prep", name)
    paint(os.path.join(ROOT, ".work", "rolled.jpg"), SEAM, os.path.join(ROOT, ".work", "seamfix.jpg"))
    run("seam.py", "apply", name)
else:
    run("seam.py", "level", name)
run("build.py", name)
print(f"done in {time.time() - t0:.0f}s -> world/index.html?w={name}")
