// Exercise the actual viewer handlers with mocked rendering and HTTP; never calls fal.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync(new URL("../world/index.html", import.meta.url), "utf8");
const generation = html.slice(html.indexOf("let busy = false;"), html.indexOf("// ---- input"));
const keyStart = html.indexOf('addEventListener("keydown", (e) => {');
const keyboard = html.slice(keyStart, html.indexOf('addEventListener("keyup",', keyStart));

function fixture() {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      value: "", disabled: false, handlers: {},
      classList: { add() {}, remove() {} },
      addEventListener(type, handler) { this.handlers[type] = handler; }, blur() {},
    });
    return elements.get(id);
  };
  const sent = [], events = {};
  const context = vm.createContext({
    $: element, keys: new Set(), takeOver() {}, lastInput: 0, genStatus: "", mode: "single", name: "room3",
    camera: { updateMatrixWorld() {}, matrixWorld: { elements: Array(16).fill(0) }, fov: 62 },
    capture: () => "data:image/jpeg;base64,example", performance: { now: () => 0 },
    setInterval: () => 1, clearInterval() {}, console: { warn() {} },
    applyGen: async () => {},
    fetch: async (url, options) => {
      if (url === "/health") return { ok: true, json: async () => ({ fal_configured: true, sharp_ready: true }) };
      sent.push(JSON.parse(options.body));
      return { json: async () => ({ replace: {}, gens: [] }) };
    },
    addEventListener: (type, handler) => { events[type] = handler; },
    replay: () => { throw Error("Typing must not replay"); },
    location: {}, names: ["room3", "room1"],
    historyLoading: false, historyRequest: 0, historyChain: Promise.resolve(), requestedStep: null,
    historyState: { n: 0, cursor: 0, replace: {}, gens: [], timeline: [{ label: "Starting view" }] },
    document: { querySelectorAll: () => [] }, setTimeout: () => 1, clearTimeout() {},
  });
  vm.runInContext(generation + keyboard, context);
  return { context, element, sent, events };
}

test("optional prompt is sent with a single generation and retained afterwards", async () => {
  const { context, element, sent } = fixture();
  element("prompt").value = "  Add a bookshelf  ";
  assert.equal(await context.generate(), "");
  assert.equal(sent.length, 1);
  assert.equal(sent[0].prompt, "Add a bookshelf");
  assert.equal(sent[0].mode, "single");
  assert.equal(element("prompt").value, "  Add a bookshelf  ");
  assert.equal(element("prompt").disabled, false);
  assert.equal(element("gen").disabled, false);
});

test("typing G, X, R, WASD and numbers cannot generate, reset or move the camera", () => {
  const { context, events, sent } = fixture();
  for (const key of "gxrwasdqe123") events.keydown({ key, target: { closest: () => ({}) } });
  assert.equal(sent.length, 0);
  assert.equal(context.keys.size, 0);
  assert.equal(context.location.search, undefined);
});

test("G outside the input generates once; repeated keydown does not submit", async () => {
  const { context, events, sent } = fixture();
  await events.keydown({ key: "g", target: { closest: () => null }, repeat: false });
  await events.keydown({ key: "g", target: { closest: () => null }, repeat: true });
  assert.equal(sent.length, 1);
});

test("Enter or Generate submits the prompt through the form", async () => {
  const { context, element, sent } = fixture();
  let prevented = false;
  element("prompt").value = 'Put a sign reading "WELCOME" on the wall';
  element("gen-controls").handlers.submit({ preventDefault: () => { prevented = true; } });
  // Drain the mocked HTTP promise chain.
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(prevented, true);
  assert.equal(sent[0].prompt, element("prompt").value);
});

test("capture failures release the busy state so the user can try again", async () => {
  const { context, element, sent } = fixture();
  context.capture = () => { throw Error("Capture unavailable"); };
  assert.match(await context.generate(), /Capture unavailable/);
  assert.equal(element("gen").disabled, false);
  context.capture = () => "data:image/jpeg;base64,example";
  assert.equal(await context.generate(), "");
  assert.equal(sent.length, 1);
});
