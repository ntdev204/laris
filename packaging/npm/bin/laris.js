#!/usr/bin/env node
// `laris`: opens the Ink interface over the self-contained engine program that ships in the
// per-platform package (@ntdev204/laris-cli-<platform>, an optional dependency npm picks for this
// machine). The engine needs no Python and no network at start-up. When the interface cannot start
// (the build is missing, or Node is too old for Ink) this launcher says so and starts the engine's
// plain-text mode instead, so `laris` always works.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const platform = `${process.platform}-${process.arch}`;
const exeName = process.platform === "win32" ? "laris.exe" : "laris";

function locate() {
  const override = process.env.LARIS_ENGINE_BIN; // a development checkout or a test double
  if (override) return override;
  try {
    const manifest = createRequire(import.meta.url).resolve(`@ntdev204/laris-cli-${platform}/package.json`);
    const exe = path.join(path.dirname(manifest), "laris", exeName);
    if (fs.existsSync(exe)) return exe;
  } catch {
    /* fall through to a source checkout */
  }
  const local = path.join(here, "..", "dist", "laris", exeName);
  return fs.existsSync(local) ? local : null;
}

function runPlain(exe, args) {
  if (process.platform !== "win32") {
    try {
      fs.chmodSync(exe, 0o755); // some installers drop the executable bit
    } catch {
      /* read-only install: it is usually already executable */
    }
  }
  const result = spawnSync(exe, args, { stdio: "inherit" });
  if (result.error) {
    console.error(`Could not start ${exe}: ${result.error.message}`);
    return 1;
  }
  return result.status === null ? 1 : result.status;
}

const exe = locate();
if (!exe) {
  console.error(`LARIS has no build for ${platform} (or optional dependencies were skipped).`);
  console.error("Reinstall without --omit=optional: npm i -g @ntdev204/laris-cli");
  process.exit(1);
}
const argv = process.argv.slice(2);

let ui = null;
try {
  ui = await import("../build/src/main.js");
} catch (error) {
  const why = error instanceof Error ? error.message.split("\n")[0] : String(error);
  console.error(`laris: the interface could not start (${why}); using plain-text mode.`);
}
if (ui === null) {
  process.exit(runPlain(exe, argv.includes("--plain") ? argv : ["--plain", ...argv]));
}
process.exit(await ui.main(argv, { exe }));
