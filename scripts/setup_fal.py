"""Save a fal key locally without echoing it or putting it in shell history."""
import getpass
import os
from pathlib import Path

path = Path(__file__).resolve().parent.parent / ".env"
key = getpass.getpass("Paste your fal API key (hidden): ").strip()
if not key or any(c.isspace() for c in key) or key == "your-fal-key-here":
    raise SystemExit("No valid key entered; .env was not changed.")
lines = path.read_text().splitlines() if path.exists() else []
lines = [line for line in lines if line.strip().removeprefix("export ").split("=", 1)[0].strip() != "FAL_KEY"]
lines.append("FAL_KEY=" + key)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    os.fchmod(f.fileno(), 0o600)
    f.write("\n".join(lines) + "\n")
print("Saved to local .env. Go back to the viewer and press G; no restart needed.")
