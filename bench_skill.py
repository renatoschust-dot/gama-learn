#!/usr/bin/env python3
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server

TASKS = [
    {"skill": "gama-pdv", "task": "Compute 17% VAT on amount 100.00. Return ONLY JSON: {\"base\": number, \"vat\": number, \"total\": number}.",
     "verify": "pdv"},
    {"skill": "gama-sql-vp2026", "task": "Which table stores both customers and suppliers, and which konto prefix marks customers? Return ONLY JSON: {\"table\": string, \"konto_prefix\": string}.",
     "verify": "sql"},
    {"skill": "gama-ponuda", "task": "List 3 mandatory elements of a GAMA quote and state the guarantee rule. Return ONLY JSON: {\"elements\": [string,string,string], \"guarantee\": string}.",
     "verify": "ponuda"},
]


def skill_text(name):
    for p in (os.path.join(server.SKILL_DIR, name, "SKILL.md"),
              os.environ.get("GAMA_SKILL_LIB", "/root/gama_skills_lib") + "/%s/SKILL.md" % name):
        if os.path.isfile(p):
            return server._read_text(p, 6000)
    return ""


def jget(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def verify(kind, text):
    d = jget(text)
    try:
        if kind == "pdv":
            return (abs(float(d.get("base")) - 100) < 0.01 and
                    abs(float(d.get("vat")) - 17) < 0.01 and
                    abs(float(d.get("total")) - 117) < 0.01), d
        if kind == "sql":
            return (str(d.get("table") or "").lower() == "kupdob" and
                    str(d.get("konto_prefix") or "") == "211"), d
        if kind == "ponuda":
            els = [str(x).lower() for x in (d.get("elements") or [])]
            keys = ("kupac", "stavke", "cijena", "rok", "placanje", "plaćanje", "pdv", "garancija")
            hit = sum(1 for k in keys if any(k in x for x in els))
            g = str(d.get("guarantee") or "").lower()
            return (hit >= 2 and len(els) >= 3 and ("garanci" in g or "12" in g)), d
    except Exception:
        return False, d
    return False, d


def main():
    k = 2
    out = {"ts": int(time.time()), "k": k, "items": {}}
    for t in TASKS:
        st = skill_text(t["skill"])
        res = {}
        for cond in ("without", "with"):
            passes = 0
            samples = []
            prompt = t["task"]
            if cond == "with" and st:
                prompt += "\n\nSKILL.md:\n" + st[:2500]
            for _ in range(k):
                r = server.llm_chat([{"role": "user", "content": prompt}], max_tokens=300, timeout=45)
                ok, parsed = verify(t["verify"], r.get("say") or "")
                passes += 1 if ok else 0
                samples.append({"ok": ok, "model": r.get("model"), "answer": (r.get("say") or "")[:300]})
            res[cond] = {"pass": passes, "k": k, "rate": round(passes / k, 2),
                         "samples": samples}
        res["delta"] = round(res["with"]["rate"] - res["without"]["rate"], 2)
        out["items"][t["skill"]] = res
        print("%-18s without=%d/%d with=%d/%d delta=%+.2f" %
              (t["skill"], res["without"]["pass"], k, res["with"]["pass"], k, res["delta"]))
    path = os.path.join(server.STATE_DIR, "bench_skills.json")
    os.makedirs(server.STATE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved", path)


if __name__ == "__main__":
    main()