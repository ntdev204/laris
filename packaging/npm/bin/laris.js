#!/usr/bin/env node
// `laris`: starts the Python client from a private virtualenv in ~/.laris/runtime/<version>.
// The first run creates the environment and installs the bundled wheel; later runs just start it.
"use strict";
const { spawnSync } = require("child_process");
const crypto = require("crypto");
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

// Wheels are compiled per Python version and platform: use an interpreter that has a matching wheel.
// Each candidate is [command, ...leading args]; Windows tries every installed version via `py`.
function candidates() {
  if (process.env.LARIS_PYTHON) return [[process.env.LARIS_PYTHON]];
  if (win) return [["py", "-3.13"], ["py", "-3.12"], ["py", "-3.11"], ["py", "-3.10"], ["python"]];
  return ["3.13", "3.12", "3.11", "3.10"].map((v) => ["python" + v]).concat([["python3"], ["python"]]);
}

function findPython(vendor) {
  const wheels = fs.existsSync(vendor) ? fs.readdirSync(vendor).filter((f) => f.endsWith(".whl")) : [];
  const probe = "import sys;print('cp%d%d' % sys.version_info[:2])";
  for (const [cmd, ...pre] of candidates()) {
    const r = spawnSync(cmd, [...pre, "-c", probe], { encoding: "utf8" });
    if (r.status !== 0) continue;
    const tag = r.stdout.trim();
    if (wheels.some((w) => w.includes(`-${tag}-`))) return [cmd, ...pre];
  }
  return null;
}

// The compiled wheels live in a per-platform package (an optional dependency of this one), so npm
// only downloads the build for this machine. A source checkout keeps them in ./vendor.
function vendorDir() {
  const platform = `${process.platform}-${process.arch}`;
  try {
    const manifest = require.resolve(`@ntdev204/laris-cli-${platform}/package.json`);
    return path.join(path.dirname(manifest), "vendor");
  } catch (_) {
    const local = path.join(__dirname, "..", "vendor");
    return fs.existsSync(local) ? local : null;
  }
}

// uv builds, one per platform. Override the download base with LARIS_UV_URL (a mirror or proxy).
const UV_TARGETS = {
  "win32-x64": ["x86_64-pc-windows-msvc", "zip"],
  "linux-x64": ["x86_64-unknown-linux-gnu", "tar.gz"],
  "linux-arm64": ["aarch64-unknown-linux-gnu", "tar.gz"],
  "darwin-x64": ["x86_64-apple-darwin", "tar.gz"],
  "darwin-arm64": ["aarch64-apple-darwin", "tar.gz"],
};
const UV_BASE = process.env.LARIS_UV_URL || "https://github.com/astral-sh/uv/releases/latest/download";

async function download(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return Buffer.from(await res.arrayBuffer());
}

function findFile(dir, name) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      const hit = findFile(full, name);
      if (hit) return hit;
    } else if (entry.name === name) {
      return full;
    }
  }
  return null;
}

// Downloads uv once (checksum verified) into ~/.laris/tools.
async function ensureUv() {
  const tools = path.join(home, "tools");
  const uv = path.join(tools, win ? "uv.exe" : "uv");
  if (fs.existsSync(uv)) return uv;
  const target = UV_TARGETS[`${process.platform}-${process.arch}`];
  if (!target) throw new Error(`no uv build for ${process.platform}/${process.arch}`);
  const [triple, ext] = target;
  const url = `${UV_BASE}/uv-${triple}.${ext}`;
  console.error(`Downloading a private Python toolchain (uv) from ${UV_BASE} ...`);
  const archive = await download(url);
  const expected = (await download(`${url}.sha256`)).toString("utf8").trim().split(/\s+/)[0];
  const actual = crypto.createHash("sha256").update(archive).digest("hex");
  if (actual !== expected) throw new Error("uv download failed its SHA-256 check; nothing was installed");
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "laris-uv-"));
  try {
    const file = path.join(work, `uv.${ext}`);
    fs.writeFileSync(file, archive);
    const flags = ext === "zip" ? ["-xf"] : ["-xzf"]; // bsdtar (Windows 10+) reads zip too
    if (run("tar", [...flags, file, "-C", work]).status !== 0) throw new Error("could not unpack uv");
    const found = findFile(work, win ? "uv.exe" : "uv");
    if (!found) throw new Error("uv binary not found in its archive");
    fs.mkdirSync(tools, { recursive: true });
    fs.copyFileSync(found, uv);
    if (!win) fs.chmodSync(uv, 0o755);
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
  return uv;
}

// No suitable Python on this machine: fetch a private one. Leaves the user's own Python untouched.
async function managedPython(vendor) {
  if (process.env.LARIS_NO_DOWNLOAD === "1") return null;
  // the newest Python for which this package carries a wheel
  const minors = fs.readdirSync(vendor)
    .map((f) => /-cp3(\d+)-/.exec(f))
    .filter(Boolean)
    .map((m) => Number(m[1]));
  if (!minors.length) return null;
  const version = `3.${Math.max(...minors)}`;
  const uv = await ensureUv();
  const env = {
    ...process.env,
    UV_PYTHON_INSTALL_DIR: path.join(home, "python"),
    UV_PYTHON_BIN_DIR: path.join(home, "python", "bin"), // never write shims into the user's PATH
    UV_PYTHON_PREFERENCE: "only-managed",
  };
  console.error(`Installing a private Python ${version} (one-off) ...`);
  if (run(uv, ["python", "install", version], { env }).status !== 0) return null;
  const r = spawnSync(uv, ["python", "find", version], { env, encoding: "utf8" });
  return r.status === 0 ? [r.stdout.trim()] : null;
}

async function bootstrap() {
  const vendor = vendorDir();
  if (!vendor) {
    console.error(`No LARIS build for ${process.platform}/${process.arch} was installed.`);
    console.error("Reinstall without --omit=optional, or ask for a build for your platform.");
    process.exit(1);
  }
  let python = findPython(vendor);
  if (!python) {
    try {
      python = await managedPython(vendor);
    } catch (err) {
      console.error(`Could not fetch a private Python: ${err.message}`);
    }
  }
  if (!python) {
    console.error("No Python on this machine matches a build shipped in this package.");
    console.error("Install Python 3.10-3.13 (64-bit), allow downloads, or set LARIS_PYTHON.");
    console.error(`Platform: ${process.platform}/${process.arch}`);
    process.exit(1);
  }
  console.error("Setting up LARIS for the first time (one-off, needs internet)...");
  fs.mkdirSync(runtime, { recursive: true });
  if (run(python[0], [...python.slice(1), "-m", "venv", runtime]).status !== 0) process.exit(1);
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

async function main() {
  if (!fs.existsSync(ready)) {
    fs.rmSync(runtime, { recursive: true, force: true }); // an interrupted setup starts over
    await bootstrap();
  }
  const result = run(entry, process.argv.slice(2), {});
  process.exit(result.status === null ? 1 : result.status);
}

main().catch((err) => {
  console.error(err && err.message ? err.message : err);
  process.exit(1);
});
