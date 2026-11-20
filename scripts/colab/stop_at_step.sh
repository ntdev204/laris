#!/usr/bin/env bash
# Stop a chunked run (T219) right after the checkpoint of a given step. Run ON THE VM, next to the run. OWNER tool: it only stops a process.
# Usage: bash scripts/colab/stop_at_step.sh RUN_ID STEP        e.g. english-r1-ext 20000
# Waits until the validation row of STEP is in the log, waits until `last/model.pt` stops changing (the save that follows the evaluation),
# then sends SIGTERM to the training process. Prints CHUNK_STOPPED when the process has exited.
set -euo pipefail
run="${1:?run id}"; step="${2:?step}"
cd "$(dirname "$0")/../.."
log="artifacts/profiles/$run.log"; last="artifacts/checkpoints/language_encoder/$run/last/model.pt"
until tr '\r' '\n' < "$log" | grep -qE "^ +$step +[0-9]"; do sleep 20; done
prev=""; same=0
while [ "$same" -lt 3 ]; do                       # three equal readings in a row, 20 s apart
  cur="$(stat -c '%Y %s' "$last" 2>/dev/null || echo none)"
  if [ "$cur" = "$prev" ] && [ "$cur" != none ]; then same=$((same+1)); else same=0; fi
  prev="$cur"; sleep 20
done
pid="$(ps -eo pid,cmd | awk -v r="--run-id $run" 'index($0,"cli.model train") && index($0,r) && !/awk/ {print $1; exit}')"
[ -n "$pid" ] && kill -TERM "$pid"
while [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; do sleep 5; done
echo "CHUNK_STOPPED at step $step"
