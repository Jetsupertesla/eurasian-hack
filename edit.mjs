// Usage: node edit.mjs room3 sixties [seed]  -> edited/cand/room3-sixties-s<seed>.png
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
const env = Object.fromEntries(readFileSync(".env", "utf8").split(/\r?\n/).filter(l => l.includes("=")).map(l => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]));
const KEY = process.env.FAL_KEY || env.FAL_KEY;
const MODEL = process.env.EDIT_MODEL || "fal-ai/qwen-image-edit-2511";
const [room, style, seedArg] = process.argv.slice(2);
const seed = Number(seedArg ?? 1);

const LOCK = "This is a restyle of an existing photo, not a new scene. The image geometry stays exactly identical: same camera position, lens, framing and perspective, no zoom, crop, shift or rotation. Every wall, window, window frame, door, ceiling, beam, pipe, radiator, built-in cabinet, appliance, shelf and the floor plane stays exactly where it is with exactly the same shape and size. Every piece of furniture and every object stays in its current position at its current size; do not add, remove, move or resize any object. Do not add wallpaper, patterns, murals, artwork, clocks, lamps, rugs or any new item.";
const LOOK = {
  sixties: "Only change colours and materials. Paint the plain wall surfaces one flat solid warm ochre-orange, with no pattern. Existing wood furniture and shelves become warm teak. Existing seating and upholstery become olive green or burnt orange. Existing floor gets a warm teak wood tone, and existing metal parts become chrome. Soft warm 1960s lighting.",
  industrial: "Only change colours and materials. Plain wall surfaces become flat raw grey concrete with no pattern. Existing wood furniture and shelves become dark reclaimed wood. Existing seating and upholstery become dark brown leather. Existing metal parts become matte black steel. Floor becomes a slightly darker wood tone. Moody warm low lighting.",
};
const prompt = `${LOCK} ${LOOK[style]} Photorealistic interior photo.`;
const negative = "wallpaper, pattern, mural, extra objects, new furniture, added lamps, clock, rug, artwork, text, distortion, warped lines, shifted windows, different camera angle, zoom, crop, blur";

const img = "data:image/jpeg;base64," + readFileSync(`rooms/${room}-before.jpg`).toString("base64");
const H = { Authorization: `Key ${KEY}`, "Content-Type": "application/json" };
const sub = await (await fetch(`https://queue.fal.run/${MODEL}`, { method: "POST", headers: H, body: JSON.stringify({ prompt, negative_prompt: negative, image_urls: [img], output_format: "png", image_size: { width: 1536, height: 1152 }, seed, guidance_scale: 4 }) })).json();
if (!sub.request_id) throw new Error("submit failed: " + JSON.stringify(sub));
for (;;) {
  await new Promise(r => setTimeout(r, 2500));
  const s = await (await fetch(sub.status_url, { headers: H })).json();
  if (s.status === "COMPLETED") break;
  if (s.status !== "IN_QUEUE" && s.status !== "IN_PROGRESS") throw new Error(JSON.stringify(s));
}
const res = await (await fetch(sub.response_url, { headers: H })).json();
const url = res.images?.[0]?.url;
if (!url) throw new Error("no image: " + JSON.stringify(res));
mkdirSync("edited/cand", { recursive: true });
const out = `edited/cand/${room}-${style}-s${seed}.png`;
writeFileSync(out, Buffer.from(await (await fetch(url)).arrayBuffer()));
console.log(out);
