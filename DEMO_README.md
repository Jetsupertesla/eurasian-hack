# Renovate3D demo

Wipe between a room and its AI-redesigned version in 3D (Gaussian splats). Runs offline from this folder.

See **AGENTS.md** for current state and tasks, and `docs/hackathon-handover.pdf` for the full plan.

## Setup
    npm install

## Make images (needs FAL_KEY in .env, copy .env.example)
    node prep.mjs before originals/room1.jpg
    node edit.mjs room1 sixties 1          # styles: sixties | industrial
    node score.mjs room1 sixties           # pick the highest score
    node prep.mjs after room1 sixties edited/cand/room1-sixties-s1.png
    # move rooms/*-overlay.jpg to overlays/ and eyeball them: window frames = single sharp lines

## Make 3D (Apple SHARP, ~65 MB per .ply, gitignored)
Install [Apple SHARP](https://github.com/apple/ml-sharp) in a separate Python
environment first. On the Mac used for this demo, `conda` already has a
`sharp` environment:

    conda run -n sharp sharp predict -i rooms -o rooms --device mps

This processes all nine prepared images and writes matching `.ply` files
beside them in `rooms/`. The first run downloads about 2.8 GB of weights.
Do not process `originals/` instead: the edited images are aligned to the
1536-pixel versions in `rooms/`.

The `.ply` files are ignored by Git because nine of them total roughly
570 MB. Copy `rooms/` (including its `.ply` files) to the presenting laptop
separately. A fresh GitHub clone has the images and viewer, but **not** the
3D files.

## Run the viewer
    npm run serve        # open the printed URL + /viewer.html?room=room1&style=sixties

Alternatively, without Node.js, run `python3 -m http.server 8001` from
this directory and open
`http://localhost:8001/viewer.html?room=room1&style=sixties`.
Open it through a local server, not `file://`, then turn Wi-Fi off and reload.
Keys: space = sweep, r = reset view. Room upside down? Set `FLIP` in viewer.html to `[0, 0, 0, 1]`.
To change rooms/styles edit `ROOMS` / `STYLES` at the top of the module script in viewer.html.
