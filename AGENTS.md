# AGENTS.md — Renovate3D (Eurasian hack demo)

Read this first. Full plan: `docs/hackathon-handover.pdf` (sections 2, A2, B1–B5, 9, 10 still apply).

## What this is
Upload/pick a room photo, redesign it with AI, turn both photos into 3D Gaussian splats, and **wipe between before and after in 3D** in the browser. Demo deadline: **16:00 on 2026-11-14**, must run from a local folder with Wi-Fi OFF.

## Pipeline
1. `node prep.mjs before <photo>`  -> `rooms/<room>-before.jpg` (longest side 1536, EXIF-rotated)
2. `node edit.mjs <room> <style> [seed]` -> fal `fal-ai/qwen-image-edit-2511`, writes `edited/cand/<room>-<style>-s<seed>.png`
3. `node score.mjs <room> <style>` -> edge-correlation vs the before image (higher = better aligned; ~0.35+ is fine)
4. `node prep.mjs after <room> <style> edited/cand/<best>.png` -> `rooms/<room>-<style>.jpg` (same size as before) + `rooms/<room>-<style>-overlay.jpg` (move overlays to `overlays/`; they must NOT sit in `rooms/` when SHARP runs)
5. `sharp predict -i rooms -o rooms` (Apple SHARP) -> one `.ply` per image (~65 MB each; gitignored)
6. `npm run serve`, open `viewer.html?room=room1&style=sixties`

## Current state (as of handoff)
- DONE: 3 rooms x (before + `sixties` + `industrial`) images in `rooms/`, all 1536x1152 and aligned. Best seeds were picked by `score.mjs`.
- DONE: `viewer.html` (three.js 0.180 + Spark 2.4) with wipe slider, Sweep, room/style links, camera limits. Libraries are vendored in `lib/` so it works offline.
- NOT DONE (blocking): **no `.ply` files exist yet** -> the viewer has never been run on real data. SHARP is not installed on the dev machine.
- NOT DONE: offline (Wi-Fi off) test, orientation check, second-laptop copy, backup video, pitch/slides.

## Tasks for Devin (in priority order)
1. Get SHARP running (see `docs/hackathon-handover.pdf` B1). Mac (Apple Silicon) is fastest; otherwise Windows CPU/GPU, otherwise Replicate `kfarr/sharp-ml`. Generate 9 `.ply` files into `rooms/` with the same base names as the images.
2. Run `npm install && npm run serve`, open the viewer for each room/style. Verify: right way up (if not, change `FLIP` in `viewer.html` from `[1,0,0,0]` to `[0,0,0,1]`), wipe lines up, no console errors, loads with network disabled. Screenshot each.
3. If the wipe misbehaves, apply the fallbacks in the PDF ("If 13:00 fails") rather than redesigning.
4. Tune camera limits / push-in in `viewer.html` for a good first impression. Keep changes small.
5. Update `DEMO_README.md` and record findings in this file.

## Rules / gotchas
- **Never commit `.env` or any API key.** `FAL_KEY` lives in local `.env` (see `.env.example`). Do not print it.
- Before/after images MUST be identical pixel size; don't resize them separately.
- Do not re-run `edit.mjs` casually: each call costs ~$0.05 of a ~$10 fal budget. Prompts in `edit.mjs` are deliberately restrictive (lock geometry, recolour only, no new objects) because looser prompts hallucinated objects and shifted windows.
- Known weak spots: room2 contains a person at the left edge (may smear in 3D; ideally retake without them); `industrial` edits are subtle.
- Feature freeze 14:30. After that, no new features.
- Licence note for pitch: SHARP weights are research/non-commercial only.
