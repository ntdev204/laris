#!/usr/bin/env node
'use strict';
// Launcher: runs the native binary that install.js put in ../vendor and passes its exit code on.
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');

const binary = path.join(__dirname, '..', 'vendor', process.platform === 'win32' ? 'laris.exe' : 'laris');
if (!fs.existsSync(binary)) {
  console.error('laris: the native binary is missing; reinstall the package (npm install -g @ntdev204/laris).');
  process.exit(1);
}
const child = spawn(binary, process.argv.slice(2), { stdio: 'inherit' });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('error', (error) => {
  console.error(`laris: cannot start ${binary}: ${error.message}`);
  process.exit(1);
});
child.on('exit', (code, signal) => process.exit(code ?? (signal ? 128 : 1)));
