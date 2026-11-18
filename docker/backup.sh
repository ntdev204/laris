#!/bin/sh
# Backs up the database (keys, usage, traces) with pg_dump.
#   docker/backup.sh [DIR]                 writes DIR/laris-<UTC time>.dump (default: ./backups)
#   docker/backup.sh --with-secrets [DIR]  also archives docker/secrets (needed to reveal stored keys)
# Keep the dump and the secrets in different places: the dump alone cannot decrypt stored keys.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
compose="docker compose -f $here/compose.yaml"
secrets=no
if [ "${1:-}" = "--with-secrets" ]; then secrets=yes; shift; fi
dir=${1:-backups}
mkdir -p "$dir"
chmod 700 "$dir"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="$dir/laris-$stamp.dump"
umask 077
$compose exec -T postgres pg_dump -U laris -d laris -Fc --no-owner > "$out.part"
if [ ! -s "$out.part" ]; then rm -f "$out.part"; echo "backup failed: empty dump" >&2; exit 1; fi
mv "$out.part" "$out"
echo "database -> $out ($(wc -c < "$out") bytes)"
if [ "$secrets" = yes ]; then
    tar -C "$here" -czf "$dir/laris-secrets-$stamp.tgz" secrets
    echo "secrets  -> $dir/laris-secrets-$stamp.tgz (store it apart from the dump)"
else
    echo "note: docker/secrets/master.secret is NOT in this backup; without it stored keys cannot be revealed"
fi
