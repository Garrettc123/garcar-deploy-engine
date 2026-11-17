# Garcar Enterprise — four-tier release plan (review only)

The pasted `deploy_all.sh` is **not safe to run unchanged**. This plan derives its Railway service IDs, GitHub repository names, branches, and commits from connected live configuration, not local folder guesses. It is a **read-only preflight**, not a deployment.

## The specific risks eliminated

- No `git reset --hard`, unpinned `git pull`, implicit `main` checkout, blanket `npm ci --omit=dev` before frontend compilation, or PM2 reload with fallback start.
- No silently skipped missing directories, guessed ports 3000–3007, blind dependency promotion, or GitHub workflow dispatch that quietly ignores failure.
- No production operations, Stripe calls, customer messages, AWS mutations, SQLite checkpoints, process kills, migrations or backups. WAL checkpointing is **not** a substitute for an application-coordinated SQLite backup and rollback plan.
- A Railway `SUCCESS` deployment is **not** proof of readiness, verified migrations, authorized task dispatch, signed webhook delivery, or downstream fulfillment.
- The sovereign-autonomy-worker in **separate** `garcar-sovereign-staging` remains **CRASHED**. Its signed operator grant must not be bypassed.

## Actual staged order

Source: `registry/stack_release_staging.json`. Dependencies are a proposed release-order policy, **not proof of code-level runtime coupling**.

1. **Control plane:** existing Redis prerequisite → `garcar-mesh-sync-core-canary` → `garcar-mesh-deploy-engine-canary`. Only proceed after actual dependency probes and signed approvals.
2. **Federated eight-node mesh:** `rhns-agent-core` first, then `mars-api`, `neural-mesh`, `TITAN-Autonomous-Business-Empire`, `nwu-protocol`, `garcar-payments`, `garcar-product-factory`, `garcar-revenue-os`. Their deployed SHA pins are recorded. This does **not** authorize changing the live payment receiver.
3. **Eve micro-kernel:** **unmapped/blocked**. `eve-chat-template` is private, but no confirmed host, process, SQLite data path, health endpoint, backup or deployment authority is available.
4. **Buyer UI:** existing Railway staging `review-workspace-sandbox`, currently on a pinned `garcar-revenue-os` source; the proposed `contractor-lead-recovery` repository was not found. Other production/UI surfaces remain independent.

The proposed `ueep-core` repo/AWS control-plane mapping was not found. No AWS deploy should be inferred.

## Reviewed CI-only branch descendant: not a deployment repin

`garcar-payments` staging remains pinned to `ea4de1f55275e18d52c3742f543eebfce4093e28`; branch HEAD is `cb87ff7a1c7ef2e1a1c4d8f23590d2fb6d48b2fa`. I independently inspected the exact GitHub comparison and old/new file contents. The single descendant commit modifies only `.github/workflows/ci.yml`; it broadens CI trigger branches and Python file paths while preserving the test job, read-only `contents: read` permission, and test command. It is **not** a runtime change and **does not modify the deployed SHA**.

The manifest records only this specific immutable descendant and the exact CI workflow path. On every GitHub source verification, the checker re-fetches the public branch HEAD and the GitHub compare API and requires: HEAD equals the exact reviewed SHA; exactly one commit ahead; zero commits behind; merge base equals deployed SHA; exactly one changed file, `.github/workflows/ci.yml`, with status `modified`. Otherwise it reports `drift` or `unavailable` and fails closed. For this one check, `github_check_status=reviewed_ci_only` is acceptable **source-review evidence**, but `github_head_matches_pin=false` and `all_heads_match_pinned_sha=false` remain truthful.

No exception applies to future commits, any other file, or any other service. This review is not release authorization, an application canary, or evidence the service was redeployed.

## GitHub Actions source-access boundary

The staging manifest maps **five private repositories**: `garcar-enterprise-sync-core`, `rhns-agent-core`, `garcar-product-factory`, `garcar-revenue-os` (used by two services). The deploy-engine repository's ephemeral GitHub Actions token cannot inspect their refs; a 404 in that job is **source access unavailable**, not proof of source drift. The read-only preflight fails closed and reports `github_check_status=unavailable`. These private source pins **were separately checked** via the connected GitHub app when this draft was prepared, but that is point-in-time evidence rather than permission for the CI workflow.

The one public payments descendant is now reviewed through the immutable CI-only comparison policy. The five entries for private repositories remain `github_check_status=unavailable` in the repository-scoped Actions job; the aggregate source review therefore **still fails closed**. No full-stack promotion is authorized. Do not create or expose personal access tokens solely to make this check green.

## Termux / Linux read-only commands

```bash
python3 -m unittest discover -s tests -p 'test_stack_release_preflight.py' -v
python3 scripts/stack_release_preflight.py --output /tmp/garcar-stack-plan.json
python3 scripts/stack_release_preflight.py --verify-github --output /tmp/garcar-stack-pin-check.json
```

The second command validates the local manifest. The third checks public GitHub branch HEADs and, for the single reviewed payments exception, its exact diff ancestry; it **exits 2 on unreviewed drift or read errors**. Because five service entries reference private repositories, a public-only runner is still expected to fail with their source access `unavailable` rather than inventing a pass. The report always states `release_action=NONE`, `deployment_performed=false`, and `ready_to_promote=false`. No downloaded source is executed and no credentials are requested.

## Before any real deployment

Explicitly approve a **specific** staging or production target set, exact reviewed SHA and change window. Confirm signed operator grant, application-level health probes, migration plan/rollback, backup evidence, persistent database ownership, zero pending unreviewed patches, and staged canary metrics. Roll back by **approved source or deployment revision**, not by resetting files or silently spawning a replacement process. Payment receiver release retains separate Stripe signature and authenticated fulfillment gates. The user's earlier deployment approval applied only to the single independent-CI staging service, not this stack.
