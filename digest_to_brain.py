#!/usr/bin/env python3
import json
import os
import urllib.parse
import urllib.request

API = os.environ.get("GAMA_LEARN_API") or "http://100.106.202.123:8078"
BRAIN = os.environ.get("GAMA_BRAIN_URL") or "http://127.0.0.1:8065"
TOKEN = os.environ.get("GAMA_LEARN_TOKEN") or ""


def main():
    url = API.rstrip("/") + "/api/digest"
    if TOKEN:
        url += "?token=" + urllib.parse.quote(TOKEN)
    try:
        with urllib.request.urlopen(url, timeout=40) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print("digest_fail", str(e)[:200])
        return 1
    c = d.get("challenges") or {}
    k = d.get("catalog") or {}
    rec = d.get("recent") or {}
    sug = ", ".join("%s:%s" % (s.get("kind"), s.get("skill"))
                    for s in (d.get("suggestions") or [])[:5]) or "nema"
    fact = ("[digest][%s] challenge %s PASS/%s FAIL/%s SKIP od %s; katalog %s verified/%s; "
            "novo 24h: %s tema, %s skillova; predlozi: %s" % (
                d.get("date") or "", c.get("PASS", 0), c.get("FAIL", 0), c.get("SKIP", 0),
                c.get("total", 0), k.get("verified", 0), k.get("total", 0),
                len(rec.get("topics") or []), len(rec.get("skills") or []), sug))
    body = json.dumps({"kind": "lesson", "topic": "gama-learn-digest", "fact": fact},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BRAIN.rstrip("/") + "/write", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print("brain_fail", str(e)[:200])
        print(fact)
        return 1
    print(fact)
    print(json.dumps(out, ensure_ascii=False)[:300])
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
