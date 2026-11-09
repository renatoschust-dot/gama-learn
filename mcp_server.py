#!/usr/bin/env python3
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = (os.environ.get("GAMA_LEARN_API") or "http://100.106.202.123:8078").rstrip("/")
TOKEN = os.environ.get("GAMA_LEARN_TOKEN") or ""


def api(path, timeout=20):
    url = BASE + path
    headers = {}
    if TOKEN:
        url += ("&" if "?" in url else "?") + "token=" + urllib.parse.quote(TOKEN)
        headers["X-Learn-Token"] = TOKEN
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            return {"ok": True, "data": json.loads(r.read().decode("utf-8", "replace"))}
    except Exception as e:
        return {"ok": False, "err": str(e)[:200]}


def api_post(path, body, timeout=20):
    url = BASE + path
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-Learn-Token"] = TOKEN
    data = json.dumps(body or {}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "data": json.loads(r.read().decode("utf-8", "replace"))}
    except Exception as e:
        return {"ok": False, "err": str(e)[:200]}


def tool_search(args):
    q = urllib.parse.quote(str(args.get("q") or ""))
    k = max(1, min(20, int(args.get("k") or 8)))
    return api("/api/search?q=%s&k=%d" % (q, k))


def tool_lesson(args):
    ref = str(args.get("ref") or "")
    if not ref:
        return {"ok": False, "err": "ref required"}
    return api("/api/lesson?ref=" + urllib.parse.quote(ref))


def tool_catalog(args):
    q = urllib.parse.quote(str(args.get("q") or ""))
    kind = urllib.parse.quote(str(args.get("kind") or ""))
    limit = max(1, min(50, int(args.get("limit") or 10)))
    return api("/api/catalog?q=%s&kind=%s&limit=%d" % (q, kind, limit))


def tool_status(args):
    q = urllib.parse.quote(str(args.get("skill") or ""))
    return api("/api/catalog?q=%s&kind=skill&limit=5" % q)


def tool_review(args):
    agent = urllib.parse.quote(str(args.get("agent") or "opencode"))
    return api("/api/review?agent=" + agent)


def tool_health(args):
    return api("/api/health")


def tool_bench(args):
    if args.get("run"):
        try:
            k = max(1, min(5, int(args.get("k") or 2)))
        except (TypeError, ValueError):
            k = 2
        return api_post("/api/bench", {"k": k, "only": str(args.get("only") or "")})
    return api("/api/bench")


def tool_artifacts(args):
    q = urllib.parse.quote(str(args.get("q") or ""))
    kind = urllib.parse.quote(str(args.get("kind") or ""))
    status = urllib.parse.quote(str(args.get("status") or ""))
    try:
        limit = max(1, min(500, int(args.get("limit") or 50)))
    except (TypeError, ValueError):
        limit = 50
    return api("/api/artifacts?q=%s&kind=%s&status=%s&limit=%d" % (q, kind, status, limit))


def tool_sentinel(args):
    return api("/api/sentinel")


def tool_live(args):
    try:
        limit = max(1, min(500, int(args.get("limit") or 100)))
    except (TypeError, ValueError):
        limit = 100
    return api("/api/live?limit=%d" % limit)


def tool_fixes(args):
    return api("/api/fixes")


TOOLS = [
    {"name": "learn_search", "description": "Pretrazi GAMA Learn puni korpus (teme + skillovi + brain).",
     "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}, "k": {"type": "integer"}}, "required": ["q"]}},
    {"name": "learn_lesson", "description": "Vrati lekciju/SKILL.md za ref.",
     "inputSchema": {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}},
    {"name": "learn_catalog", "description": "Pretrazi katalog skillova i alata sa statusom i dokazom.",
     "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}, "kind": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "learn_status", "description": "Status i dokaz za jedan skill.",
     "inputSchema": {"type": "object", "properties": {"skill": {"type": "string"}}, "required": ["skill"]}},
    {"name": "learn_review", "description": "Due ponavljanja za agenta.",
     "inputSchema": {"type": "object", "properties": {"agent": {"type": "string"}}}},
    {"name": "learn_health", "description": "GAMA Learn health provjere.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "learn_bench", "description": "20-skill with/without benchmark: čitanje rezultata ili pokretanje (run=true, k=1..5, only=ime,ime).",
     "inputSchema": {"type": "object", "properties": {"run": {"type": "boolean"}, "k": {"type": "integer"}, "only": {"type": "string"}}}},
    {"name": "learn_artifacts", "description": "Inventar artefakata (skill/tool/service) sa statusom i dokazom.",
     "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}, "kind": {"type": "string"}, "status": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "learn_sentinel", "description": "Sentinel summary: probe counts, problemi, zadnji događaji.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "learn_live", "description": "Living log (ok/fail/forgotten/missing/run) sa limitom.",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "learn_fixes", "description": "Lista predloženih/odobrenih/popravljenih skill fix draftova.",
     "inputSchema": {"type": "object", "properties": {}}},
]
MAP = {"learn_search": tool_search, "learn_lesson": tool_lesson, "learn_catalog": tool_catalog,
       "learn_status": tool_status, "learn_review": tool_review, "learn_health": tool_health,
       "learn_bench": tool_bench, "learn_artifacts": tool_artifacts,
       "learn_sentinel": tool_sentinel, "learn_live": tool_live, "learn_fixes": tool_fixes}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" not in msg:
            continue
        method = msg.get("method")
        rid = msg["id"]
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05",
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "gama-learn", "version": "1.0"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            fn = MAP.get(name)
            if not fn:
                print(json.dumps({"jsonrpc": "2.0", "id": rid,
                                  "error": {"code": -32601, "message": "unknown tool"}}))
                continue
            out = fn(params.get("arguments") or {})
            text = json.dumps(out, ensure_ascii=False)
            result = {"content": [{"type": "text", "text": text}],
                      "isError": not bool(out.get("ok"))}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": rid,
                              "error": {"code": -32601, "message": "method not found"}}))
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()