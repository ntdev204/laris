'use strict';
// postinstall: download the archive for this machine, verify it, and unpack laris into ./vendor.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { verifyArchive } = require('./check/verify');

const config = require('./config.json');
const pkg = require('./package.json');

const TARGETS = {
  'linux:x64': 'x86_64-unknown-linux-musl',
  'linux:arm64': 'aarch64-unknown-linux-musl',
  'darwin:x64': 'x86_64-apple-darwin',
  'darwin:arm64': 'aarch64-apple-darwin',
  'win32:x64': 'x86_64-pc-windows-msvc',
};

function fail(message) {
  console.error(`laris install: ${message}`);
  process.exit(1);
}

async function download(url) {
  if (url.startsWith('file://')) return fs.readFileSync(new URL(url));
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return Buffer.from(await response.arrayBuffer());
}

async function main() {
  const releaseUrl = (process.env.LARIS_RELEASE_URL || config.releaseUrl).replace(/\/+$/, '');
  if (releaseUrl.startsWith('__LARIS')) fail('this package was not rendered for a release (cargo xtask dist scripts)');
  if (!/^(https|file):\/\//.test(releaseUrl)) fail('the release address must start with https:// (or file:// for a local mirror)');
  const version = process.env.LARIS_VERSION || pkg.version;
  if (/[\\/]|\.\./.test(version)) fail(`bad version: ${version}`);
  const target = TARGETS[`${process.platform}:${process.arch}`];
  if (!target) fail(`no build for ${process.platform} ${process.arch}`);
  const windows = process.platform === 'win32';
  const name = `laris-${target}.${windows ? 'zip' : 'tar.gz'}`;
  const base = `${releaseUrl}/${version}`;

  let sums, signature, archive;
  try {
    [sums, signature, archive] = await Promise.all([
      download(`${base}/SHA256SUMS`),
      download(`${base}/SHA256SUMS.sig`),
      download(`${base}/${name}`),
    ]);
  } catch (error) {
    fail(`cannot download from ${base}: ${error.message}`);
  }
  try {
    verifyArchive({ sums, signature, publicKey: config.publicKey, name, archive });
  } catch (error) {
    fail(`${error.message}: nothing was installed`);
  }

  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'laris-npm-'));
  try {
    const file = path.join(work, name);
    fs.writeFileSync(file, archive);
    const binary = windows ? 'laris.exe' : 'laris';
    const list = spawnSync('tar', ['-tf', file], { encoding: 'utf8' });
    if (list.status !== 0 || list.stdout.trim().replace(/\r/g, '') !== binary) {
      fail('the archive holds unexpected files: nothing was installed');
    }
    const unpacked = path.join(work, 'unpacked');
    fs.mkdirSync(unpacked);
    const result = spawnSync('tar', ['-xf', file, '-C', unpacked, binary], { encoding: 'utf8' });
    if (result.status !== 0) fail(`cannot unpack the archive: ${result.stderr}`);
    const vendor = path.join(__dirname, 'vendor');
    fs.mkdirSync(vendor, { recursive: true });
    const destination = path.join(vendor, binary);
    fs.copyFileSync(path.join(unpacked, binary), `${destination}.new`);
    fs.chmodSync(`${destination}.new`, 0o755);
    fs.renameSync(`${destination}.new`, destination);
    console.log(`laris installed: ${destination}`);
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
}

main().catch((error) => fail(error.message));
