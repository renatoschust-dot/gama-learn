#!/usr/bin/env python3
"""GAMA Learn artifacts registry (P31).

Per-artifact inventory with status and evidence. It deliberately reuses the
existing catalog and systemd sources instead of creating a second catalog.
"""
import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server

HOST = socket.gethostname()
OUT = os.path.join(server.STATE_DIR, "artifacts.json")
HIST = os.path.join(server.STATE_DIR, "artifacts_history.jsonl")


def _atomic(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def collector_services():
    items = []
    try:
        p = subprocess.run(["systemctl", "list-units", "--type=service",
                            "--all", "--no-legend", "--no-pager"],
                           capture_output=True, text=True, timeout=15)
        for line in (p.stdout or "").splitlines():
            parts = line.split(None, 4)
            if len(parts) < 4 or not parts[0].endswith(".service"):
                continue
            unit, load, active, sub = parts[0], parts[1], parts[2], parts[3]
            desc = parts[4] if len(parts) > 4 else ""
            if not unit.startswith("gama") and "gama" not in desc.lower():
                continue
            old = active in ("failed", "inactive", "activating")
            items.append({
                "id": "service:%s@%s" % (unit, HOST), "kind": "service",
                "name": unit, "host": HOST, "path": "/etc/systemd/system/" + unit,
                "status": active, "sub": sub, "evidence": {"source": "systemd",
                "load": load, "active": active, "sub": sub},
                "observed_at": int(time.time()), "ttl_s": 300,
                "severity": "high" if old else "info", "desc": desc[:200],
            })
    except Exception as e:
        items.append({"id": "collector:systemd@%s" % HOST, "kind": "collector",
                      "name": "systemd", "host": HOST, "status": "broken",
                      "evidence": {"err": str(e)[:200]}, "observed_at": int(time.time())})
    return items


def collector_catalog():
    items = []
    try:
        cat = server.load_catalog()
        for it in cat.get("items") or []:
            kind = it.get("kind")
            if kind not in ("skill", "tool"):
                continue
            name = it.get("name") or it.get("id")
            if not name:
                continue
            status = it.get("status") or "unknown"
            items.append({
                "id": "%s:%s@%s" % (kind, name, HOST), "kind": kind,
                "name": name, "host": HOST, "path": it.get("path") or "",
                "status": status, "installed": bool(it.get("installed")),
                "evidence": {"source": "catalog",
                             "challenge": it.get("challenge_status") or "",
                             "evidence_level": it.get("evidence_level") or "",
                             "verified": bool(it.get("verified"))},
                "observed_at": int(time.time()), "ttl_s": 86400,
                "severity": "info" if status == "verified" else "warn",
            })
    except Exception as e:
        items.append({"id": "collector:catalog@%s" % HOST, "kind": "collector",
                      "name": "catalog", "host": HOST, "status": "broken",
                      "evidence": {"err": str(e)[:200]}, "observed_at": int(time.time())})
    return items


def collector_registry():
    path = "/root/gamaos/gama_registry.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return [{"id": "registry:gama@%s" % HOST, "kind": "registry",
                 "name": "gama_registry", "host": HOST, "path": path,
                 "status": "ok", "evidence": {"source": "gama_registry",
                 "keys": sorted(d)[:20]}, "observed_at": int(time.time()),
                 "ttl_s": 3600, "severity": "info"}]
    except (OSError, ValueError) as e:
        return [{"id": "registry:gama@%s" % HOST, "kind": "registry",
                 "name": "gama_registry", "host": HOST, "path": path,
                 "status": "missing", "evidence": {"err": str(e)[:160]},
                 "observed_at": int(time.time()), "ttl_s": 3600,
                 "severity": "warn"}]


def build():
    items = collector_services() + collector_catalog() + collector_registry()
    counts = {}
    for x in items:
        counts[x.get("status") or "unknown"] = counts.get(x.get("status") or "unknown", 0) + 1
    data = {"ts": int(time.time()), "host": HOST, "counts": counts,
            "items": items}
    _atomic(OUT, data)
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    with open(HIST, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": data["ts"], "host": HOST,
                            "counts": counts, "total": len(items)},
                           ensure_ascii=False) + "\n")
    return {"ok": True, "total": len(items), "counts": counts, "path": OUT}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        print(json.dumps(build(), ensure_ascii=False))
    else:
        print("usage: artifacts.py build")
