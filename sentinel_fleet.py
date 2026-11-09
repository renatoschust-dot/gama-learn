#!/usr/bin/env python3
"""GAMA Learn cross-machine fleet sentinel (read-only).

Sources:
- server.fleet_report() -> Contabo (:8078) + vmlab/vastvm (:8077)
- GAMA fleet bridge HTTP :7200 (/fleet, cmd=who)
- known GAMA health URLs for Oracle and Vast

Writes:
- state/sentinel_fleet.json (current snapshot)
- state/live.jsonl (append-only; only online/fail/forgotten changes)

No mutating actions. Timeout per request is 8 s.
"""
import json
import os
import socket
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server

STATE_DIR = server.STATE_DIR
OUT = os.path.join(STATE_DIR, "sentinel_fleet.json")
LIVE = os.path.join(STATE_DIR, "live.jsonl")
MAX_LIVE = 5 * 1024 * 1024
NOW = int(time.time())
HOST = socket.gethostname()
TIMEOUT = 8.0
FLEET_URL = (os.environ.get("GAMA_FLEET_URL") or "http://127.0.0.1:7200").rstrip("/")

NODES = [
    {"name": "contabo", "kind": "learn", "hc": "contabo", "hc_host": "127.0.0.1",
     "base": os.environ.get("GAMA_LEARN_SELF") or "http://100.106.202.123:8078"},
    {"name": "vmlab", "alias": "vastvm", "kind": "learn", "hc": "vastvm", "hc_host": "100.106.182.69",
     "base": os.environ.get("GAMA_LEARN_VMLAB") or "http://100.106.182.69:8077"},
    {"name": "oracle", "kind": "probe", "hc": "oracle", "hc_host": "100.96.186.2",
     "checks": [("harness", "http://100.96.186.2:7125/health"),
                ("engine", "http://100.96.186.2:8000/health"),
                ("gateway", "http://100.96.186.2:8070/health")]},
    {"name": "vast", "kind": "probe", "hc": "vast", "hc_host": "100.109.101.98",
     "checks": [("engine", "http://100.109.101.98:8000/health"),
                ("embed", "http://100.109.101.98:8090/health")]},
]


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
    fd = os.open(LIVE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        for e in events:
            os.write(fd, (json.dumps(e, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _get_json(url, timeout=TIMEOUT):
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gama-sentinel-fleet/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = getattr(r, "status", 0)
            raw = r.read()
        return {"ok": True, "status": status, "ms": int((time.time() - t0) * 1000),
                "data": json.loads(raw.decode("utf-8", "replace") or "{}")}
    except Exception as e:
        return {"ok": False, "ms": int((time.time() - t0) * 1000), "err": str(e)[:160]}


def _fleet_who(name, timeout=TIMEOUT):
    t0 = time.time()
    try:
        body = json.dumps({"cmd": "who", "to": name}).encode("utf-8")
        req = urllib.request.Request(FLEET_URL + "/fleet", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace") or "{}")
        res = d.get("result") or {}
        return {"ok": bool(res.get("ok")), "ms": int((time.time() - t0) * 1000),
                "host": res.get("host"), "err": (res.get("err") or "")[:160],
                "via": res.get("via_cascade")}
    except Exception as e:
        return {"ok": False, "ms": int((time.time() - t0) * 1000), "err": str(e)[:160]}


def _hc_who(host, port=7100, timeout=TIMEOUT):
    t0 = time.time()
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        try:
            s.sendall(b'{"cmd":"who"}\n')
            s.settimeout(timeout)
            buf = b""
            while len(buf) < 200000:
                d = s.recv(65536)
                if not d:
                    break
                buf += d
                try:
                    json.loads(buf.decode("utf-8", "replace"))
                    break
                except ValueError:
                    pass
        finally:
            s.close()
        r = json.loads(buf.decode("utf-8", "replace") or "{}")
        return {"ok": bool(r.get("ok")), "ms": int((time.time() - t0) * 1000),
                "host": r.get("host"), "err": (r.get("err") or "")[:160],
                "via": "hc-direct"}
    except Exception as e:
        return {"ok": False, "ms": int((time.time() - t0) * 1000), "err": str(e)[:160]}


def _fleet_node(spec):
    r = _fleet_who(spec["hc"])
    if not r.get("ok") and spec.get("hc_host"):
        alt = _hc_who(spec["hc_host"])
        if alt.get("ok"):
            alt["bridge_err"] = r.get("err")
            return alt
    return r


def _learn_node(spec, rep, report_err):
    n = rep or {}
    health = n.get("health") or {}
    summary = health.get("summary") or {}
    checks = health.get("checks") or {}
    failed_checks = [k for k, v in checks.items() if isinstance(v, dict) and not v.get("ok")]
    catalog = (n.get("catalog") or {}).get("stats") or {}
    digest = n.get("digest") or {}
    chal = digest.get("challenges") or {}
    version = n.get("version") or {}
    errors = list(n.get("errors") or [])
    if report_err:
        errors.append("fleet_report: " + report_err)
    health_out = None
    if health:
        total = summary.get("total", 0)
        ok_count = summary.get("online", 0)
        health_out = {"ok": bool(total) and ok_count == total and not failed_checks,
                      "online": ok_count, "total": total, "failed_checks": failed_checks}
    graph = None
    if version:
        graph = {"nodes": version.get("nodes", 0)}
    catalog_out = None
    if catalog:
        catalog_out = {"total": catalog.get("total", 0), "verified": catalog.get("verified", 0),
                       "installed": catalog.get("installed", 0),
                       "tools_verified": catalog.get("tools_verified", 0)}
    chal_out = None
    if chal:
        chal_out = {"pass": chal.get("PASS", 0), "fail": chal.get("FAIL", 0),
                    "total": chal.get("total", 0)}
    return {
        "name": spec["name"], "alias": spec.get("alias"), "kind": spec["kind"],
        "base": spec["base"], "online": bool(n.get("ok")),
        "latency_ms": int(n.get("ms") or 0),
        "health": health_out, "graph": graph,
        "catalog": catalog_out, "challenges": chal_out,
        "failed_units": None, "errors": errors,
    }


def _probe_node(spec, results):
    checks = results.get(spec["name"]) or {}
    ok_checks = [k for k, v in checks.items() if v.get("ok")]
    failed = [k for k, v in checks.items() if not v.get("ok")]
    errors = ["%s: %s" % (k, (checks[k].get("err") or "HTTP %s" % checks[k].get("status")))
              for k in failed]
    latencies = [checks[k].get("ms") or 0 for k in checks]
    health = {"ok": len(failed) == 0 and bool(checks),
              "online": len(ok_checks), "total": len(checks), "failed_checks": failed}
    return {
        "name": spec["name"], "alias": spec.get("alias"), "kind": spec["kind"],
        "base": ", ".join(url for _, url in spec["checks"]),
        "online": bool(ok_checks), "latency_ms": max(latencies) if latencies else 0,
        "health": health, "graph": None, "catalog": None, "challenges": None,
        "failed_units": None, "errors": errors,
    }


def collect():
    report = {}
    report_err = ""
    try:
        report = server.fleet_report(force=True)
    except Exception as e:
        report_err = str(e)[:160]
    learn = report.get("nodes") or {}

    probe_checks = {}
    fleet = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {}
        for spec in NODES:
            if spec["kind"] == "probe":
                for cid, url in spec["checks"]:
                    futs[ex.submit(_get_json, url)] = (spec["name"], "check", cid)
            futs[ex.submit(_fleet_node, spec)] = (spec["name"], "fleet", None)
        for fut in as_completed(futs):
            name, kind, cid = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"ok": False, "err": str(e)[:160]}
            if kind == "check":
                probe_checks.setdefault(name, {})[cid] = res
            else:
                fleet[name] = res

    nodes = {}
    for spec in NODES:
        if spec["kind"] == "learn":
            node = _learn_node(spec, learn.get(spec["name"]), report_err)
        else:
            node = _probe_node(spec, probe_checks)
        node["fleet"] = fleet.get(spec["name"]) or {"ok": False, "err": "no fleet result"}
        node["online"] = bool(node["online"] or node["fleet"].get("ok"))
        node["latency_ms"] = max(node.get("latency_ms") or 0,
                                 node["fleet"].get("ms") or 0)
        if not node["online"]:
            node["status"] = "fail"
        elif node.get("errors") or ((node.get("health") or {}).get("ok") is False):
            node["status"] = "degraded"
        else:
            node["status"] = "ok"
        nodes[spec["name"]] = node
    return nodes


def _event(name, online, previous, node, ts):
    ev = "fleet_ok" if online else "fleet_fail"
    detail = "online" if online else ("; ".join(node.get("errors") or [])[:200] or
                                      (node.get("fleet") or {}).get("err") or "offline")
    return {"ts": ts, "host": HOST, "event": ev, "node": name,
            "status": "ok" if online else "fail", "previous": previous,
            "latency_ms": node.get("latency_ms"), "detail": detail,
            "source": "sentinel_fleet"}


def main():
    prev = _read(OUT, {})
    prev_nodes = prev.get("nodes") or {}
    nodes = collect()
    events = []
    for name, node in nodes.items():
        old = (prev_nodes.get(name) or {}).get("online")
        if old is None or bool(old) != bool(node["online"]):
            events.append(_event(name, node["online"], old, node, NOW))
    for name, old in prev_nodes.items():
        if name not in nodes:
            events.append({"ts": NOW, "host": HOST, "event": "fleet_forgotten",
                           "node": name, "status": "forgotten",
                           "previous": old.get("online"), "detail": "node removed",
                           "source": "sentinel_fleet"})
    online = [n for n in nodes.values() if n["online"]]
    slow = max(online, key=lambda n: n.get("latency_ms") or 0) if online else None
    summary = {
        "total": len(nodes), "online": len(online), "failed": len(nodes) - len(online),
        "degraded": sum(1 for n in nodes.values() if n.get("status") == "degraded"),
        "slowest": ({"node": slow["name"], "ms": slow.get("latency_ms")} if slow else None),
    }
    data = {"ts": NOW, "nodes": nodes, "summary": summary}
    _write(OUT, data)
    _live(events)
    return data


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
