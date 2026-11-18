#!/usr/bin/env bash
# Rebuilds gen1_v2.sql and gen1_v3.sql: pg_dump output of a generation-1 server database (synthetic rows only).
# Needs a throwaway PostgreSQL 16 container name in $PG_CONTAINER (default laris-t142-pg); touches only schema `__schema__`.
set -euo pipefail
C=${PG_CONTAINER:-laris-t142-pg}
M=$(cd "$(dirname "$0")/../.." && pwd)/migrations
HERE=$(cd "$(dirname "$0")" && pwd)
psql() { docker exec -i "$C" psql -q -v ON_ERROR_STOP=1 -U postgres "$@"; }
dump() { docker exec "$C" pg_dump -U postgres -n __schema__ --no-owner --no-privileges --inserts --column-inserts | grep -v '^\\' ; }
seed_keys='INSERT INTO keys (id, digest, label, role, created_at, token_limit, tokens_used, tokens_reserved) VALUES
 (E'"'"'k1'"'"', E'"'"'d1'"'"', E'"'"'admin key'"'"', E'"'"'admin'"'"', 1760000000, NULL, 120, 0),
 (E'"'"'k2'"'"', E'"'"'d2'"'"', E'"'"'user key'"'"', E'"'"'user'"'"', 1760000100, 1000000, 5000, 40);'
for v in 2 3; do
  psql -c 'DROP SCHEMA IF EXISTS __schema__ CASCADE' -c 'CREATE SCHEMA __schema__'
  {
    echo 'SET search_path = __schema__;'
    echo 'CREATE TABLE schema_version (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TIMESTAMPTZ DEFAULT now());'
    cat "$M/0001_initial.sql" "$M/0002_reserved_tokens.sql"
    echo "INSERT INTO schema_version (version, name) VALUES (1,'0001_initial.sql'),(2,'0002_reserved_tokens.sql');"
    echo "$seed_keys"
    # rows in three different months (2026-08, 2026-09, 2026-10), seconds since the epoch
    echo "INSERT INTO usage (key_id, ts, session_id, kind, prompt_tokens, completion_tokens) VALUES
      ('k1', 1786000000, 's1', 'chat', 10, 20), ('k2', 1788700000, 's2', 'chat', 30, 40),
      ('k2', 1788700100, 's2', 'embed', 5, 0), ('k2', 1791400000, 's3', 'chat', 7, 9);"
    echo "INSERT INTO traces (key_id, ts, session_id, model, prompt_sha256, task, reasoning, tool_calls, brain, answer_chars) VALUES
      ('k1', 1786000000, 's1', 'm', 'abc', 'task one', 'reasoning one', '[]', '[\"n1\"]', 11),
      ('k2', 1791400000, 's3', 'm', 'def', 'task two', 'reasoning two', '[\"t\"]', '[]', 22);"
    if [ "$v" = 3 ]; then
      cat "$M/0003_partitions.sql"
      echo "INSERT INTO schema_version (version, name) VALUES (3,'0003_partitions.sql');"
      echo "INSERT INTO usage (key_id, ts, session_id) VALUES ('k1', 1791500000, 's4');"
    fi
  } | psql -c 'SET search_path = __schema__' -f - >/dev/null
  dump > "$HERE/gen1_v$v.sql"
done
psql -c 'DROP SCHEMA IF EXISTS __schema__ CASCADE'
