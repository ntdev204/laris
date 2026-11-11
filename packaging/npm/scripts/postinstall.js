#!/usr/bin/env node
// After a global install, make sure the folder that holds the `laris` command is on PATH.
// Windows: adds it to the user's PATH (HKCU only, no admin). Linux/macOS: prints the line to add.
// Opt out with LARIS_NO_PATH_EDIT=1. This script never fails the install.
"use strict";
const { spawnSync } = require("child_process");
const path = require("path");

function globalBinDir(env, platform) {
  const prefix = env.npm_config_prefix;
  if (!prefix) return null;
  return platform === "win32" ? prefix : path.join(prefix, "bin");
}

function norm(p, platform) {
  const trimmed = p.replace(/[\\/]+$/, "");
  return platform === "win32" ? trimmed.toLowerCase() : trimmed;
}

function onPath(dir, pathVar, platform) {
  const sep = platform === "win32" ? ";" : ":";
  return pathVar.split(sep).some((e) => e && norm(e, platform) === norm(dir, platform));
}

function main(env = process.env, platform = process.platform) {
  if (env.npm_config_global !== "true" || env.LARIS_NO_PATH_EDIT === "1") return 0;
  const dir = globalBinDir(env, platform);
  if (!dir) return 0;
  if (onPath(dir, env.PATH || env.Path || "", platform)) return 0;

  if (platform !== "win32") {
    console.log(`\nlaris: ${dir} is not on your PATH. Add this to your shell profile:`);
    console.log(`  export PATH="${dir}:$PATH"\n`);
    return 0;
  }
  // Read the *user* PATH (not the merged one), append the folder once, write it back.
  const script =
    "$d=$env:LARIS_BIN_DIR;$u=[Environment]::GetEnvironmentVariable('Path','User');" +
    "$e=@($u -split ';' | Where-Object { $_ });" +
    "if(-not ($e | Where-Object { $_.TrimEnd('\\') -ieq $d.TrimEnd('\\') })){" +
    "[Environment]::SetEnvironmentVariable('Path',(($e + $d) -join ';'),'User')}";
  const r = spawnSync(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-Command", script],
    { env: { ...env, LARIS_BIN_DIR: dir }, stdio: "ignore" }
  );
  if (r.status === 0) {
    console.log(`\nlaris: added ${dir} to your user PATH. Open a new terminal, then run: laris\n`);
  } else {
    console.log(`\nlaris: could not update PATH automatically. Add ${dir} to your PATH, then reopen the terminal.\n`);
  }
  return 0;
}

if (require.main === module) {
  try {
    main();
  } catch (_) {
    /* never block the install */
  }
}
module.exports = { globalBinDir, onPath, main };
