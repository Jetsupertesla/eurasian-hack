# Renovate3D demo — how to run

Two files do all the work: `prep.mjs` (Person A, photo sizing) and `viewer.html` (Person B, the 3D wipe).

## One-time setup

    npm install        # installs sharp, for prep.mjs only

## Person A: make an aligned before/after pair

    node prep.mjs before room1.jpg
    # -> rooms/room1-before.jpg   (upload THIS to the fal playground)

Redesign `rooms/room1-before.jpg` in the fal playground with the prompt below,
download the result as e.g. `edited.png`, then:

    node prep.mjs after room1 japandi edited.png
    # -> rooms/room1-japandi.jpg  + rooms/room1-japandi-overlay.jpg

Open the overlay. Window frames, door frames and the wall/ceiling lines must be
SINGLE SHARP LINES. Furniture looking doubled and ghostly is correct. If the
window frames are doubled, redo that edit or switch model.

Prompt:

    Redesign this room in Scandinavian style. Keep the exact same camera angle,
    framing, walls, windows, doors, ceiling and room layout. Change only
    furniture, decor, materials, colours and lighting. Photorealistic interior photo.

Delete the `*-overlay.jpg` files before sending the folder on, so SHARP does not
process them.

## Person B: make the 3D files

Run Apple SHARP over the `rooms` folder; it writes one `.ply` per image, keeping
the names. Expect ~60-70 MB each.

    sharp predict -i rooms -o rooms

## Person B: run the viewer

    npm run serve        # then open the printed URL + /viewer.html

Naming the viewer expects, inside a `rooms/` folder next to `viewer.html`:

    room1-before.ply   room1-japandi.ply   room1-industrial.ply
    room2-before.ply   room2-japandi.ply   ...

URL switches room and style: `viewer.html?room=room2&style=industrial`
Keys: space = sweep, r = reset view.

To change the room and style lists, edit the `ROOMS` and `STYLES` arrays at the
top of the module script in `viewer.html`.

## If the room is upside down

Change `FLIP` in `viewer.html` from `[1, 0, 0, 0]` to `[0, 0, 0, 1]`.
