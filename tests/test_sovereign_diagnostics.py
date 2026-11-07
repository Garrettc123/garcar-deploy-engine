import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway.sovereign_diagnostics import REQUIRED_CHECKS, issue_signed_diagnostic


KEY = b"test-only-signing-key-that-is-at-least-thirty-two-bytes-long"


def fixture(tmp_path):
    config = {
        "version": 1, "workspace": ".",
        "tasks": {
            "environment_check": {"mutating": False, "steps": [{"argv": ["python3", "--version"]}]},
            "repository_status": {"mutating": False, "steps": [{"argv": ["git", "status"]}]},
            "danger": {"mutating": True, "steps": [{"argv": ["true"]}]},
        },
    }
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(config))
    tpa = SimpleNamespace(action_class="SOVEREIGN_DIAGNOSTIC",
                          scope={"task_name": "environment_check"}, action_id="act_1")
    verdict = SimpleNamespace(verdict="AUTHORIZED",
                              code=SimpleNamespace(value="AUTHORIZED"),
                              checks={k: "PASS" for k in REQUIRED_CHECKS})
    gate = SimpleNamespace(validate=lambda _: verdict)
    return path, config, tpa, verdict, gate


def test_signed_diagnostic_is_well_formed(tmp_path):
    path, config, tpa, verdict, gate = fixture(tmp_path)
    envelope = issue_signed_diagnostic(gate, tpa, path, KEY)
    payload = envelope["payload"]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    expected = hmac.new(KEY, canonical, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(envelope["signature"], expected)
    assert payload["mutating"] is False
    assert payload["expires_at"] - payload["issued_at"] == 90
    assert payload["task"] == "environment_check"


def test_rejected_gateway_verdict_blocks_issuance(tmp_path):
    path, config, tpa, verdict, gate = fixture(tmp_path)
    verdict.verdict = "REJECTED"
    with pytest.raises(PermissionError):
        issue_signed_diagnostic(gate, tpa, path, KEY)


def test_missing_identity_check_blocks_issuance(tmp_path):
    path, config, tpa, verdict, gate = fixture(tmp_path)
    verdict.checks["identity"] = "FAIL"
    with pytest.raises(PermissionError):
        issue_signed_diagnostic(gate, tpa, path, KEY)


def test_mutating_task_blocks_issuance(tmp_path):
    path, config, tpa, verdict, gate = fixture(tmp_path)
    tpa.scope["task_name"] = "danger"
    with pytest.raises(PermissionError):
        issue_signed_diagnostic(gate, tpa, path, KEY)


def test_deployment_action_cannot_sign_diagnostic(tmp_path):
    path, config, tpa, verdict, gate = fixture(tmp_path)
    tpa.action_class = "DEPLOYMENT"
    with pytest.raises(PermissionError):
        issue_signed_diagnostic(gate, tpa, path, KEY)


def test_short_key_blocks_issuance(tmp_path):
    path, config, tpa, verdict, gate = fixture(tmp_path)
    with pytest.raises(PermissionError):
        issue_signed_diagnostic(gate, tpa, path, b"weak")


def test_readonly_classification_must_match_registry(tmp_path):
    path, config, tpa, verdict, gate = fixture(tmp_path)
    config["tasks"]["environment_check"]["mutating"] = True
    path.write_text(json.dumps(config))
    with pytest.raises(PermissionError):
        issue_signed_diagnostic(gate, tpa, path, KEY)
