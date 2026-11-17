# Sovereign v7 — grant-authorized autonomous operations (review note)

**Status: local reference package validated, remote service NOT deployed.**

The v7 standalone runtime changes the v6 controller from observe-only to two modes:
- `observe`: unchanged read-only diagnostic allowlist.
- `operate`: reviewed, explicitly classified mutating task registry, scheduling, crash-persistent reservations, per-task hashes, and an operator-signed grant that authorizes repeated unattended execution within a limited duration and budget.

Local release proof:
- Clean extraction: **96 Python standard-library tests passed**.
- Real signed autonomously scheduled `runtime_report` write succeeded.
- Report file created under `.sovereign/reports/latest.json`.
- Audit-chain verification passed.
- Immediate repeat returned `no_due_authorized_job`.
- 34 source/config/test file SHA-256 hashes matched the included integrity manifest.
- ZIP SHA-256: `dd6eeb1068e6e1259e92a206ce499779420269284d8bcbafb13aed5c70518811`.

Runtime components in the standalone v7 archive:
`sovereign_autonomy.py`, `sovereign_dispatch.py`, `sovereign_engine.py`, `sovereign_http.py`, `sovereign_report.py`,
`sovereign_tasks_operate.json`, `autonomy_operate_plan.json`, `OPERATE.md`, tests, and manifest.

Important grant details:
- HMAC-SHA256 authorization is bound to config/plan/task digests, grant UUID, expiration and a maximum total run count.
- Two distinct keys are required for dispatch and operator grant signing.
- Low-impact registered write and deployment tasks can be granted for up to 30 days, subject to a rolling hourly cap.
- Financial, communication and irreversible categories require a one-shot grant with a <=1h lifetime.
- This is **not a sandbox** and HMAC signatures do **not** provide strong separation of duties when an executing worker holds a signing-capable key.

**Release gates not satisfied**:
1. The complete v7 source archive is not yet committed to this GitHub repository. Do not pretend this doc alone is deployable.
2. GitHub Actions CI was last reported failing before job steps. Runner/account issue remains unverified.
3. No dedicated Railway worker or volume has been provisioned; unrelated staged Railway changes are preserved.
4. No production operator passkey grant issuer, asymmetric signature verifier, endpoint isolation or real external write adapter is deployed.
5. No Stripe charges, email sends, GitHub repository mutations, or production deployments have been performed by this autonomous controller.

Keep the parent PR as **draft**, maintain production authority boundaries and require evidence-backed integration testing before release.
