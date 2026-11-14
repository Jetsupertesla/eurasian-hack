"""Immutable world snapshots. Geometry files are never deleted by undo or redo."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import time


def snapshot(replace=None, gens=None, label="Starting view", kind="base", step_id=0):
    return {"replace": deepcopy(replace or {}), "gens": deepcopy(gens or []),
            "label": label, "kind": kind, "id": step_id}


def load_history(path, views, prefix, single):
    path = Path(path)
    if not path.exists():
        return {"version": 2, "n": 0, "cursor": 0, "history": [snapshot()]}
    old = json.loads(path.read_text())
    if old.get("version") == 2 and old.get("history"):
        return old
    # Earlier versions kept every PLY but only the latest metadata. Reconstruct
    # each original/cut version from its monotonically increasing generation ID.
    root = path.parent
    suffix = "single-c" if single else "c"

    def file_at(original, step):
        choices = [(0, original)] if (root / original).is_file() else []
        stem = Path(original).stem
        pattern = re.compile(re.escape(stem + "." + suffix) + r"(\d+)\.ply$")
        for file in root.glob(stem + "." + suffix + "*.ply"):
            match = pattern.fullmatch(file.name)
            if match and int(match[1]) <= step:
                choices.append((int(match[1]), file.name))
        if not choices:
            raise FileNotFoundError(original)
        return max(choices)[1]

    gens = deepcopy(old.get("gens", []))
    for g in gens:
        g.setdefault("kind", "generation")
        g.setdefault("image", f"{prefix}_{g['id']:02d}.jpg")
        g.setdefault("label", f"Generation {g['id']}")
    history = [snapshot()]
    for index, g in enumerate(gens):
        step = g["id"]
        try:
            replace = {v["file"]: file_at(v["file"], step) for v in views}
            replace = {src: dest for src, dest in replace.items() if src != dest}
            active = deepcopy(gens[:index + 1])
            for item in active:
                item["file"] = file_at(f"{prefix}_{item['id']:02d}.ply", step)
            history.append(snapshot(replace, active, g["label"], g["kind"], step))
        except FileNotFoundError:
            # Do not invent an undo state when an older file was removed.
            continue
    if gens:
        latest = snapshot(old.get("replace", {}), gens, gens[-1]["label"], gens[-1]["kind"], gens[-1]["id"])
        if history[-1]["id"] == latest["id"]:
            history[-1] = latest
        else:
            history.append(latest)
    return {"version": 2, "n": old.get("n", 0), "cursor": len(history) - 1, "history": history}


def active_state(doc):
    current = doc["history"][doc["cursor"]]
    return {"version": 2, "n": doc["n"], "cursor": doc["cursor"],
            "replace": deepcopy(current["replace"]), "gens": deepcopy(current["gens"]),
            "timeline": [{"index": i, "id": s["id"], "label": s["label"], "kind": s["kind"]}
                         for i, s in enumerate(doc["history"])]}


def seek(doc, cursor):
    if type(cursor) is not int or not 0 <= cursor < len(doc["history"]):
        raise ValueError("History step is out of range.")
    doc["cursor"] = cursor


def append_step(doc, replace, gens, step_id):
    last = gens[-1]
    step = snapshot(replace, gens, last["label"], last["kind"], step_id)
    step["created_at"] = time.time()
    # A new action after undo starts a new branch; old images/PLYs stay on disk.
    doc["history"] = doc["history"][:doc["cursor"] + 1] + [step]
    doc["cursor"] = len(doc["history"]) - 1
    doc["n"] = step_id


def save_history(path, doc):
    path = Path(path)
    if path.exists() and not path.with_suffix(".legacy.json").exists():
        raw = path.read_text()
        if "history" not in json.loads(raw):
            path.with_suffix(".legacy.json").write_text(raw)
    # Top-level current state keeps older tools that read gen.json compatible.
    stored = dict(doc, **{k: v for k, v in active_state(doc).items() if k in ("replace", "gens")})
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(stored))
    os.replace(temporary, path)
