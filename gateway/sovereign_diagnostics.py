"""Optional Garcar gateway bridge: sign read-only local-runtime diagnostics.

This module is deliberately NOT registered as an HTTP route. Importing it does
not trigger work; an authenticated authority context must be supplied by caller.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import uuid
import time
from pathlib import Path

ALLOWED_TASKS = frozenset({"environment_check", "repository_status"})
REQUIRED_CHECKS = ("identity", "scope", "destination", "confidence", "world_state")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def issue_signed_diagnostic(authority_gate, tpa, config_path: str | Path, signing_key: bytes, *, transport_scope: str = "local") -> dict:
    """Produce dispatcher-compatible signed envelope; does not execute anything."""
    if getattr(tpa, "action_class", None) != "SOVEREIGN_DIAGNOSTIC":
        raise PermissionError("Only SOVEREIGN_DIAGNOSTIC is supported")
    scope = getattr(tpa, "scope", None)
    task_name = scope.get("task_name") if isinstance(scope, dict) else None
    if not isinstance(task_name, str) or task_name not in ALLOWED_TASKS or scope != {"task_name": task_name}:
        raise PermissionError("Task is not an allowlisted read-only diagnostic")
    verdict = authority_gate.validate(tpa)
    code = getattr(getattr(verdict, "code", None), "value", None)
    if getattr(verdict, "verdict", None) != "AUTHORIZED" or code != "AUTHORIZED":
        raise PermissionError("Gateway authorization failed")
    checks = getattr(verdict, "checks", None)
    if not isinstance(checks, dict) or any(checks.get(check) != "PASS" for check in REQUIRED_CHECKS):
        raise PermissionError("Gateway did not pass all authority checks")
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        raise PermissionError("Missing strong signing key")
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    task = config.get("tasks", {}).get(task_name)
    if config.get("version") != 1 or not isinstance(task, dict) or task.get("mutating") is not False:
        raise PermissionError("Task definition is absent or mutating")
    action_id = getattr(tpa, "action_id", None)
    if not isinstance(action_id, str) or not action_id or len(action_id) > 96:
        raise PermissionError("Invalid authority action ID")
    if transport_scope not in {"local", "garcar-diagnostics-v1"}:\n        raise PermissionError("Unsupported diagnostic transport scope")\n    now = int(time.time())
    payload = {
        "version": 1,
        "directive_id": str(uuid.uuid4()),
        "task": task_name,
        "config_sha256": _sha(config),
        "task_sha256": _sha(task),
        "issued_at": now,
        "expires_at": now + 90,
        "mutating": False,
        "issuer": "garcar-gateway:" + action_id,
        "scope": transport_scope,
    }
    signature = hmac.new(signing_key, _canonical(payload), hashlib.sha256).hexdigest()
    return {"payload": payload, "signature": signature}
