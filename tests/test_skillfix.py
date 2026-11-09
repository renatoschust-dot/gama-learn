#!/usr/bin/env python3
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import skillfix

ORIG = (
    "---\nname: demo\ndescription: \"Demo skill.\"\n---\n"
    "# Demo\n\nRun the demo tool.\n"
)

NEW = (
    "---\nname: demo\ndescription: \"Use when you need to run and verify the demo tool with evidence.\"\n---\n"
    "# Demo\n\n## When to use\nUse when the demo tool must be validated.\n\n"
    "## Commands\n```bash\npython3 demo.py --check\n```\n\n"
    "## Steps\n1. Run the command.\n2. Read the output.\n\n"
    "## Verification\nRun the check and cite the output as evidence.\n\n"
    "## Guardrails\nDo not write to production without approval.\n"
)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestSkillfix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.skills = os.path.join(self.tmp, "skills")
        self.skill_dir = os.path.join(self.skills, "demo")
        os.makedirs(self.skill_dir)
        self.skill = os.path.join(self.skill_dir, "SKILL.md")
        with open(self.skill, "w", encoding="utf-8") as f:
            f.write(ORIG)
        self.saved = (skillfix.SKILL_ROOTS, skillfix.STATE_DIR, skillfix.FIXES_DIR,
                      skillfix.BACKUPS_DIR, skillfix.FIXES_JSON, skillfix._generate,
                      skillfix._run_bench)
        skillfix.SKILL_ROOTS = [self.skills]
        skillfix.STATE_DIR = os.path.join(self.tmp, "state")
        skillfix.FIXES_DIR = os.path.join(skillfix.STATE_DIR, "fixes")
        skillfix.BACKUPS_DIR = os.path.join(skillfix.FIXES_DIR, "backups")
        skillfix.FIXES_JSON = os.path.join(skillfix.STATE_DIR, "fixes.json")
        skillfix._generate = lambda name, text, issues: (NEW, {"ok": True, "model": "test"})

    def tearDown(self):
        (skillfix.SKILL_ROOTS, skillfix.STATE_DIR, skillfix.FIXES_DIR,
         skillfix.BACKUPS_DIR, skillfix.FIXES_JSON, skillfix._generate,
         skillfix._run_bench) = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_analyze_bad(self):
        codes = {i["code"] for i in skillfix.analyze_issues("# X\n\nkratko\n", "kratko")}
        self.assertTrue({"no_command", "no_trigger", "short_description", "no_check"} <= codes)

    def test_analyze_good(self):
        self.assertEqual(skillfix.analyze_issues(NEW, "Use when you need to validate the demo tool."), [])

    def test_resolve(self):
        self.assertEqual(skillfix.resolve_skill("demo"), os.path.realpath(self.skill))
        self.assertEqual(skillfix.resolve_skill("skill:demo"), os.path.realpath(self.skill))
        self.assertIsNone(skillfix.resolve_skill("../../etc/passwd"))
        self.assertIsNone(skillfix.resolve_skill("nope"))

    def test_propose_does_not_touch_original(self):
        res = skillfix.propose("demo")
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "proposed")
        self.assertEqual(res["before_hash"], sha(ORIG))
        self.assertTrue(os.path.isfile(os.path.join(skillfix.FIXES_DIR, "demo.md")))
        with open(self.skill, encoding="utf-8") as f:
            self.assertEqual(f.read(), ORIG)
        self.assertEqual(skillfix.list_fixes()["count"], 1)

    def test_apply_requires_approved_and_yes(self):
        skillfix.propose("demo")
        self.assertFalse(skillfix.apply_fix("demo", yes=True)["ok"])
        self.assertTrue(skillfix.approve("demo")["ok"])
        self.assertFalse(skillfix.apply_fix("demo", yes=False)["ok"])
        res = skillfix.apply_fix("demo", yes=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "applied")
        with open(self.skill, encoding="utf-8") as f:
            self.assertEqual(f.read(), NEW)
        with open(res["backup"], encoding="utf-8") as f:
            self.assertEqual(f.read(), ORIG)
        self.assertEqual(res["after_hash"], sha(NEW))
        self.assertFalse(skillfix.propose("demo")["ok"])

    def test_apply_detects_drift(self):
        skillfix.propose("demo")
        skillfix.approve("demo")
        with open(self.skill, "w", encoding="utf-8") as f:
            f.write(ORIG + "\nchanged\n")
        res = skillfix.apply_fix("demo", yes=True)
        self.assertFalse(res["ok"])
        self.assertIn("drift", res["err"])

    def test_verify_runs_bench(self):
        seen = {}

        def fake(name, out):
            seen["name"] = name
            seen["out"] = out
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"summary": {"n": 1, "avg_delta": 0.5},
                           "items": {name: {"cat": "explicit"}}}, f)
            return {"rc": 0, "stdout": "ok", "stderr": ""}

        skillfix._run_bench = fake
        res = skillfix.verify("demo")
        self.assertTrue(res["ok"])
        self.assertEqual(seen["name"], "demo")
        self.assertTrue(seen["out"].endswith("demo_bench.json"))
        self.assertEqual(res["summary"]["n"], 1)
        self.assertIn("before/after", res["note"])


if __name__ == "__main__":
    unittest.main()
