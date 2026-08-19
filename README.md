# Garcar Deploy Engine

**Zero-touch deployment system for all Garcar repos.**

## Activation

This repo is self-activating. Just run:

**GitHub Actions → 🏗️ Bootstrap Deploy Engine → Run workflow**

Bootstrap now runs:
- **Autokey system** — validates every registered deployment key in `/home/runner/work/garcar-deploy-engine/garcar-deploy-engine/registry/repos.json`
- **Auto secret system** — verifies the required GitHub deploy secrets (`RAILWAY_TOKEN`, `VERCEL_TOKEN`)

## Deploy Commands

**GitHub Actions → 🚀 Garcar Codeless Deploy Engine**

Enter plain English:
- `Deploy garcar-payments to production`
- `Deploy mars-api to staging`
- `Deploy revenue-intelligence-engine to production`

## Architecture

- `registry/repos.json` — All deployable repos, platforms, and target IDs.
- `engine/` — Orchestration logic parser.
- `.github/workflows/` — GitHub Actions automation.

**No manual secrets required** — uses GitHub org secrets extracted from local environments.
