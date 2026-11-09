#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://100.106.202.123:8078").rstrip("/")
TOKEN = os.environ.get("GAMA_LEARN_TOKEN") or ""


def get(path, timeout=30):
    url = BASE + path
    if TOKEN:
        url += ("&" if "?" in url else "?") + "token=" + urllib.parse.quote(TOKEN)
    headers = {"X-Learn-Token": TOKEN} if TOKEN else {}
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    return data, int((time.time() - t0) * 1000)


def check_version():
    d, ms = get("/api/version")
    return bool(d.get("ok") and d.get("fp")), "fp=%s nodes=%s" % (str(d.get("fp"))[:8], d.get("nodes")), ms


def check_graph():
    d, ms = get("/api/graph", 30)
    n = len(d.get("nodes") or [])
    return n > 0, "nodes=%d edges=%d" % (n, len(d.get("edges") or [])), ms


def check_search():
    d, ms = get("/api/search?q=firecracker&k=3", 20)
    m = int(d.get("matches") or 0)
    return m > 0, "matches=%d" % m, ms


def check_catalog():
    d, ms = get("/api/catalog?limit=1", 20)
    s = d.get("stats") or {}
    return bool(d.get("ok") and s.get("total")), "total=%s cache=%s" % (s.get("total"), s.get("cache")), ms


def check_eval():
    d, ms = get("/api/eval?skill=gama-kasa", 30)
    return bool(d.get("ok") and d.get("status") == "PASS"), "status=%s" % d.get("status"), ms


def check_eval_llm():
    d, ms = get("/api/eval/llm?skill=gama-kasa&k=1", 90)
    runs = d.get("runs") or []
    run = runs[0] if runs else {}
    ok = bool(d.get("ok") and len(runs) == 1 and not run.get("error"))
    return ok, "pass@1=%s judge=%s err=%s" % (
        d.get("pass_at_k"), (run.get("judge") or {}).get("pass"), run.get("error")), ms


def check_health():
    d, ms = get("/api/health", 20)
    s = d.get("summary") or {}
    return bool(s.get("total") and s.get("online")), "online=%s/%s" % (s.get("online"), s.get("total")), ms


def check_auth():
    d, ms = get("/api/auth", 10)
    a = d.get("auth") or {}
    return bool(d.get("ok") and a.get("role")), "role=%s mode=%s" % (a.get("role"), a.get("mode")), ms


def check_digest():
    d, ms = get("/api/digest", 40)
    return bool(d.get("ok") and d.get("challenges")), "challenges=%s" % (d.get("challenges") or {}).get("total"), ms


def check_review():
    d, ms = get("/api/review?agent=opencode", 20)
    return bool(d.get("ok") and "due" in d), "due=%s scheduled=%s" % (d.get("due"), d.get("scheduled")), ms


def check_fleet():
    d, ms = get("/api/fleet", 40)
    s = d.get("summary") or {}
    return bool(d.get("ok") and s.get("nodes") == 2 and s.get("online", 0) >= 1), \
        "online=%s/%s verified=%s" % (s.get("online"), s.get("nodes"), s.get("verified")), ms


def check_pwa():
    t0 = time.time()
    codes = []
    for p in ("/manifest.webmanifest", "/sw.js", "/icons/icon-192.png", "/icons/icon-512.png"):
        req = urllib.request.Request(BASE + p)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                codes.append((p, r.status, r.headers.get("Content-Type") or ""))
        except Exception as e:
            codes.append((p, 0, str(e)[:40]))
    ok = all(c[1] == 200 for c in codes) and codes[0][2].startswith("application/manifest")
    return ok, " ".join("%s=%s" % (c[0].rsplit("/", 1)[-1], c[1]) for c in codes), int((time.time() - t0) * 1000)


TESTS = [
    ("version", check_version),
    ("graph", check_graph),
    ("search", check_search),
    ("catalog", check_catalog),
    ("eval", check_eval),
    ("eval_llm", check_eval_llm),
    ("health", check_health),
    ("auth", check_auth),
    ("digest", check_digest),
    ("review", check_review),
    ("fleet", check_fleet),
    ("pwa", check_pwa),
]

fails = 0
for name, fn in TESTS:
    try:
        ok, info, ms = fn()
    except Exception as e:
        ok, info, ms = False, "ERR " + str(e)[:160], 0
    print("%-4s %-9s %6d ms  %s" % ("PASS" if ok else "FAIL", name, ms, info), flush=True)
    if not ok:
        fails += 1
print("\n%d/%d PASS" % (len(TESTS) - fails, len(TESTS)))
raise SystemExit(1 if fails else 0)