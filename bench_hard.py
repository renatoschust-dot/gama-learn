#!/usr/bin/env python3
"""Hard skill-grounding benchmark (40 tasks / 20 gama skills).

Different from bench20.py: every task forces a concrete command variant
(required tokens), a relevant use-case, and a concrete success check.
Writes state/bench_hard.json only; never touches state/bench20.json.
"""
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server

PREFER = os.environ.get("BENCH_PREFER") or None

BENCH20_FIXED = {"gama-pdv", "gama-sql-vp2026", "gama-ponuda"}


def jget(text):
    s = text or ""
    for m in re.finditer(r"\{", s):
        try:
            obj, _ = json.JSONDecoder().raw_decode(s[m.start():])
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    out = {}
    for key in ("use_case", "command", "check"):
        m = re.search(r'"%s"\s*:\s*"(.+?)"\s*(?:,|\})' % key, s, re.S)
        if m:
            out[key] = m.group(1)
    return out


def skill_text(name):
    for p in (os.path.join(server.SKILL_DIR, name, "SKILL.md"),
              os.environ.get("GAMA_SKILL_LIB", "/root/gama_skills_lib") + "/%s/SKILL.md" % name):
        if os.path.isfile(p):
            return server._read_text(p, 6000)
    return ""


def _norm(s):
    return " ".join(str(s or "").split())


def _clean_cmd(s):
    s = str(s or "").strip().strip("`")
    s = re.sub(r"\s+#.*$", "", s)
    s = re.sub(r"<[^>]*>", "", s)
    return _norm(s).lower()


def _cmd_tokens(s):
    return re.sub(r"[^a-z0-9_./-]+", " ", _clean_cmd(s)).split()


def _grounded_in_text(answer, text):
    at = _cmd_tokens(answer)
    if len(at) < 2:
        return False
    tt = set(_cmd_tokens(text))
    hits = sum(1 for t in set(at) if len(t) >= 4 and t in tt)
    return hits >= 2


def _cmd_match(answer, commands):
    a = _clean_cmd(answer)
    if len(a) < 4:
        return False
    at = a.split()
    for c in commands[:8]:
        c = _clean_cmd(c)
        if not c:
            continue
        for part in [c] + [p.strip() for p in c.split("|")]:
            if len(part) < 4:
                continue
            if part in a or a in part:
                return True
            pt = part.split()
            if len(pt) >= 2 and len(at) >= 2 and pt[:2] == at[:2]:
                if len(pt) >= 3 and pt[:3] == at[:3]:
                    return True
                if len(set(pt) & set(at)) >= max(2, min(len(set(pt)), len(set(at))) // 2):
                    return True
    return False


def _any_in(text, alts):
    t = str(text or "").lower()
    return any(str(a).lower() in t for a in alts)


# 20 skills x 2 tasks. must_cmd = list of groups; every group must match.
# use_terms = list of groups (relevant scenario); every group must match.
# check_terms = at least one concrete evidence word must appear in `check`.
SELECT = [
    {
        "name": "gama-brains",
        "tasks": [
            {"id": "cascade",
             "task": "The preferred CLI brain may be offline. Route a prompt through the "
                     "automatic fallback so the best available brain answers.",
             "must_cmd": [["gama-brains"], ["cascade"]],
             "use_terms": [["fallback", "offline", "auto"], ["mozak", "brain", "model", "llm"]],
             "check_terms": ["answer", "odgovor", "model", "output", "exit", "rc", "fallback"]},
            {"id": "team",
             "task": "Split one goal across 3 brains in parallel and merge their answers.",
             "must_cmd": [["gama-brains"], ["team"], ["-n"]],
             "use_terms": [["paralel", "parallel", "tim", "team", "3"], ["spoj", "merge", "odgovor", "answer"]],
             "check_terms": ["output", "exit", "rc", "merge", "spoj", "3", "answers"]},
        ],
    },
    {
        "name": "gama-find",
        "tasks": [
            {"id": "pdf-limit",
             "task": "On the fleet, find PDF files but return at most 20 hits.",
             "must_cmd": [["gama-find"], ["*.pdf"], ["--limit"]],
             "use_terms": [["pdf"], ["fajl", "file", "pretrag", "search", "fleet", "flot"]],
             "check_terms": ["output", "list", "count", "path", "json", "exit", "rc", "20"]},
            {"id": "xlsx-recent",
             "task": "Find .xlsx files changed in the last 30 days, newest first, machine-readable JSON.",
             "must_cmd": [["gama-find"], [".xlsx"], ["--recent"], ["--sort"], ["json"]],
             "use_terms": [["xlsx", "excel", "tabel"], ["datum", "date", "recent", "30", "json"]],
             "check_terms": ["output", "json", "path", "mtime", "date", "exit", "rc", "list"]},
        ],
    },
    {
        "name": "gama-keyless",
        "tasks": [
            {"id": "ddg",
             "task": "Run a web search with no API key by posting the query to DuckDuckGo's HTML endpoint.",
             "must_cmd": [["curl"], ["duckduckgo"], ["-d"]],
             "use_terms": [["search", "pretrag", "web", "query"], ["keyless", "bez kljuca", "no api key", "free"]],
             "check_terms": ["html", "result", "200", "http", "output", "response", "grep"]},
            {"id": "jina",
             "task": "Read an arbitrary web page as clean text/markdown through the Jina reader proxy.",
             "must_cmd": [["curl"], ["r.jina.ai"]],
             "use_terms": [["read", "extract", "citat", "sadrzaj", "markdown", "page", "sajt"], ["proxy", "jina", "reader"]],
             "check_terms": ["output", "text", "markdown", "200", "http", "content", "sadrzaj"]},
        ],
    },
    {
        "name": "gama-lead",
        "tasks": [
            {"id": "plan-only",
             "task": "Only decompose a big goal into 3 sub-tasks (do not execute them).",
             "must_cmd": [["gama-lead"], ["plan"], ["-n"]],
             "use_terms": [["pod-zadat", "subtask", "plan", "razdvoji", "decompose"], ["3"]],
             "check_terms": ["plan", "subtask", "output", "json", "exit", "rc", "3"]},
            {"id": "run-merge",
             "task": "Plan a goal, assign sub-tasks to different CLI brains, then merge the final answer.",
             "must_cmd": [["gama-lead"], ["run"], ["-n"]],
             "use_terms": [["spoj", "merge", "raspored", "assign", "brain", "mozg"], ["3", "tim", "team"]],
             "check_terms": ["output", "exit", "rc", "merge", "spoj", "answer", "odgovor"]},
        ],
    },
    {
        "name": "gama-openrig",
        "tasks": [
            {"id": "dry-run",
             "task": "Test the OpenRig installer without changing the machine (dry run).",
             "must_cmd": [["curl"], ["openrig"], ["install.sh"], ["dry-run"]],
             "use_terms": [["dry", "test", "sigurn", "prije", "without"], ["install", "instal"]],
             "check_terms": ["dry", "output", "exit", "rc", "no changes", "plan"]},
            {"id": "install-cli",
             "task": "Install the OpenRig CLI globally with npm.",
             "must_cmd": [["npm"], ["install", "i"], ["@openrig/cli"]],
             "use_terms": [["install", "instal"], ["cli", "global"]],
             "check_terms": ["version", "installed", "rc", "exit", "global", "npm", "openrig"]},
        ],
    },
    {
        "name": "gama-selfimprove",
        "tasks": [
            {"id": "list-min",
             "task": "List repeatable successful experiences seen at least 5 times before turning any into skills.",
             "must_cmd": [["gama_learn.py"], ["list"], ["--min"]],
             "use_terms": [["skill", "iskustv", "experience", "case"], ["5", "kandidat", "candidate"]],
             "check_terms": ["5", "count", "list", "output", "json", "exit", "rc"]},
            {"id": "promote-dry",
             "task": "Dry-run promoting candidates with at least 5 occurrences into skills, without writing.",
             "must_cmd": [["gama_learn.py"], ["promote"], ["--min"], ["--dry"]],
             "use_terms": [["promote", "unaprijed", "skill"], ["dry", "without", "bez upisa", "5"]],
             "check_terms": ["dry", "would", "skill", "output", "exit", "rc", "5"]},
        ],
    },
    {
        "name": "gama-tablet",
        "tasks": [
            {"id": "unlock",
             "task": "Check the Android tablet and unlock it with its PIN if it is locked.",
             "must_cmd": [["gama_tablet_agent.py"], ["otkljucaj"]],
             "use_terms": [["zakljucan", "locked", "unlock", "otkljuc"], ["tablet", "android"]],
             "check_terms": ["pin", "screen", "ekran", "status", "output", "locked", "unlocked"]},
            {"id": "open-viber",
             "task": "Open the Viber app on the Android tablet.",
             "must_cmd": [["gama_tablet_agent.py"], ["otvori"], ["viber"]],
             "use_terms": [["app", "aplikacij", "viber"], ["otvori", "open"]],
             "check_terms": ["app", "viber", "screen", "ekran", "output", "opened", "otvoren"]},
        ],
    },
    {
        "name": "gama-ops-toolkit",
        "tasks": [
            {"id": "residential-up",
             "task": "Bring up a residential hand with a home BiH IP for a task and get its CDP URL.",
             "must_cmd": [["gama node up"], ["--task"]],
             "use_terms": [["residen", "home", "kucn", "bih", "ip"], ["cdp", "browser", "ruka", "hand"]],
             "check_terms": ["cdp", "http", "19333", "output", "url", "port", "exit"]},
            {"id": "verify-claim",
             "task": "Prove or refute a claimed exact number against its SQL check before trusting it.",
             "must_cmd": [["gama verify"]],
             "use_terms": [["provjer", "verify", "tvrdnj", "claim"], ["broj", "count", "exact", "sql"]],
             "check_terms": ["pass", "fail", "output", "exact", "match", "result", "rc"]},
        ],
    },
    {
        "name": "gama-dag",
        "tasks": [
            {"id": "levels-real",
             "task": "Branch a supplier-analysis task into levels 2,2,2 and actually execute every branch.",
             "must_cmd": [["gama_dag.py"], ["--levels"], ["2,2,2"], ["--real"]],
             "use_terms": [["gran", "branch", "dag", "paralel", "dobavljac", "supplier"], ["2,2,2", "levels"]],
             "check_terms": ["branch", "gran", "pass", "verify", "output", "json", "exit", "rc"]},
            {"id": "memory-db",
             "task": "After the DAG finishes, persist the findings into the Postgres knowledge base.",
             "must_cmd": [["gama_dag.py"], ["--memory-db"]],
             "use_terms": [["pg", "postgres", "gama_znanje", "memorij", "database", "baza"], ["upis", "write", "persist", "sacuvaj"]],
             "check_terms": ["db", "write", "upis", "rows", "output", "exit", "rc", "insert"]},
        ],
    },
    {
        "name": "gama-media",
        "tasks": [
            {"id": "cloud-sdxl",
             "task": "Generate a photo image at 1024x1024 using the Cloudflare SDXL cloud model explicitly.",
             "must_cmd": [["gama media img"], ["--size"], ["--model"]],
             "use_terms": [["slik", "image", "img", "photo"], ["sdxl", "cloudflare", "cloud", "cf"]],
             "check_terms": ["url", "file", "path", "output", "png", "jpg", "image"]},
            {"id": "strict-local",
             "task": "Try local ComfyUI only and fail with a reason instead of falling back to cloud.",
             "must_cmd": [["gama media img"], ["--local"], ["--strict-local"]],
             "use_terms": [["comfy", "local", "vram"], ["fallback", "strict", "bez fallback", "reason"]],
             "check_terms": ["reason", "fail", "vram", "pid", "output", "error", "exit", "rc"]},
        ],
    },
    {
        "name": "gama-vmlab-lab",
        "tasks": [
            {"id": "runsc-bench",
             "task": "Run the benchmark inside the gVisor (runsc) runtime with the bench directory mounted read-only.",
             "must_cmd": [["docker run"], ["--runtime"], ["runsc"]],
             "use_terms": [["gvisor", "runsc", "sandbox", "izol"], ["bench", "benchmark", "mjer"]],
             "check_terms": ["output", "result", "ms", "ns", "time", "bench", "exit", "rc"]},
            {"id": "compose-validate",
             "task": "Validate the compose file syntax without starting any services or printing YAML.",
             "must_cmd": [["docker compose"], ["config"], ["-q"]],
             "use_terms": [["compose", "valid", "provjer", "syntax"], ["yml", "yaml", "config"]],
             "check_terms": ["exit", "rc", "0", "valid", "config", "no output", "quiet"]},
        ],
    },
    {
        "name": "gama-cli",
        "tasks": [
            {"id": "ask",
             "task": "Get one smart unified answer for a question using the single GAMA entry CLI (not web search).",
             "must_cmd": [["gama ask"]],
             "use_terms": [["pamet", "answer", "odgovor", "unified", "ask"], ["cli", "gama"]],
             "check_terms": ["output", "answer", "response", "text", "exit", "rc"]},
            {"id": "rag",
             "task": "Answer from local knowledge/context in under 300ms with source grounding.",
             "must_cmd": [["gama rag"]],
             "use_terms": [["rag", "lokal", "local", "kontekst", "context"], ["300", "source", "izvor", "ground"]],
             "check_terms": ["ms", "output", "chunk", "source", "izvor", "300", "rc"]},
        ],
    },
    {
        "name": "gama-redroid-grants",
        "tasks": [
            {"id": "start-registration",
             "task": "Start an end-to-end grant registration on the real Android/Redroid device: navigate and fill the form.",
             "must_cmd": [["gama-web-registracija"]],
             "use_terms": [["grant", "registracij", "prijava", "android", "redroid"], ["forma", "form", "navig"]],
             "check_terms": ["screenshot", "captcha", "email", "imap", "step", "output", "proof", "dokaz"]},
            {"id": "proof-otp",
             "task": "After submitting a grant form, capture proof and read the verification code from our IMAP mailbox.",
             "must_cmd": [["gama-web-registracija"]],
             "use_terms": [["captcha", "kod", "code", "otp", "imap", "email"], ["dokaz", "proof", "screenshot"]],
             "check_terms": ["screenshot", "code", "imap", "proof", "dokaz", "saved", "file", "output"]},
        ],
    },
    {
        "name": "gama-ocr-ulaz-robe",
        "tasks": [
            {"id": "pdf-text",
             "task": "OCR a supplier PDF invoice and return its text page by page.",
             "must_cmd": [["gama_ocr.py"], ["pdf"]],
             "use_terms": [["faktur", "invoice", "otpremnic", "pdf"], ["ocr", "tekst", "text"]],
             "check_terms": ["text", "strane", "page", "chars", "output", "content"]},
            {"id": "json-items",
             "task": "OCR a scanned PNG and return machine-readable JSON with the recognized content for goods entry.",
             "must_cmd": [["gama_ocr.py"], ["--json"]],
             "use_terms": [["json", "item", "stavk", "sifra", "kolicin", "cijena"], ["png", "slik", "scan"]],
             "check_terms": ["file", "chars", "text", "json", "output", "items", "stavk"]},
        ],
    },
    {
        "name": "gama-sandbox-srt",
        "tasks": [
            {"id": "run-untrusted",
             "task": "Run an untrusted skill/tool in an isolated offline sandbox (no Docker).",
             "must_cmd": [["gama sandbox"], ["--"]],
             "use_terms": [["nepouzdan", "untrusted", "izol", "offline"], ["skill", "mcp", "kod", "code"]],
             "check_terms": ["exit", "rc", "output", "blocked", "network", "denied", "provjer"]},
            {"id": "install-srt",
             "task": "Install the Anthropic Sandbox Runtime CLI globally with npm.",
             "must_cmd": [["npm"], ["@anthropic-ai/sandbox-runtime"]],
             "use_terms": [["install", "instal"], ["srt", "runtime", "sandbox"]],
             "check_terms": ["version", "installed", "rc", "exit", "global", "npm"]},
        ],
    },
    {
        "name": "gama-formfill",
        "tasks": [
            {"id": "shot-coords",
             "task": "Dump every form element (x, y, text) on the dispatcher screen before filling.",
             "must_cmd": [["formfill.py"], ["--node"], ["--shot"], ["dispecer"]],
             "use_terms": [["element", "koordinat", "x,y", "screen", "ekran"], ["dispecer", "dispatcher"]],
             "check_terms": ["x", "y", "tekst", "text", "elements", "output", "count"]},
            {"id": "click-text",
             "task": "Click the visible button labelled 'Save and continue' on the dispatcher by text.",
             "must_cmd": [["formfill.py"], ["--click"], ["Save and continue"]],
             "use_terms": [["klik", "click", "button", "dugm"], ["form", "forma"]],
             "check_terms": ["screenshot", "dokaz", "clicked", "success", "output", "verify"]},
        ],
    },
    {
        "name": "gama-node",
        "tasks": [
            {"id": "up-linux3",
             "task": "Bring up the linux3 residential node as a hand on port 9333 for task 'aws' and return its CDP endpoint.",
             "must_cmd": [["gama node up"], ["--node"], ["linux3"], ["--port"]],
             "use_terms": [["residen", "home", "ip", "tunel", "tunnel"], ["cdp", "9333", "browser"]],
             "check_terms": ["cdp", "http", "9333", "url", "output", "port"]},
            {"id": "egress-proof",
             "task": "Prove the public egress IP, ASN, UA and timezone through the browser for task 'aws'.",
             "must_cmd": [["gama node egress"], ["--task"]],
             "use_terms": [["ip", "asn", "timezone", "tz", "ua", "egress"], ["dokaz", "proof", "browser"]],
             "check_terms": ["ip", "asn", "tz", "ua", "output", "json"]},
        ],
    },
    {
        "name": "gama-hand",
        "tasks": [
            {"id": "who",
             "task": "List all HC nodes and their OS using the single GAMA hand CLI.",
             "must_cmd": [["gama_hand.py"], ["who"]],
             "use_terms": [["hc", "node", "cvor", "flot"], ["list", "lista", "os"]],
             "check_terms": ["9", "node", "os", "output", "count", "list"]},
            {"id": "find-text",
             "task": "Find a text label on the contabo screen via OCR and return its coordinates.",
             "must_cmd": [["gama_hand.py"], ["find"], ["contabo"]],
             "use_terms": [["ocr", "tekst", "text", "koordinat", "x,y"], ["screen", "ekran", "contabo"]],
             "check_terms": ["x", "y", "coord", "output", "ocr", "found"]},
        ],
    },
    {
        "name": "gama-grantfill",
        "tasks": [
            {"id": "open-slot",
             "task": "Open a grant application URL in browser slot 0 and snapshot the page elements.",
             "must_cmd": [["gama formfill open"], ["--slot"]],
             "use_terms": [["open", "url", "slot", "grant", "forma"], ["snapshot", "elements", "prijava"]],
             "check_terms": ["slot", "url", "snapshot", "elements", "output", "opened"]},
            {"id": "verify-thankyou",
             "task": "Verify that the submitted grant page actually shows the text 'Thank you'.",
             "must_cmd": [["gama formfill verify"], ["--text"]],
             "use_terms": [["verif", "thank", "success", "uspjeh", "submit"], ["text", "tekst", "page", "stranic"]],
             "check_terms": ["pass", "fail", "text", "output", "200", "found", "rc"]},
        ],
    },
    {
        "name": "gama-dind",
        "tasks": [
            {"id": "python-image",
             "task": "Run a short Python one-liner in an ephemeral python:3.12-slim container.",
             "must_cmd": [["gama-run"], ["--image"], ["python:3.12-slim"]],
             "use_terms": [["ephemeral", "kontejner", "container", "python"], ["izol", "sandbox", "one-liner"]],
             "check_terms": ["2", "output", "result", "exit", "rc"]},
            {"id": "resources",
             "task": "Run a heavy job in a container limited to 8 CPUs and 32 GB RAM.",
             "must_cmd": [["gama-run"], ["--cpus"], ["--mem"]],
             "use_terms": [["resource", "resurs", "cpu", "memorij", "heavy"], ["limit", "8", "32"]],
             "check_terms": ["output", "exit", "rc", "hostname", "uname", "memory", "cpu"]},
        ],
    },
]


def _check_names():
    """Validate SELECT against the live catalog + _extract_commands."""
    cat = server.load_catalog()
    installed = {}
    for it in cat.get("items") or []:
        if it.get("kind") == "skill" and it.get("installed"):
            installed[it.get("name") or ""] = it
    picked, missing = [], []
    for spec in SELECT:
        name = spec["name"]
        if name in BENCH20_FIXED:
            missing.append(name + " (bench20 fixed)")
            continue
        it = installed.get(name)
        if not it:
            missing.append(name + " (not installed)")
            continue
        text = skill_text(name)
        cmds = server._extract_commands(text)
        if not cmds:
            missing.append(name + " (no commands)")
            continue
        picked.append({"name": name, "desc": (it.get("description") or "")[:500],
                       "text": text, "commands": cmds, "tasks": spec["tasks"]})
    return picked, missing


def _verify(text, spec, commands, s_text, name, desc):
    d = jget(text)
    cmd = d.get("command") or ""
    use = d.get("use_case") or ""
    chk = d.get("check") or ""
    cn = _clean_cmd(cmd)
    grounded = _cmd_match(cmd, commands) or _grounded_in_text(cmd, s_text)
    token_ok = all(_any_in(cn, alts) for alts in spec["must_cmd"])
    use_ok = all(_any_in(use, alts) for alts in spec["use_terms"])
    chk_norm = _norm(chk)
    check_ok = len(chk_norm) >= 12 and any(t.lower() in chk_norm.lower() for t in spec["check_terms"])
    ok = bool(grounded and token_ok and use_ok and check_ok)
    detail = {"cmd_grounded": grounded, "must_cmd": token_ok,
              "use_case": use_ok, "check": check_ok}
    return ok, detail


def task_prompt(name, desc, task, s_text, with_skill):
    p = ("You are an AI agent taking a HARD skill-grounding benchmark.\n"
         "SKILL: %s\nDESCRIPTION: %s\n" % (name, desc))
    if with_skill:
        p += "SKILL.md EXCERPT:\n%s\n" % s_text[:3500]
    p += ("TASK: %s\n" % task)
    p += ("Return ONLY JSON: {\"use_case\": string, \"command\": string, \"check\": string}. "
          "command MUST be the exact executable command (flags included) copied from SKILL.md; "
          "no placeholders beyond what the skill itself uses. "
          "use_case must state the concrete situation. "
          "check must be a concrete observable proof (output/exit code/HTTP status/file). "
          "Do not dump the skill; answer the TASK.")
    return p


def judge_answer(name, desc, s_text, answer):
    d0 = jget(answer)
    cmd0 = _clean_cmd(d0.get("command"))
    if not cmd0 or len(cmd0.split()) < 2 or cmd0.strip() in (name.lower(), "gama"):
        return {"pass": False, "reason": "command is only skill name or empty"}
    jp = ('Judge the candidate against the skill. Return JSON only: '
          '{"pass": true|false, "reason": "<=160 chars"}.\\n'
          'SKILL: %s - %s\\nEXCERPT: %s\\nCANDIDATE: %s\\n'
          'Pass only if the command is a real executable command grounded in the excerpt, '
          'the use_case is the right situation, and the check is concrete.' %
          (name, (desc or "")[:240], (s_text or "")[:700],
           (answer or "")[:900].replace("\n", " ")))
    r = server.llm_chat([{"role": "user", "content": jp}], max_tokens=120, timeout=30, prefer="fallback")
    if not r.get("ok"):
        r = server.harness_ask(jp, timeout=45)
    p = jget(r.get("say") or "").get("pass")
    if isinstance(p, str):
        p = p.strip().lower() in ("true", "1", "yes")
    return {"pass": p, "reason": str(jget(r.get("say") or "").get("reason") or "")[:160]}


def run_one(prompt, verify, k, judge, name, desc, s_text):
    passes, samples = 0, []
    for _ in range(k):
        r = server.llm_chat([{"role": "user", "content": prompt}], max_tokens=450,
                            timeout=45, prefer=PREFER)
        ans = r.get("say") or ""
        det_ok, det_detail = verify(ans)
        jr = None
        ok = det_ok
        if judge and not det_ok:
            jr = judge_answer(name, desc, s_text, ans)
            if jr.get("pass") is True:
                ok = True
        passes += 1 if ok else 0
        samples.append({"ok": ok, "det": det_ok, "detail": det_detail, "judge": jr,
                        "model": r.get("model"), "answer": ans[:800]})
    return {"pass": passes, "k": k, "rate": round(passes / k, 2), "samples": samples}


def main():
    args = sys.argv[1:]

    def arg(name, default=None):
        if name in args:
            try:
                return args[args.index(name) + 1]
            except IndexError:
                return default
        return default

    try:
        k = max(1, min(5, int(arg("--k", 1))))
    except (TypeError, ValueError):
        k = 1
    try:
        jobs = max(1, min(12, int(arg("--jobs", 6))))
    except (TypeError, ValueError):
        jobs = 6
    out_path = arg("--out", "") or os.path.join(server.STATE_DIR, "bench_hard.json")
    only = {x.strip() for x in (arg("--only", "") or "").split(",") if x.strip()}
    judge = "--judge" in args

    picked, missing = _check_names()
    if missing:
        print("skipped:", ", ".join(missing), flush=True)
    todo = [p for p in picked if not only or p["name"] in only]
    if only and not todo:
        print("no matching skills for --only", flush=True)
        return 2
    if not todo:
        print("no skills selected", flush=True)
        return 2

    out = {"ts": int(time.time()), "k": k, "n_skills": len(todo),
           "n_tasks": sum(len(p["tasks"]) for p in todo), "judge": judge, "items": {}}
    os.makedirs(server.STATE_DIR, exist_ok=True)

    def work(skill):
        name, desc, s_text, cmds = skill["name"], skill["desc"], skill["text"], skill["commands"]
        res = {"cat": "hard", "tasks": []}
        tot = {"without": [0, 0], "with": [0, 0]}
        for spec in skill["tasks"]:
            trow = {"id": spec["id"], "prompt": spec["task"]}
            for cond in ("without", "with"):
                prompt = task_prompt(name, desc, spec["task"], s_text, cond == "with")
                verify = lambda t, s=spec: _verify(t, s, cmds, s_text, name, desc)
                r = run_one(prompt, verify, k, judge, name, desc, s_text)
                trow[cond] = r
                tot[cond][0] += r["pass"]
                tot[cond][1] += r["k"]
            trow["delta"] = round(trow["with"]["rate"] - trow["without"]["rate"], 2)
            res["tasks"].append(trow)
        for cond in ("without", "with"):
            p, n = tot[cond]
            res[cond] = {"pass": p, "k": n, "rate": round(p / n, 2) if n else 0.0}
        res["delta"] = round(res["with"]["rate"] - res["without"]["rate"], 2)
        return name, res

    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(work, p) for p in todo]
        for fut in as_completed(futs):
            name, data = fut.result()
            with lock:
                out["items"][name] = data
                print("%-30s tasks=%d without=%d/%d with=%d/%d delta=%+.2f" %
                      (name, len(data["tasks"]), data["without"]["pass"], data["without"]["k"],
                       data["with"]["pass"], data["with"]["k"], data["delta"]), flush=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(out, f, ensure_ascii=False, indent=1)

    vals = list(out["items"].values())
    if vals:
        out["summary"] = {
            "n": len(vals),
            "n_tasks": out["n_tasks"],
            "avg_delta": round(sum(v["delta"] for v in vals) / len(vals), 3),
            "with_avg": round(sum(v["with"]["rate"] for v in vals) / len(vals), 3),
            "without_avg": round(sum(v["without"]["rate"] for v in vals) / len(vals), 3),
        }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("summary", out.get("summary"))
    print("saved", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
