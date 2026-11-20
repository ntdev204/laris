# laris

Thin npm wrapper of the LARIS client. `npm install -g @ntdev204/laris` downloads the native binary for this machine, checks the
signature of the checksum list and the checksum of the archive, and installs it inside the package. Nothing is
installed when a check fails. The package holds no other code than the downloader and the launcher.

- `LARIS_VERSION` selects a release (default: the version of this package).
- `LARIS_RELEASE_URL` selects another release address; the signature is still checked against the key in `config.json`.
