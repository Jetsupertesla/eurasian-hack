# world/ — one photo in, a room you can look around in

One photo covers about a fifth of what you see when you turn around. An image model paints the other
four fifths as a 360° panorama, the panorama is cut into 12 ordinary views, Apple SHARP turns each view
into Gaussian splats, and the 12 pieces are fitted together into one world.

## See it

    npm run serve          # from the repo root, then open http://localhost:3095/world/
    # or: python3 -m http.server 3092   ->  http://localhost:3092/world/

The default starts with only the front view. Prebuilt 360 surroundings are hidden, so you can
look into the missing areas and press **G** to generate them yourself. No model runs on page load.
Keep some existing geometry in the frame to give the model context. Manual generations are
saved separately in `gen_single.json`; **X** resets only that mode. The original worlds remain intact.
To see the saved full panorama demo, use `?mode=360`.

Keys: drag = look, WASD = step, scroll = zoom, R = reset the camera (replay in 360 mode),
1 2 3 = switch world. Any input skips the build animation.

The splat files (`worlds/<name>/view_XX.ply`, about 25 MB each, 300 MB per world) are **not in git**.
Either copy the `world/worlds` folder from a laptop that has them, or rebuild them from the panoramas
that are in git: `python world/build.py room3` (4 minutes on an M2, no API key needed).

## Free camera and generate

    npm run setup:fal     # paste your key into the hidden terminal prompt; saves ignored .env
    npm run serve        # uses .sharp/venv/bin/python; open http://localhost:3095/world/

Run this in your normal Terminal, or double-click `Start.command` in the repo root. An agent's
restricted runner can serve local files while being unable to reach fal. Run only one server on
port 3095; if it is already running, open the URL instead of starting a second copy.

Fly anywhere (WASD, Q/E down/up, Shift faster), frame what you want inside the square, press G. The image model
repaints that view (repairs the smeared parts, continues into what was never captured), SHARP turns it into splats,
and they replace what the world had inside the frame. About 40 seconds and $0.03 per press. X undoes every generated
view of the current mode. Needs `FAL_KEY` in `.env`; the plain static server shows the worlds but cannot generate.
Use the **Additional prompt** field at the bottom for a specific change, then press **Enter** or click
**Generate**. Leave it blank for the usual repair/extension. **G** generates when you are outside the
text field; camera and world shortcuts are ignored while typing. **Escape** leaves the field.
Requested changes take precedence over preserving the named objects, while the camera and the
rest of the scene stay fixed. The prompt is saved with each generated view.
Keys in `.env.local` and the `FAL_KEY` environment variable are also supported. Saving a key needs no
server restart. The fal MCP connection uses separate authentication and does not supply the app's key.
`/health` reports whether a key is configured and SHARP is loaded, without revealing the key.
`/health?check_fal=1` also verifies DNS and authenticates a read-only fal request; it never generates.
Set `SHARP_PYTHON` if your SHARP installation uses another Python executable.
The server checks Metal access before loading SHARP and falls back to CPU if macOS blocks it.
CPU inference takes longer; `/health` reports the selected device. `SHARP_DEVICE=cpu` forces CPU.

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
