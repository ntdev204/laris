#!/bin/sh
# Create docker/secrets/* once. Never overwrites an existing file; the folder is git-ignored.
# The folder is 0700 (only you can enter it); the files are 0644 because Compose bind-mounts them
# and the containers run as an unprivileged user that must be able to read them.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
dir="$here/secrets"
mkdir -p "$dir"
chmod 700 "$dir"
make() {  # name, generator
    [ -e "$dir/$1" ] && { echo "keep    $1"; return; }
    umask 022
    "$2" > "$dir/$1"
    echo "created $1"
}
token() { python3 -c 'import secrets; print(secrets.token_hex(32))'; }
make master.secret token
make postgres_password token
if [ ! -e "$dir/database_url" ]; then
    umask 022
    printf 'postgresql://laris:%s@postgres:5432/laris\n' "$(cat "$dir/postgres_password")" \
        > "$dir/database_url"
    echo "created database_url"
else
    echo "keep    database_url"
fi
