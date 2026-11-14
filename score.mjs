// Usage: node score.mjs room3 sixties  -> prints edge-alignment score per candidate (higher = better)
import sharp from "sharp";
import { readdirSync } from "node:fs";
const [room, style] = process.argv.slice(2);
const W = 384, H = 288;
async function edges(input) {
  const { data } = await sharp(input).resize(W, H, { fit: "fill" }).grayscale().blur(1.2).raw().toBuffer({ resolveWithObject: true });
  const e = new Float32Array(W * H);
  for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
    const i = y * W + x;
    const gx = data[i + 1] - data[i - 1], gy = data[i + W] - data[i - W];
    e[i] = Math.hypot(gx, gy);
  }
  return e;
}
const ncc = (a, b) => { let sa = 0, sb = 0; for (let i = 0; i < a.length; i++) { sa += a[i]; sb += b[i]; } sa /= a.length; sb /= a.length; let n = 0, da = 0, db = 0; for (let i = 0; i < a.length; i++) { const x = a[i] - sa, y = b[i] - sb; n += x * y; da += x * x; db += y * y; } return n / Math.sqrt(da * db); };
const base = await edges(`rooms/${room}-before.jpg`);
for (const f of readdirSync("edited/cand").filter(f => f.startsWith(`${room}-${style}-s`))) {
  console.log(f, ncc(base, await edges(`edited/cand/${f}`)).toFixed(3));
}
