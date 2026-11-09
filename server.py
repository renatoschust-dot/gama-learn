#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GAMA Learn — interaktivni graf znanja za ucenje agenata.

Bez vanjskih zavisnosti (stdlib). Cita lokalnu memoriju (~/.agents/memory/gama),
skillove (~/.agents/skills) i proxy-uje GAMA brain (:8065).

Pokretanje:
    python3 server.py [--port 8077]

API:
    GET  /api/graph               -> {nodes, edges, stats}
    GET  /api/search?q=&k=        -> pretraga punog korpusa (teme+skillovi) + brain
    GET  /api/lesson?ref=         -> sadrzaj cvora (lokalni fajl ili brain /read)
    GET  /api/learned?agent=      -> nauceni cvorovi za agenta
    POST /api/learned             -> {agent, node, learned}
    POST /api/note                -> {agent, node, text} (upis u brain, kind=lesson)
"""
import hashlib
import json
import math
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
MEM_DIR = os.path.expanduser("~/.agents/memory/gama")
SKILL_DIR = os.environ.get("GAMA_SKILL_DIR") or os.path.expanduser("~/.agents/skills")
STATE_DIR = os.environ.get("GAMA_STATE_DIR") or os.path.join(HERE, "state")
SKILL_LIB = os.environ.get("GAMA_SKILL_LIB") or "/root/gama_skills_lib"
LEARNED_FILE = os.path.join(STATE_DIR, "learned.json")
TOKENS_FILE = os.path.join(STATE_DIR, "tokens.json")
SOURCES_FILE = os.path.join(HERE, "sources.json")
POWERS_FILE = os.path.join(HERE, "powers.json")
CATALOG_FILES = [
    os.environ.get("GAMA_LEARN_CATALOG") or "",
    "/root/gama_catalog/catalog.yaml",
    "/opt/gamacode/workspace/gama_catalog/catalog.yaml",
    os.path.expanduser("~/C:/Users/User/Documents/Default Project/gama_catalog/catalog.yaml"),
]
HEALTH_CHECKS = [
    {"id": "mvm", "type": "http", "url": "http://100.106.182.69:7110/health"},
    {"id": "shard", "type": "http", "url": "http://100.106.182.69:7150/health"},
    {"id": "brain", "type": "http", "url": "http://127.0.0.1:8065/stats"},
    {"id": "harness-verify", "type": "http", "url": "http://127.0.0.1:7125/health"},
    {"id": "gateway", "type": "http", "url": "http://100.96.186.2:8070/health"},
    {"id": "engine", "type": "http", "url": "http://100.96.186.2:8000/health"},
    {"id": "fastd", "type": "http", "url": "http://127.0.0.1:8094/health"},
    {"id": "deep-research", "type": "http", "url": "http://127.0.0.1:8088/health"},
    {"id": "node", "type": "http", "url": "http://127.0.0.1:7200/health"},
    {"id": "catalog", "type": "path", "dynamic": "catalog"},
    {"id": "gama-run", "type": "path", "paths": ["/usr/local/bin/gama-run"]},
    {"id": "gamashell", "type": "path", "paths": ["/usr/local/bin/gamashell"]},
    {"id": "gama-l", "type": "path", "paths": ["/root/gama_l", "/root/gama-l", "/opt/gama-l"]},
    {"id": "dsc", "type": "path", "paths": ["/root/C:/Users/User/Documents/Default Project/gama_dsc",
                                             "/root/gama-lab/gama_dsc", "/opt/gama_dsc"]},
    {"id": "ops", "type": "path", "paths": ["/root/gamaos/tools", "/root/gamaos"]},
    {"id": "guard", "type": "path", "paths": ["/root/gamaos/tools/gama_mcp_guard.py",
                                              "/opt/gama-harness/gama_mcp_guard.py"]},
]
MAX_TOPICS = int(os.environ.get("GAMA_LEARN_MAX_TOPICS") or 300)
MAX_SKILLS = int(os.environ.get("GAMA_LEARN_MAX_SKILLS") or 180)
BRAIN = (os.environ.get("GAMA_BRAIN_URL") or "http://127.0.0.1:8065").rstrip("/")
PORT = int(os.environ.get("GAMA_LEARN_PORT") or 8077)
TOKEN = os.environ.get("GAMA_LEARN_TOKEN") or ""
STREAM_URL = (os.environ.get("GAMA_STREAM_URL") or "").rstrip("/")
HARNESS_URL = (os.environ.get("GAMA_HARNESS_URL") or "http://127.0.0.1:7125").rstrip("/")
HARNESS_ENV = os.environ.get("GAMA_HARNESS_ENV") or "/etc/gama-harness.env"
LLM_URL = (os.environ.get("GAMA_LLM_URL") or "http://100.109.101.98:8100/v1/chat/completions").rstrip("/")
LLM_MODEL = os.environ.get("GAMA_LLM_MODEL") or "Qwen/Qwen2.5-7B-Instruct-AWQ"
LLM_FALLBACK_URL = (os.environ.get("GAMA_LLM_FALLBACK_URL") or "http://100.96.186.2:8000/v1/chat/completions").rstrip("/")
LLM_FALLBACK_MODEL = os.environ.get("GAMA_LLM_FALLBACK_MODEL") or "deepseek-v4-flash"
LLM_EVAL_FILE = os.path.join(STATE_DIR, "llm_eval.json")
CATALOG_CACHE_FILE = os.path.join(STATE_DIR, "catalog_cache.json")
BULK_FILE = os.path.join(STATE_DIR, "bulk_eval.json")
TOOL_EVAL_FILE = os.path.join(STATE_DIR, "tool_eval.json")
EVAL_HISTORY_FILE = os.path.join(STATE_DIR, "eval_history.json")
AUDIT_FILE = os.path.join(STATE_DIR, "audit.log")
REVIEW_FILE = os.path.join(STATE_DIR, "review.json")
BENCH_FILE = os.path.join(STATE_DIR, "bench20.json")
BENCH_SKILLS_FILE = os.path.join(STATE_DIR, "bench_skills.json")
BENCH_STATUS_FILE = os.path.join(STATE_DIR, "bench_status.json")
BENCH_HISTORY_FILE = os.path.join(STATE_DIR, "bench_history.json")
BENCH_K2_FILE = os.path.join(STATE_DIR, "bench20_k2.json")
BENCH_K3_FILE = os.path.join(STATE_DIR, "bench20_k3.json")
ARTIFACTS_FILE = os.path.join(STATE_DIR, "artifacts.json")
SENTINEL_FILE = os.path.join(STATE_DIR, "sentinel.json")
SENTINEL_DEEP_FILE = os.path.join(STATE_DIR, "sentinel_deep.json")
LIVE_FILE = os.path.join(STATE_DIR, "live.jsonl")
FIXES_FILE = os.path.join(STATE_DIR, "fixes.json")
FLEET_NODES = [
    {"name": "contabo", "base": os.environ.get("GAMA_LEARN_SELF") or "http://100.106.202.123:8078"},
    {"name": "vmlab", "base": os.environ.get("GAMA_LEARN_VMLAB") or "http://100.106.182.69:8077"},
]
_fleet_cache = {"t": 0.0, "data": None}

STOP = set("""
the and for with that this from into your you are was were will can not but all any
kako kao samo jos još nije koji koja koje ovo ono kada gdje gde zato preko izmedju
also more most than then them they have has had been being using use used user users
file files path paths tool tools agent agents gama learn ucenje učenje rad rada
""".split())

_cache = {"t": 0.0, "graph": None, "fp": None}
_full_cache = {"fp": None, "t": 0.0, "items": None, "stats": None}
_catalog_cache = {"mtime": None, "size": None, "data": None, "t": 0.0}
_health_cache = {"t": 0.0, "data": None}
_health_lock = threading.Lock()
_eval_lock = threading.Lock()
_tokens_cache = {"mtime": None, "data": {}}
_tokens_lock = threading.Lock()
_bulk_cache = {"mtime": None, "map": {}, "meta": {}}
_bulk_lock = threading.Lock()
_tool_cache = {"mtime": None, "map": {}, "meta": {}}
_llm_eval_cache = {"mtime": None, "map": {}}
_batch_state = {"running": False, "ts": 0, "total": 0, "done": 0,
                "current": "", "result": None, "error": ""}
_batch_lock = threading.Lock()
_history_lock = threading.Lock()
_rate_buckets = {}
_rate_lock = threading.Lock()
_audit_lock = threading.Lock()
_review_lock = threading.Lock()
RATE_LIMIT = int(os.environ.get("GAMA_LEARN_RATE") or 240)
RATE_POST = int(os.environ.get("GAMA_LEARN_RATE_POST") or 60)
_build_lock = threading.Lock()
_full_lock = threading.Lock()
_catalog_lock = threading.Lock()


def fingerprint():
    """Brzi prstni otisak memorije + skillova (mtime/size)."""
    h = hashlib.sha1()
    try:
        st = os.stat(SOURCES_FILE)
        h.update(("sources|%d|%d;" % (int(st.st_mtime), st.st_size)).encode())
    except OSError:
        pass
    for root, leaf in ((MEM_DIR, None), (SKILL_DIR, "SKILL.md")):
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            continue
        for fn in entries:
            p = os.path.join(root, fn)
            if leaf:
                if not os.path.isdir(p):
                    continue
                p = os.path.join(p, leaf)
            if not os.path.isfile(p):
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            h.update(("%s|%d|%d;" % (p, int(st.st_mtime), st.st_size)).encode("utf-8", "replace"))
    return h.hexdigest()


def _read_text(path, limit=20000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def _tokens(text):
    words = re.findall(r"[A-Za-zČĆŽŠĐčćžšđ][A-Za-zČĆŽŠĐčćžšđ0-9_-]{3,}", text.lower())
    return {w for w in words if w not in STOP}


def _first_para(text):
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("---"):
            continue
        if s.lower().startswith("description:"):
            s = s.split(":", 1)[-1].strip()
        if s:
            return s[:200]
    return ""


def full_index():
    """Indeks SVIH tema i skillova (bez grafnog capa) za pretragu; kes po fingerprintu."""
    now = time.time()
    fp = fingerprint()
    if _full_cache["items"] is not None and _full_cache["fp"] == fp and now - _full_cache["t"] < 600:
        return _full_cache
    with _full_lock:
        fp = fingerprint()
        if _full_cache["items"] is not None and _full_cache["fp"] == fp:
            _full_cache["t"] = now
            return _full_cache
        items = []
        mem_total = 0
        try:
            mem_files = []
            for fn in os.listdir(MEM_DIR):
                if not fn.endswith(".md"):
                    continue
                p = os.path.join(MEM_DIR, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                mem_files.append((st.st_mtime, fn, p))
            mem_files.sort(reverse=True)
            mem_total = len(mem_files)
            for _, fn, p in mem_files:
                text = _read_text(p, 12000)
                if not text.strip():
                    continue
                items.append({
                    "id": "mem:" + fn[:-3],
                    "label": _title_from_md(text, fn[:-3].replace("-", " ")),
                    "kind": "topic",
                    "group": "memorija",
                    "ref": fn,
                    "sub": _first_para(text),
                    "_hay": (fn + "\n" + text[:8000]).lower(),
                })
        except OSError:
            pass
        skill_total = 0
        try:
            sk = []
            for name in os.listdir(SKILL_DIR):
                d = os.path.join(SKILL_DIR, name)
                p = os.path.join(d, "SKILL.md")
                if not os.path.isdir(d) or not os.path.isfile(p):
                    continue
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                sk.append((0 if name.startswith("gama") else 1, -st.st_mtime, name, p))
            sk.sort()
            skill_total = len(sk)
            for _, _, name, p in sk:
                sname, title, desc, text = _skill_meta(p)
                items.append({
                    "id": "skill:" + name,
                    "label": title[:80],
                    "kind": "skill",
                    "group": "skill",
                    "ref": p,
                    "sub": desc[:200],
                    "_hay": (name + " " + title + " " + desc + " " + text[:8000]).lower(),
                })
        except OSError:
            pass
        _full_cache.update({"fp": fp, "t": time.time(), "items": items,
                            "stats": {"topics_total": mem_total, "skills_total": skill_total,
                                      "items": len(items), "built": int(now)}})
        return _full_cache


def _title_from_md(text, fallback):
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            t = line.lstrip("#").strip()
            if t:
                return t[:80]
    return fallback


def _skill_meta(path):
    """Parsira frontmatter/description iz SKILL.md."""
    text = _read_text(path, 8000)
    name = os.path.basename(os.path.dirname(path))
    desc = ""
    m = re.search(r"^description:\s*(.+)$", text, re.M)
    if m:
        desc = m.group(1).strip()[:400]
    else:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("---"):
                desc = line[:400]
                break
    title = _title_from_md(text, name)
    if len(title) < 3 or title.lower() in ("skill", "name"):
        title = name
    return name, title, desc, text


def build_graph(force=False):
    now = time.time()
    fp = fingerprint()
    if not force and _cache["graph"] and _cache["fp"] == fp and now - _cache["t"] < 600:
        return _cache["graph"]
    with _build_lock:
        fp = fingerprint()
        if not force and _cache["graph"] and _cache["fp"] == fp:
            _cache["t"] = now
            return _cache["graph"]
        graph = _build_graph_inner(now)
        graph["fp"] = fp
        _cache["graph"], _cache["t"], _cache["fp"] = graph, time.time(), fp
        return graph


def _build_graph_inner(now):
    nodes, corpus = [], {}

    mem_files = []
    try:
        for fn in os.listdir(MEM_DIR):
            if not fn.endswith(".md"):
                continue
            path = os.path.join(MEM_DIR, fn)
            try:
                st = os.stat(path)
            except OSError:
                continue
            mem_files.append((st.st_mtime, fn, path))
    except OSError:
        mem_files = []
    mem_total = len(mem_files)
    mem_files.sort(reverse=True)
    for _, fn, path in mem_files[:MAX_TOPICS]:
        text = _read_text(path, 12000)
        if not text.strip():
            continue
        nid = "mem:" + fn[:-3]
        nodes.append({
            "id": nid,
            "label": _title_from_md(text, fn[:-3].replace("-", " ")),
            "kind": "topic",
            "group": "memorija",
            "size": max(6, min(20, len(text) // 400)),
            "ref": fn,
        })
        corpus[nid] = _tokens(text[:6000])

    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            src_data = json.load(f).get("sources", [])
    except (OSError, ValueError):
        src_data = []
    for src in src_data:
        sid = str(src.get("id") or "").strip()
        if not sid:
            continue
        nid = "src:" + sid
        url = str(src.get("url") or "")
        nodes.append({
            "id": nid,
            "label": str(src.get("label") or sid)[:60],
            "kind": "web",
            "group": "izvori",
            "size": 12,
            "ref": nid,
            "sub": str(src.get("sub") or "")[:160],
            "url": url,
            "built": str(src.get("built") or "")[:300],
        })
        corpus[nid] = _tokens(" ".join([sid, str(src.get("label") or ""),
                                        str(src.get("sub") or ""), str(src.get("tags") or ""),
                                        str(src.get("built") or "")])[:6000])

    skill_files = []
    try:
        for name in os.listdir(SKILL_DIR):
            d = os.path.join(SKILL_DIR, name)
            p = os.path.join(d, "SKILL.md")
            if not os.path.isdir(d) or not os.path.isfile(p):
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            skill_files.append((0 if name.startswith("gama") else 1, -st.st_mtime, name, p))
    except OSError:
        skill_files = []
    skill_total = len(skill_files)
    skill_files.sort()
    for _, _, name, p in skill_files[:MAX_SKILLS]:
        d = os.path.dirname(p)
        nid = "skill:" + name
        sname, title, desc, text = _skill_meta(p)
        nodes.append({
            "id": nid,
            "label": title[:60],
            "kind": "skill",
            "group": "skill",
            "size": max(6, min(18, len(desc) // 25 + 6)),
            "ref": os.path.join(d, "SKILL.md"),
            "sub": desc[:160],
        })
        corpus[nid] = _tokens((name + " " + title + " " + desc + " " + text)[:6000])

    # cosine similarity, top-K edges
    ids = list(corpus.keys())
    norms = {i: math.sqrt(len(corpus[i])) or 1.0 for i in ids}
    cand = {i: [] for i in ids}
    for a in range(len(ids)):
        ia = ids[a]
        for b in range(a + 1, len(ids)):
            ib = ids[b]
            small, big = (corpus[ia], corpus[ib]) if len(corpus[ia]) < len(corpus[ib]) else (corpus[ib], corpus[ia])
            inter = len(small & big)
            if not inter:
                continue
            sim = inter / (norms[ia] * norms[ib])
            if sim >= 0.16:
                cand[ia].append((sim, ib))
                cand[ib].append((sim, ia))
    edges, seen = [], set()
    for i, lst in cand.items():
        for sim, j in sorted(lst, reverse=True)[:3]:
            key = tuple(sorted((i, j)))
            if key in seen:
                continue
            seen.add(key)
            edges.append({"source": key[0], "target": key[1], "w": round(sim, 3)})

    # izvori (web) uvek dobiju 3 najbliže veze, i kad su ispod praga
    web_ids = [n["id"] for n in nodes if n["kind"] == "web"]
    if web_ids:
        existing = {tuple(sorted((e["source"], e["target"]))) for e in edges}
        for wid in web_ids:
            sims = []
            for other in ids:
                if other == wid:
                    continue
                small, big = (corpus[wid], corpus[other]) if len(corpus[wid]) < len(corpus[other]) else (corpus[other], corpus[wid])
                inter = len(small & big)
                if not inter:
                    continue
                sims.append((inter / (norms[wid] * norms[other]), other))
            sims.sort(reverse=True)
            for sim, other in sims[:3]:
                key = tuple(sorted((wid, other)))
                if key in existing:
                    continue
                existing.add(key)
                edges.append({"source": key[0], "target": key[1], "w": round(max(sim, 0.05), 3)})

    for n in nodes:
        n["deg"] = 0
    idx = {n["id"]: n for n in nodes}
    for e in edges:
        if e["source"] in idx: idx[e["source"]]["deg"] += 1
        if e["target"] in idx: idx[e["target"]]["deg"] += 1
    graph = {"nodes": nodes, "edges": edges,
             "stats": {"nodes": len(nodes), "edges": len(edges),
                       "topics": sum(1 for n in nodes if n["kind"] == "topic"),
                       "skills": sum(1 for n in nodes if n["kind"] == "skill"),
                       "sources": sum(1 for n in nodes if n["kind"] == "web"),
                       "topics_total": mem_total, "skills_total": skill_total,
                       "capped": (mem_total > MAX_TOPICS) or (skill_total > MAX_SKILLS),
                       "built": int(now)}}
    return graph


def _facts_to_text(data):
    """Normalizuj brain /read odgovor u cist tekst."""
    if isinstance(data, dict) and data.get("raw"):
        try:
            data = json.loads(data["raw"])
        except Exception:
            pass
    facts = data.get("facts") if isinstance(data, dict) else None
    if isinstance(facts, list) and facts:
        parts = []
        for i, f in enumerate(facts, 1):
            head = "### zapis %d · %s" % (i, f.get("kind") or "?")
            ref = f.get("ref") or ""
            content = f.get("content") or f.get("text") or ""
            parts.append("%s\n%s\n\n%s" % (head, ref, content))
        return "\n\n".join(parts)
    if isinstance(data, dict):
        for key in ("text", "content", "fact"):
            if isinstance(data.get(key), str):
                return data[key]
    return None


def brain_get(path, timeout=20):
    try:
        with urllib.request.urlopen(BRAIN + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"ok": False, "err": str(e)[:200]}


def brain_post(path, payload, timeout=30):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BRAIN + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"ok": False, "err": str(e)[:200]}


def load_learned():
    try:
        with open(LEARNED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"agents": {}}


def save_learned(data):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = LEARNED_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LEARNED_FILE)


def load_tokens():
    try:
        st = os.stat(TOKENS_FILE)
    except OSError:
        return {}
    if _tokens_cache["mtime"] == st.st_mtime_ns:
        return _tokens_cache["data"]
    with _tokens_lock:
        try:
            st = os.stat(TOKENS_FILE)
            with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            toks = raw.get("tokens") if isinstance(raw, dict) and "tokens" in raw else raw
            if not isinstance(toks, dict):
                toks = {}
            _tokens_cache.update({"mtime": st.st_mtime_ns, "data": toks})
            return toks
        except (OSError, ValueError):
            return {}


def save_tokens(toks):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = TOKENS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"tokens": toks}, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, TOKENS_FILE)


def token_id(tok):
    return hashlib.sha1(tok.encode("utf-8")).hexdigest()[:8]


def audit_log(action, info, ip=""):
    entry = {"ts": int(time.time()), "ip": ip, "action": action, "info": info}
    with _audit_lock:
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if os.path.getsize(AUDIT_FILE) > 5 * 1024 * 1024:
                os.replace(AUDIT_FILE, AUDIT_FILE + ".1")
        except OSError:
            pass


def audit_tail(limit=50):
    try:
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    out.reverse()
    return out


def rate_check(ip, is_post):
    now = time.time()
    key = (ip, bool(is_post))
    limit = RATE_POST if is_post else RATE_LIMIT
    with _rate_lock:
        arr = [t for t in _rate_buckets.get(key, []) if now - t < 60.0]
        if len(arr) >= limit:
            _rate_buckets[key] = arr
            return False, limit
        arr.append(now)
        _rate_buckets[key] = arr
        return True, limit


def _learned_set(agent):
    return set(load_learned().get("agents", {}).get(agent, {}).get("nodes", {}) or {})


def challenge_result(name):
    """Nadji challenge rezultat za skill (capability ili auto-id)."""
    cat = _catalog_path()
    if not cat:
        return {}
    rf = os.path.join(os.path.dirname(cat), "challenges", "results.json")
    try:
        with open(rf, "r", encoding="utf-8") as f:
            res = json.load(f).get("results") or {}
    except (OSError, ValueError):
        return {}
    for cid, r in res.items():
        if str((r or {}).get("capability") or "") == "skill:" + name:
            return {"id": cid, "status": (r or {}).get("status") or "",
                    "evidence": str((r or {}).get("evidence") or "")[:300]}
    cid = "auto-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    r = res.get(cid) or {}
    if r:
        return {"id": cid, "status": r.get("status") or "",
                "evidence": str(r.get("evidence") or "")[:300]}
    return {}


def load_review():
    try:
        with open(REVIEW_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("agents"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"agents": {}}


def save_review(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = REVIEW_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, REVIEW_FILE)


def _review_lookup(agent, node):
    r = load_review()
    return r, r.setdefault("agents", {}).setdefault(agent, {"nodes": {}})


def _review_name(node, ev):
    ref = (ev or {}).get("ref") or ""
    if node.startswith("skill:"):
        return node[6:]
    if ref.endswith("SKILL.md"):
        return os.path.basename(os.path.dirname(ref))
    return ""


def _file_fp(path):
    try:
        st = os.stat(path)
        return "%d:%d" % (st.st_mtime_ns, st.st_size)
    except OSError:
        return ""


def review_due(agent):
    r = load_review()
    l = load_learned().get("agents", {}).get(agent, {}).get("nodes", {}) or {}
    a = (r.get("agents") or {}).get(agent, {}).get("nodes", {}) or {}
    now = int(time.time())
    items = []
    for node, e in a.items():
        ev = l.get(node) or {}
        if isinstance(ev, int):
            ev = {"ts": ev}
        ref = ev.get("ref") or ""
        cur_fp = _file_fp(ref) if ref else ""
        drone = bool(e.get("fp") and cur_fp and e.get("fp") != cur_fp)
        if int(e.get("due") or 0) > now and not drone:
            continue
        name = _review_name(node, ev)
        cr = challenge_result(name) if name else {}
        items.append({"node": node, "label": ev.get("label") or node,
                      "kind": ev.get("kind") or ("skill" if name else "topic"),
                      "ref": ref, "due": int(e.get("due") or 0),
                      "interval": e.get("interval") or 0, "reps": e.get("reps") or 0,
                      "lapses": e.get("lapses") or 0,
                      "overdue_days": max(0, (now - int(e.get("due") or now)) // 86400),
                      "drift": drone,
                      "challenge": cr.get("status") or ev.get("challenge") or ""})
    items.sort(key=lambda x: x["due"])
    nxt = min([int(e.get("due") or 0) for e in a.values() if int(e.get("due") or 0) > now] or [0])
    return {"ok": True, "agent": agent, "due": len(items), "scheduled": len(a),
            "next_due": nxt, "items": items}


def review_apply(agent, node, result):
    result = "pass" if str(result).lower() in ("pass", "ok", "polozeno", "položeno") else "fail"
    r, a = _review_lookup(agent, node)
    now = int(time.time())
    e = a["nodes"].get(node) or {"interval": 0, "ease": 2.5, "reps": 0,
                                 "lapses": 0, "due": now, "last": 0, "history": []}
    if result == "pass":
        ev = (load_learned().get("agents", {}).get(agent, {}).get("nodes", {}) or {}).get(node) or {}
        if isinstance(ev, int):
            ev = {"ts": ev}
        name = _review_name(node, ev)
        if name:
            ok = str(ev.get("challenge") or "") == "PASS"
            if not ok:
                cat = load_catalog()
                for x in cat.get("items") or []:
                    if x.get("name") == name or x.get("path") == ev.get("ref"):
                        ok = x.get("status") == "verified"
                        break
            if not ok:
                return {"ok": False, "err": "nema dokaza: challenge/skill nije verified"}
        reps = int(e.get("reps") or 0) + 1
        intervals = [1, 3, 7, 14, 30]
        interval = intervals[min(reps - 1, len(intervals) - 1)]
        e.update({"reps": reps, "interval": interval,
                  "ease": round(min(3.0, float(e.get("ease") or 2.5) + 0.1), 2),
                  "due": now + interval * 86400, "last": now})
    else:
        e.update({"reps": 0, "interval": 1, "lapses": int(e.get("lapses") or 0) + 1,
                  "due": now + 86400, "last": now})
    h = list(e.get("history") or [])
    h.append({"ts": now, "result": result, "interval": e.get("interval")})
    e["history"] = h[-30:]
    ev = (load_learned().get("agents", {}).get(agent, {}).get("nodes", {}) or {}).get(node) or {}
    if isinstance(ev, int):
        ev = {"ts": ev}
    ref = ev.get("ref") or ""
    if ref:
        e["fp"] = _file_fp(ref)
    a["nodes"][node] = e
    with _review_lock:
        save_review(r)
    audit_log("review_pass" if result == "pass" else "review_fail",
              {"agent": agent, "node": node, "interval": e.get("interval")},
              "")
    return {"ok": True, "agent": agent, "node": node, "entry": e}


def _catalog_path():
    for p in CATALOG_FILES:
        if p and os.path.isfile(p):
            return p
    return ""


def _catalog_read_cache(path, st, allow_stale=False):
    try:
        with open(CATALOG_CACHE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("source") != path:
            return None
        if not allow_stale and (d.get("mtime") != st.st_mtime or d.get("size") != st.st_size):
            return None
        caps = d.get("capabilities")
        if not isinstance(caps, list):
            return None
        return caps, str(d.get("generated") or ""), "hit"
    except (OSError, ValueError):
        return None


def _catalog_write_cache(path, st, caps, generated):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = CATALOG_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"source": path, "mtime": st.st_mtime, "size": st.st_size,
                       "generated": generated, "capabilities": caps},
                      f, ensure_ascii=False)
        os.replace(tmp, CATALOG_CACHE_FILE)
    except OSError:
        pass


def _desc_from_fm(fm):
    m = re.search(r"^description:\s*[>|][+-]?\s*\n((?:[ \t]+.*(?:\n|$))+)", fm, re.M)
    if m:
        return " ".join(x.strip() for x in m.group(1).splitlines() if x.strip())
    m = re.search(r"^description:\s*(.+)$", fm, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def _normalize_skill_text(text, name):
    changed = False
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if m:
        fm = m.group(1)
        body = text[m.end():]
    else:
        fm = None
        body = text
    if fm is None:
        desc = _first_para(body) or (name + " — GAMA skill za agente.")
        if len(desc) < 15:
            desc = name + " — GAMA skill za agente."
        fm = "name: %s\ndescription: \"%s\"" % (name, desc.replace('"', "'"))
        changed = True
    else:
        if not re.search(r"^name:\s*\S", fm, re.M):
            fm = "name: %s\n" % name + fm
            changed = True
        if len(_desc_from_fm(fm)) < 15:
            desc = _first_para(body) or (name + " — GAMA skill za agente.")
            if len(desc) < 15:
                desc = name + " — GAMA skill za agente."
            bm = re.search(r"^description:\s*[>|][+-]?\s*\n((?:[ \t]+.*(?:\n|$))+)", fm, re.M)
            if bm:
                fm = fm[:bm.start()] + 'description: "%s"' % desc.replace('"', "'") + fm[bm.end():]
            elif re.search(r"^description:.*$", fm, re.M):
                fm = re.sub(r"^description:.*$", 'description: "%s"' % desc.replace('"', "'"),
                            fm, count=1, flags=re.M)
            else:
                fm = fm.rstrip() + '\ndescription: "%s"\n' % desc.replace('"', "'")
            changed = True
    pre = "---\n" + fm.rstrip() + "\n---\n\n"
    if not re.search(r"^##+\s+\S", body, re.M):
        lm = re.match(r"^(#\s+.+\n)", body)
        body = (lm.group(1) + "\n## Sadržaj\n" + body[lm.end():]) if lm else ("## Sadržaj\n" + body)
        changed = True
    return pre + body, changed


def _bulk_fingerprint(paths):
    h = hashlib.sha1()
    for p in sorted(set(paths)):
        try:
            st = os.stat(p)
        except OSError:
            h.update((p + "|miss;").encode("utf-8", "replace"))
            continue
        h.update(("%s|%d|%d;" % (p, st.st_mtime_ns, st.st_size)).encode("utf-8", "replace"))
    return h.hexdigest()


def _load_bulk():
    try:
        st = os.stat(BULK_FILE)
    except OSError:
        return {}, {}
    if _bulk_cache["mtime"] == st.st_mtime_ns:
        return _bulk_cache["map"], _bulk_cache["meta"]
    try:
        with open(BULK_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}, {}
    res = d.get("results") or {}
    meta = {k: d.get(k) for k in ("ts", "fingerprint", "summary", "normalize")}
    _bulk_cache.update({"mtime": st.st_mtime_ns, "map": res, "meta": meta})
    return res, meta


def bulk_verify(normalize=True):
    t0 = time.time()
    cat = load_catalog()
    items = [x for x in (cat.get("items") or [])
             if x.get("kind") == "skill" and x.get("installed") and x.get("path")]
    results = {}
    counts = {"PASS": 0, "SKIP": 0, "FAIL": 0}
    normalized = refs_skills = refs_links = 0
    fails = []
    paths = []
    for it in items:
        p = it["path"]
        name = it.get("name") or os.path.basename(os.path.dirname(p))
        if not name.startswith("gama-auto-"):
            paths.append(p)
        text = _read_text(p, 20000)
        if not text.strip():
            results[p] = {"status": "SKIP", "note": "empty"}
            counts["SKIP"] += 1
            continue
        text2, changed = _normalize_skill_text(text, name)
        if changed and normalize:
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(text2)
                normalized += 1
            except OSError:
                text2 = text
                changed = False
        else:
            text2 = text
        m = re.match(r"^---\s*\n(.*?)\n---", text2, re.S)
        fm = m.group(1) if m else ""
        has_name = bool(re.search(r"^name:\s*\S", fm, re.M))
        desc = _desc_from_fm(fm) if fm else ""
        sections = len(re.findall(r"^##+\s+\S", text2, re.M))
        refs = sorted(set(re.findall(r"references/[A-Za-z0-9_.\-/]+", text2)))
        base = os.path.dirname(p)
        missing = [r for r in refs if not os.path.isfile(os.path.join(base, r.rstrip("./")))]
        if missing:
            refs_skills += 1
            refs_links += len(missing)
        ok = has_name and len(desc) >= 15 and sections >= 1
        status = "PASS" if ok else "FAIL"
        results[p] = {"status": status, "changed": bool(changed)}
        counts[status] += 1
        if not ok:
            fails.append({"name": name, "path": p, "has_name": has_name,
                          "desc_len": len(desc), "sections": sections})
    fp = _bulk_fingerprint(paths)
    summary = {"considered": len(items), "PASS": counts["PASS"], "SKIP": counts["SKIP"],
               "FAIL": counts["FAIL"], "normalized": normalized,
               "missing_refs_skills": refs_skills, "missing_refs_links": refs_links,
               "fingerprint": fp, "normalize": bool(normalize),
               "ms": int((time.time() - t0) * 1000)}
    payload = {"ts": int(time.time()), "fingerprint": fp, "normalize": bool(normalize),
               "summary": summary, "results": results}
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = BULK_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, BULK_FILE)
    except OSError:
        pass
    with _catalog_lock:
        _catalog_cache["data"] = None
        _catalog_cache["t"] = 0
    return {"ok": True, "summary": summary, "sample_failures": fails[:20]}


def _load_tool_eval():
    try:
        st = os.stat(TOOL_EVAL_FILE)
    except OSError:
        return {}, {}
    if _tool_cache["mtime"] == st.st_mtime_ns:
        return _tool_cache["map"], _tool_cache["meta"]
    try:
        with open(TOOL_EVAL_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}, {}
    res = d.get("results") or {}
    meta = {k: d.get(k) for k in ("ts", "registry", "summary")}
    _tool_cache.update({"mtime": st.st_mtime_ns, "map": res, "meta": meta})
    return res, meta


def _harness_token():
    return _env_value(HARNESS_ENV, "GAMA_HARNESS_TOKEN")


def _harness_json(path, data=None, timeout=20):
    token = _harness_token()
    if not token:
        return {"ok": False, "err": "harness token nema"}
    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(HARNESS_URL + path, data=body,
                                 headers={"Content-Type": "application/json", "X-Token": token},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"ok": False, "err": str(e)[:200]}


TOOL_LIVE = {
    "help": {},
    "list_tools": {},
    "machine_info": {},
    "file_list": {"path": "/tmp"},
    "free_api": {"api": "list"},
    "web_fetch": {"url": "https://example.com"},
    "find": {"pattern": "*.md", "path": "/tmp"},
    "brain_ask": {"q": "ping"},
    "kalkul": {"cijena": 100, "cijena_sa_pdv": 117},
    "qr": {"text": "GAMA"},
    "file_get": {"path": "/etc/hostname"},
    "repomap": {"path": "/opt/gama_learn", "query": "server"},
}


def _tool_registry():
    d = _harness_json("/mcp/tools", timeout=10)
    names = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                if isinstance(v, str):
                    names.add(v)
                else:
                    walk(v)
    if d.get("ok"):
        walk(d)
    return names


def tool_eval(run=True):
    t0 = time.time()
    cat = load_catalog()
    tools = [x for x in (cat.get("items") or []) if x.get("kind") == "tool"]
    reg = _tool_registry()
    results = {}
    counts = {"verified": 0, "partial": 0, "untested": 0}
    for it in tools:
        name = it.get("name") or it.get("id", "").split(":", 1)[-1]
        item = {"status": "untested", "mode": "missing", "ms": 0, "evidence": ""}
        if run and name in TOOL_LIVE:
            r = _harness_json("/mcp/call", {"name": name, "args": TOOL_LIVE[name]}, timeout=25)
            ok = bool(r.get("ok"))
            inner = r.get("result") if isinstance(r.get("result"), dict) else {}
            if inner.get("ok") is False:
                ok = False
            item = {"status": "verified" if ok else "untested",
                    "mode": "live", "ms": int(r.get("ms") or 0),
                    "evidence": (json.dumps(inner, ensure_ascii=False) if inner else str(r))[:300]}
        elif name in reg:
            item = {"status": "partial", "mode": "registry", "ms": 0,
                    "evidence": "registered in harness (%d tools)" % len(reg)}
        else:
            item = {"status": "untested", "mode": "missing", "ms": 0,
                    "evidence": "nije u /mcp/tools"}
        results[name] = item
        counts[item["status"]] += 1
    summary = {"considered": len(tools), "verified": counts["verified"],
               "partial": counts["partial"], "untested": counts["untested"],
               "registry": len(reg), "live_tested": len([x for x in results.values() if x["mode"] == "live"]),
               "ms": int((time.time() - t0) * 1000)}
    payload = {"ts": int(time.time()), "registry": len(reg), "summary": summary, "results": results}
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = TOOL_EVAL_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, TOOL_EVAL_FILE)
    except OSError:
        pass
    with _catalog_lock:
        _catalog_cache["data"] = None
        _catalog_cache["t"] = 0
    return {"ok": True, "summary": summary,
            "live": {k: results[k] for k in TOOL_LIVE if k in results}}


def _load_llm_eval_names():
    try:
        st = os.stat(LLM_EVAL_FILE)
    except OSError:
        return {}
    if _llm_eval_cache["mtime"] == st.st_mtime_ns:
        return _llm_eval_cache["map"]
    try:
        with open(LLM_EVAL_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    m = {k: (v or {}).get("pass_at_k", 0) for k, v in d.items() if isinstance(v, dict)}
    _llm_eval_cache.update({"mtime": st.st_mtime_ns, "map": m})
    return m


def load_catalog(force=False):
    """Ucitaj gama_catalog/catalog.yaml + sinhronizuj lokalne skillove (kes po mtime)."""
    path = _catalog_path()
    if not path:
        return {"ok": False, "err": "catalog.yaml nije nadjen", "items": [], "stats": {}}
    try:
        st = os.stat(path)
    except OSError as e:
        return {"ok": False, "err": str(e)[:200], "items": [], "stats": {}}
    now = time.time()
    rf = os.path.join(os.path.dirname(path), "challenges", "results.json")
    try:
        res_mtime = os.stat(rf).st_mtime
    except OSError:
        res_mtime = 0
    if (not force and _catalog_cache["data"] is not None
            and _catalog_cache["mtime"] == st.st_mtime
            and _catalog_cache["size"] == st.st_size
            and _catalog_cache.get("res_mtime") == res_mtime
            and now - _catalog_cache["t"] < 600):
        return _catalog_cache["data"]
    with _catalog_lock:
        try:
            st = os.stat(path)
        except OSError:
            pass
        if (not force and _catalog_cache["data"] is not None
                and _catalog_cache["mtime"] == st.st_mtime
                and _catalog_cache["size"] == st.st_size
                and _catalog_cache.get("res_mtime") == res_mtime):
            _catalog_cache["t"] = now
            return _catalog_cache["data"]
        generated = ""
        cache_state = "miss"
        cached = None if force else _catalog_read_cache(path, st)
        if cached is not None:
            caps, generated, cache_state = cached
        else:
            try:
                import yaml
                with open(path, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f)
            except Exception as e:
                cached = _catalog_read_cache(path, st, allow_stale=True)
                if cached is None:
                    return {"ok": False, "err": "catalog parse: " + str(e)[:200],
                            "items": [], "stats": {}}
                caps, generated, cache_state = cached
                cache_state = "stale"
            else:
                caps = (raw or {}).get("capabilities") or []
                generated = str((raw or {}).get("generated") or "")
                _catalog_write_cache(path, st, caps, generated)
        base = os.path.dirname(path)
        results = {}
        try:
            with open(os.path.join(base, "challenges", "results.json"), encoding="utf-8") as f:
                results = (json.load(f).get("results") or {})
        except (OSError, ValueError):
            results = {}
        items, seen = [], set()
        for c in caps:
            cid = str(c.get("id") or "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            entry = c.get("entry") or {}
            p = str(entry.get("path") or "")
            name = str(c.get("name") or cid.split(":", 1)[-1])
            ch = str(c.get("challenge") or "")
            if not ch:
                auto = "challenges/auto-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] + ".json"
                if os.path.isfile(os.path.join(base, auto)):
                    ch = auto
            ch_id = os.path.basename(ch)[:-5] if ch.endswith(".json") else ""
            rr = results.get(ch_id) or {}
            stt = str(c.get("status") or "untested")
            if rr.get("status") == "PASS":
                stt = "verified"
            items.append({
                "id": cid,
                "name": name,
                "kind": str(c.get("kind") or "skill"),
                "domain": str(c.get("domain") or "ostalo"),
                "description": str(c.get("description") or "").strip()[:500],
                "trigger": str(c.get("trigger") or "").strip()[:300],
                "status": stt,
                "review": str(c.get("review") or "unchecked"),
                "risk": str(c.get("risk") or ""),
                "path": p,
                "installed": bool(p and os.path.isfile(p)),
                "challenge": ch,
                "challenge_exists": bool(ch and os.path.isfile(os.path.join(base, ch))),
                "challenge_status": str(rr.get("status") or ""),
                "source": "katalog",
            })
        # sync: lokalni skillovi kojih nema u katalogu
        try:
            for name in os.listdir(SKILL_DIR):
                d = os.path.join(SKILL_DIR, name)
                p = os.path.join(d, "SKILL.md")
                if not os.path.isdir(d) or not os.path.isfile(p):
                    continue
                cid = "skill:" + name
                if cid in seen:
                    continue
                seen.add(cid)
                sname, title, desc, _ = _skill_meta(p)
                ch = ""
                auto = "challenges/auto-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] + ".json"
                if os.path.isfile(os.path.join(base, auto)):
                    ch = auto
                ch_id = os.path.basename(ch)[:-5] if ch.endswith(".json") else ""
                rr = results.get(ch_id) or {}
                items.append({
                    "id": cid, "name": name, "kind": "skill", "domain": "lokalno",
                    "description": desc[:500], "trigger": "",
                    "status": ("verified" if rr.get("status") == "PASS" else "untested"),
                    "review": "unchecked", "risk": "", "path": p, "installed": True,
                    "challenge": ch, "challenge_exists": bool(ch),
                    "challenge_status": str(rr.get("status") or ""), "source": "lokalno",
                })
        except OSError:
            pass
        bulk_map, bulk_meta = _load_bulk()
        bpaths = [x.get("path") for x in items if x.get("kind") == "skill"
                  and x.get("installed") and x.get("path")
                  and not (x.get("name") or "").startswith("gama-auto-")]
        bulk_fp = _bulk_fingerprint(bpaths) if bulk_meta else ""
        bulk_stale = bool(bulk_meta.get("fingerprint") and bulk_meta["fingerprint"] != bulk_fp)
        for it in items:
            if it.get("kind") != "skill":
                continue
            bro = bulk_map.get(it.get("path") or "")
            bst = (bro or {}).get("status") if isinstance(bro, dict) else (bro or "")
            it["bulk_status"] = bst or ""
            if it.get("status") != "verified" and bst == "PASS":
                it["status"] = "verified"
        tool_map, tool_meta = _load_tool_eval()
        for it in items:
            if it.get("kind") != "tool":
                continue
            tr = tool_map.get(it.get("name") or "") or {}
            tst = tr.get("status") if isinstance(tr, dict) else ""
            it["tool_status"] = tst or ""
            it["tool_mode"] = tr.get("mode") if isinstance(tr, dict) else ""
            if tst == "verified":
                it["status"] = "verified"
            elif tst == "partial" and it.get("status") != "verified":
                it["status"] = "partial"
        llm_names = _load_llm_eval_names()
        levels = {"L0": 0, "L1": 0, "L2": 0, "L3": 0}
        for it in items:
            if it.get("kind") == "skill":
                lvl = "L1" if it.get("challenge_status") == "PASS" else ("L0" if it.get("bulk_status") == "PASS" else "")
                if llm_names.get(it.get("name")) == 1:
                    lvl = "L2"
                it["evidence_level"] = lvl
            elif it.get("kind") == "tool":
                lvl = "L1" if it.get("status") == "verified" else ("L0" if it.get("status") == "partial" else "")
                it["evidence_level"] = lvl
            if it.get("evidence_level") in levels:
                levels[it["evidence_level"]] += 1
        domains = {}
        for it in items:
            domains[it["domain"]] = domains.get(it["domain"], 0) + 1
        stats = {
            "total": len(items),
            "skills": sum(1 for x in items if x["kind"] == "skill"),
            "tools": sum(1 for x in items if x["kind"] == "tool"),
            "installed": sum(1 for x in items if x["installed"]),
            "verified": sum(1 for x in items if x["status"] == "verified"),
            "partial": sum(1 for x in items if x["status"] == "partial"),
            "untested": sum(1 for x in items if x["status"] == "untested"),
            "with_challenge": sum(1 for x in items if x["challenge_exists"]),
            "challenges_run": len(results),
            "bulk": bulk_meta.get("summary") or {},
            "bulk_stale": bulk_stale,
            "bulk_fingerprint": bulk_fp,
            "tools_verified": sum(1 for x in items if x["kind"] == "tool" and x["status"] == "verified"),
            "tools_partial": sum(1 for x in items if x["kind"] == "tool" and x["status"] == "partial"),
            "tools_untested": sum(1 for x in items if x["kind"] == "tool" and x["status"] == "untested"),
            "tool_eval": tool_meta.get("summary") or {},
            "levels": levels,
            "domains": dict(sorted(domains.items(), key=lambda kv: -kv[1])),
            "generated": generated,
            "cache": cache_state,
            "file": path,
            "built": int(now),
        }
        data = {"ok": True, "items": items, "stats": stats}
        _catalog_cache.update({"mtime": st.st_mtime, "size": st.st_size,
                               "data": data, "t": time.time(), "res_mtime": res_mtime})
        return data


def _check_one(c):
    t0 = time.time()
    typ = c.get("type")
    ok, info = False, ""
    try:
        if typ == "http":
            with urllib.request.urlopen(c.get("url") or "", timeout=2) as r:
                code = r.status
            ok = 200 <= code < 400
            info = "HTTP %d" % code
        elif typ == "path":
            paths = list(c.get("paths") or [])
            if c.get("dynamic") == "catalog":
                p = _catalog_path()
                paths = [p] if p else []
            for p in paths:
                if p and os.path.exists(p):
                    ok, info = True, p
                    break
            if not ok:
                info = "nema: " + (", ".join(paths)[:140] or "?")
    except Exception as e:
        ok, info = False, str(e)[:140]
    return {"ok": ok, "ms": int((time.time() - t0) * 1000), "kind": typ, "info": info}


def health_report(force=False):
    now = time.time()
    if not force and _health_cache["data"] is not None and now - _health_cache["t"] < 15:
        return _health_cache["data"]
    with _health_lock:
        if not force and _health_cache["data"] is not None and time.time() - _health_cache["t"] < 15:
            return _health_cache["data"]
        t0 = time.time()
        checks = {}
        with ThreadPoolExecutor(max_workers=min(12, len(HEALTH_CHECKS))) as ex:
            futs = {ex.submit(_check_one, c): c for c in HEALTH_CHECKS}
            for f in as_completed(futs):
                c = futs[f]
                try:
                    checks[c["id"]] = f.result()
                except Exception as e:
                    checks[c["id"]] = {"ok": False, "ms": 0, "kind": c.get("type"), "info": str(e)[:140]}
        data = {"ok": True, "ts": int(now), "ms": int((time.time() - t0) * 1000),
                "checks": checks,
                "summary": {"online": sum(1 for v in checks.values() if v.get("ok")),
                            "total": len(checks)}}
        _health_cache.update({"t": time.time(), "data": data})
        return data


def eval_skill(name):
    """Pokreni challenge za skill i upisi svjez rezultat u results.json."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "err": "skill required"}
    cat = _catalog_path()
    if not cat:
        return {"ok": False, "err": "catalog nije nadjen"}
    base = os.path.dirname(cat)
    vpath = os.path.join(base, "verify.py")
    rf = os.path.join(base, "challenges", "results.json")
    if not os.path.isfile(vpath):
        return {"ok": False, "err": "verify.py nema"}
    cid = ""
    auto = "auto-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    if os.path.isfile(os.path.join(base, "challenges", auto + ".json")):
        cid = auto
    else:
        try:
            with open(rf, "r", encoding="utf-8") as f:
                rr = json.load(f).get("results") or {}
        except (OSError, ValueError):
            rr = {}
        for k, v in rr.items():
            if str((v or {}).get("capability") or "") == "skill:" + name:
                cid = k
                break
    if not cid:
        return {"ok": False, "err": "nema challenge-a za " + name}
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, vpath, cid], cwd=base,
                           capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        return {"ok": False, "err": "timeout 25s", "skill": name, "challenge": cid}
    ms = int((time.time() - t0) * 1000)
    out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    m = re.search(r"^\[(PASS|FAIL|SKIP|ERR\s*)\]", out, re.M)
    raw = (m.group(1).strip() if m else "")
    status = {"ERR": "ERROR"}.get(raw, raw or ("PASS" if p.returncode == 0 else "ERROR"))
    ev = ""
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("dokaz"):
            ev = s.split(":", 1)[-1].strip()
            break
    if not ev:
        ev = " | ".join([l.strip() for l in out.splitlines() if l.strip()][1:4])[:600]
    with _eval_lock:
        try:
            with open(rf, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("results", {})[cid] = {
                "id": cid, "status": status, "capability": "skill:" + name,
                "evidence": ev, "ts": int(time.time())}
            cnt = {}
            for v in data["results"].values():
                s = (v or {}).get("status") or "?"
                cnt[s] = cnt.get(s, 0) + 1
            data["summary"] = cnt
            data["generated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            tmp = rf + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, rf)
        except (OSError, ValueError):
            pass
    return {"ok": True, "skill": name, "challenge": cid, "status": status,
            "evidence": ev, "ms": ms, "rc": p.returncode, "output": out[-1200:]}


def digest(agent="opencode"):
    """Dnevni digest: challenge status, novo u memoriji/skillovima, nauceno, predlozi."""
    now = time.time()
    day = 86400
    cat = load_catalog()
    items = cat.get("items") or []
    st = cat.get("stats") or {}
    cpath = _catalog_path()
    rf = os.path.join(os.path.dirname(cpath), "challenges", "results.json") if cpath else ""
    results, generated = {}, ""
    try:
        with open(rf, "r", encoding="utf-8") as f:
            j = json.load(f)
        results = j.get("results") or {}
        generated = j.get("generated") or ""
    except (OSError, ValueError):
        pass
    cnt, fails = {}, []
    for cid, r in results.items():
        s = (r or {}).get("status") or "?"
        cnt[s] = cnt.get(s, 0) + 1
        if s in ("FAIL", "ERROR"):
            fails.append({"id": cid, "capability": (r or {}).get("capability") or "",
                          "evidence": str((r or {}).get("evidence") or "")[:200]})
    fails.sort(key=lambda x: x["capability"] or x["id"])

    recent_topics, rt = [], []
    try:
        for fn in os.listdir(MEM_DIR):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(MEM_DIR, fn)
            try:
                m = os.stat(p).st_mtime
            except OSError:
                continue
            if now - m < day:
                rt.append((m, fn, p))
    except OSError:
        pass
    rt.sort(reverse=True)
    for m, fn, p in rt[:8]:
        txt = _read_text(p, 600)
        recent_topics.append({"file": fn, "title": _title_from_md(txt, fn[:-3]), "mtime": int(m)})

    recent_skills, rs = [], []
    try:
        for name in os.listdir(SKILL_DIR):
            p = os.path.join(SKILL_DIR, name, "SKILL.md")
            if not os.path.isfile(p):
                continue
            try:
                m = os.stat(p).st_mtime
            except OSError:
                continue
            if now - m < day:
                rs.append((m, name))
    except OSError:
        pass
    rs.sort(reverse=True)
    for m, name in rs[:8]:
        recent_skills.append({"name": name, "mtime": int(m)})

    ldata = load_learned().get("agents", {}) or {}
    counts = {a: len((v or {}).get("nodes") or {}) for a, v in ldata.items()}
    recent_learned = []
    for a, v in ldata.items():
        for nid, val in ((v or {}).get("nodes") or {}).items():
            ts = val.get("ts") if isinstance(val, dict) else val
            try:
                ts = int(ts or 0)
            except (TypeError, ValueError):
                ts = 0
            if ts and now - ts < day:
                recent_learned.append({"agent": a, "node": nid,
                                       "challenge": (val or {}).get("challenge") if isinstance(val, dict) else ""})
    recent_learned.sort(key=lambda x: (x["agent"], x["node"]))

    suggestions = []
    for f in fails[:4]:
        suggestions.append({"kind": "fix", "skill": (f["capability"] or "").replace("skill:", ""),
                            "reason": "challenge " + f["id"] + " " + (f.get("evidence") or "")[:80]})
    untested = [x for x in items if x.get("installed") and x.get("kind") == "skill"
                and x.get("status") != "verified"]
    local_root = os.path.realpath(SKILL_DIR) + os.sep

    def _up(x):
        p = os.path.realpath(x.get("path") or "")
        return (0 if x.get("challenge_exists") else 1,
                0 if p.startswith(local_root) else 1,
                0 if (x.get("name") or "").startswith("gama") else 1,
                x.get("name") or "")

    untested.sort(key=_up)
    for x in untested[:6]:
        has_ch = bool(x.get("challenge_exists"))
        suggestions.append({"kind": "eval" if has_ch else "challenge",
                            "skill": x.get("name") or "",
                            "reason": "instaliran, nije verified" + ("" if has_ch else "; nema challenge")})
    hist = _history_latest()
    eval_block = {"ts": hist.get("ts"), "n": hist.get("n"), "k": hist.get("k"),
                  "regressions": hist.get("regressions") or [],
                  "improvements": hist.get("improvements") or [],
                  "ms": hist.get("ms")}
    for name in eval_block["regressions"][:5]:
        suggestions.insert(0, {"kind": "regression", "skill": name, "reason": "pass@k pao"})
    rv = review_due(agent)
    for it in rv["items"][:3]:
        suggestions.insert(0, {"kind": "review", "skill": it["label"],
                               "reason": "due %dd · %s" % (it["overdue_days"],
                                                           it.get("challenge") or "nema dokaza")})
    return {"ok": True, "ts": int(now), "date": time.strftime("%Y-%m-%d %H:%M"),
            "agent": agent,
            "review": {"due": rv["due"], "scheduled": rv["scheduled"],
                       "next_due": rv["next_due"]},
            "eval": eval_block,
            "challenges": {"total": len(results), "PASS": cnt.get("PASS", 0),
                           "FAIL": cnt.get("FAIL", 0), "SKIP": cnt.get("SKIP", 0),
                           "ERROR": cnt.get("ERROR", 0), "generated": generated},
            "catalog": {"total": st.get("total", 0), "installed": st.get("installed", 0),
                        "verified": st.get("verified", 0), "untested": st.get("untested", 0)},
            "recent": {"topics": recent_topics, "skills": recent_skills,
                       "learned": recent_learned[:12]},
            "learned_counts": counts,
            "fails": fails[:10],
            "suggestions": suggestions[:10]}


def _env_value(path, name):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return os.environ.get(name, "")


def harness_ask(text, timeout=90):
    token = _env_value(HARNESS_ENV, "GAMA_HARNESS_TOKEN")
    if not token:
        return {"ok": False, "err": "harness token nema", "ms": 0}
    payload = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(HARNESS_URL + "/chat", data=payload,
                                 headers={"Content-Type": "application/json", "X-Token": token})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return {"ok": bool(d.get("ok", True)), "say": str(d.get("say") or d.get("text") or ""),
                "ms": int((time.time() - t0) * 1000),
                "model": str(d.get("via") or d.get("engine") or "")}
    except Exception as e:
        return {"ok": False, "err": str(e)[:200], "ms": int((time.time() - t0) * 1000)}


def llm_chat(messages, max_tokens=400, timeout=40, temperature=0.2, prefer=None):
    base = [(LLM_URL, LLM_MODEL)]
    if LLM_FALLBACK_URL and (LLM_FALLBACK_URL, LLM_FALLBACK_MODEL) != (LLM_URL, LLM_MODEL):
        base.append((LLM_FALLBACK_URL, LLM_FALLBACK_MODEL))
    if prefer == "fallback":
        base.reverse()
    targets, seen = [], set()
    for t in base:
        if t not in seen:
            seen.add(t)
            targets.append(t)
    last = {"ok": False, "err": "no llm", "ms": 0}
    for url, model in targets:
        payload = json.dumps({"model": model, "messages": messages,
                              "max_tokens": max_tokens, "temperature": temperature},
                             ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            ch = (d.get("choices") or [{}])[0] or {}
            msg = ch.get("message") or {}
            return {"ok": True, "say": str(msg.get("content") or ""),
                    "ms": int((time.time() - t0) * 1000), "model": str(d.get("model") or model)}
        except Exception as e:
            last = {"ok": False, "err": str(e)[:200], "ms": int((time.time() - t0) * 1000)}
    return last


def _parse_judge(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        jd = json.loads(m.group(0))
    except Exception:
        return None
    p = jd.get("pass")
    if isinstance(p, str):
        p = p.strip().lower() in ("true", "1", "yes")
    return {"score": jd.get("score"), "pass": p,
            "reason": str(jd.get("reason") or "")[:200]}


def _det_score(name, desc, answer, has_cmd=True):
    a = answer.lower()
    score, why = 0.0, []
    if 60 <= len(answer) <= 1800:
        score += 0.25
    else:
        why.append("duzina")
    toks = list(_tokens(name + " " + desc))[:40]
    hits = sum(1 for t in toks if t in a)
    if hits >= 1:
        score += 0.25
    else:
        why.append("malo poklapanja")
    if not has_cmd:
        score += 0.25
    elif re.search(r"`[^`]+`|(?:^|\s)(gama|python3?|curl|docker|kubectl|sqlcmd|systemctl|npm|node|git)\s", answer, re.I | re.M):
        score += 0.25
    else:
        why.append("nema komande")
    if len(re.findall(r"(?m)^\s*(?:\d+[.)]|[-*])\s+", answer)) >= 2:
        score += 0.25
    else:
        why.append("nema strukture")
    return round(min(1.0, score), 2), why


def llm_eval_skill(name, k=3, judge=True):
    name = (name or "").strip()
    if not name:
        return {"ok": False, "err": "skill required"}
    try:
        k = max(1, min(5, int(k)))
    except (TypeError, ValueError):
        k = 3
    cat = load_catalog()
    it = None
    for x in cat.get("items") or []:
        if x["id"] == "skill:" + name or x["name"] == name:
            it = x
            break
    path = (it or {}).get("path") or os.path.join(SKILL_DIR, name, "SKILL.md")
    text = _read_text(path, 16000) if os.path.isfile(path) else ""
    if not text:
        return {"ok": False, "err": "skill nije nadjen ili nema SKILL.md: " + name}
    desc = (it or {}).get("description") or _first_para(text)
    title = _title_from_md(text, name)
    excerpt = text[:3500]
    has_cmd = bool(_extract_commands(text))
    cand_prompt = (
        "You are an AI agent taking a practical skill test.\n"
        "SKILL: %s\nDESCRIPTION: %s\nSKILL.md EXCERPT:\n%s\n\n"
        "TASK (<=180 words):\n"
        "1) When should this skill be used? (one sentence)\n"
        "2) Give a concrete mini-plan with 3 numbered steps.\n"
        "3) Include at least one exact command from the excerpt if the skill has commands; otherwise give one concrete example.\n"
        "4) State the success check/evidence that proves it worked.\n"
        "5) Name one failure mode or guardrail.\n"
        "Do not invent file paths or commands that are not in the excerpt. Answer plain text."
        % (name, desc[:600], excerpt))
    runs, t0 = [], time.time()
    model = ""
    for i in range(k):
        r = llm_chat([{"role": "user", "content": cand_prompt}], max_tokens=500, timeout=45)
        if not r.get("ok"):
            r = harness_ask(cand_prompt)
        model = r.get("model") or model
        if not r.get("ok"):
            runs.append({"n": i + 1, "error": r.get("err") or "harness error", "ms": r.get("ms", 0)})
            continue
        ans = (r.get("say") or "").strip()
        det, det_why = _det_score(name, desc, ans, has_cmd)
        det_pass = det >= 0.7
        jr = None
        if judge:
            crit = ("correct use, 3-step plan, exact command grounded in excerpt, success check, no invented paths"
                    if has_cmd else
                    "correct use, 3 concrete steps/examples grounded in excerpt, success check, no invented facts")
            jp = ("You are a strict evaluator. Return ONLY a JSON object, no markdown.\n"
                  "SKILL: %s\nSKILL.md EXCERPT:\n%s\n\nCANDIDATE ANSWER:\n%s\n\n"
                  "Criteria: %s. A command anywhere in the answer counts; do not require it in a specific numbered step. If the skill is non-technical, do not require a shell command. Give pass=true if the core criteria are met.\n"
                  'JSON schema: {"score": 0.0-1.0, "pass": true|false, "reason": "<=200 chars"}'
                  % (name, excerpt, ans[:2500], crit))
            j = llm_chat([{"role": "user", "content": jp}], max_tokens=240, timeout=30, prefer="fallback")
            if not j.get("ok"):
                j = harness_ask(jp, timeout=60)
            jr = None
            if j.get("ok"):
                jr = _parse_judge(j.get("say") or "")
                if not jr or jr.get("pass") is None:
                    j2 = harness_ask(jp, timeout=60)
                    if j2.get("ok"):
                        jr = _parse_judge(j2.get("say") or "") or jr
            if not jr or jr.get("pass") is None:
                jr = {"score": None, "pass": None, "reason": "judge unavailable"}
        judge_ok = jr.get("pass") if isinstance(jr, dict) else None
        if judge:
            passed = det_pass and (judge_ok is True)
        else:
            passed = det_pass
        runs.append({"n": i + 1, "pass": passed, "det": det, "det_why": det_why,
                     "judge": jr, "ms": r.get("ms", 0), "answer": ans[:700]})
    ok_runs = [x for x in runs if x.get("pass")]
    result = {"ok": True, "skill": name, "title": title, "k": k,
              "pass_at_k": 1 if ok_runs else 0,
              "pass_all": 1 if ok_runs and len(ok_runs) == k else 0,
              "passed": len(ok_runs),
              "total_ms": int((time.time() - t0) * 1000), "model": model,
              "runs": runs}
    with _eval_lock:
        try:
            data = {}
            if os.path.isfile(LLM_EVAL_FILE):
                with open(LLM_EVAL_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data[name] = {"ts": int(time.time()), "k": k, "pass_at_k": result["pass_at_k"],
                          "passed": result["passed"], "model": model, "runs": runs}
            tmp = LLM_EVAL_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, LLM_EVAL_FILE)
        except (OSError, ValueError):
            pass
    return result


def _history_read():
    try:
        with open(EVAL_HISTORY_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("runs"), list):
            return d
    except (OSError, ValueError):
        pass
    return {"runs": []}


def _history_write(d):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = EVAL_HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, EVAL_HISTORY_FILE)
    except OSError:
        pass


def _history_latest():
    runs = _history_read().get("runs") or []
    return runs[-1] if runs else {}


def _batch_skills(n):
    cat = load_catalog()
    names, extra = [], []
    for x in cat.get("items") or []:
        if x.get("kind") != "skill" or not x.get("installed") or not x.get("path"):
            continue
        name = x.get("name") or ""
        if name.startswith("gama-") and not name.startswith("gama-auto-"):
            names.append(name)
        elif not name.startswith("gama-auto-"):
            extra.append(name)
    out = sorted(set(names))
    if len(out) < n:
        out += sorted(set(extra) - set(out))
    return out[:n]


def batch_status():
    with _batch_lock:
        st = dict(_batch_state)
    st["latest"] = _history_latest()
    return st


def batch_start(n=10, k=2):
    try:
        n = max(1, min(30, int(n)))
    except (TypeError, ValueError):
        n = 10
    try:
        k = max(1, min(5, int(k)))
    except (TypeError, ValueError):
        k = 2
    with _batch_lock:
        if _batch_state["running"]:
            return {"ok": True, "started": False, "status": batch_status()}
        names = _batch_skills(n)
        if not names:
            return {"ok": False, "err": "nema skillova za batch"}
        _batch_state.update({"running": True, "ts": int(time.time()), "total": len(names),
                             "done": 0, "current": "", "result": None, "error": ""})
        t = threading.Thread(target=_batch_run, args=(names, k), daemon=True)
        t.start()
    return {"ok": True, "started": True, "status": batch_status()}


def _batch_run(names, k):
    t0 = time.time()
    items = {}
    for name in names:
        with _batch_lock:
            _batch_state["current"] = name
        try:
            r = llm_eval_skill(name, k, True)
        except Exception as e:
            r = {"ok": False, "err": str(e)[:200]}
        if r.get("ok"):
            runs = r.get("runs") or []
            scores = [x.get("judge", {}).get("score") for x in runs
                      if isinstance(x.get("judge"), dict) and isinstance(x["judge"].get("score"), (int, float))]
            items[name] = {"pass_at_k": r.get("pass_at_k", 0), "passed": r.get("passed", 0),
                           "k": r.get("k", k), "judge_avg": round(sum(scores) / len(scores), 3) if scores else None,
                           "model": r.get("model"), "ms": r.get("total_ms", 0), "error": ""}
        else:
            items[name] = {"pass_at_k": 0, "passed": 0, "k": k, "judge_avg": None,
                           "model": "", "ms": 0, "error": r.get("err") or "error"}
        with _batch_lock:
            _batch_state["done"] += 1
    prev = (_history_latest().get("items") or {})
    regressions, improvements = [], []
    for name, cur in items.items():
        p = prev.get(name) or {}
        if p and p.get("pass_at_k") == 1 and cur.get("pass_at_k") == 0:
            regressions.append(name)
        if p and p.get("pass_at_k") == 0 and cur.get("pass_at_k") == 1:
            improvements.append(name)
    run = {"ts": int(time.time()), "n": len(names), "k": k, "items": items,
           "regressions": regressions, "improvements": improvements,
           "ms": int((time.time() - t0) * 1000)}
    with _history_lock:
        hist = _history_read()
        hist.setdefault("runs", []).append(run)
        hist["runs"] = hist["runs"][-30:]
        _history_write(hist)
    with _batch_lock:
        _batch_state.update({"running": False, "current": "", "result": run})


def _fleet_get(base, path, timeout=8):
    t0 = time.time()
    try:
        with urllib.request.urlopen(base.rstrip("/") + path, timeout=timeout) as r:
            return {"ok": True, "data": json.loads(r.read().decode("utf-8", "replace")),
                    "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "err": str(e)[:160], "ms": int((time.time() - t0) * 1000)}


def fleet_report(force=False):
    now = time.time()
    if not force and _fleet_cache["data"] is not None and now - _fleet_cache["t"] < 20:
        return _fleet_cache["data"]
    paths = [("/api/version", "version"), ("/api/health", "health"),
             ("/api/catalog?limit=1", "catalog"), ("/api/digest", "digest"),
             ("/api/eval/batch", "batch"), ("/api/review?agent=opencode", "review")]
    nodes = {}
    jobs = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for node in FLEET_NODES:
            for path, key in paths:
                jobs.append((node["name"], node["base"], key, ex.submit(_fleet_get, node["base"], path)))
        for name, base, key, fut in jobs:
            r = fut.result()
            n = nodes.setdefault(name, {"name": name, "base": base, "ok": True, "ms": 0, "errors": []})
            n["ms"] = max(n["ms"], r.get("ms") or 0)
            if not r.get("ok"):
                n["errors"].append(key + ": " + (r.get("err") or "?"))
                n[key] = None
                if key == "version":
                    n["ok"] = False
            else:
                n[key] = r.get("data") or {}
    for n in nodes.values():
        d = n.get("digest") or {}
        c = (n.get("catalog") or {}).get("stats") or {}
        h = (n.get("health") or {}).get("summary") or {}
        b = (n.get("batch") or {}).get("status") or {}
        rv = n.get("review") or {}
        n["snapshot"] = {
            "nodes": (n.get("version") or {}).get("nodes", 0),
            "health": "%s/%s" % (h.get("online", 0), h.get("total", 0)),
            "catalog": "%s/%s" % (c.get("verified", 0), c.get("total", 0)),
            "installed": c.get("installed", 0),
            "tools": "%s/%s" % (c.get("tools_verified", 0), (c.get("tools_verified", 0) + c.get("tools_partial", 0) + c.get("tools_untested", 0))),
            "challenges": "%s/%s/%s" % ((d.get("challenges") or {}).get("PASS", 0),
                                       (d.get("challenges") or {}).get("FAIL", 0),
                                       (d.get("challenges") or {}).get("total", 0)),
            "bulk_stale": c.get("bulk_stale"),
            "batch_running": bool(b.get("running")),
            "batch_latest": (b.get("latest") or {}).get("ts"),
            "regressions": (b.get("latest") or {}).get("regressions") or [],
            "review_due": rv.get("due", 0),
            "review_scheduled": rv.get("scheduled", 0),
        }
    online = [n for n in nodes.values() if n.get("ok")]
    summary = {
        "nodes": len(nodes), "online": len(online),
        "verified": sum(((n.get("catalog") or {}).get("stats") or {}).get("verified", 0) for n in nodes.values()),
        "installed": sum(((n.get("catalog") or {}).get("stats") or {}).get("installed", 0) for n in nodes.values()),
        "untested": sum(((n.get("catalog") or {}).get("stats") or {}).get("untested", 0) for n in nodes.values()),
        "tools_verified": sum(((n.get("catalog") or {}).get("stats") or {}).get("tools_verified", 0) for n in nodes.values()),
        "review_due": sum((n.get("review") or {}).get("due", 0) for n in nodes.values()),
        "batch_running": any(((n.get("batch") or {}).get("status") or {}).get("running") for n in nodes.values()),
        "regressions": [{"node": n["name"], "skill": s}
                        for n in nodes.values()
                        for s in ((((n.get("batch") or {}).get("status") or {}).get("latest") or {}).get("regressions") or [])],
    }
    data = {"ok": True, "ts": int(now), "summary": summary, "nodes": nodes}
    _fleet_cache.update({"t": time.time(), "data": data})
    return data


def alerts(agent="opencode"):
    out = []
    rv = review_due(agent)
    if rv.get("due"):
        out.append({"id": "review", "severity": "warn",
                    "title": "Ponavljanje: %d due" % rv["due"],
                    "detail": "Sljedeći: " + (rv["items"][0]["label"] if rv.get("items") else "?"),
                    "action": "review"})
    hist = _history_latest()
    for skill in hist.get("regressions") or []:
        out.append({"id": "regression:" + skill, "severity": "error",
                    "title": "Regresija: " + skill,
                    "detail": "pass@k pao u zadnjem batchu", "action": "digest"})
    cat = load_catalog()
    st = cat.get("stats") or {}
    if st.get("bulk_stale"):
        out.append({"id": "bulk_stale", "severity": "warn",
                    "title": "Bulk verifikacija je stale",
                    "detail": "SKILL.md promijenjen; timer će osvježiti", "action": "catalog"})
    tev = st.get("tool_eval") or {}
    if st.get("tools_untested") and tev.get("considered"):
        out.append({"id": "tools_untested", "severity": "warn",
                    "title": "Alati untested: %d" % st["tools_untested"],
                    "detail": "Pokreni tool eval", "action": "catalog"})
    cpath = _catalog_path()
    fails = 0
    if cpath:
        try:
            with open(os.path.join(os.path.dirname(cpath), "challenges", "results.json"),
                      "r", encoding="utf-8") as f:
                res = json.load(f).get("results") or {}
            fails = sum(1 for v in res.values() if (v or {}).get("status") in ("FAIL", "ERROR"))
        except (OSError, ValueError):
            fails = 0
    if fails:
        out.append({"id": "challenge_fails", "severity": "error",
                    "title": "Challenge FAIL: %d" % fails,
                    "detail": "Provjeri results.json / Eval", "action": "digest"})
    try:
        fr = fleet_report()
        offline = [n["name"] for n in (fr.get("nodes") or {}).values() if not n.get("ok")]
        if offline:
            out.append({"id": "fleet_offline", "severity": "error",
                        "title": "Fleet offline: " + ", ".join(offline),
                        "detail": "Provjeri čvorove", "action": "fleet"})
    except Exception:
        pass
    sent = _bench_read(SENTINEL_FILE, {}) or {}
    probs = sent.get("problems") or []
    if probs:
        out.append({"id": "sentinel", "severity": "error",
                    "title": "Sentinel problemi: %d" % len(probs),
                    "detail": ", ".join(str(x.get("name")) for x in probs[:3]),
                    "action": "live"})
    deep = _bench_read(SENTINEL_DEEP_FILE, {}) or {}
    if deep.get("failed"):
        out.append({"id": "sentinel_deep", "severity": "warn",
                    "title": "Deep probe FAIL: %d" % deep["failed"],
                    "detail": "Skripte sa syntax greškom; vidi Live", "action": "live"})
    return {"ok": True, "agent": agent, "ts": int(time.time()),
            "count": len(out), "items": out}


def _extract_commands(text):
    cmds = []
    for block in re.findall(r"```[^\n]*\n(.*?)```", text, re.S):
        for line in block.splitlines():
            s = line.strip().lstrip("$ ").strip()
            if not s or s.startswith("#"):
                continue
            if re.match(r"^(gama|python3?|curl|docker|kubectl|sqlcmd|node|npm|systemctl|git|bash|sh)\b", s):
                cmds.append(s[:200])
    for m in re.findall(r"`([^`\n]{8,160})`", text):
        m = m.strip()
        if re.match(r"^(gama|python3?|curl|docker|kubectl|sqlcmd|node|npm|systemctl|git|bash|sh)\b", m):
            cmds.append(m[:200])
    out = []
    for c in cmds:
        if c not in out:
            out.append(c)
    return out[:5]


def skill_curriculum(ref):
    """Kurikulum po skillu: 4 nivoa + verifikacijski challenge (deterministicki)."""
    ref = (ref or "").strip()
    if not ref:
        return {"ok": False, "err": "skill required"}
    name = ref[6:] if ref.startswith("skill:") else ref
    if name.endswith("/SKILL.md"):
        name = os.path.basename(os.path.dirname(name))
    cat = load_catalog()
    it = None
    for x in cat.get("items") or []:
        if x["id"] == "skill:" + name or x["name"] == name:
            it = x
            break
    path = (it or {}).get("path") or ""
    if not (path and os.path.isfile(path)):
        path = os.path.join(SKILL_DIR, name, "SKILL.md")
    text = _read_text(path, 30000) if os.path.isfile(path) else ""
    if not it and not text:
        return {"ok": False, "err": "skill nije nadjen: " + name}
    desc = (it or {}).get("description") or ""
    if not desc and text:
        m = re.search(r"^description:\s*\"?(.+?)\"?$", text, re.M)
        desc = (m.group(1) if m else _first_para(text))[:400]
    title = _title_from_md(text, name) if text else name
    triggers = (it or {}).get("trigger") or ""
    if not triggers and text:
        m = re.search(r"Trigger:\s*(.+)", text, re.I)
        triggers = m.group(1)[:300] if m else ""
    heads = [h.strip()[:80] for h in re.findall(r"^##+\s+(.+)$", text, re.M)][:8]
    cmds = _extract_commands(text)
    ch = (it or {}).get("challenge") or ""
    ch_id = os.path.basename(ch)[:-5] if ch.endswith(".json") else ""
    cpath = _catalog_path()
    vpath = os.path.join(os.path.dirname(cpath), "verify.py") if cpath else ""
    if ch and ch_id and vpath and os.path.isfile(vpath):
        ch_task = "Pokreni dokaz: `python3 %s %s` — ocekuj PASS/FAIL/SKIP (SKIP je castan ako zavisnost nije dostupna)." % (vpath, ch_id)
        ch_ev = "PASS/FAIL/SKIP + evidence"
    else:
        ch_task = "Nema gotovog challenge-a: daj 3 provjerljive tvrdnje; svaka mora imati dokaz (komanda + izlaz) i izvor (fajl/URL)."
        ch_ev = "3 tvrdnje + 3 dokaza"
    first_cmd = cmds[0] if cmds else ""
    levels = [
        {"n": 1, "title": "Razumijevanje", "minutes": 10,
         "task": "Procitaj SKILL.md i napisi 3 recenice: sta radi, kada se koristi, kada NE treba.",
         "evidence": "3 recenice + referenca na fajl", "hint": desc[:300]},
        {"n": 2, "title": "Primjena", "minutes": 15,
         "task": ("Pokreni minimalni primjer: `%s`" % first_cmd) if first_cmd else "Napravi mali testni ulaz i primijeni skill od pocetka do kraja.",
         "evidence": "komanda + izlaz (rc=0)",
         "hint": ("dostupne komande: " + " · ".join(cmds[:3])) if cmds else ""},
        {"n": 3, "title": "Verifikacija", "minutes": 15, "task": ch_task,
         "evidence": ch_ev, "hint": ("challenge: " + ch) if ch else "dokaz, ne tvrdnja"},
        {"n": 4, "title": "Prijenos", "minutes": 20,
         "task": "Primijeni skill na stvarni GAMA zadatak i upisi lesson u brain (kind=lesson) sa dokazom.",
         "evidence": "brain ref + broj/izlaz", "hint": "brain_write(topic, fact, kind='lesson')"},
    ]
    return {"ok": True,
            "skill": {"id": (it or {}).get("id") or "skill:" + name, "name": name,
                      "title": title[:80], "domain": (it or {}).get("domain") or "lokalno",
                      "status": (it or {}).get("status") or "untested",
                      "risk": (it or {}).get("risk") or "",
                      "installed": bool(path and os.path.isfile(path)), "path": path,
                      "description": desc[:400], "triggers": triggers[:300],
                      "challenge_status": (it or {}).get("challenge_status") or ""},
            "levels": levels, "minutes_total": sum(l["minutes"] for l in levels),
            "headings": heads, "commands": cmds,
            "challenge": {"file": ch, "id": ch_id, "exists": bool(ch and ch_id)} if ch else None,
            "source": "katalog" if it else "lokalno"}


def pick_next(agent, focus=None):
    g = build_graph()
    learned = _learned_set(agent)
    idx = {n["id"]: n for n in g["nodes"]}
    neigh = set()
    if focus:
        for e in g["edges"]:
            if e["source"] == focus:
                neigh.add(e["target"])
            elif e["target"] == focus:
                neigh.add(e["source"])
    best = []
    for n in g["nodes"]:
        if n["id"] in learned:
            continue
        deg = n.get("deg", 0) or 0
        score = deg * 3.2 + (n.get("size") or 8) * 0.35
        if n["kind"] == "skill" and deg >= 3:
            score += 2.5
        if neigh and n["id"] in neigh:
            score += 9.0
        seed = int(hashlib.sha1((agent + n["id"]).encode()).hexdigest()[:6], 16) / 0xFFFFFF
        score += seed * 1.4
        best.append((score, n))
    best.sort(key=lambda x: -x[0])
    if not best:
        return {"ok": True, "done": True, "node": None,
                "reason": "svi čvorovi su označeni kao naučeni"}
    score, n = best[0]
    reason = []
    if neigh and n["id"] in neigh:
        reason.append("povezano sa fokusom")
    if (n.get("deg") or 0) >= 5:
        reason.append("čvorište (deg %d)" % n["deg"])
    if n["kind"] == "skill":
        reason.append("skill")
    return {"ok": True, "done": False, "node": n, "score": round(score, 2),
            "reason": ", ".join(reason) or "slobodan izbor",
            "alternatives": [{"id": x[1]["id"], "label": x[1]["label"],
                              "kind": x[1]["kind"], "deg": x[1].get("deg", 0)}
                             for x in best[1:6]]}


def pick_curriculum(agent, n=6, focus=None):
    g = build_graph()
    learned = _learned_set(agent)
    idx = {n2["id"]: n2 for n2 in g["nodes"]}
    adj = {}
    for e in g["edges"]:
        adj.setdefault(e["source"], set()).add(e["target"])
        adj.setdefault(e["target"], set()).add(e["source"])
    chosen = []
    pool = [x for x in g["nodes"] if x["id"] not in learned]
    first = pick_next(agent, focus)
    if first.get("done"):
        return {"ok": True, "done": True, "items": []}
    order_ids = []
    if first.get("node"):
        order_ids.append(first["node"]["id"])
    while len(order_ids) < n:
        front = set()
        for i in order_ids:
            front |= adj.get(i, set())
        cands = [x for x in pool if x["id"] not in order_ids]
        if not cands:
            break
        def sc(x):
            s = (x.get("deg") or 0) * 2.0 + (2.0 if x["kind"] == "skill" else 0)
            if x["id"] in front:
                s += 6.0
            seed = int(hashlib.sha1((agent + x["id"]).encode()).hexdigest()[:6], 16) / 0xFFFFFF
            return s + seed
        cands.sort(key=sc, reverse=True)
        order_ids.append(cands[0]["id"])
    for i, nid in enumerate(order_ids, 1):
        x = idx.get(nid)
        if not x:
            continue
        chosen.append({"order": i, "id": x["id"], "label": x["label"], "kind": x["kind"],
                       "deg": x.get("deg", 0), "ref": x.get("ref", ""),
                       "linked": nid in adj.get(order_ids[i - 2], set()) if i > 1 else False})
    return {"ok": True, "done": False, "agent": agent, "items": chosen}


# ---------- research (legalni izvori) ----------
_research_cache = {}


def _http_json(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "GAMALearn/0.3 (research)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _http_text(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "GAMALearn/0.3 (research)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _oa_abstract(inv):
    if not isinstance(inv, dict):
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs or []:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def _research_openalex(q, n=6):
    mail = os.environ.get("GAMA_LEARN_MAILTO") or ""
    url = ("https://api.openalex.org/works?search=%s&per-page=%d"
           "&select=id,title,publication_year,doi,authorships,primary_location,"
           "best_oa_location,open_access,abstract_inverted_index"
           % (urllib.parse.quote(q), n))
    if mail:
        url += "&mailto=" + urllib.parse.quote(mail)
    data = _http_json(url)
    out = []
    for w in data.get("results", []) or []:
        authors = [a.get("author", {}).get("display_name") for a in (w.get("authorships") or [])]
        loc = w.get("primary_location") or {}
        best = w.get("best_oa_location") or {}
        urlw = loc.get("landing_page_url") or (("https://doi.org/" + w["doi"].split("doi.org/")[-1]) if w.get("doi") else "")
        pdf = best.get("pdf_url") or (w.get("open_access") or {}).get("oa_url") or ""
        out.append({"source": "OpenAlex", "title": (w.get("title") or "").strip(),
                    "year": w.get("publication_year"), "doi": w.get("doi") or "",
                    "authors": [a for a in authors if a][:6],
                    "url": urlw or "", "pdf": pdf or "",
                    "abstract": _oa_abstract(w.get("abstract_inverted_index"))[:1200]})
    return out


def _research_arxiv(q, n=5):
    url = ("https://export.arxiv.org/api/query?search_query=all:%s&start=0&max_results=%d"
           "&sortBy=relevance" % (urllib.parse.quote(q), n))
    xml = _http_text(url)
    root = ET.fromstring(xml)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in root.findall("a:entry", ns):
        title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
        summ = (e.findtext("a:summary", default="", namespaces=ns) or "").strip()
        pub = (e.findtext("a:published", default="", namespaces=ns) or "")[:4]
        link = ""
        pdf = ""
        for l in e.findall("a:link", ns):
            if l.get("rel") == "alternate":
                link = l.get("href") or ""
            if l.get("title") == "pdf":
                pdf = l.get("href") or ""
        authors = [a.findtext("a:name", default="", namespaces=ns) for a in e.findall("a:author", ns)]
        out.append({"source": "arXiv", "title": " ".join(title.split()),
                    "year": pub, "doi": "", "authors": [a for a in authors if a][:6],
                    "url": link, "pdf": pdf, "abstract": " ".join(summ.split())[:1200]})
    return out


def research(q, n=8):
    key = q.strip().lower()
    now = time.time()
    hit = _research_cache.get(key)
    if hit and now - hit[0] < 600:
        return hit[1]
    n_oa = max(3, n // 2 + 1)
    n_ax = max(2, n - n_oa + 1)
    items = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_oa = ex.submit(_research_openalex, q, n_oa)
        f_ax = ex.submit(_research_arxiv, q, n_ax)
        for fut in (f_oa, f_ax):
            try:
                items.extend(fut.result())
            except Exception:
                pass
    seen, ded = set(), []
    for it in items:
        t = re.sub(r"[^a-z0-9]+", "", (it.get("title") or "").lower())[:80]
        if not t or t in seen:
            continue
        seen.add(t)
        ded.append(it)
    ded = ded[:n]
    res = {"ok": True, "q": q, "count": len(ded), "items": ded,
           "sources": ["OpenAlex", "arXiv"]}
    _research_cache[key] = (now, res)
    return res


# ---------- study kit (bez LLM, deterministicno) ----------
def _blocks(text):
    blocks, heading, buf = [], None, []

    def flush():
        nonlocal buf
        if buf:
            blocks.append((heading, " ".join(buf)))
            buf = []

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("```") or line.startswith("|"):
            continue
        m = re.match(r"^(#{1,6})\s*(.+)$", line)
        if m:
            flush()
            heading = m.group(2).strip()
            blocks.append((heading, None))
            continue
        if not line:
            flush()
            continue
        line = re.sub(r"^[-*+]\s+|^\d+[.)]\s+", "", line)
        buf.append(line)
    flush()
    return blocks


def _sentences(txt):
    parts = re.split(r"(?<=[.!?])\s+", txt)
    return [p.strip() for p in parts if len(p.strip()) > 24]


def study_kit(text, title, ref=""):
    text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S)
    blocks = _blocks(text)
    freq = {}
    for _, body in blocks:
        if not body:
            continue
        for w in re.findall(r"[A-Za-zČĆŽŠĐčćžšđ][A-Za-zČĆŽŠĐčćžšđ0-9_-]{3,}", body.lower()):
            if w in STOP:
                continue
            freq[w] = freq.get(w, 0) + 1

    scored = []
    order = 0
    for heading, body in blocks:
        if not body:
            continue
        for sent in _sentences(body):
            order += 1
            words = [w for w in re.findall(r"[A-Za-zČĆŽŠĐčćžšđ][A-Za-zČĆŽŠĐčćžšđ0-9_-]{3,}", sent.lower())
                     if w not in STOP]
            if not words:
                continue
            score = sum(freq.get(w, 0) for w in set(words)) / (len(words) ** 0.5)
            score += max(0, 8 - order) * 0.6
            if len(sent) > 320:
                score *= 0.6
            scored.append((score, order, sent, heading))
    scored.sort(key=lambda x: -x[0])
    top = sorted(scored[:10], key=lambda x: x[1])
    points = []
    for _, _, sent, heading in top:
        s = sent.strip()
        if len(s) > 300:
            s = s[:297].rsplit(" ", 1)[0] + "…"
        points.append({"text": s, "heading": heading})
    key_points = [p["text"] for p in points[:8]]

    cards = []
    for heading, body in blocks:
        if heading and body:
            first = _sentences(body)
            if first:
                cards.append({"front": "Objasni: " + heading, "back": first[0][:260]})
        if not body:
            continue
        for sent in _sentences(body):
            m = re.match(r"^([A-Za-zČĆŽŠĐčćžšđ0-9 .()/+-]{3,60}?)\s*(?:—|–|=|:)\s+(.{20,240})$", sent)
            if m:
                cards.append({"front": m.group(1).strip() + "?", "back": m.group(2).strip()})
    seen_f, uniq = set(), []
    for c in cards:
        k = c["front"].lower()
        if k in seen_f:
            continue
        seen_f.add(k)
        uniq.append(c)
    cards = uniq[:8]
    for p in points[:6]:
        if len(cards) >= 6:
            break
        if p["heading"] and not any(p["heading"] in c["front"] for c in cards):
            cards.append({"front": "Šta je ključno kod: " + p["heading"] + "?",
                          "back": p["text"][:260]})
    cards = cards[:8]

    quiz = []
    if len(cards) >= 3:
        import random
        rnd = random.Random(hashlib.sha1((ref or title).encode()).hexdigest()[:8])
        backs = [c["back"] for c in cards]
        for i, c in enumerate(cards[:6], 1):
            others = [b for b in backs if b != c["back"]]
            rnd.shuffle(others)
            opts = others[:2] + [c["back"]]
            rnd.shuffle(opts)
            quiz.append({"n": i, "q": c["front"], "options": opts,
                         "answer": opts.index(c["back"])})

    script = title + ".\n\n" + " ".join(key_points) + "\n\nKraj. Zapiši šta si naučio."
    return {"ok": True, "title": title, "ref": ref,
            "summary": key_points[:3], "key_points": key_points,
            "flashcards": cards, "quiz": quiz,
            "script": script[:4000], "stats": {"chars": len(text),
            "points": len(key_points), "cards": len(cards), "quiz": len(quiz)}}


# ---------- TTS ----------
def _tts(text, voice, slug):
    os.makedirs(os.path.join(STATE_DIR, "audio"), exist_ok=True)
    h = hashlib.sha1((voice + "|" + text).encode("utf-8")).hexdigest()[:16]
    fn = (slug or "lekcija")[:40] + "-" + h + ".mp3"
    fn = re.sub(r"[^A-Za-z0-9_.-]+", "-", fn)
    out = os.path.join(STATE_DIR, "audio", fn)
    made = False
    if not os.path.isfile(out) or os.path.getsize(out) < 1024:
        try:
            subprocess.run(["edge-tts", "--voice", voice, "--text", text,
                            "--write-media", out], check=True, timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            made = True
        except Exception as e:
            return {"ok": False, "err": "TTS greška: %s" % str(e)[:160]}
    return {"ok": True, "url": "/audio/" + fn, "voice": voice,
            "bytes": os.path.getsize(out), "cached": not made}


# ---------- certificate ----------
def certificate_svg(agent, node_id):
    g = build_graph()
    node = next((n for n in g["nodes"] if n["id"] == node_id), None)
    if not node:
        return None, "nepoznat čvor"
    learned = load_learned().get("agents", {}).get(agent, {}).get("nodes", {}) or {}
    if node_id not in learned:
        return None, "čvor nije označen kao naučen"
    date = time.strftime("%d.%m.%Y.")
    title = re.sub(r"\s+", " ", node["label"])[:80]
    serial = hashlib.sha1(("%s|%s|%d" % (agent, node_id, learned[node_id])).encode()).hexdigest()[:12].upper()
    neighbor_total = sum(1 for e in g["edges"] if node_id in (e["source"], e["target"]))
    neighbor_done = sum(1 for e in g["edges"]
                        if node_id in (e["source"], e["target"]) and
                        (e["source"] if e["target"] == node_id else e["target"]) in learned)

    def esc2(x):
        return (x.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="640" viewBox="0 0 1000 640">'
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#0a111c"/><stop offset="1" stop-color="#0d1a2b"/>'
        '</linearGradient><linearGradient id="line" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#5aa9ff"/><stop offset="1" stop-color="#46d38b"/>'
        '</linearGradient></defs>'
        '<rect width="1000" height="640" fill="url(#bg)"/>'
        '<rect x="18" y="18" width="964" height="604" rx="18" fill="none" stroke="#24405f" stroke-width="2"/>'
        '<rect x="18" y="18" width="964" height="6" rx="3" fill="url(#line)"/>'
        '<text x="60" y="86" fill="#7fb7ee" font-family="Segoe UI, Arial" font-size="18" letter-spacing="6">GAMA LEARN</text>'
        '<text x="60" y="180" fill="#eaf2fb" font-family="Segoe UI, Arial" font-size="46" font-weight="700">Sertifikat</text>'
        '<text x="60" y="220" fill="#8fa3bd" font-family="Segoe UI, Arial" font-size="17">o savladanom čvoru znanja</text>'
        '<text x="60" y="300" fill="#ffffff" font-family="Segoe UI, Arial" font-size="30" font-weight="600">' + esc2(title) + '</text>'
        '<text x="60" y="348" fill="#9fc0e8" font-family="Segoe UI, Arial" font-size="16">' + esc2("id: " + node_id) + '</text>'
        '<text x="60" y="410" fill="#8fa3bd" font-family="Segoe UI, Arial" font-size="15">Agent</text>'
        '<text x="60" y="440" fill="#eaf2fb" font-family="Segoe UI, Arial" font-size="24">' + esc2(agent) + '</text>'
        '<text x="360" y="410" fill="#8fa3bd" font-family="Segoe UI, Arial" font-size="15">Datum</text>'
        '<text x="360" y="440" fill="#eaf2fb" font-family="Segoe UI, Arial" font-size="24">' + date + '</text>'
        '<text x="640" y="410" fill="#8fa3bd" font-family="Segoe UI, Arial" font-size="15">Povezano naučeno</text>'
        '<text x="640" y="440" fill="#eaf2fb" font-family="Segoe UI, Arial" font-size="24">' + str(neighbor_done) + ' / ' + str(neighbor_total) + '</text>'
        '<text x="60" y="520" fill="#6b7f98" font-family="Segoe UI, Arial" font-size="13">Serijski broj: ' + serial + ' · generisano automatski iz GAMA brain memorije</text>'
        '<text x="60" y="548" fill="#6b7f98" font-family="Segoe UI, Arial" font-size="13">gamatrade.ba · GAMA Learn v0.3</text>'
        '<circle cx="880" cy="520" r="46" fill="none" stroke="#46d38b" stroke-width="2"/>'
        '<text x="880" y="527" fill="#46d38b" font-family="Segoe UI, Arial" font-size="16" text-anchor="middle">NAUČENO</text>'
        '</svg>'
    )
    return svg, None


def _source_by_ref(ref):
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            items = json.load(f).get("sources", [])
    except (OSError, ValueError):
        items = []
    sid = ref.split(":", 1)[1] if ":" in ref else ref
    for src in items:
        if str(src.get("id")) == sid:
            return src
    return None


def _source_text(src):
    return ("# " + str(src.get("label") or src.get("id")) + "\n\n" +
            str(src.get("sub") or "") + "\n\n" +
            "URL: " + str(src.get("url") or "") + "\n\n" +
            "U GAMA Learn: " + str(src.get("built") or "") + "\n")


def lesson_text(ref):
    if not ref:
        return "", ""
    if ref.startswith("src:"):
        src = _source_by_ref(ref)
        return (_source_text(src) if src else ""), ref
    if ref.startswith("brain:ref:"):
        data = brain_get("/read?ref=" + urllib.parse.quote(ref[10:]), timeout=20)
        return _facts_to_text(data) or "", ref
    if ref.startswith("brain:"):
        data = brain_get("/read?id=" + urllib.parse.quote(ref[6:]), timeout=20)
        return _facts_to_text(data) or "", ref
    p = safe_local(ref)
    if not p or not os.path.isfile(p):
        return "", ref
    return _read_text(p, 60000), ref


def safe_local(ref):
    """Dozvoli citanje samo iz MEM_DIR / SKILL_DIR."""
    for root in (MEM_DIR, SKILL_DIR):
        p = os.path.realpath(os.path.join(root, ref))
        if p == os.path.realpath(root) or p.startswith(os.path.realpath(root) + os.sep):
            return p
    return None


_BENCH_LOCK = threading.Lock()
_BENCH_LOG = "/tmp/gama_bench.log"


def _bench_read(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _bench_write(path, obj):
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def bench_status():
    st = _bench_read(BENCH_STATUS_FILE, {"running": False})
    if st.get("running") and st.get("pid"):
        try:
            os.kill(int(st["pid"]), 0)
        except OSError:
            st.update({"running": False, "err": "process ended", "finished": int(time.time())})
            _bench_write(BENCH_STATUS_FILE, st)
    return st


def bench_history():
    h = _bench_read(BENCH_HISTORY_FILE, [])
    return h if isinstance(h, list) else []


def _bench_wait(proc, k, only, started, outpath):
    rc = proc.wait()
    bench = _bench_read(outpath, {}) or {}
    summary = bench.get("summary")
    err = ""
    if rc != 0 and not summary:
        try:
            with open(_BENCH_LOG, "r", encoding="utf-8", errors="replace") as f:
                err = f.read()[-800:]
        except OSError:
            err = "rc=%s" % rc
    st = {"running": False, "started": started, "finished": int(time.time()),
          "k": k, "only": only, "rc": rc, "summary": summary, "err": err}
    _bench_write(BENCH_STATUS_FILE, st)
    if summary:
        hist = bench_history()
        hist.append({"ts": int(time.time()), "k": k, "only": only, "summary": summary})
        _bench_write(BENCH_HISTORY_FILE, hist[-20:])


def bench_start(k=2, only=""):
    try:
        k = max(1, min(5, int(k)))
    except (TypeError, ValueError):
        k = 2
    names = [x for x in re.split(r"[,\s]+", only or "") if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", x)]
    if (only or "").strip() and not names:
        return {"ok": False, "err": "invalid only filter"}
    only = ",".join(names)
    with _BENCH_LOCK:
        st = bench_status()
        if st.get("running"):
            return {"ok": False, "err": "benchmark already running", "status": st}
        script = os.path.join(HERE, "bench20.py")
        if not os.path.isfile(script):
            return {"ok": False, "err": "bench20.py missing"}
        cmd = [sys.executable, script, "--k", str(k)]
        outpath = BENCH_FILE if not only else os.path.join(STATE_DIR, "bench20_only.json")
        cmd += ["--out", outpath]
        if only:
            cmd += ["--only", only]
        started = int(time.time())
        logf = open(_BENCH_LOG, "ab")
        proc = subprocess.Popen(cmd, cwd=HERE, stdout=logf, stderr=subprocess.STDOUT)
        logf.close()
        st = {"running": True, "started": started, "pid": proc.pid,
              "k": k, "only": only, "out": outpath, "summary": None, "err": ""}
        _bench_write(BENCH_STATUS_FILE, st)
        threading.Thread(target=_bench_wait, args=(proc, k, only, started, outpath), daemon=True).start()
        return {"ok": True, "started": True, "status": st}


class Handler(BaseHTTPRequestHandler):
    server_version = "GAMALearn/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[learn] " + (fmt % args) + "\n")

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        raw = body.encode("utf-8", "replace") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(raw)
        except BrokenPipeError:
            pass

    def _static(self, path):
        files = {"/": "index.html", "/index.html": "index.html",
                 "/app.js": "app.js", "/style.css": "style.css",
                 "/manifest.webmanifest": "manifest.webmanifest",
                 "/sw.js": "sw.js",
                 "/icons/icon-192.png": "icons/icon-192.png",
                 "/icons/icon-512.png": "icons/icon-512.png"}
        fn = files.get(path)
        if not fn:
            return self._send(404, {"ok": False, "err": "not found"})
        p = os.path.join(HERE, fn)
        ext = fn.split(".")[-1]
        ctype = {"html": "text/html; charset=utf-8",
                 "js": "application/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8",
                 "webmanifest": "application/manifest+json; charset=utf-8",
                 "png": "image/png"}.get(ext, "application/octet-stream")
        try:
            if ext == "png":
                with open(p, "rb") as f:
                    self._send(200, f.read(), ctype)
            else:
                with open(p, "r", encoding="utf-8") as f:
                    self._send(200, f.read(), ctype)
        except OSError:
            self._send(404, {"ok": False, "err": "missing " + fn})

    def _auth_info(self, q, method):
        supplied = self.headers.get("X-Learn-Token") or (q.get("token", [""])[0] if q else "")
        toks = load_tokens()
        if toks:
            info = toks.get(supplied)
            if not isinstance(info, dict):
                return False, {}, "token required"
            role = str(info.get("role") or "read")
            if method != "GET" and role == "read":
                return False, info, "read-only"
            return True, {"agent": str(info.get("agent") or ""), "role": role,
                          "mode": "tokens"}, ""
        if not TOKEN:
            return True, {"agent": "", "role": "admin", "mode": "open"}, ""
        if supplied == TOKEN:
            return True, {"agent": "", "role": "admin", "mode": "legacy"}, ""
        return False, {}, "token required"

    def _deny(self, code=401, err="token required"):
        self._send(code, {"ok": False, "err": err, "auth": err})

    def load_bench(self):
        out = {"ok": True, "bench20": None, "bench_skills": None}
        for key, path in (("bench20", BENCH_FILE), ("bench20_k2", BENCH_K2_FILE),
                          ("bench20_k3", BENCH_K3_FILE),
                          ("bench_skills", BENCH_SKILLS_FILE)):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    out[key] = json.load(f)
            except (OSError, ValueError):
                out[key] = None
        out["status"] = bench_status()
        out["history"] = bench_history()[-10:]
        return out

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path.startswith("/audio/"):
            fn = os.path.basename(u.path)
            p = os.path.join(STATE_DIR, "audio", fn)
            if not os.path.isfile(p):
                return self._send(404, {"ok": False, "err": "nema audio fajla"})
            with open(p, "rb") as f:
                return self._send(200, f.read(), "audio/mpeg")
        if not u.path.startswith("/api/"):
            return self._static(u.path)
        if not rate_check(self.client_address[0], False)[0]:
            return self._send(429, {"ok": False, "err": "rate limit"},
                              extra={"Retry-After": "60"})
        ok, info, aerr = self._auth_info(q, "GET")
        if not ok:
            return self._deny(401 if aerr == "token required" else 403, aerr)

        if u.path == "/api/auth":
            return self._send(200, {"ok": True, "auth": info})

        if u.path == "/api/tokens":
            if info.get("role") != "admin":
                return self._send(403, {"ok": False, "err": "admin required"})
            toks = load_tokens()
            items = [{"id": token_id(t), "agent": str(v.get("agent") or ""),
                      "role": str(v.get("role") or "read"), "created": v.get("created") or 0,
                      "token": "…" + t[-4:]} for t, v in toks.items()]
            return self._send(200, {"ok": True, "count": len(items), "items": items})

        if u.path == "/api/alerts":
            agent = (q.get("agent", ["opencode"])[0] or "opencode")[:40]
            return self._send(200, alerts(agent))

        if u.path == "/api/fleet":
            return self._send(200, fleet_report(force=(q.get("refresh", ["0"])[0] == "1")))

        if u.path == "/api/review":
            agent = (q.get("agent", ["opencode"])[0] or "opencode")[:40]
            return self._send(200, review_due(agent))

        if u.path == "/api/audit":
            if info.get("role") != "admin":
                return self._send(403, {"ok": False, "err": "admin required"})
            try:
                limit = max(1, min(200, int(q.get("limit", ["50"])[0] or 50)))
            except ValueError:
                limit = 50
            items = audit_tail(limit)
            return self._send(200, {"ok": True, "count": len(items), "items": items})

        if u.path == "/api/version":
            fp = fingerprint()
            g = _cache["graph"]
            return self._send(200, {"ok": True, "fp": fp,
                                    "built": (g or {}).get("stats", {}).get("built", 0),
                                    "nodes": len((g or {}).get("nodes", [])),
                                    "stream": STREAM_URL,
                                    "stale": bool(g and _cache["fp"] != fp)})

        if u.path == "/api/graph":
            return self._send(200, build_graph())

        if u.path == "/api/powers":
            try:
                with open(POWERS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                items = data.get("items", [])
                counts = {}
                for it in items:
                    c = it.get("kategorija") or "ostalo"
                    counts[c] = counts.get(c, 0) + 1
                return self._send(200, {"ok": True, "updated": data.get("updated", ""),
                                        "count": len(items), "counts": counts, "items": items})
            except (OSError, ValueError) as e:
                return self._send(200, {"ok": False, "err": str(e)[:160], "items": []})

        if u.path == "/api/sources":
            try:
                with open(SOURCES_FILE, "r", encoding="utf-8") as f:
                    return self._send(200, {"ok": True, "sources": json.load(f).get("sources", [])})
            except (OSError, ValueError) as e:
                return self._send(200, {"ok": False, "err": str(e)[:160], "sources": []})

        if u.path == "/api/research":
            query = (q.get("q", [""])[0] or "").strip()
            if not query:
                return self._send(400, {"ok": False, "err": "q required"})
            try:
                n = max(3, min(15, int(q.get("n", ["8"])[0] or 8)))
            except ValueError:
                n = 8
            try:
                return self._send(200, research(query, n))
            except Exception as e:
                return self._send(200, {"ok": False, "err": "izvor nedostupan: %s" % str(e)[:160],
                                        "q": query, "items": []})

        if u.path == "/api/study":
            ref = (q.get("ref", [""])[0] or "")
            text, _ = lesson_text(ref)
            if not text.strip():
                return self._send(404, {"ok": False, "err": "nema teksta za taj čvor"})
            m = re.search(r"^#\s+(.+)$", text, re.M)
            title = (m.group(1) if m else ref) or "lekcija"
            return self._send(200, study_kit(text, title.strip()[:120], ref))

        if u.path == "/api/tts":
            ref = (q.get("ref", [""])[0] or "")
            voice = (q.get("voice", ["bs-BA-VesnaNeural"])[0] or "bs-BA-VesnaNeural")[:60]
            text = (q.get("text", [""])[0] or "").strip()
            if not text:
                body, _ = lesson_text(ref)
                if not body.strip():
                    return self._send(404, {"ok": False, "err": "nema teksta"})
                m = re.search(r"^#\s+(.+)$", body, re.M)
                title = (m.group(1) if m else "lekcija").strip()
                text = title + ". " + body[:3000]
            else:
                title = "tekst"
            text = text[:3500]
            return self._send(200, _tts(text, voice, re.sub(r"[^A-Za-z0-9]+", "-", title)[:40]))

        if u.path == "/api/certificate":
            agent = (q.get("agent", ["opencode"])[0] or "opencode")[:40]
            node = (q.get("node", [""])[0] or "").strip()
            if not node:
                return self._send(400, {"ok": False, "err": "node required"})
            svg, err = certificate_svg(agent, node)
            if err:
                return self._send(404, {"ok": False, "err": err})
            fn = "sertifikat-" + re.sub(r"[^A-Za-z0-9_-]+", "-", agent + "-" + node.split(":")[-1])[:60] + ".svg"
            return self._send(200, svg, "image/svg+xml; charset=utf-8",
                              {"Content-Disposition": 'inline; filename="%s"' % fn})

        if u.path == "/api/next":
            agent = (q.get("agent", ["opencode"])[0] or "opencode")[:40]
            focus = (q.get("focus", [""])[0] or "").strip()
            return self._send(200, pick_next(agent, focus or None))

        if u.path == "/api/fixes":
            return self._send(200, _bench_read(FIXES_FILE, {"ok": True, "items": [], "count": 0}))

        if u.path == "/api/sentinel":
            return self._send(200, _bench_read(SENTINEL_FILE, {"ok": False, "err": "not built"}))

        if u.path == "/api/live":
            try:
                limit = max(1, min(500, int(q.get("limit", ["100"])[0] or 100)))
            except ValueError:
                limit = 100
            needle = (q.get("artifact", [""])[0] or "").strip()
            event = (q.get("event", [""])[0] or "").strip()
            try:
                with open(LIVE_FILE, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()[-2000:]
            except OSError:
                lines = []
            events = []
            for line in lines:
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if needle and needle not in str(x.get("artifact", "")):
                    continue
                if event and x.get("event") != event:
                    continue
                events.append(x)
            return self._send(200, {"ok": True, "total": len(events), "events": events[-limit:]})

        if u.path == "/api/artifacts":
            d = _bench_read(ARTIFACTS_FILE, {}) or {}
            kind = (q.get("kind", [""])[0] or "").strip()
            status = (q.get("status", [""])[0] or "").strip()
            needle = (q.get("q", [""])[0] or "").strip().lower()
            try:
                limit = max(1, min(500, int(q.get("limit", ["100"])[0] or 100)))
            except ValueError:
                limit = 100
            items = []
            for x in d.get("items") or []:
                if kind and x.get("kind") != kind:
                    continue
                if status and x.get("status") != status:
                    continue
                if needle and needle not in (str(x.get("id", "")) + " " +
                                             str(x.get("name", "")) + " " +
                                             str(x.get("desc", ""))).lower():
                    continue
                items.append(x)
            return self._send(200, {"ok": True, "ts": d.get("ts"), "host": d.get("host"),
                                    "counts": d.get("counts") or {},
                                    "total": len(items), "items": items[:limit]})

        if u.path == "/api/bench":
            return self._send(200, self.load_bench())

        if u.path == "/api/digest":
            agent = (q.get("agent", ["opencode"])[0] or "opencode")[:40]
            return self._send(200, digest(agent))

        if u.path == "/api/eval/batch":
            start = (q.get("start", ["0"])[0] or "0").lower() in ("1", "true", "yes")
            try:
                n = int(q.get("n", ["10"])[0] or 10)
            except ValueError:
                n = 10
            try:
                k = int(q.get("k", ["2"])[0] or 2)
            except ValueError:
                k = 2
            if start:
                return self._send(200, batch_start(n, k))
            return self._send(200, {"ok": True, "status": batch_status()})

        if u.path == "/api/eval/tools":
            run = (q.get("run", ["1"])[0] or "1").lower() not in ("0", "false", "no")
            return self._send(200, tool_eval(run))

        if u.path == "/api/eval/bulk":
            norm = (q.get("normalize", ["0"])[0] or "0").lower() not in ("0", "false", "no")
            return self._send(200, bulk_verify(norm))

        if u.path == "/api/eval/llm":
            name = (q.get("skill", [""])[0] or "").strip()
            try:
                k = int(q.get("k", ["3"])[0] or 3)
            except ValueError:
                k = 3
            judge = (q.get("judge", ["1"])[0] or "1").lower() not in ("0", "false", "no")
            return self._send(200, llm_eval_skill(name, k, judge))

        if u.path == "/api/eval":
            name = (q.get("skill", [""])[0] or "").strip()
            return self._send(200, eval_skill(name))

        if u.path == "/api/curriculum":
            skill = (q.get("skill", [""])[0] or "").strip()
            if skill:
                return self._send(200, skill_curriculum(skill))
            agent = (q.get("agent", ["opencode"])[0] or "opencode")[:40]
            try:
                n = max(1, min(12, int(q.get("n", ["6"])[0] or 6)))
            except ValueError:
                n = 6
            focus = (q.get("focus", [""])[0] or "").strip()
            return self._send(200, pick_curriculum(agent, n, focus or None))

        if u.path == "/api/health":
            return self._send(200, health_report(force=(q.get("refresh", [""])[0] == "1")))

        if u.path == "/api/catalog":
            qq = (q.get("q", [""])[0] or "").strip().lower()
            dom = (q.get("domain", [""])[0] or "").strip()
            status = (q.get("status", [""])[0] or "").strip()
            kind = (q.get("kind", [""])[0] or "").strip()
            inst = (q.get("installed", [""])[0] or "").strip()
            try:
                limit = max(1, min(200, int(q.get("limit", ["50"])[0] or 50)))
            except ValueError:
                limit = 50
            try:
                offset = max(0, int(q.get("offset", ["0"])[0] or 0))
            except ValueError:
                offset = 0
            data = load_catalog(force=(q.get("refresh", [""])[0] == "1"))
            if not data.get("ok"):
                return self._send(200, data)
            items = []
            for it in data["items"]:
                if kind and it["kind"] != kind:
                    continue
                if dom and it["domain"] != dom:
                    continue
                if status and it["status"] != status:
                    continue
                if inst == "1" and not it["installed"]:
                    continue
                if inst == "0" and it["installed"]:
                    continue
                if qq and qq not in (it["name"] + " " + it["description"] + " " + it["trigger"] + " " + it["domain"]).lower():
                    continue
                items.append(it)
            return self._send(200, {"ok": True, "stats": data["stats"], "total": len(items),
                                    "offset": offset, "limit": limit,
                                    "items": items[offset:offset + limit]})

        if u.path == "/api/search":
            query = (q.get("q", [""])[0] or "").strip()
            k = int(q.get("k", ["8"])[0] or 8)
            k = max(1, min(30, k))
            if not query:
                return self._send(200, {"ok": True, "hits": []})
            fi = full_index()
            local = []
            low = query.lower()
            toks = [t for t in re.split(r"\s+", low) if t]
            for it in fi["items"]:
                label = it["label"].lower()
                hay = it["_hay"]
                if low in hay:
                    score = 1.0 if low in label else 0.7
                elif toks and all(t in hay for t in toks):
                    score = 0.8 if all(t in label for t in toks) else 0.55
                else:
                    continue
                local.append({"id": it["id"], "label": it["label"], "kind": it["kind"],
                              "ref": it["ref"], "score": score})
            local.sort(key=lambda x: -x["score"])
            brain = brain_get("/search?q=%s&k=%d" % (urllib.parse.quote(query), k), timeout=6)
            hits = brain.get("hits", []) if brain.get("ok") else []
            return self._send(200, {"ok": True, "local": local[:k], "brain": hits,
                                    "brain_ok": bool(brain.get("ok")),
                                    "index": fi["stats"], "matches": len(local)})

        if u.path == "/api/lesson":
            ref = q.get("ref", [""])[0]
            if not ref:
                return self._send(400, {"ok": False, "err": "ref required"})
            if ref.startswith("brain:ref:"):
                data = brain_get("/read?ref=" + urllib.parse.quote(ref[10:]), timeout=20)
                text = _facts_to_text(data)
                if text is None:
                    return self._send(200, {"ok": False, "err": "brain raw nije parsiran",
                                            "raw": str(data.get("raw") or "")[:3000]})
                return self._send(200, {"ok": True, "text": text})
            if ref.startswith("brain:"):
                data = brain_get("/read?id=" + urllib.parse.quote(ref[6:]), timeout=20)
                text = _facts_to_text(data)
                if text is None:
                    return self._send(200, {"ok": False, "err": "brain bez teksta",
                                            "raw": json.dumps(data, ensure_ascii=False)[:3000]})
                return self._send(200, {"ok": True, "text": text})
            if ref.startswith("src:"):
                src = _source_by_ref(ref)
                if not src:
                    return self._send(404, {"ok": False, "err": "nepoznat izvor"})
                return self._send(200, {"ok": True, "ref": ref, "text": _source_text(src),
                                        "url": src.get("url") or "", "kind": "web"})
            p = safe_local(ref)
            if not p or not os.path.isfile(p):
                return self._send(404, {"ok": False, "err": "nema fajla"})
            text = _read_text(p, 60000)
            return self._send(200, {"ok": True, "ref": ref, "text": text,
                                    "path": p, "bytes": len(text)})

        if u.path == "/api/learned":
            agent = q.get("agent", ["opencode"])[0] or "opencode"
            data = load_learned()
            nodes = data.get("agents", {}).get(agent, {}).get("nodes", {})
            return self._send(200, {"ok": True, "agent": agent, "nodes": nodes,
                                    "count": len(nodes)})

        return self._send(404, {"ok": False, "err": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if not rate_check(self.client_address[0], True)[0]:
            return self._send(429, {"ok": False, "err": "rate limit"},
                              extra={"Retry-After": "60"})
        ok, info, aerr = self._auth_info(urllib.parse.parse_qs(u.query), "POST")
        if not ok:
            return self._deny(401 if aerr == "token required" else 403, aerr)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            return self._send(400, {"ok": False, "err": "bad json"})

        if u.path in ("/api/fix/propose", "/api/fix/approve", "/api/fix/apply"):
            if info.get("role") != "admin":
                return self._deny(403, "admin required")
            skill = str(body.get("skill") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", skill):
                return self._send(400, {"ok": False, "err": "invalid skill"})
            action = u.path.rsplit("/", 1)[1]
            if action == "apply" and not body.get("yes"):
                return self._send(400, {"ok": False, "err": "apply requires yes=true"})
            args = [sys.executable, os.path.join(HERE, "skillfix.py"), action, skill]
            if action == "apply":
                args.append("--yes")
            p = subprocess.run(args, cwd=HERE, capture_output=True, text=True, timeout=180)
            return self._send(200, {"ok": p.returncode == 0,
                                    "out": (p.stdout or "")[-2000:],
                                    "err": (p.stderr or "")[-800:]})

        if u.path == "/api/fix/rollback":
            if info.get("role") != "admin":
                return self._deny(403, "admin required")
            skill = str(body.get("skill") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", skill):
                return self._send(400, {"ok": False, "err": "invalid skill"})
            bdir = os.path.join(STATE_DIR, "fixes", "backups")
            try:
                files = [f for f in os.listdir(bdir)
                         if f.startswith(skill + ".") and f.endswith(".SKILL.md")]
            except OSError:
                files = []
            if not files:
                return self._send(404, {"ok": False, "err": "backup not found"})
            src = os.path.join(bdir, sorted(files)[-1])
            targets = [os.path.join(SKILL_DIR, skill, "SKILL.md"),
                       os.path.join(SKILL_LIB, skill, "SKILL.md")]
            dst = next((p for p in targets if os.path.isfile(p)), "")
            if not dst:
                return self._send(404, {"ok": False, "err": "skill not found"})
            with open(src, "rb") as f:
                data = f.read()
            backup = os.path.join(bdir, "%s.%d.pre_rollback.SKILL.md" % (skill, int(time.time())))
            with open(dst, "rb") as f:
                cur = f.read()
            with open(backup, "wb") as f:
                f.write(cur)
            with open(dst, "wb") as f:
                f.write(data)
            return self._send(200, {"ok": True, "skill": skill, "restored": src,
                                    "backup_before_rollback": backup})

        if u.path == "/api/sentinel/run":
            if info.get("role") != "admin":
                return self._deny(403, "admin required")
            p = subprocess.run([sys.executable, os.path.join(HERE, "sentinel.py")],
                               cwd=HERE, capture_output=True, text=True, timeout=90)
            return self._send(200, {"ok": p.returncode == 0,
                                    "out": (p.stdout or "")[-1000:],
                                    "err": (p.stderr or "")[-500:]})

        if u.path == "/api/artifacts/scan":
            if info.get("role") != "admin":
                return self._deny(403, "admin required")
            p = subprocess.run([sys.executable, os.path.join(HERE, "artifacts.py"), "build"],
                               cwd=HERE, capture_output=True, text=True, timeout=60)
            return self._send(200, {"ok": p.returncode == 0,
                                    "out": (p.stdout or "")[-1000:],
                                    "err": (p.stderr or "")[-500:]})

        if u.path == "/api/bench":
            if info.get("role") != "admin":
                return self._deny(403, "admin required")
            try:
                k = int(body.get("k") or 2)
            except (TypeError, ValueError):
                k = 2
            only = str(body.get("only") or "")
            return self._send(200, bench_start(k, only))

        if u.path == "/api/review":
            agent = str(body.get("agent") or "opencode")[:40]
            if info.get("agent") and info.get("role") != "admin":
                agent = info["agent"]
            node = str(body.get("node") or "")
            if not node:
                return self._send(400, {"ok": False, "err": "node required"})
            return self._send(200, review_apply(agent, node, str(body.get("result") or "fail")))

        if u.path == "/api/learned":
            agent = str(body.get("agent") or "opencode")[:40]
            if info.get("agent") and info.get("role") != "admin":
                agent = info["agent"]
            node = str(body.get("node") or "")
            learned = bool(body.get("learned"))
            if not node:
                return self._send(400, {"ok": False, "err": "node required"})
            data = load_learned()
            agents = data.setdefault("agents", {})
            a = agents.setdefault(agent, {"nodes": {}})
            out = {}
            if learned:
                label = str(body.get("label") or "")[:120]
                ref = str(body.get("ref") or "")[:400]
                kind = str(body.get("kind") or "")
                ev = {"ts": int(time.time()), "label": label, "ref": ref, "kind": kind}
                if kind == "skill" or node.startswith("skill:") or ref.endswith("SKILL.md"):
                    if node.startswith("skill:"):
                        name = node[6:]
                    elif ref.endswith("SKILL.md"):
                        name = os.path.basename(os.path.dirname(ref))
                    else:
                        name = node
                    cr = challenge_result(name)
                    ev.update({"skill": name, "challenge_id": cr.get("id") or "",
                               "challenge": cr.get("status") or "",
                               "challenge_evidence": cr.get("evidence") or ""})
                    fact = ("[learned] agent=%s skill=%s challenge=%s evidence=%s ref=%s ts=%s"
                            % (agent, name, cr.get("status") or "nema",
                               (cr.get("evidence") or "")[:200], ref,
                               time.strftime("%Y-%m-%d %H:%M:%S")))
                else:
                    fact = ("[learned] agent=%s node=%s kind=%s ref=%s ts=%s"
                            % (agent, node, kind or "?", ref,
                               time.strftime("%Y-%m-%d %H:%M:%S")))
                out = brain_post("/write", {"kind": "lesson", "topic": "gama-learn", "fact": fact})
                ev["brain"] = bool(out.get("ok"))
                a["nodes"][node] = ev
            else:
                a["nodes"].pop(node, None)
            save_learned(data)
            try:
                rv = load_review()
                an = rv.setdefault("agents", {}).setdefault(agent, {"nodes": {}})
                if learned:
                    if node not in an["nodes"]:
                        an["nodes"][node] = {"interval": 0, "ease": 2.5, "reps": 0,
                                             "lapses": 0, "due": int(time.time()),
                                             "last": 0, "fp": _file_fp(ref) if ref else "",
                                             "history": []}
                else:
                    an["nodes"].pop(node, None)
                save_review(rv)
            except OSError:
                pass
            resp = {"ok": True, "agent": agent, "count": len(a["nodes"])}
            if learned:
                resp["evidence"] = a["nodes"][node]
                resp["brain"] = out
            audit_log("learned", {"agent": agent, "node": node, "learned": learned},
                      self.client_address[0])
            return self._send(200, resp)

        if u.path == "/api/tokens":
            if info.get("role") != "admin":
                return self._send(403, {"ok": False, "err": "admin required"})
            action = str(body.get("action") or "")
            toks = load_tokens()
            if action == "add":
                tok = str(body.get("token") or "").strip() or secrets.token_hex(12)
                if tok in toks:
                    return self._send(400, {"ok": False, "err": "token postoji"})
                role = str(body.get("role") or "read")
                if role not in ("read", "write", "admin"):
                    role = "read"
                agent = str(body.get("agent") or "agent")[:40]
                toks[tok] = {"agent": agent, "role": role, "created": int(time.time())}
                save_tokens(toks)
                audit_log("token_add", {"agent": agent, "role": role, "id": token_id(tok)},
                          self.client_address[0])
                return self._send(200, {"ok": True, "action": "add", "token": tok,
                                        "id": token_id(tok), "agent": agent, "role": role})
            if action == "remove":
                rid = str(body.get("id") or "")
                tok = str(body.get("token") or "")
                hit = ""
                for t in list(toks):
                    if (tok and t == tok) or (rid and token_id(t) == rid):
                        hit = t
                        break
                if not hit:
                    return self._send(404, {"ok": False, "err": "token nije nadjen"})
                toks.pop(hit, None)
                save_tokens(toks)
                audit_log("token_remove", {"id": token_id(hit)}, self.client_address[0])
                return self._send(200, {"ok": True, "action": "remove", "id": token_id(hit)})
            return self._send(400, {"ok": False, "err": "action add|remove"})

        if u.path == "/api/note":
            agent = str(body.get("agent") or "opencode")[:40]
            if info.get("agent") and info.get("role") != "admin":
                agent = info["agent"]
            node = str(body.get("node") or "")
            text = str(body.get("text") or "").strip()
            if not node or not text:
                return self._send(400, {"ok": False, "err": "node i text required"})
            topic = node.replace(":", "-")
            fact = "[learn][%s] %s" % (agent, text)
            out = brain_post("/write", {"kind": "lesson", "topic": topic, "fact": fact})
            audit_log("note", {"agent": agent, "node": node, "chars": len(text)},
                      self.client_address[0])
            return self._send(200, out)

        return self._send(404, {"ok": False, "err": "not found"})


def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def main():
    port = PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    host = os.environ.get("GAMA_LEARN_HOST") or "127.0.0.1"
    if "--host" in sys.argv:
        host = sys.argv[sys.argv.index("--host") + 1]
    os.makedirs(STATE_DIR, exist_ok=True)
    srv = ThreadingHTTPServer((host, port), Handler)
    print("GAMA Learn na http://%s:%d  (brain=%s)" % (host, port, BRAIN), flush=True)
    if host in ("0.0.0.0", "::"):
        for ip in lan_ips():
            print("  LAN: http://%s:%d%s" % (ip, port, "  (token!)" if TOKEN else ""), flush=True)
    if TOKEN:
        print("  token zastita ukljucena (X-Learn-Token / ?token=)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
