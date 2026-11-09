#!/bin/bash
set -euo pipefail
umask 077
SRC="${GAMA_LEARN_STATE:-/opt/gama_learn/state}"
DST="${GAMA_LEARN_BACKUP_DIR:-/root/gama-backups/gama-learn}"
BASE="$(dirname "$SRC")"
NAME="$(basename "$SRC")"
mkdir -p "$DST"
ts="$(date +%Y%m%d_%H%M%S)"
out="$DST/state_${ts}.tar.gz"
tar -czf "$out" -C "$BASE" "$NAME"
chmod 600 "$out"
find "$DST" -maxdepth 1 -name 'state_*.tar.gz' -mtime +7 -delete
echo "$out"