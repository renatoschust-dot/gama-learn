#!/bin/bash
set -euo pipefail
BASE="${GAMA_LEARN_API:-http://100.106.202.123:8078}"
TOK="${GAMA_LEARN_TOKEN:-}"
URL="$BASE/api/alerts?agent=opencode"
if [ -n "$TOK" ]; then
  ENC="$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$TOK")"
  URL="$URL&token=$ENC"
fi
D="$(curl -s --max-time 60 "$URL")"
COUNT="$(printf '%s' "$D" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("count",0))' 2>/dev/null || echo 0)"
if [ "$COUNT" -le 0 ]; then
  echo "alerts=0"
  exit 0
fi
HASH="$(printf '%s' "$D" | sha256sum | cut -d' ' -f1)"
STAMP="$(date +%F):$HASH"
LAST="/root/gamaos/.learn_alert_last"
if [ -f "$LAST" ] && [ "$(cat "$LAST")" = "$STAMP" ]; then
  echo "alerts=$COUNT dedup"
  exit 0
fi
FACT="$(printf '%s' "$D" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("; ".join(x.get("title","") for x in (d.get("items") or [])[:8]))')"
BRAIN="${GAMA_BRAIN_URL:-http://127.0.0.1:8065}"
python3 - "$FACT" "$BRAIN" <<'PY'
import json, sys, urllib.request
fact = sys.argv[1][:500]
brain = sys.argv[2].rstrip("/")
body = json.dumps({"kind": "lesson", "topic": "gama-learn-alerts",
                   "fact": "[learn-alert] " + fact}, ensure_ascii=False).encode("utf-8")
req = urllib.request.Request(brain + "/write", data=body,
                             headers={"Content-Type": "application/json"}, method="POST")
print(urllib.request.urlopen(req, timeout=20).read().decode()[:200])
PY
mkdir -p /root/gamaos
echo "$STAMP" > "$LAST"
echo "alerts=$COUNT posted"