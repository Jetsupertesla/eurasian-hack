"""Local credentials, re-read on each request so saving .env needs no restart."""
import os
import shlex
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def fal_key():
    values = {}
    for name in (".env", ".env.local"):
        path = REPO / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip().removeprefix("export ").strip()
            key, sep, value = line.partition("=")
            if sep and key.strip() == "FAL_KEY":
                try:
                    values["FAL_KEY"] = " ".join(shlex.split(value, comments=True))
                except ValueError:
                    raise RuntimeError(f"Invalid FAL_KEY quoting in {name}") from None
    key = (os.environ.get("FAL_KEY") or values.get("FAL_KEY", "")).strip()
    return "" if key in ("your-fal-key-here", "your-key", "...") else key


def require_fal_key():
    key = fal_key()
    if not key:
        raise RuntimeError("FAL_KEY missing: run npm run setup:fal, then press G again")
    return key
