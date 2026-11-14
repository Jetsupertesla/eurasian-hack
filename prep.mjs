// Step 1: node prep.mjs before room1.jpg        -> rooms/room1-before.jpg (upload THIS file to fal)
// Step 2: node prep.mjs after room1 japandi edited.png -> rooms/room1-japandi.jpg (same size as before) + overlay
import sharp from "sharp";
import { mkdirSync } from "node:fs";
mkdirSync("rooms", { recursive: true });
const [mode, a, b, c] = process.argv.slice(2);
if (mode === "before") {
  const name = a.replace(/\.[^.]+$/, "").split(/[\\/]/).pop();
  const info = await sharp(a).rotate().resize({ width: 1536, height: 1536, fit: "inside", withoutEnlargement: true }).jpeg({ quality: 92 }).toFile(`rooms/${name}-before.jpg`);
  console.log(`rooms/${name}-before.jpg`, info.width, "x", info.height);
} else if (mode === "after") {
  const before = `rooms/${a}-before.jpg`;
  const { width, height } = await sharp(before).metadata();
  const out = `rooms/${a}-${b}.jpg`;
  await sharp(c).resize(width, height, { fit: "fill" }).jpeg({ quality: 92 }).toFile(out);
  const top = await sharp(out).ensureAlpha(0.5).png().toBuffer();
  await sharp(before).composite([{ input: top }]).jpeg().toFile(`rooms/${a}-${b}-overlay.jpg`);
  console.log(out, width, "x", height, "| check", `rooms/${a}-${b}-overlay.jpg`);
} else console.log("usage: see top of file");
