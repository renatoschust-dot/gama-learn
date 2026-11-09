#!/usr/bin/env python3
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


def verify_pdv(text):
    d = jget(text)
    try:
        return (abs(float(d.get("base")) - 100) < 0.01 and
                abs(float(d.get("vat")) - 17) < 0.01 and
                abs(float(d.get("total")) - 117) < 0.01), d
    except Exception:
        return False, d


def verify_sql(text):
    d = jget(text)
    return (str(d.get("table") or "").lower() == "kupdob" and
            str(d.get("konto_prefix") or "") == "211"), d


def verify_ponuda(text):
    d = jget(text)
    els = [str(x).lower() for x in (d.get("elements") or [])]
    keys = ("kupac", "stavke", "cijena", "rok", "placanje", "plaćanje", "pdv", "garancija")
    hit = sum(1 for k in keys if any(k in x for x in els))
    g = str(d.get("guarantee") or "").lower()
    return (hit >= 2 and len(els) >= 3 and ("garanci" in g or "12" in g)), d


EXPLICIT = [
    ("gama-pdv", "Compute 17% VAT on amount 100.00. Return ONLY JSON: {\"base\": number, \"vat\": number, \"total\": number}.", verify_pdv),
    ("gama-sql-vp2026", "Which table stores both customers and suppliers, and which konto prefix marks customers? Return ONLY JSON: {\"table\": string, \"konto_prefix\": string}.", verify_sql),
    ("gama-ponuda", "List 3 mandatory elements of a GAMA quote and state the guarantee rule. Return ONLY JSON: {\"elements\": [string,string,string], \"guarantee\": string}.", verify_ponuda),
]


def select_grounding(n=17):
    cat = server.load_catalog()
    out = []
    used = {x[0] for x in EXPLICIT}
    for it in cat.get("items") or []:
        if it.get("kind") != "skill" or not it.get("installed"):
            continue
        name = it.get("name") or ""
        if not name.startswith("gama-") or name.startswith("gama-auto-") or name in used:
            continue
        text = skill_text(name)
        cmds = server._extract_commands(text)
        if not cmds:
            continue
        out.append({"name": name, "desc": (it.get("description") or "")[:500],
                    "text": text, "commands": cmds})
        if len(out) >= n:
            break
    return out


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


def task_prompt(name, desc, text, with_skill):
    p = ("You are an AI agent taking a grounding benchmark.\n"
         "SKILL: %s\nDESCRIPTION: %s\n" % (name, desc))
    if with_skill:
        p += "SKILL.md EXCERPT:\n%s\n" % text[:2500]
    p += ("TASK: Return ONLY JSON: {\"use_case\": string, \"command\": string, \"check\": string}. "
          "The command MUST be copied exactly from the skill; do not invent. "
          "check = how to verify that applying the skill succeeded. "
          "Do not dump skill contents; answer the TASK.")
    return p


def verify_grounding(text, commands, name, desc, skill_text=""):
    d = jget(text)
    cmd = d.get("command")
    use = _norm(d.get("use_case"))
    chk = _norm(d.get("check"))
    hit = _cmd_match(cmd, commands) or _grounded_in_text(cmd, skill_text)
    return (hit and len(chk) >= 5 and bool(use)), d


def judge_answer(name, desc, skill_text, answer):
    d0 = jget(answer)
    cmd0 = _clean_cmd(d0.get("command"))
    if not cmd0 or len(cmd0.split()) < 2 or cmd0.strip() in (name.lower(), "gama"):
        return {"pass": False, "reason": "command is only skill name or empty"}
    jp = ('Judge the candidate against the skill. Return JSON only: '
          '{"pass": true|false, "reason": "<=160 chars"}.\n'
          'SKILL: %s — %s\nEXCERPT: %s\nCANDIDATE: %s\n'
          'Pass only if the candidate uses the skill correctly, names a real executable '
          'command (not just the skill name) grounded in the excerpt, and gives a concrete '
          'success check.' % (name, (desc or "")[:240], (skill_text or "")[:700],
                              (answer or "")[:900].replace("\n", " ")))
    r = server.llm_chat([{"role": "user", "content": jp}], max_tokens=120, timeout=30, prefer="fallback")
    if not r.get("ok"):
        r = server.harness_ask(jp, timeout=45)
    d = jget(r.get("say") or "")
    p = d.get("pass")
    if isinstance(p, str):
        p = p.strip().lower() in ("true", "1", "yes")
    return {"pass": p, "reason": str(d.get("reason") or "")[:160]}


def run_one(name, prompt, verifier_args, k, judge=False, desc="", skill_text=""):
    passes, samples = 0, []
    for _ in range(k):
        r = server.llm_chat([{"role": "user", "content": prompt}], max_tokens=400, timeout=45, prefer=PREFER)
        ans = r.get("say") or ""
        det_ok, _ = verifier_args(ans)
        jr = None
        ok = det_ok
        if judge and not det_ok:
            jr = judge_answer(name, desc, skill_text, ans)
            if jr.get("pass") is True:
                ok = True
        passes += 1 if ok else 0
        samples.append({"ok": ok, "det": det_ok, "judge": jr,
                        "model": r.get("model"), "answer": ans[:800]})
    return {"pass": passes, "k": k, "rate": round(passes / k, 2), "samples": samples}


def main():
    k = 1
    only = set()
    merge = ""
    out_path = ""
    args = sys.argv[1:]
    if "--k" in args:
        try:
            k = max(1, min(5, int(args[args.index("--k") + 1])))
        except (IndexError, ValueError):
            k = 1
    if "--out" in args:
        try:
            out_path = args[args.index("--out") + 1]
        except IndexError:
            out_path = ""
    if "--only" in args:
        try:
            only = {x.strip() for x in args[args.index("--only") + 1].split(",") if x.strip()}
        except IndexError:
            pass
    if "--merge" in args:
        try:
            merge = args[args.index("--merge") + 1]
        except IndexError:
            pass
    out = {"ts": int(time.time()), "k": k, "items": {}}
    if merge and os.path.isfile(merge):
        try:
            with open(merge, "r", encoding="utf-8") as f:
                out["items"] = (json.load(f) or {}).get("items") or {}
        except (OSError, ValueError):
            pass
    items = []
    for name, task, fn in EXPLICIT:
        text = skill_text(name)
        items.append({"name": name, "cat": "explicit", "task": task,
                      "text": text, "verify": fn})
    for g in select_grounding(17):
        items.append({"name": g["name"], "cat": "grounding",
                      "task": "Return JSON with use_case, exact command from the skill, and a success check.",
                      "text": g["text"], "commands": g["commands"], "desc": g["desc"],
                      "verify": lambda t, g=g: verify_grounding(t, g["commands"], g["name"], g["desc"], g["text"])})
    if "--jobs" in args:
        try:
            jobs = max(1, min(12, int(args[args.index("--jobs") + 1])))
        except (IndexError, ValueError):
            jobs = 6
    else:
        jobs = 6
    judge = "--judge" in args
    path = out_path or os.path.join(server.STATE_DIR, "bench20.json")

    def work(it):
        res = {}
        for cond in ("without", "with"):
            if cond == "without":
                prompt = (it["task"] if it["cat"] == "explicit" else
                          task_prompt(it["name"], it.get("desc") or "", "", False))
            elif it["cat"] == "explicit":
                prompt = (it["task"] + "\n\nSKILL.md:\n" + it["text"][:2500] +
                          "\n\nAnswer the TASK in JSON; ignore tables/examples in the skill.")
            else:
                prompt = task_prompt(it["name"], it.get("desc") or "", it["text"], True)
            res[cond] = run_one(it["name"], prompt, it["verify"], k, judge,
                                it.get("desc") or "", it["text"])
        res["delta"] = round(res["with"]["rate"] - res["without"]["rate"], 2)
        return it["name"], {"cat": it["cat"], **res}

    todo = [it for it in items if not only or it["name"] in only]
    if not todo:
        print("no matching skills for --only", flush=True)
        return 2
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(work, it) for it in todo]
        for fut in as_completed(futs):
            name, data = fut.result()
            with lock:
                out["items"][name] = data
                print("%-34s %-10s without=%d/%d with=%d/%d delta=%+.2f" %
                      (name, data["cat"], data["without"]["pass"], k,
                       data["with"]["pass"], k, data["delta"]), flush=True)
                os.makedirs(server.STATE_DIR, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(out, f, ensure_ascii=False, indent=1)
    vals = [v["delta"] for v in out["items"].values()]
    out["summary"] = {"n": len(vals), "avg_delta": round(sum(vals) / len(vals), 3),
                      "with_avg": round(sum(v["with"]["rate"] for v in out["items"].values()) / len(vals), 3),
                      "without_avg": round(sum(v["without"]["rate"] for v in out["items"].values()) / len(vals), 3)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("summary", out["summary"])
    print("saved", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())