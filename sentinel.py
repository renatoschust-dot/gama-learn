#!/usr/bin/env python3
"""GAMA Learn Sentinel (P32).

Read-only probes over the artifacts registry. Writes:
- state/sentinel.json     (summary + current problems)
- state/sentinel_state.json (previous status per artifact, for change detection)
- state/live.jsonl        (append-only living log; only changes + run summary)

No auto-fix. No business actions. Safe to run from a timer.
"""
import json
import os
import subprocess
import sys
import time
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server

ARTIFACTS = os.path.join(server.STATE_DIR, "artifacts.json")
STATE = os.path.join(server.STATE_DIR, "sentinel_state.json")
OUT = os.path.join(server.STATE_DIR, "sentinel.json")
DEEP = os.path.join(server.STATE_DIR, "sentinel_deep.json")
LIVE = os.path.join(server.STATE_DIR, "live.jsonl")
TG = "/root/gama_free/gama_tg.py"
NOTIFY = os.path.join(server.STATE_DIR, "sentinel_notify.json")
MAX_LIVE = 5 * 1024 * 1024
HOST = __import__("socket").gethostname()
NOW = int(time.time())


def _read(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _live(events):
    if not events:
        return
    try:
        if os.path.getsize(LIVE) > MAX_LIVE:
            os.replace(LIVE, LIVE + ".1")
    except OSError:
        pass
    with open(LIVE, "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _service(name):
    try:
        p = subprocess.run(["systemctl", "is-active", name], capture_output=True,
                           text=True, timeout=5)
        active = (p.stdout or "").strip() or "unknown"
    except Exception as e:
        return "fail", "probe error: " + str(e)[:120]
    if active == "active":
        return "ok", active
    if active == "failed":
        return "fail", active
    if active in ("activating", "deactivating"):
        return "busy", active
    return "idle", active


def _skill(item):
    path = item.get("path") or ""
    if not path or not os.path.isfile(path):
        return "missing", "file missing"
    return "ok", "exists"


def _deep_probe():
    """Static syntax probe of installed skill scripts (no execution)."""
    art = _read(ARTIFACTS, {})
    checked = 0
    ok = 0
    fails = []
    for it in art.get("items") or []:
        if it.get("kind") != "skill" or not it.get("installed"):
            continue
        base = os.path.dirname(it.get("path") or "")
        if not base:
            continue
        files = glob.glob(os.path.join(base, "scripts", "*.py"))
        files += glob.glob(os.path.join(base, "scripts", "*.sh"))
        for f in files:
            if checked >= 120:
                break
            checked += 1
            try:
                if f.endswith(".py"):
                    cmd = [sys.executable, "-c",
                           "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8', errors='replace').read())", f]
                else:
                    cmd = ["bash", "-n", f]
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if p.returncode == 0:
                    ok += 1
                else:
                    fails.append({"path": f, "err": (p.stderr or p.stdout or "rc=%s" % p.returncode)[:200]})
            except Exception as e:
                fails.append({"path": f, "err": str(e)[:200]})
        if checked >= 120:
            break
    now = int(time.time())
    events = [{"ts": now, "host": HOST, "artifact": "script:" + x["path"],
               "event": "fail", "status": "syntax_fail", "detail": x["err"],
               "level": "E1", "source": "sentinel_deep"} for x in fails[:100]]
    _live(events + [{"ts": now, "host": HOST, "event": "deep_run",
                     "checked": checked, "ok": ok, "failed": len(fails),
                     "source": "sentinel_deep"}])
    out = {"ts": now, "host": HOST, "checked": checked, "ok": ok,
           "failed": len(fails), "fails": fails[:100]}
    _write(DEEP, out)
    return out


def _notify(text):
    if not text or not os.path.isfile(TG):
        return False
    key = text[:500]
    st = _read(NOTIFY, {})
    if st.get("key") == key and NOW - int(st.get("ts") or 0) < 3600:
        return False
    try:
        p = subprocess.run([sys.executable, TG, text], capture_output=True, text=True, timeout=20)
        ok = p.returncode == 0 and "sent" in (p.stdout or "")
    except Exception:
        ok = False
    _write(NOTIFY, {"ts": NOW, "key": key, "ok": ok})
    return ok


def main():
    art = _read(ARTIFACTS, {})
    items = art.get("items") or []
    prev = _read(STATE, {})
    counts = {"ok": 0, "fail": 0, "idle": 0, "missing": 0, "skipped": 0}
    problems = []
    events = []
    probed = 0
    for it in items:
        kind = it.get("kind")
        aid = str(it.get("id") or "")
        name = str(it.get("name") or "")
        if kind == "service":
            status, detail = _service(name)
        elif kind == "skill":
            if not it.get("installed"):
                counts["skipped"] += 1
                continue
            status, detail = _skill(it)
        else:
            counts["skipped"] += 1
            continue
        probed += 1
        counts[status] = counts.get(status, 0) + 1
        old = prev.get(aid)
        if status != old:
            ev = "ok"
            if status == "fail":
                ev = "fail"
            elif status == "missing":
                ev = "missing"
            elif status == "idle" and old == "ok":
                ev = "forgotten"
            events.append({"ts": NOW, "host": HOST, "artifact": aid, "kind": kind,
                           "name": name, "event": ev, "status": status,
                           "previous": old, "detail": detail, "level": "E1",
                           "source": "sentinel"})
        if status in ("fail", "missing"):
            problems.append({"id": aid, "kind": kind, "name": name,
                             "status": status, "detail": detail,
                             "observed_at": NOW})
        prev[aid] = status
    summary = {"ts": NOW, "host": HOST, "probed": probed,
               "counts": counts, "problems": problems[:200],
               "events": events[-100:], "ttl_s": 300}
    _write(OUT, summary)
    _write(STATE, prev)
    _live(events + [{"ts": NOW, "host": HOST, "event": "run",
                     "probed": probed, "counts": counts,
                     "problem_count": len(problems), "source": "sentinel"}])
    if "--deep" in sys.argv[1:]:
        summary["deep"] = _deep_probe()
        _write(OUT, summary)
    deep = summary.get("deep") or {}
    msg = []
    if problems:
        msg.append("Sentinel %s: %d problema — %s" % (
            HOST, len(problems), ", ".join(str(x.get("name")) for x in problems[:3])))
    if deep.get("failed"):
        msg.append("Deep probe: %d syntax FAIL" % deep["failed"])
    if msg:
        _notify(" | ".join(msg)[:900])
    return summary


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
