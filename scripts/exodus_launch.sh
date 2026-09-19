#!/bin/bash
# scripts/exodus_launch.sh
# Garcar Enterprise — Exodus launch orchestration
#
# Revenue targets in this script are planning targets, not guaranteed outcomes.
# This script does not create or store secrets; it expects them via the environment.

set -euo pipefail

echo "EXODUS — launching configured revenue infrastructure..."

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: required environment variable $name is not set." >&2
    exit 1
  fi
}

require_path() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    echo "ERROR: required path is missing: $path" >&2
    exit 1
  fi
}

# Required environment-backed credentials/config.
require_env SHOPIFY_WEBHOOK_SECRET
require_env APOLLO_API_KEY
require_env HUNTER_API_KEY
require_env HUBSPOT_TOKEN
require_env CLICKUP_TOKEN
require_env CLICKUP_SPACE_ID
require_env ASANA_TOKEN
require_env ASANA_WS

# Required local infrastructure declared by this launch plan.
require_path "infrastructure/vault"
require_path "docker/docker-compose.exodus.yml"
require_path "cron/master_scheduler.py"

# Vault + infrastructure.
terraform -chdir=infrastructure/vault apply -auto-approve
docker compose exec vault bash /vault/bootstrap_vault.sh

# Store runtime secrets in Vault; values are supplied only from the environment.
vault kv put garos/shopify webhook_secret="$SHOPIFY_WEBHOOK_SECRET"
vault kv put garos/apollo api_key="$APOLLO_API_KEY"
vault kv put garos/hunter api_key="$HUNTER_API_KEY"
vault kv put garos/hubspot access_token="$HUBSPOT_TOKEN"
vault kv put garos/clickup api_token="$CLICKUP_TOKEN" space_id="$CLICKUP_SPACE_ID"
vault kv put garos/asana personal_access_token="$ASANA_TOKEN" workspace_id="$ASANA_WS"

# Launch full swarm + revenue integrations.
docker compose -f docker/docker-compose.exodus.yml up -d --build

# Launch master cron scheduler.
docker compose exec orchestrator python cron/master_scheduler.py &

echo ""
echo "============================================================"
echo " EXODUS LIVE — configured revenue orchestration started"
echo " Shopify  -> Stripe   -> Supabase evidence ledger"
echo " Apollo   -> Hunter   -> HubSpot -> Stripe invoices"
echo " HF API   -> Stripe   -> metered subscriptions"
echo " ClickUp  -> Notion   -> client delivery automation"
echo " Coinbase -> Base     -> yield workflow (if separately configured)"
echo " Linear   -> AngelList-> investor pipeline"
echo " Slack    -> alerts   -> operational notifications"
echo "============================================================"
echo ""
echo "Month 1 planning target: $5,000"
echo "Month 3 planning target: $12,608"
echo "Month 6 objective: evaluate pre-seed readiness using measured MRR and operating evidence"
