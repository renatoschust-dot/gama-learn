#!/bin/bash
set -euo pipefail
BASE="${GAMA_LEARN_API:-http://100.106.202.123:8078}"
TOK="${GAMA_LEARN_TOKEN:-}"
URL="$BASE/api/eval/bulk?normalize=1"
if [ -n "$TOK" ]; then
  ENC="$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$TOK")"
  URL="$URL&token=$ENC"
fi
curl -s --max-time 600 "$URL" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(json.dumps(d.get("summary") or d,ensure_ascii=False))'