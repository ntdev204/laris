#!/bin/sh
# Restore a dump made by docker/backup.sh into the running postgres service.
#   docker/restore.sh FILE.dump --yes
# Stops the API while it runs, empties the database schema, loads the dump, starts the API again.
# If anything fails the API stays stopped, so a half-restored database is never served.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
compose="docker compose -f $here/compose.yaml ${LARIS_COMPOSE_EXTRA:-}"
file=${1:?usage: restore.sh FILE.dump --yes}
[ "${2:-}" = "--yes" ] || { echo "this replaces the database; add --yes to go on" >&2; exit 2; }
[ -s "$file" ] || { echo "no such dump: $file" >&2; exit 2; }
$compose stop api
# a clean slate: pg_restore --clean cannot drop the partitions' inherited constraints one by one
$compose exec -T postgres psql -U laris -d laris -v ON_ERROR_STOP=1 \
    -c 'DROP SCHEMA public CASCADE' -c 'CREATE SCHEMA public'
$compose exec -T postgres pg_restore -U laris -d laris --no-owner --exit-on-error < "$file"
$compose start api
echo "restored $file"
