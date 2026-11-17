"""Fail-closed stack release preflight regression tests."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stack_release_preflight", ROOT / "scripts" / "stack_release_preflight.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
DATA = json.loads((ROOT / "registry" / "stack_release_staging.json").read_text())


class StackReleasePreflightTests(unittest.TestCase):
    def test_real_inventory_dependency_sequence(self):
        rows = MOD.ordered_services(DATA)
        ids = [r["id"] for r in rows]
        self.assertEqual(len(ids), 11)
        self.assertLess(ids.index("mesh-sync"), ids.index("deploy-engine"))
        self.assertLess(ids.index("deploy-engine"), ids.index("rhns"))
        self.assertLess(ids.index("payments"), ids.index("revenue"))
        self.assertLess(ids.index("revenue"), ids.index("review-ui"))

    def test_dry_run_never_claims_deployment(self):
        report, ok = MOD.preflight(DATA)
        self.assertTrue(ok)
        self.assertEqual(report["release_action"], "NONE")
        self.assertFalse(report["deployment_performed"])
        self.assertFalse(report["ready_to_promote"])
        self.assertIsNone(report["all_heads_match_pinned_sha"])

    def test_verified_source_pins_are_not_release_authorization(self):
        mapping = {(x["repo"], x["branch"]): x["sha"] for x in DATA["services"]}
        report, good = MOD.preflight(DATA, verify_github=True, resolver=lambda r, b: mapping[(r, b)])
        self.assertTrue(good)
        self.assertTrue(report["all_heads_match_pinned_sha"])
        self.assertFalse(report["ready_to_promote"])

    def test_branch_drift_is_blocked(self):
        report, good = MOD.preflight(DATA, verify_github=True, resolver=lambda *_: "0" * 40)
        self.assertFalse(good)
        self.assertFalse(report["all_heads_match_pinned_sha"])

    def test_access_unavailable_is_not_mislabeled_as_drift(self):
        from urllib.error import HTTPError
        def denied(*_):
            raise HTTPError("https://api.github.com", 404, "Not Found", {}, None)
        report, good = MOD.preflight(DATA, verify_github=True, resolver=denied)
        self.assertFalse(good)
        self.assertFalse(report["all_heads_match_pinned_sha"])
        self.assertTrue(all(row["github_check_status"] == "unavailable" for row in report["services"]))
        self.assertTrue(all(row["github_head_matches_pin"] is None for row in report["services"]))
        self.assertTrue(all(row["github_http_status"] == 404 for row in report["services"]))

    def test_real_sha_difference_is_classified_as_drift(self):
        report, good = MOD.preflight(DATA, verify_github=True, resolver=lambda *_: "0" * 40)
        self.assertFalse(good)
        self.assertTrue(all(row["github_check_status"] == "drift" for row in report["services"]))

    def test_production_scope_is_rejected(self):
        invalid = copy.deepcopy(DATA)
        invalid["environment"] = "production"
        with self.assertRaises(MOD.PreflightError):
            MOD.ordered_services(invalid)

    def test_unpinned_sha_is_rejected(self):
        invalid = copy.deepcopy(DATA)
        invalid["services"][0]["sha"] = "main"
        with self.assertRaises(MOD.PreflightError):
            MOD.ordered_services(invalid)

    def test_missing_dependency_is_rejected(self):
        invalid = copy.deepcopy(DATA)
        invalid["services"][1]["depends_on"] = ["not-a-service"]
        with self.assertRaises(MOD.PreflightError):
            MOD.ordered_services(invalid)

    def test_dependency_cycle_is_rejected(self):
        invalid = copy.deepcopy(DATA)
        invalid["services"][0]["depends_on"] = ["deploy-engine"]
        with self.assertRaises(MOD.PreflightError):
            MOD.ordered_services(invalid)

    def test_duplicate_service_is_rejected(self):
        invalid = copy.deepcopy(DATA)
        invalid["services"][1]["service_id"] = invalid["services"][0]["service_id"]
        with self.assertRaises(MOD.PreflightError):
            MOD.ordered_services(invalid)

    def test_json_report_is_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            filename = Path(tmp) / "result.json"
            self.assertEqual(MOD.main(["--output", str(filename)]), 0)
            report = json.loads(filename.read_text())
            self.assertFalse(report["deployment_performed"])
            self.assertFalse(report["ready_to_promote"])
            self.assertEqual(len(report["services"]), 11)


if __name__ == "__main__":
    unittest.main()
