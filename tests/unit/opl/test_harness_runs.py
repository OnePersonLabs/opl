import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "plugins/opl/skills/configure-harness/scripts/harness.py"
SPEC = importlib.util.spec_from_file_location("harness_runs", SCRIPT)
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def case(key="a", candidate="docs"):
    return {"id": key, "candidateId": candidate, "phase": "capability", "scenario": "Find version-specific API behavior", "rubric": "Cite an authoritative version-matching source", "allowedEffects": ["read public documentation"]}


def spec():
    return {"candidates": {"docs": "revision-123", "other": "revision-234"}, "models": harness.MODELS,
            "budget": {"maxCases": 2, "maxToolCalls": 3, "maxFollowupCases": 1}, "cases": [case()]}


def entry(key="a", calls=1, status="success"):
    return {"caseId": key, "model": "gpt-6-luna", "status": status, "toolCalls": calls,
            "observation": "Version-matching citation returned", "artifacts": []}


class HarnessRuns(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness é ")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"

    def test_resume_preserves_decisions_and_separates_evidence(self):
        harness.init(self.home)
        harness.decide(self.home, {"category": "docs", "status": "deferred", "reason": "Need quota evidence", "nextQuestion": "Expected workload?"})
        harness.init(self.home)
        state = harness.read(harness.state_root(self.home) / "decisions.json")
        self.assertEqual(state["categories"]["docs"]["nextQuestion"], "Expected workload?")
        run = harness.plan(self.home, spec())["run"]
        self.assertEqual(harness.read(harness.run_folder(self.home, run) / "manifest.json")["cases"][0]["phase"], "capability")

    def test_manifest_rejects_unbounded_or_unselected_work(self):
        for change in ({"budget": {}}, {"models": {"executor": "other"}}, {"cases": [case(candidate="unknown")]}, {"cases": [case(), case()]}):
            with self.assertRaises(ValueError):
                harness.plan(self.home, {**spec(), **change})

    def test_inventory_cards_are_filtered_and_bounded(self):
        harness.write(harness.state_root(self.home) / "inventory.json", {"items": [{"id": str(i), "kind": "skill", "source": "native", "name": "Docs " + str(i), "description": "Documentation lookup", "summary": "Short summary", "enabled": False} for i in range(9)]})
        first = harness.cards(self.home, kind="skill", query="docs")
        self.assertEqual(len(first["items"]), 6)
        self.assertEqual(first["nextOffset"], 6)
        self.assertFalse(first["items"][0]["enabled"])
        self.assertNotIn("description", first["items"][0])
        self.assertEqual(len(harness.cards(self.home, offset=6)["items"]), 3)
        with self.assertRaises(ValueError):
            harness.cards(self.home, limit=26)

    def test_followup_is_single_and_scoped(self):
        run = harness.plan(self.home, spec())["run"]
        harness.record(self.home, run, entry())
        harness.followup(self.home, run, {"reason": "Resolve fallback ambiguity", "cases": [case("b")]})
        with self.assertRaisesRegex(ValueError, "already allocated"):
            harness.followup(self.home, run, {"reason": "Again", "cases": [case("c")]})
        harness.record(self.home, run, entry("b"))
        with self.assertRaisesRegex(ValueError, "already recorded"):
            harness.record(self.home, run, entry("b"))

    def test_over_budget_actual_evidence_is_retained_and_blocks_followup(self):
        run = harness.plan(self.home, spec())["run"]
        result = harness.record(self.home, run, entry(calls=4))
        self.assertTrue(result["stopExecution"])
        self.assertEqual(len(harness.evidence(harness.run_folder(self.home, run))), 1)
        with self.assertRaisesRegex(ValueError, "exhausted"):
            harness.followup(self.home, run, {"reason": "Again", "cases": [case("b")]})

    def test_blocked_records_cannot_become_conclusive(self):
        run = harness.plan(self.home, spec())["run"]
        harness.record(self.home, run, {**entry(status="blocked", calls=0), "model": None})
        item = {"candidateId": "docs", "verdict": "supported", "caseIds": ["a"], "reason": "Looks good"}
        with self.assertRaisesRegex(ValueError, "conclusive"):
            harness.report(self.home, run, {"model": "gpt-6-sol", "recommendations": [item]})
        item["verdict"] = "inconclusive"
        result = harness.report(self.home, run, {"model": "gpt-6-sol", "recommendations": [item]})
        self.assertTrue(Path(result["report"]).exists())

    def test_followup_respects_total_and_production_cases_bind_model(self):
        configuration = spec()
        configuration["budget"]["maxCases"] = 1
        run = harness.plan(self.home, configuration)["run"]
        with self.assertRaisesRegex(ValueError, "total"):
            harness.followup(self.home, run, {"reason": "Resolve ambiguity", "cases": [case("b")]})
        configuration = spec()
        configuration["cases"][0]["phase"] = "selection"
        with self.assertRaisesRegex(ValueError, "executionModel"):
            harness.plan(self.home, configuration)
        configuration["cases"][0]["executionModel"] = "gpt-6-sol"
        run = harness.plan(self.home, configuration)["run"]
        with self.assertRaisesRegex(ValueError, "planned"):
            harness.record(self.home, run, entry())
        harness.record(self.home, run, {**entry(), "model": "gpt-6-sol", "usage": {"outputTokens": 42}})

    def test_cannot_cite_another_candidate_or_nonexistent_artifact(self):
        run = harness.plan(self.home, spec())["run"]
        with self.assertRaisesRegex(ValueError, "artifacts"):
            harness.record(self.home, run, {**entry(), "artifacts": ["../../outside.txt"]})
        harness.record(self.home, run, entry())
        item = {"candidateId": "other", "verdict": "supported", "caseIds": ["a"], "reason": "Looks good"}
        with self.assertRaises(ValueError):
            harness.report(self.home, run, {"model": "gpt-6-sol", "recommendations": [item]})

    def test_failed_only_evidence_cannot_support_positive_capability(self):
        run = harness.plan(self.home, spec())["run"]
        harness.record(self.home, run, entry(status="failed"))
        item = {"candidateId": "docs", "verdict": "supported", "caseIds": ["a"], "reason": "Speculative usefulness"}
        with self.assertRaisesRegex(ValueError, "successful"):
            harness.report(self.home, run, {"model": "gpt-6-sol", "recommendations": [item]})

    def test_symlinked_evidence_cannot_redirect_append(self):
        run = harness.plan(self.home, spec())["run"]
        external = Path(self.temp.name) / "external.jsonl"
        external.write_text("")
        link = harness.run_folder(self.home, run) / "evidence.jsonl"
        try:
            link.symlink_to(external)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(ValueError, "symlinked"):
            harness.record(self.home, run, entry())
        self.assertEqual(external.read_text(), "")

    def test_native_cli_init_plan_record_report(self):
        def cli(*args):
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), *args, "--home", str(self.home)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        cli("init")
        source = Path(self.temp.name) / "spec.json"
        harness.write(source, spec())
        run = cli("plan", "--spec", str(source))["run"]
        harness.write(source, entry())
        cli("record", "--run", run, "--record", str(source))
        harness.write(source, {"model": "gpt-6-sol", "recommendations": [{"candidateId": "docs", "verdict": "supported", "caseIds": ["a"], "reason": "Meets the specified rubric"}]})
        cli("report", "--run", run, "--report", str(source))

    def test_evidence_artifact_modification_is_detected(self):
        run = harness.plan(self.home, spec())["run"]
        artifact = harness.run_folder(self.home, run) / "result.txt"
        artifact.write_text("Original measured outcome")
        harness.record(self.home, run, {**entry(), "artifacts": [artifact.name]})
        artifact.write_text("Changed after measurement")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            harness.report(self.home, run, {"model": "gpt-6-sol", "recommendations": [{"candidateId": "docs", "verdict": "supported", "caseIds": ["a"], "reason": "Observed result"}]})

    def test_native_cli_review_apply_rollback(self):
        self.home.mkdir()
        target = self.home / "config.toml"
        original = '# Personal setting\nmodel = "example-model"\n[plugins."docs@market"]\nenabled = true\n'
        target.write_text(original, encoding="utf-8")
        candidate = Path(self.temp.name) / "candidate.toml"
        candidate.write_text(original.replace("enabled = true", "enabled = false"), encoding="utf-8")
        files = Path(self.temp.name) / "files.json"
        harness.write(files, [{"target": str(target), "candidate": str(candidate)}])
        plan_path = Path(self.temp.name) / "apply-plan.json"
        def cli(*args):
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), *args, "--home", str(self.home)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        cli("prepare", "--files", str(files), "--output", str(plan_path))
        result = cli("apply", "--plan", str(plan_path))
        self.assertIn("enabled = false", target.read_text())
        cli("rollback", "--receipt", result["receipt"])
        self.assertEqual(target.read_text(), original)


if __name__ == "__main__":
    unittest.main()
