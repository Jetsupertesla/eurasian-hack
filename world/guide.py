"""Step 1: photo -> equirect guide for the image model.

    python world/guide.py originals/room3.jpg room3 [hfov_deg]
writes world/worlds/room3/photo.jpg and guide.jpg (photo in the middle, black = not captured yet).
"""
import sys, os
import numpy as np
from PIL import Image, ImageOps
sys.path.insert(0, os.path.dirname(__file__))
from geo import photo_to_guide

src, name = sys.argv[1], sys.argv[2]
hfov = float(sys.argv[3]) if len(sys.argv) > 3 else 75.0
out = os.path.join(os.path.dirname(__file__), "worlds", name)
os.makedirs(out, exist_ok=True)

im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
im.thumbnail((2048, 2048))
im.save(os.path.join(out, "photo.jpg"), quality=92)
W, H = 3360, 1440  # 21:9, the widest ratio the image model takes
guide, ok = photo_to_guide(np.asarray(im, np.float32), hfov, W, H)
Image.fromarray(guide.clip(0, 255).astype(np.uint8)).save(os.path.join(out, "guide.jpg"), quality=93)
print(out, "guide", W, "x", H, "known %.1f%%" % (100 * ok.mean()), "hfov", hfov)
