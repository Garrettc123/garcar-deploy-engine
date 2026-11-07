# Garcar Sovereign isolated staging activation

This is a **limited staging activation adapter**, not the complete Sovereign v7 runtime. The pinned source is in `worker.py.gz.b64` (gzip-compressed Python text, base64-encoded for connector transfer); `Dockerfile.sovereign` verifies the decoded script SHA-256 `c775e875d25d33741896d8ac0de9eb4acab0cc422411489c8a3327c66b26810b` at build time. To review: `base64 -d worker.py.gz.b64 | gunzip`.

**Scope:** unattended report writing to `/data/sovereign/latest.json`, SQLite reservations to `/data/sovereign/jobs.sqlite3`, SHA-256-linked audit to `/data/sovereign/audit.jsonl`. The app logs real execution receipts. Every cycle checks a separate HMAC operating grant bound to the exact executable hash, expiry and total run budget, and verifies volume, SQLite, audit integrity and replay state. Run interval: 600 seconds; hourly cap: 6; grant budget <= 1000.

**No external credentials or integrations:** worker does not send email, charge customers, trade, invoke shell supplied by agents or deploy production. Operating grant signature is only an additional admission check for this isolated staging workload, not sufficient passkey-based separation of duties for higher-impact actions. No public HTTP route. Persistent volume at exactly `/data` is required. Railway injects `RAILWAY_ENVIRONMENT`; do not spoof this in validation.

**Operator setup:** create an isolated Railway project, attach a 512MB persistent volume to /data, set strong random `SOVEREIGN_APPROVAL_KEY` and matching `SOVEREIGN_GRANT_JSON` as private service variables, set Dockerfile path `Dockerfile.sovereign`, connect this branch. Never commit keys/grants. Grant JSON must sign `garcar-sovereign-stage-v1\\0 + canonical_json(payload)` where payload has `version:1`, `task:'environment_report'`, pinned `code_sha256`, `issued_at`, `expires_at` (<=30 days), and `max_total_runs` (<=1000).

**Release gates:** inspect Railway build logs, first real receipt, persistent restart recovery, volume mount and audit state. CI runner failures on the existing GitHub account remain an independent blocker for promotion. Do not merge to main for staging activation.
