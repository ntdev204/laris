#!/usr/bin/env node
// `laris`: starts the Python client from a private virtualenv in ~/.laris/runtime/<version>.
// The first run creates the environment and installs the bundled wheel; later runs just start it.
"use strict";
const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const pkg = require("../package.json");
const home = process.env.LARIS_HOME || path.join(os.homedir(), ".laris");
const runtime = path.join(home, "runtime", pkg.version);
const win = process.platform === "win32";
const venvBin = path.join(runtime, win ? "Scripts" : "bin");
const entry = path.join(venvBin, win ? "laris.exe" : "laris");
const ready = path.join(runtime, ".laris-ready");

function run(cmd, args, opts) {
  return spawnSync(cmd, args, { stdio: "inherit", ...opts });
}

// Wheels are compiled per Python version: use an interpreter that has a matching wheel.
function findPython(vendor) {
  const wheels = fs.existsSync(vendor) ? fs.readdirSync(vendor).filter((f) => f.endsWith(".whl")) : [];
  const candidates = process.env.LARIS_PYTHON
    ? [process.env.LARIS_PYTHON]
    : win
      ? ["py", "python"]
      : ["python3.13", "python3.12", "python3.11", "python3.10", "python3", "python"];
  for (const c of candidates) {
    const r = spawnSync(c, ["-c", "import sys;print('cp%d%d' % sys.version_info[:2])"], { encoding: "utf8" });
    if (r.status !== 0) continue;
    const tag = r.stdout.trim();
    if (wheels.some((w) => w.includes(`-${tag}-`))) return c;
  }
  return null;
}

function bootstrap() {
  const vendor = path.join(__dirname, "..", "vendor");
  const python = findPython(vendor);
  if (!python) {
    console.error("No Python on this machine matches a build shipped in this package.");
    console.error("Install Python 3.10-3.13 for your platform, or set LARIS_PYTHON.");
    process.exit(1);
  }
  console.error("Setting up LARIS for the first time (one-off, needs internet)...");
  fs.mkdirSync(runtime, { recursive: true });
  if (run(python, ["-m", "venv", runtime]).status !== 0) process.exit(1);
  const pip = path.join(venvBin, win ? "python.exe" : "python");
  const extra = process.env.LARIS_PIP_ARGS ? process.env.LARIS_PIP_ARGS.split(" ") : [];
  const fail = (message, status) => {
    fs.rmSync(runtime, { recursive: true, force: true }); // never leave a half-installed runtime
    console.error(message);
    process.exit(status || 1);
  };
  // 1. the compiled client, only from the files shipped here (never from an online index)
  let r = run(pip, ["-m", "pip", "install", "-q", "--no-index", "--no-deps",
                    "--find-links", vendor, `laris==${pkg.version}`]);
  if (r.status !== 0) fail("This package has no build for your Python version or platform.", r.status);
  // 2. third-party libraries, from the pinned list
  r = run(pip, ["-m", "pip", "install", "-q", ...extra, "-r", path.join(vendor, "requirements.txt")]);
  if (r.status !== 0) fail("Could not install the libraries LARIS needs.", r.status);
  fs.writeFileSync(ready, pkg.version); // only now is the runtime complete
}

if (!fs.existsSync(ready)) {
  fs.rmSync(runtime, { recursive: true, force: true }); // an interrupted setup starts over
  bootstrap();
}
const result = run(entry, process.argv.slice(2), {});
process.exit(result.status === null ? 1 : result.status);
