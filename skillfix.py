#!/usr/bin/env python3
"""P33 skill fix loop: propose -> approve -> apply -> verify (review-only)."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server

STATE_DIR = server.STATE_DIR
FIXES_DIR = os.path.join(STATE_DIR, "fixes")
BACKUPS_DIR = os.path.join(FIXES_DIR, "backups")
FIXES_JSON = os.path.join(STATE_DIR, "fixes.json")
SKILL_LIB = "/root/gama_skills_lib"
SKILL_ROOTS = [server.SKILL_DIR, SKILL_LIB]
BENCH = os.path.join(HERE, "bench20.py")
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
VERIFY_TIMEOUT = int(os.environ.get("SKILLFIX_VERIFY_TIMEOUT") or 1800)


def _now():
    return int(time.time())


def _bare_name(skill):
    s = str(skill or "").strip()
    if s.startswith("skill:"):
        s = s[6:]
    s = s.replace("\\", "/").rstrip("/")
    if s.endswith("/SKILL.md"):
        s = s[: -len("/SKILL.md")]
        s = s.rsplit("/", 1)[-1]
    return s


def _sha(data):
    h = hashlib.sha256()
    h.update(data if isinstance(data, bytes) else str(data).encode("utf-8"))
    return h.hexdigest()


def _file_hash(path):
    try:
        with open(path, "rb") as f:
            return _sha(f.read())
    except OSError:
        return ""


def _write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def load_fixes():
    try:
        with open(FIXES_JSON, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("items", {})
            if not isinstance(d.get("items"), dict):
                d["items"] = {}
            return d
    except (OSError, ValueError):
        pass
    return {"items": {}}


def save_fixes(d):
    d["ts"] = _now()
    _write_atomic(FIXES_JSON, json.dumps(d, ensure_ascii=False, indent=1))


def resolve_skill(skill):
    name = _bare_name(skill)
    if not name or not NAME_RE.match(name):
        return None
    for root in SKILL_ROOTS:
        cand = os.path.realpath(os.path.join(root, name, "SKILL.md"))
        real_root = os.path.realpath(root)
        if not cand.startswith(real_root + os.sep):
            continue
        if os.path.isfile(cand):
            return cand
    raw = str(skill or "").strip()
    if raw and os.path.isfile(raw):
        real = os.path.realpath(raw)
        for root in SKILL_ROOTS:
            if real.startswith(os.path.realpath(root) + os.sep):
                return real
    return None


def analyze_issues(text, desc=""):
    issues = []
    cmds = server._extract_commands(text or "")
    if not cmds:
        issues.append({"code": "no_command",
                       "detail": "SKILL.md nema izvrsnu komandu u code bloku ili inline backticks."})
    if not re.search(r"(?i)\b(when to use|use when|kada koristiti|kada se koristi|aktivira se)\b",
                     text or "") and not re.search(r"(?im)^\s*triggers?\s*:", text or ""):
        issues.append({"code": "no_trigger",
                       "detail": "Nema triggera (kada se skill koristi)."})
    d = (desc or "").strip()
    if len(d) < 25:
        issues.append({"code": "short_description",
                       "detail": "Opis je prekratak (%d znakova)." % len(d)})
    if not re.search(r"(?i)\b(check|verify|verification|evidence|proof|dokaz|provjer|success|uspjeh)\b",
                     text or ""):
        issues.append({"code": "no_check",
                       "detail": "Nema provjere/dokaza da je primjena uspjela."})
    if len((text or "").strip()) < 120:
        issues.append({"code": "too_short",
                       "detail": "SKILL.md je prekratak (<120 znakova)."})
    return issues


def build_prompt(name, text, issues):
    codes = ", ".join(i["code"] for i in issues) or "general improvement"
    return (
        "You improve an agent SKILL.md file. Return the complete improved Markdown "
        "document and nothing else (no wrapper fences, no commentary).\n\n"
        "SKILL NAME: %s\nDEFECTS TO FIX: %s\n\n"
        "RULES:\n"
        "1. Keep the original purpose, facts, paths and commands; never invent URLs or paths.\n"
        "2. Start with YAML frontmatter: ---\\nname: %s\\ndescription: \"<one clear sentence, >=40 chars>\"\\n---\n"
        "3. Include a '## When to use' section with explicit triggers.\n"
        "4. Include a '## Commands' section with 1-3 real executable commands in fenced code blocks "
        "(use commands already present in the original, or a safe read-only example from it).\n"
        "5. Include '## Steps' (numbered), '## Verification' (concrete check/evidence), "
        "'## Guardrails' (what not to do).\n"
        "6. Be concise and practical; do not add tables of unrelated material.\n\n"
        "ORIGINAL SKILL.md:\n%s\n" % (name, codes, name, (text or "")[:8000])
    )


def _strip_fence(s):
    s = (s or "").strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*?)\n```\s*$", s, re.S)
    if m:
        s = m.group(1).strip()
    return s


def _generate(name, text, issues):
    prompt = build_prompt(name, text, issues)
    r = server.llm_chat([{"role": "user", "content": prompt}],
                        max_tokens=1400, timeout=120)
    if not r.get("ok") or not (r.get("say") or "").strip():
        r = server.harness_ask(prompt, timeout=150)
    out = _strip_fence(r.get("say") or "")
    if not out:
        return None, {"ok": False, "err": (r.get("err") or "llm nije vratio sadrzaj")[:200]}
    return out, {"ok": True, "model": str(r.get("model") or "")}


def propose(skill):
    path = resolve_skill(skill)
    if not path:
        return {"ok": False, "err": "skill nije nadjen: " + str(skill)}
    name = _bare_name(skill) or os.path.basename(os.path.dirname(path))
    text = server._read_text(path, 40000)
    if not text.strip():
        return {"ok": False, "err": "SKILL.md je prazan: " + path}
    fixes = load_fixes()
    prev = fixes["items"].get(name) or {}
    if prev.get("status") == "applied":
        return {"ok": False, "err": "vec primijenjen; napravi novi propose samo ako zelis novi ciklus "
                                    "(status applied)", "skill": name}
    desc = ""
    try:
        _, _, desc, _ = server._skill_meta(path)
    except Exception:
        desc = ""
    issues = analyze_issues(text, desc)
    draft, meta = _generate(name, text, issues)
    if not meta.get("ok"):
        return {"ok": False, "err": meta.get("err") or "generation failed", "skill": name}
    if len(draft.strip()) < 80:
        return {"ok": False, "err": "predlog je prekratak (%d znakova)" % len(draft.strip()),
                "skill": name}
    draft_path = os.path.join(FIXES_DIR, name + ".md")
    _write_atomic(draft_path, draft + ("\n" if not draft.endswith("\n") else ""))
    rec = {
        "skill": name,
        "status": "proposed",
        "path": path,
        "draft_path": draft_path,
        "before_hash": _file_hash(path),
        "ts": _now(),
        "updated_ts": _now(),
        "issues": issues,
        "model": meta.get("model") or "",
    }
    fixes["items"][name] = rec
    save_fixes(fixes)
    return {"ok": True, "skill": name, "status": "proposed", "draft_path": draft_path,
            "before_hash": rec["before_hash"], "issues": issues, "model": rec["model"]}


def list_fixes():
    fixes = load_fixes()
    items = []
    for name, rec in (fixes.get("items") or {}).items():
        items.append({k: rec.get(k) for k in ("skill", "status", "ts", "updated_ts",
                                              "before_hash", "after_hash", "issues", "model")})
    items.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return {"ok": True, "count": len(items), "items": items}


def approve(skill):
    name = _bare_name(skill)
    fixes = load_fixes()
    rec = fixes["items"].get(name)
    if not rec:
        return {"ok": False, "err": "nema predloga za: " + name}
    if rec.get("status") == "applied":
        return {"ok": False, "err": "vec primijenjen: " + name}
    rec["status"] = "approved"
    rec["approved_ts"] = _now()
    rec["updated_ts"] = _now()
    fixes["items"][name] = rec
    save_fixes(fixes)
    return {"ok": True, "skill": name, "status": "approved"}


def apply_fix(skill, yes=False):
    name = _bare_name(skill)
    if not yes:
        return {"ok": False, "err": "apply zahtijeva --yes (bez auto-apply)"}
    fixes = load_fixes()
    rec = fixes["items"].get(name)
    if not rec:
        return {"ok": False, "err": "nema predloga za: " + name}
    if rec.get("status") != "approved":
        return {"ok": False, "err": "status nije approved (je: %s)" % rec.get("status")}
    path = rec.get("path") or resolve_skill(name)
    if not path or not os.path.isfile(path):
        return {"ok": False, "err": "originalni SKILL.md nije nadjen"}
    cur = _file_hash(path)
    if not cur or cur != rec.get("before_hash"):
        return {"ok": False, "err": "original se promijenio od propose; odbijam apply (drift)",
                "before_hash": rec.get("before_hash"), "current_hash": cur}
    draft_path = rec.get("draft_path") or os.path.join(FIXES_DIR, name + ".md")
    if not os.path.isfile(draft_path):
        return {"ok": False, "err": "draft ne postoji: " + draft_path}
    new_text = server._read_text(draft_path, 200000)
    if len(new_text.strip()) < 80:
        return {"ok": False, "err": "draft je prekratak"}
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    backup = os.path.join(BACKUPS_DIR, "%s.%d.SKILL.md" % (name, _now()))
    with open(path, "rb") as f:
        orig = f.read()
    with open(backup, "wb") as f:
        f.write(orig)
    _write_atomic(path, new_text)
    rec["status"] = "applied"
    rec["applied_ts"] = _now()
    rec["updated_ts"] = _now()
    rec["backup"] = backup
    rec["after_hash"] = _file_hash(path)
    fixes["items"][name] = rec
    save_fixes(fixes)
    return {"ok": True, "skill": name, "status": "applied", "backup": backup,
            "before_hash": rec.get("before_hash"), "after_hash": rec["after_hash"]}


def _run_bench(name, out_path):
    cmd = [sys.executable, BENCH, "--only", name, "--k", "3", "--judge",
           "--jobs", "2", "--out", out_path]
    try:
        p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                           timeout=VERIFY_TIMEOUT)
        return {"rc": p.returncode, "stdout": (p.stdout or "")[-4000:],
                "stderr": (p.stderr or "")[-2000:]}
    except subprocess.TimeoutExpired:
        return {"rc": -1, "stdout": "", "stderr": "timeout %ss" % VERIFY_TIMEOUT}


def verify(skill):
    name = _bare_name(skill)
    if not NAME_RE.match(name or ""):
        return {"ok": False, "err": "neispravno ime skilla"}
    if not os.path.isfile(BENCH):
        return {"ok": False, "err": "bench20.py nije nadjen"}
    out_path = os.path.join(FIXES_DIR, name + "_bench.json")
    os.makedirs(FIXES_DIR, exist_ok=True)
    run = _run_bench(name, out_path)
    data = {}
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        data = {}
    summary = data.get("summary")
    item = (data.get("items") or {}).get(name)
    ok = run.get("rc") == 0 and summary is not None
    return {"ok": ok, "skill": name, "rc": run.get("rc"), "summary": summary,
            "item": item, "out": out_path,
            "stdout": run.get("stdout"), "stderr": run.get("stderr"),
            "note": "before/after nije automatski; ovo je samo trenutni bench rezultat"}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="skillfix.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("propose")
    sp.add_argument("skill")
    sub.add_parser("list")
    sa = sub.add_parser("approve")
    sa.add_argument("skill")
    sy = sub.add_parser("apply")
    sy.add_argument("skill")
    sy.add_argument("--yes", action="store_true")
    sv = sub.add_parser("verify")
    sv.add_argument("skill")
    args = ap.parse_args(argv)
    if args.cmd == "propose":
        res = propose(args.skill)
    elif args.cmd == "list":
        res = list_fixes()
    elif args.cmd == "approve":
        res = approve(args.skill)
    elif args.cmd == "apply":
        res = apply_fix(args.skill, yes=args.yes)
    else:
        res = verify(args.skill)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
