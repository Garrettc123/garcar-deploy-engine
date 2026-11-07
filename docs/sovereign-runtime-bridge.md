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


## v3: HTTP diagnostic transport (review branch)

- `gateway/sovereign_transport.py`: opt-in, no route registration. Validates AuthorityGate, signs a 90-second diagnostic with explicit `garcar-diagnostics-v1` scope, sends to a TLS HTTPS worker (loopback HTTP permitted only for local tests), forbids redirects, and verifies an independently HMAC-signed receipt matched to the directive and task.
- `gateway/authority.py`: now rejects unknown action classes, non-allowlisted diagnostic task scope, nonfinite confidence, and invalid Stripe charge amounts. Existing action-class usage must be regression tested before merge.
- `gateway/sovereign_diagnostics.py`: accepts `transport_scope="garcar-diagnostics-v1"` for the independent worker, retaining `local` for v2 callers.
- `tests/test_sovereign_transport.py`: tests signing, mocked transport, receipt integrity and denied gateway authorization.
- The worker implementation, isolated Dockerfile and durable /data task registry are available in **Sovereign Execution Engine v3** archive. They have not been added to this deployment repository or provisioned on Railway. Do not assume deploying this repository starts a worker.

### Verified vs pending

The standalone v3 worker and gateway-to-loopback-worker test suite ran locally: **53 tests passed**. The repository's GitHub Actions workflow was updated to run three test files, but current GitHub Actions attempts are marked FAILED with zero visible steps and unavailable job logs. Thus **repository CI has not been verified passing**. The existing Railway staging project has other pending changes; do not accept, discard or overwrite those changes as part of this PR.

No production credentials, network endpoint, secret sharing, Railway service provisioning, or business/payment automation are included. Before a real staging run, review and implement TLS ingress, non-root isolation, a separately approved volume-backed worker, durable receipts and gateway access controls.
