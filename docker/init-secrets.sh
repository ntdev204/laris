#!/bin/sh
# Creates docker/secrets/* once. Never overwrites a file; the folder is git-ignored. The folder is 0700; the files
# are 0644 because Compose bind-mounts them and the containers run as unprivileged users that must read them.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
dir="$here/secrets"
mkdir -p "$dir"
chmod 700 "$dir"
token() { od -An -N32 -tx1 /dev/urandom | tr -d ' \n'; echo; }
make() {
    if [ -e "$dir/$1" ]; then echo "keep    $1"; return; fi
    (umask 022; "$2" > "$dir/$1")
    echo "created $1"
}
make master.secret token
make postgres_password token
if [ ! -e "$dir/database_url" ]; then
    (umask 022; printf 'postgresql://laris:%s@postgres:5432/laris\n' "$(cat "$dir/postgres_password")" > "$dir/database_url")
    echo "created database_url"
else
    echo "keep    database_url"
fi
