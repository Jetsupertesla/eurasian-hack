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
    sharp predict -i rooms -o rooms

## Run the viewer
    npm run serve        # open the printed URL + /viewer.html?room=room1&style=sixties
Keys: space = sweep, r = reset view. Room upside down? Set `FLIP` in viewer.html to `[0, 0, 0, 1]`.
To change rooms/styles edit `ROOMS` / `STYLES` at the top of the module script in viewer.html.
