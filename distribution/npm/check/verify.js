'use strict';
// Checks of a release: the signature of SHA256SUMS (ECDSA P-256 over SHA-256, DER) and the checksum of an archive.
const crypto = require('node:crypto');

function signatureGood(sums, signature, publicKeyPem) {
  try {
    return crypto.verify('sha256', sums, publicKeyPem, signature);
  } catch {
    return false;
  }
}

function expectedChecksum(sums, name) {
  for (const line of sums.toString('utf8').split('\n')) {
    const parts = line.trim().split(/\s+/);
    if (parts.length === 2 && parts[1] === name) return parts[0].toLowerCase();
  }
  return null;
}

function checksum(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

// Throws with the reason when the archive may not be installed.
function verifyArchive({ sums, signature, publicKey, name, archive }) {
  if (!signatureGood(sums, signature, publicKey)) {
    throw new Error('the signature of SHA256SUMS is not valid');
  }
  const expected = expectedChecksum(sums, name);
  if (!expected) throw new Error(`${name} is not in the signed list`);
  if (checksum(archive) !== expected) {
    throw new Error(`the checksum of ${name} does not match the signed list`);
  }
}

module.exports = { verifyArchive, signatureGood, expectedChecksum, checksum };
