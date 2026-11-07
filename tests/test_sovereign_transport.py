import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest

from gateway.sovereign_diagnostics import issue_signed_diagnostic, _canonical, _sha
from gateway.sovereign_transport import (
    DiagnosticTransportError, validate_endpoint,
    verify_remote_receipt, submit_authorized_diagnostic,
)

DISPATCH_KEY = b"test-dispatch-key-longer-than-thirty-two-bytes"
RECEIPT_KEY = b"test-receipt-key-different-and-thirty-two-bytes"


def fixture(tmp_path):
    config = {"version": 1, "workspace": ".", "tasks": {
        "environment_check": {"mutating": False, "steps": [{"argv": ["python3", "--version"]}]},
        "repository_status": {"mutating": False, "steps": [{"argv": ["git", "status"]}]},
    }}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    tpa = SimpleNamespace(action_class="SOVEREIGN_DIAGNOSTIC",
                          action_id="tpa_test_1", scope={"task_name": "environment_check"})
    checks = dict.fromkeys(("identity", "scope", "destination", "confidence", "world_state"), "PASS")
    verdict = SimpleNamespace(verdict="AUTHORIZED", code=SimpleNamespace(value="AUTHORIZED"), checks=checks)
    gate = SimpleNamespace(validate=lambda _: verdict)
    return path, tpa, gate


def make_result(envelope):
    p = envelope["payload"]
    receipt = {
        "version": 1, "directive_id": p["directive_id"], "directive_sha256": _sha(p),
        "task": p["task"], "state": "succeeded", "audit_entry_sha256": "a" * 64,
        "configuration_sha256": p["config_sha256"],
    }
    receipt["receipt_sha256"] = _sha(receipt)
    report = {
        "version": 1, "directive_id": p["directive_id"], "directive_sha256": _sha(p),
        "issued_at": int(time.time()), "receipt": receipt,
    }
    signature = hmac.new(RECEIPT_KEY, b"sovereign-receipt-v1\\0" + _canonical(report),
                         hashlib.sha256).hexdigest()
    return {"report": report, "signature": signature}


def test_transport_endpoint_rejects_remote_plain_http():
    for target in ("http://service.railway.internal", "http://10.2.3.4:8383", "https://user:password@example.com"):
        with pytest.raises(DiagnosticTransportError):
            validate_endpoint(target)
    assert validate_endpoint("https://worker.example.com") == "https://worker.example.com"


def test_valid_signed_receipt(tmp_path):
    path, tpa, gate = fixture(tmp_path)
    env = issue_signed_diagnostic(gate, tpa, path, DISPATCH_KEY, transport_scope="garcar-diagnostics-v1")
    assert env["payload"]["scope"] == "garcar-diagnostics-v1"
    assert verify_remote_receipt(env, make_result(env), RECEIPT_KEY)["state"] == "succeeded"


def test_tampered_receipt_denied(tmp_path):
    path, tpa, gate = fixture(tmp_path)
    env = issue_signed_diagnostic(gate, tpa, path, DISPATCH_KEY, transport_scope="garcar-diagnostics-v1")
    signed = make_result(env)
    signed["report"]["receipt"]["state"] = "failed"
    with pytest.raises(DiagnosticTransportError):
        verify_remote_receipt(env, signed, RECEIPT_KEY)


def test_gateway_transport_roundtrip_mocked(tmp_path, monkeypatch):
    from gateway import sovereign_transport as transport
    path, tpa, gate = fixture(tmp_path)

    class Result:
        status = 200
        def __init__(self, body):
            self.body = body
        def read(self, _size):
            return self.body
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "https://worker.example.com/v1/diagnostics/dispatch"
            assert timeout == 45
            envelope = json.loads(request.data)
            return Result(_canonical(make_result(envelope)))

    monkeypatch.setattr(transport, "build_opener", lambda *_: Opener())
    result = submit_authorized_diagnostic(gate, tpa, path, DISPATCH_KEY, RECEIPT_KEY, "https://worker.example.com")
    assert result["state"] == "succeeded"


def test_worker_cannot_be_called_without_gateway_approval(tmp_path, monkeypatch):
    from gateway import sovereign_transport as transport
    path, tpa, gate = fixture(tmp_path)
    gate.validate(tpa).verdict = "REJECTED"
    called = []
    monkeypatch.setattr(transport, "build_opener", lambda *_: called.append(True))
    with pytest.raises(PermissionError):
        submit_authorized_diagnostic(gate, tpa, path, DISPATCH_KEY, RECEIPT_KEY, "https://worker.example.com")
    assert not called
