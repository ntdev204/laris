#!/bin/sh
# Installs `laris`: downloads the archive for this machine, checks the signature of the checksum list and the
# checksum of the archive, and only then puts the binary in place. Rendered by `cargo xtask dist scripts`.
#
#   LARIS_VERSION      release to install (default: latest)
#   LARIS_INSTALL_DIR  where the binary goes (default: $HOME/.local/bin)
#   LARIS_RELEASE_URL  another release address (the signature is still checked against the built-in key)
set -eu

RELEASE_URL="${LARIS_RELEASE_URL:-__LARIS_RELEASE_URL__}"
VERSION="${LARIS_VERSION:-latest}"
INSTALL_DIR="${LARIS_INSTALL_DIR:-${HOME:-}/.local/bin}"
PUBLIC_KEY='__LARIS_RELEASE_PUBKEY__'

fail() {
    printf 'laris install: %s\n' "$1" >&2
    exit 1
}

case "$RELEASE_URL" in
    __LARIS*) fail "this script was not rendered for a release (cargo xtask dist scripts)" ;;
    https://* | file://*) ;;
    *) fail "the release address must start with https:// (or file:// for a local mirror)" ;;
esac
[ -n "$INSTALL_DIR" ] || fail "no install folder: set LARIS_INSTALL_DIR"
case "$VERSION" in
    */* | *..*) fail "bad version: $VERSION" ;;
esac

os=$(uname -s)
cpu=$(uname -m)
case "$os:$cpu" in
    Linux:x86_64 | Linux:amd64) target=x86_64-unknown-linux-musl ;;
    Linux:aarch64 | Linux:arm64) target=aarch64-unknown-linux-musl ;;
    Darwin:x86_64) target=x86_64-apple-darwin ;;
    Darwin:arm64 | Darwin:aarch64) target=aarch64-apple-darwin ;;
    *) fail "no build for $os $cpu (on Windows use install.ps1)" ;;
esac
archive="laris-$target.tar.gz"

command -v openssl >/dev/null 2>&1 || fail "openssl is needed to check the signature"
command -v tar >/dev/null 2>&1 || fail "tar is needed"
if command -v curl >/dev/null 2>&1; then
    fetch() { curl -fsSL --retry 2 -o "$2" "$1"; }
elif command -v wget >/dev/null 2>&1; then
    fetch() {
        case "$1" in file://*) cp "${1#file://}" "$2" ;; *) wget -q -O "$2" "$1" ;; esac
    }
else
    fail "curl or wget is needed"
fi
if command -v sha256sum >/dev/null 2>&1; then
    sha256() { sha256sum "$1" | cut -d ' ' -f 1; }
elif command -v shasum >/dev/null 2>&1; then
    sha256() { shasum -a 256 "$1" | cut -d ' ' -f 1; }
else
    sha256() { openssl dgst -sha256 "$1" | sed 's/.*= *//'; }
fi

work=$(mktemp -d "${TMPDIR:-/tmp}/laris-install.XXXXXX") || fail "cannot make a temporary folder"
trap 'rm -rf "$work"' EXIT INT TERM
base="${RELEASE_URL%/}/$VERSION"

printf 'Downloading laris %s for %s\n' "$VERSION" "$target"
fetch "$base/SHA256SUMS" "$work/SHA256SUMS" || fail "cannot download SHA256SUMS from $base"
fetch "$base/SHA256SUMS.sig" "$work/SHA256SUMS.sig" || fail "cannot download SHA256SUMS.sig"
fetch "$base/$archive" "$work/$archive" || fail "cannot download $archive"

printf '%s\n' "$PUBLIC_KEY" >"$work/release.pub"
openssl dgst -sha256 -verify "$work/release.pub" -signature "$work/SHA256SUMS.sig" "$work/SHA256SUMS" >/dev/null 2>&1 \
    || fail "the signature of SHA256SUMS is not valid: nothing was installed"

expected=$(awk -v name="$archive" '$2 == name { print $1 }' "$work/SHA256SUMS")
[ -n "$expected" ] || fail "$archive is not in the signed list: nothing was installed"
actual=$(sha256 "$work/$archive")
[ "$expected" = "$actual" ] || fail "the checksum of $archive does not match the signed list: nothing was installed"

members=$(tar -tzf "$work/$archive") || fail "the archive cannot be read"
[ "$members" = "laris" ] || fail "the archive holds unexpected files: nothing was installed"
mkdir "$work/unpacked"
tar -xzf "$work/$archive" -C "$work/unpacked" laris || fail "cannot unpack the archive"
[ -f "$work/unpacked/laris" ] && [ ! -L "$work/unpacked/laris" ] || fail "the archive holds no regular file laris"

mkdir -p "$INSTALL_DIR" || fail "cannot make $INSTALL_DIR"
cp "$work/unpacked/laris" "$INSTALL_DIR/.laris.new" || fail "cannot write in $INSTALL_DIR"
chmod 755 "$INSTALL_DIR/.laris.new"
mv -f "$INSTALL_DIR/.laris.new" "$INSTALL_DIR/laris" || fail "cannot put laris in $INSTALL_DIR"

printf 'Installed %s\n' "$INSTALL_DIR/laris"
"$INSTALL_DIR/laris" --version || fail "the installed binary does not start"
case ":${PATH:-}:" in
    *":$INSTALL_DIR:"*) ;;
    *) printf 'Add %s to your PATH to run `laris` from anywhere.\n' "$INSTALL_DIR" ;;
esac
