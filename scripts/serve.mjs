import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const root = fileURLToPath(new URL("../", import.meta.url));
const localPython = join(root, ".sharp", "venv", "bin", "python");
const python = process.env.SHARP_PYTHON || (existsSync(localPython) ? localPython : "python3");
const child = spawn(python, [join(root, "world", "serve.py"), ...process.argv.slice(2)], {
  cwd: root, stdio: "inherit",
});
child.on("error", (error) => { console.error(error.message); process.exitCode = 1; });
child.on("exit", (code, signal) => {
  if (signal && !["SIGINT", "SIGTERM"].includes(signal)) console.error(`Generation server stopped (${signal}).`);
  process.exitCode = code ?? (signal === "SIGINT" || signal === "SIGTERM" ? 0 : 1);
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
