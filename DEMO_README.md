# Renovate3D demo

Wipe between a room and its AI-redesigned version in 3D (Gaussian splats). Runs offline from this folder.

See **AGENTS.md** for current state and tasks, and `docs/hackathon-handover.pdf` for the full plan.

## Setup
    git lfs install     # install Git LFS first; it downloads the 3D room files on clone
    npm install

If you cloned before installing Git LFS, run `git lfs pull` in the repo.
The nine 3D room files total about 570 MB; download them on good Wi-Fi
before the offline demo.

## Make images (needs FAL_KEY in .env, copy .env.example)
    npm run setup:fal                     # hidden prompt; stores the key locally, never in Git
    node prep.mjs before originals/room1.jpg
    node edit.mjs room1 sixties 1          # styles: sixties | industrial
    node score.mjs room1 sixties           # pick the highest score
    node prep.mjs after room1 sixties edited/cand/room1-sixties-s1.png
    # move rooms/*-overlay.jpg to overlays/ and eyeball them: window frames = single sharp lines

## Make 3D (Apple SHARP, ~65 MB per .ply)
The generated room files are stored in Git LFS. A normal clone with Git LFS
installed receives them; this step is only needed to regenerate them.

Install [Apple SHARP](https://github.com/apple/ml-sharp) in a separate Python
environment first. On the Mac used for this demo, `conda` already has a
`sharp` environment:

    conda run -n sharp sharp predict -i rooms -o rooms --device mps

This processes all nine prepared images and writes matching `.ply` files
beside them in `rooms/`. The first run downloads about 2.8 GB of weights.
Do not process `originals/` instead: the edited images are aligned to the
1536-pixel versions in `rooms/`.

After regenerating a `.ply`, commit it normally; Git LFS stores its data
outside regular Git history. Re-running SHARP and committing a changed file
stores another full copy in Git LFS. Confirm the real files, not tiny LFS
pointers, are present before taking the presenting laptop offline.

## Run the viewer
    npm run serve        # http://localhost:3095/viewer.html?room=room1&style=sixties

This starts the Python generation server using the local `.sharp/venv` environment (or `SHARP_PYTHON`).
The root URL opens `/world/`, which starts with a single front view; press **G** to generate more.
Existing 360 worlds remain available with `/world/?mode=360`. See `world/README.md`.

Alternatively, without Node.js, run `python3 -m http.server 8001` from
this directory and open
`http://localhost:8001/viewer.html?room=room1&style=sixties`.
Open it through a local server, not `file://`, then turn Wi-Fi off and reload.
Keys: space = sweep, r = reset view. Room upside down? Set `FLIP` in viewer.html to `[0, 0, 0, 1]`.
To change rooms/styles edit `ROOMS` / `STYLES` at the top of the module script in viewer.html.
