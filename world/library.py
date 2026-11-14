"""The local photo library; only explicitly indexed image files can be placed."""
import base64
import io
import json
from pathlib import Path
import re
from urllib.parse import quote
from uuid import uuid4
from PIL import Image, ImageOps


def assets(repo):
    repo = Path(repo).resolve()
    files = []
    for folder, category in (("originals", "Photos"), ("rooms", "Room edits"), ("edited", "Room edits"),
                             ("world/library", "Uploads")):
        for path in (repo / folder).glob("*"):
            if path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and "overlay" not in path.name:
                files.append((path, category))
    for path in (repo / "world/worlds").glob("*/gen*.jpg"):
        if re.fullmatch(r"gen(?:_single)?_\d+\.jpg", path.name):
            files.append((path, "Generations"))
    items = []
    for path, category in files:
        if not path.is_file() or not path.resolve().is_relative_to(repo):
            continue
        asset_id = path.relative_to(repo).as_posix()
        name = path.stem.replace("_", " ").replace("-", " ")
        if category == "Uploads" and path.with_suffix(".json").exists():
            name = json.loads(path.with_suffix(".json").read_text()).get("name", name)
        if category == "Generations":
            name = f"{path.parent.name} · {name}"
        items.append({"id": asset_id, "name": name, "category": category,
                      "url": "/" + quote(asset_id, safe="/"),
                      "thumbnail": "/library/thumbnail?id=" + quote(asset_id, safe=""),
                      "modified": path.stat().st_mtime})
    return sorted(items, key=lambda x: (x["category"] not in ("Uploads", "Generations"), -x["modified"]))


def resolve_asset(repo, asset_id):
    if not isinstance(asset_id, str):
        raise ValueError("Choose an image from the library.")
    item = next((item for item in assets(repo) if item["id"] == asset_id), None)
    if item is None:
        raise ValueError("That library image no longer exists. Refresh the library.")
    return Path(repo) / item["id"], item


def read_image(path):
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def thumbnail(repo, asset_id):
    path, _ = resolve_asset(repo, asset_id)
    im = read_image(path)
    im.thumbnail((320, 220), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=78)
    return buf.getvalue()


def upload(repo, req):
    data_url = req.get("image", "")
    if not isinstance(data_url, str) or not data_url.startswith("data:image/") or "," not in data_url:
        raise ValueError("Choose a JPEG, PNG or WebP image.")
    if len(data_url) > 28_000_000:
        raise ValueError("Please choose an image smaller than 20 MB.")
    try:
        data = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        im = read_image(io.BytesIO(data))
    except (ValueError, OSError) as error:
        raise ValueError("The uploaded file is not a readable image.") from error
    im.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
    root = Path(repo) / "world/library"
    root.mkdir(parents=True, exist_ok=True)
    path = root / (uuid4().hex + ".jpg")
    im.save(path, "JPEG", quality=94)
    name = str(req.get("name", "Uploaded photo")).replace("\\", "/").split("/")[-1][:160]
    path.with_suffix(".json").write_text(json.dumps({"name": name}))
    return {"id": path.relative_to(repo).as_posix()}
