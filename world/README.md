# world/ — one photo in, a room you can look around in

One photo covers about a fifth of what you see when you turn around. An image model paints the other
four fifths as a 360° panorama, the panorama is cut into 12 ordinary views, Apple SHARP turns each view
into Gaussian splats, and the 12 pieces are fitted together into one world.

## See it

    npm run serve          # from the repo root, then open  <printed URL>/world/
    # or: python3 -m http.server 3092   ->  http://localhost:3092/world/

Keys: drag = look, WASD = step (about half a metre each way), scroll = zoom, R = replay the build,
1 2 3 = switch world. Any input skips the build animation.

The splat files (`worlds/<name>/view_XX.ply`, about 25 MB each, 300 MB per world) are **not in git**.
Either copy the `world/worlds` folder from a laptop that has them, or rebuild them from the panoramas
that are in git: `python world/build.py room3` (4 minutes on an M2, no API key needed).

## Free camera and generate

    .sharp/venv/bin/python world/serve.py      # instead of the plain server; open http://localhost:3095/world/

Fly anywhere (WASD, Q/E down/up, Shift faster), frame what you want inside the square, press G. The image model
repaints that view (repairs the smeared parts, continues into what was never captured), SHARP turns it into splats,
and they replace what the world had inside the frame. About 40 seconds and $0.03 per press. X undoes every generated
view of the current world. Needs `FAL_KEY` in `.env`; the plain static server shows the worlds but cannot generate.

## Make a new world

    python world/make.py originals/room3.jpg myroom
    python world/make.py originals/room3.jpg jungle "abandoned for decades and reclaimed by nature"

Needs `FAL_KEY` in `.env` (one image call, about $0.14) and SHARP installed (see DEMO_README).
Run it with the Python that has SHARP installed: `conda run -n sharp python world/make.py ...` on the
Mac with the conda environment, or `.sharp/venv/bin/python world/make.py ...` where SHARP lives in `.sharp/`.
The optional third argument describes what lies outside the photo; without it the model continues the same room.

What `make.py` does, step by step (each step can be run alone):

| step | script | in → out |
| --- | --- | --- |
| 1 | `guide.py` | photo → `guide.jpg`: the photo placed in the middle of a black 360° canvas |
| 2 | fal `google/nano-banana-2.1/edit` | `guide.jpg` → `pano.jpg`: the black is painted in |
| 3 | `seam.py level` | the panorama's left and right edges meet but differ slightly in tone; even that out (no model call) |
| 4 | `build.py` | `pano.jpg` → 12 views → SHARP → `view_XX.ply` + `world.json` |

## Limits, so nobody over-promises on stage

- You stand where the photo was taken. Every view is accurate from that spot, so walking more than about
  half a metre shows stretching. This is "look around", not "walk through".
- The model redraws the photographed part a little larger than the original, so the world matches the
  panorama, not the photo pixel for pixel.
- Straight up and straight down (the last 13°) are a blur, not generated.
- SHARP's weights are research / non-commercial only.
