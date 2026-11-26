#!/bin/bash
set -euo pipefail
BASE="${GAMA_LEARN_API:?set GAMA_LEARN_API (no internal address is committed)}"
TOK="${GAMA_LEARN_TOKEN:-}"
URL="$BASE/api/eval/tools?run=1"
if [ -n "$TOK" ]; then
  ENC="$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$TOK")"
  URL="$URL&token=$ENC"
fi
curl -s --max-time 600 "$URL" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(json.dumps(d.get("summary") or d,ensure_ascii=False))'