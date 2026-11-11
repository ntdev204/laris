#!/usr/bin/env node
// `laris`: runs the self-contained client that ships in the per-platform package
// (@ntdev204/laris-cli-<platform>, an optional dependency npm picks for this machine).
// It needs no Python, no compiler and no network at start-up.
"use strict";
const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const platform = `${process.platform}-${process.arch}`;
const exeName = process.platform === "win32" ? "laris.exe" : "laris";

function locate() {
  try {
    const manifest = require.resolve(`@ntdev204/laris-cli-${platform}/package.json`);
    const exe = path.join(path.dirname(manifest), "laris", exeName);
    if (fs.existsSync(exe)) return exe;
  } catch (_) {
    /* fall through to a source checkout */
  }
  const local = path.join(__dirname, "..", "dist", "laris", exeName);
  return fs.existsSync(local) ? local : null;
}

const exe = locate();
if (!exe) {
  console.error(`LARIS has no build for ${platform} (or optional dependencies were skipped).`);
  console.error("Reinstall without --omit=optional: npm i -g @ntdev204/laris-cli");
  process.exit(1);
}
if (process.platform !== "win32") {
  try {
    fs.chmodSync(exe, 0o755); // some installers drop the executable bit
  } catch (_) {
    /* read-only install: it is usually already executable */
  }
}
const result = spawnSync(exe, process.argv.slice(2), { stdio: "inherit" });
if (result.error) {
  console.error(`Could not start ${exe}: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status === null ? 1 : result.status);
