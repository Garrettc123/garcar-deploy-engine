"""Opt-in read-only gateway->worker bridge; no FastAPI route or side effects on import."""
from __future__ import annotations
import hashlib
import hmac
import ipaddress
import json
import time
from urllib.parse import urlsplit
from urllib.request import build_opener, Request, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

from gateway.sovereign_diagnostics import issue_signed_diagnostic, _canonical, _sha

MAX_RESPONSE = 16384
DOMAIN = b"sovereign-receipt-v1\0"


class DiagnosticTransportError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def validate_endpoint(url: str) -> str:
    if not isinstance(url, str):
        raise DiagnosticTransportError("Invalid worker endpoint")
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise DiagnosticTransportError("Invalid worker endpoint")
    if parsed.scheme == "https":
        return url.rstrip("/")
    if parsed.scheme == "http":
        try:
            host = ipaddress.ip_address(parsed.hostname)
        except ValueError as exc:
            raise DiagnosticTransportError("Plain HTTP requires numeric loopback address") from exc
        if host.is_loopback:
            return url.rstrip("/")
    raise DiagnosticTransportError("Non-loopback transport requires TLS")


def verify_remote_receipt(envelope: dict, response: dict, receipt_key: bytes) -> dict:
    if not isinstance(receipt_key, bytes) or len(receipt_key) < 32:
        raise DiagnosticTransportError("Strong independent receipt key required")
    if not isinstance(response, dict) or set(response) != {"report", "signature"}:
        raise DiagnosticTransportError("Malformed worker receipt envelope")
    report, sig = response["report"], response["signature"]
    if not isinstance(report, dict) or set(report) != {"version", "directive_id", "directive_sha256", "issued_at", "receipt"}:
        raise DiagnosticTransportError("Malformed worker report")
    if not isinstance(sig, str) or len(sig) != 64 or not hmac.compare_digest(
        hmac.new(receipt_key, DOMAIN + _canonical(report), hashlib.sha256).hexdigest(), sig
    ):
        raise DiagnosticTransportError("Worker receipt signature mismatch")
    request = envelope["payload"]
    if (report["version"] != 1 or type(report["issued_at"]) is not int or
        abs(int(time.time()) - report["issued_at"]) > 180 or
        report["directive_id"] != request["directive_id"] or
        report["directive_sha256"] != _sha(request)):
        raise DiagnosticTransportError("Worker report is stale or not bound to directive")
    receipt = report["receipt"]
    keys = {"version", "directive_id", "directive_sha256", "task", "state", "audit_entry_sha256", "configuration_sha256", "receipt_sha256"}
    if not isinstance(receipt, dict) or set(receipt) != keys:
        raise DiagnosticTransportError("Malformed execution receipt")
    if (receipt["version"] != 1 or receipt["directive_id"] != request["directive_id"] or
        receipt["directive_sha256"] != _sha(request) or receipt["task"] != request["task"] or
        receipt["configuration_sha256"] != request["config_sha256"] or
        receipt["state"] not in {"succeeded", "failed", "audit_failure"} or
        receipt["receipt_sha256"] != _sha({k: v for k, v in receipt.items() if k != "receipt_sha256"})):
        raise DiagnosticTransportError("Execution receipt digest or scope mismatch")
    return receipt


def submit_authorized_diagnostic(authority_gate, tpa, config_path, dispatch_key: bytes,
                                 receipt_key: bytes, worker_endpoint: str, *, timeout_seconds: int = 45) -> dict:
    """Issue a signed directive after live AuthorityGate validation, then verify receipt.

    This does not register an API route, manage secrets, or deploy a worker.
    """
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60:
        raise DiagnosticTransportError("Invalid timeout")
    if not isinstance(receipt_key, bytes) or len(receipt_key) < 32 or hmac.compare_digest(dispatch_key, receipt_key):
        raise DiagnosticTransportError("Dispatch and receipt keys must be distinct")
    url = validate_endpoint(worker_endpoint) + "/v1/diagnostics/dispatch"
    envelope = issue_signed_diagnostic(authority_gate, tpa, config_path, dispatch_key,
                                      transport_scope="garcar-diagnostics-v1")
    request = Request(url, method="POST", data=_canonical(envelope),
                      headers={"Content-Type": "application/json"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout_seconds) as connection:
            if connection.status != 200:
                raise DiagnosticTransportError("Worker did not return successful receipt response")
            blob = connection.read(MAX_RESPONSE + 1)
    except HTTPError as exc:
        raise DiagnosticTransportError(f"Worker declined request (HTTP {exc.code})") from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise DiagnosticTransportError("Worker unavailable") from exc
    if len(blob) > MAX_RESPONSE:
        raise DiagnosticTransportError("Worker response exceeds size limit")
    try:
        decoded = json.loads(blob.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise DiagnosticTransportError("Worker returned invalid JSON") from exc
    return verify_remote_receipt(envelope, decoded, receipt_key)
