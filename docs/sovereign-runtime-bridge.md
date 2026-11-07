# Sovereign Execution Runtime — Gateway Bridge (review-only)

The optional `gateway/sovereign_diagnostics.py` adapter is intentionally **not mounted on an HTTP route**, and does not execute a subprocess, deploy code, contact Stripe, or send messages. It issues a signed envelope for a **read-only allowlisted diagnostic** after a caller provides a live, validated `AuthorityGate` context.

## Requirements

1. A real `AuthorityGate` constructed with authenticated session and current world-state backing services. Do not use a permissive stub in production.
2. A vetted operator-controlled `sovereign_tasks.json` registry from Sovereign Execution Engine v2.
3. A securely provisioned HMAC signing key (>=32 bytes) delivered to the gateway and the isolated executor. Never expose it in JavaScript frontend, a public route, logs, or source.
4. A separately provisioned Linux/POSIX executor host with the `sovereign_dispatch.py` process and a durable SQLite replay ledger.
5. Explicit task scope: `TPA(action_class="SOVEREIGN_DIAGNOSTIC", scope={"task_name":"environment_check"}, ...)`. Only `environment_check` and `repository_status` are allowlisted.

## Contract

`issue_signed_diagnostic(authority_gate, tpa, config_path, signing_key)` returns:

- `payload.directive_id`: one unique UUID;
- `payload.task`: pre-registered diagnostic;
- `payload.config_sha256` and `task_sha256`: signed digests of exact registry definitions;
- `payload.issued_at` and `expires_at`: 90-second lifetime;
- `payload.mutating`: strictly false;
- `payload.scope`: `local`;
- `signature`: HMAC-SHA256 over canonical JSON payload.

The separate executor *must independently* revalidate the signature, schema, task registry digest, expiration, scope and replay state, then record audited process outcomes. An issued envelope is not proof of execution.

## Out of scope / open integration work

- No new production API routes or webhook behavior.
- No automatic deployments, production shell execution, charging, messaging, or agent access.
- No proof that the remote gateway and the local executor share a trusted secret.
- Before enabling a network transport, add strong machine identities (e.g., mTLS), gateway-authenticated operator sessions, per-action role checks, rate limits, durable receipt delivery and redaction. HMAC proves possession of a secret, **not a specific human identity**.
- Existing Garcar `AuthorityGate` does not implement a dedicated `SOVEREIGN_DIAGNOSTIC` policy. This bridge provides a second narrow allowlist and explicitly blocks mutating tasks, but the gateway's session and tenant authorization must be verified before connection.

The complete independent reference engine, dispatcher, GitHub inventory probe, and 37 passing standard-library tests are available in the downloadable Sovereign Execution Engine v2 package from the accompanying ChatGPT implementation. The current PR carries only a reviewable gateway bridge and its tests.
