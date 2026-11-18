#!/bin/sh
# Restores a dump made by backup.sh into the running database (replaces what is there).
#   docker/restore.sh DUMP
set -eu
[ $# -eq 1 ] && [ -f "$1" ] || { echo "usage: docker/restore.sh DUMP" >&2; exit 2; }
here=$(cd "$(dirname "$0")" && pwd)
compose="docker compose -f $here/compose.yaml"
$compose stop server
$compose exec -T postgres pg_restore -U laris -d laris --clean --if-exists --no-owner < "$1"
$compose start server
echo "restored $1"
