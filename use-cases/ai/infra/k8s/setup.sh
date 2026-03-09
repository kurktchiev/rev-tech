#!/usr/bin/env bash
# Setup: Orchestrator on K8s with tbot sidecar
#
# This script handles everything:
#   1. Creates Teleport resources (role, bot, join token with JWKS)
#   2. Applies Kubernetes manifests (namespace, SA, configmap, deployment)
#
# Prerequisites:
#   - kubectl connected to target cluster
#   - tctl available and authenticated (tsh login)
#   - Orchestrator image pushed to registry.ellin.net/orchestrator:latest
#   - Specialist agents running and registered in Teleport
#
# Usage:
#   ./infra/k8s/setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/../.."
K8S_DIR="$SCRIPT_DIR"
TELEPORT_DIR="$K8S_DIR/teleport-resources"

# Load .env if present
if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a; source "$PROJECT_DIR/.env"; set +a
fi
ORCH_TOKEN_TEMPLATE="$TELEPORT_DIR/orchestrator-bot-token.yaml.template"
ORCH_TOKEN_FILE="$TELEPORT_DIR/orchestrator-bot-token.yaml"
AGENT_DB_TOKEN_TEMPLATE="$TELEPORT_DIR/agent-db-bot-token.yaml.template"
AGENT_DB_TOKEN_FILE="$TELEPORT_DIR/agent-db-bot-token.yaml"
AGENT_SSH_TOKEN_TEMPLATE="$TELEPORT_DIR/agent-ssh-bot-token.yaml.template"
AGENT_SSH_TOKEN_FILE="$TELEPORT_DIR/agent-ssh-bot-token.yaml"

echo "=== AI Agents Orchestrator Setup ==="
echo ""

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
echo "--- Pre-flight checks ---"

if ! kubectl cluster-info &>/dev/null; then
    echo "ERROR: Cannot connect to Kubernetes cluster"
    echo "Please ensure kubectl is configured and you have cluster access"
    exit 1
fi
echo "Kubernetes cluster: $(kubectl config current-context)"

if ! command -v tctl &>/dev/null; then
    echo "ERROR: tctl not found in PATH"
    exit 1
fi

if ! tctl status &>/dev/null; then
    echo "ERROR: Not authenticated to Teleport (run: tsh login)"
    exit 1
fi
echo "Teleport cluster:  $(tctl status | grep 'Cluster' | head -1 | awk '{print $2}')"
echo ""

for tmpl in "$ORCH_TOKEN_TEMPLATE" "$AGENT_DB_TOKEN_TEMPLATE" "$AGENT_SSH_TOKEN_TEMPLATE"; do
    if [ ! -f "$tmpl" ]; then
        echo "ERROR: Token template not found: $tmpl"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# Phase 1: Teleport resources
# ---------------------------------------------------------------------------
echo "--- Phase 1: Teleport Resources ---"

# Create roles (idempotent with --force)
echo "Creating orchestrator-app-access role..."
tctl create -f "$TELEPORT_DIR/orchestrator-role.yaml" --force

echo "Creating agent-db-access role..."
tctl create -f "$TELEPORT_DIR/agent-db-role.yaml" --force

echo "Creating agent-ssh-access role..."
tctl create -f "$TELEPORT_DIR/agent-ssh-role.yaml" --force
echo ""

# Create bots (skip if already exists)
echo "Creating orchestrator-bot..."
if tctl bots ls | grep -q "orchestrator-bot"; then
    echo "  Bot orchestrator-bot already exists, skipping"
else
    tctl bots add orchestrator-bot --roles=orchestrator-app-access
fi

echo "Creating agent-db-bot..."
if tctl bots ls | grep -q "agent-db-bot"; then
    echo "  Bot agent-db-bot already exists, skipping"
else
    tctl bots add agent-db-bot --roles=agent-db-access
fi

echo "Creating agent-ssh-bot..."
if tctl bots ls | grep -q "agent-ssh-bot"; then
    echo "  Bot agent-ssh-bot already exists, skipping"
else
    tctl bots add agent-ssh-bot --roles=agent-ssh-access
fi
echo ""

# Generate join tokens from templates with cluster JWKS
echo "Extracting cluster JWKS..."
JWKS=$(kubectl get --raw /openid/v1/jwks)
if [ -z "$JWKS" ]; then
    echo "ERROR: Failed to extract JWKS from cluster"
    exit 1
fi
echo "  JWKS extracted successfully"
ESCAPED_JWKS=$(echo "$JWKS" | sed 's/"/\\"/g')

for PAIR in "orchestrator:$ORCH_TOKEN_TEMPLATE:$ORCH_TOKEN_FILE" "agent-db:$AGENT_DB_TOKEN_TEMPLATE:$AGENT_DB_TOKEN_FILE" "agent-ssh:$AGENT_SSH_TOKEN_TEMPLATE:$AGENT_SSH_TOKEN_FILE"; do
    IFS=: read -r BOT_LABEL TMPL_PATH TOKEN_PATH <<< "$PAIR"
    echo "Generating $BOT_LABEL join token from template..."
    cp "$TMPL_PATH" "$TOKEN_PATH"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|'PASTE_JWKS_HERE'|'$ESCAPED_JWKS'|" "$TOKEN_PATH"
    else
        sed -i "s|'PASTE_JWKS_HERE'|'$ESCAPED_JWKS'|" "$TOKEN_PATH"
    fi
    echo "  Generated $TOKEN_PATH"
    echo "Creating join token in Teleport..."
    tctl create -f "$TOKEN_PATH" --force
done
echo ""

# Verify
echo "Verifying Teleport resources..."
echo "  Orchestrator bot:   $(tctl bots ls | grep orchestrator-bot | awk '{print $1}' || echo 'NOT FOUND')"
echo "  Orchestrator token: $(tctl get token/orchestrator-bot-k8s-join --format=text 2>/dev/null | head -1 || echo 'NOT FOUND')"
echo "  Agent-DB bot:       $(tctl bots ls | grep agent-db-bot | awk '{print $1}' || echo 'NOT FOUND')"
echo "  Agent-DB token:     $(tctl get token/agent-db-bot-k8s-join --format=text 2>/dev/null | head -1 || echo 'NOT FOUND')"
echo "  Agent-SSH bot:      $(tctl bots ls | grep agent-ssh-bot | awk '{print $1}' || echo 'NOT FOUND')"
echo "  Agent-SSH token:    $(tctl get token/agent-ssh-bot-k8s-join --format=text 2>/dev/null | head -1 || echo 'NOT FOUND')"
echo ""

# ---------------------------------------------------------------------------
# Phase 2: Kubernetes resources
# ---------------------------------------------------------------------------
echo "--- Phase 2: Kubernetes Resources ---"

echo "Creating namespace and service account..."
kubectl apply -f "$K8S_DIR/namespace.yaml"

export ORCHESTRATOR_IMAGE="${ORCHESTRATOR_IMAGE:-registry.ellin.net/orchestrator:latest}"
export AGENT_DB_IMAGE="${AGENT_DB_IMAGE:-registry.ellin.net/agent-db:latest}"
export AGENT_SSH_IMAGE="${AGENT_SSH_IMAGE:-registry.ellin.net/agent-ssh:latest}"
export ORCHESTRATOR_TSH_DISCOVERY_QUERY="${ORCHESTRATOR_TSH_DISCOVERY_QUERY:-${TSH_DISCOVERY_QUERY:-labels[\"app-type\"] == \"specialist\" && labels[\"demo\"] == \"ai-agents\"}}"
export ORCHESTRATOR_TSH_DB_DISCOVERY_QUERY="${ORCHESTRATOR_TSH_DB_DISCOVERY_QUERY:-labels[\"demo\"] == \"ai-agents\"}"
export AGENT_DB_TSH_DISCOVERY_QUERY="${AGENT_DB_TSH_DISCOVERY_QUERY:-labels[\"env\"] == \"dev\" && labels[\"owner\"] == \"homelab\"}"
ENVSUBST_VARS='${TELEPORT_PROXY} ${LLM_PROVIDER} ${OPENAI_MODEL} ${OPENAI_BASE_URL} ${OPENAI_API_KEY} ${ORCHESTRATOR_TSH_DISCOVERY_QUERY} ${ORCHESTRATOR_TSH_DB_DISCOVERY_QUERY} ${ORCHESTRATOR_IMAGE} ${AGENT_DB_IMAGE} ${AGENT_DB_TSH_DISCOVERY_QUERY} ${AGENT_SSH_IMAGE}'

echo "--- Orchestrator ---"
echo "Applying orchestrator tbot init config..."
envsubst "$ENVSUBST_VARS" < "$K8S_DIR/orchestrator-tbot-init-config.yaml.template" | kubectl apply -f -

echo "Applying orchestrator discovery script..."
kubectl apply -f "$K8S_DIR/orchestrator-discover-script.yaml"

echo "Applying orchestrator deployment..."
envsubst "$ENVSUBST_VARS" < "$K8S_DIR/orchestrator-deployment.yaml.template" | kubectl apply -f -

echo ""
echo "--- Agent DB ---"
echo "Applying agent-db tbot init config..."
envsubst "$ENVSUBST_VARS" < "$K8S_DIR/agent-db-tbot-init-config.yaml.template" | kubectl apply -f -

echo "Applying agent-db discovery script..."
kubectl apply -f "$K8S_DIR/agent-db-discover-script.yaml"

echo "Applying agent-db deployment..."
envsubst "$ENVSUBST_VARS" < "$K8S_DIR/agent-db-deployment.yaml.template" | kubectl apply -f -

echo ""
echo "--- Agent SSH ---"
echo "Applying agent-ssh tbot config..."
envsubst "$ENVSUBST_VARS" < "$K8S_DIR/agent-ssh-tbot-init-config.yaml.template" | kubectl apply -f -

echo "Applying agent-ssh deployment..."
envsubst "$ENVSUBST_VARS" < "$K8S_DIR/agent-ssh-deployment.yaml.template" | kubectl apply -f -

# ---------------------------------------------------------------------------
# Phase 3: Wait for rollout
# ---------------------------------------------------------------------------
echo ""
echo "--- Phase 3: Waiting for rollout ---"
for DEPLOY in orchestrator agent-db agent-ssh; do
    echo "Waiting for $DEPLOY..."
    kubectl rollout status deployment/$DEPLOY -n ai-agents --timeout=180s || {
        echo ""
        echo "WARNING: $DEPLOY not ready within 180s"
        echo "Check logs:"
        echo "  kubectl logs -n ai-agents deployment/$DEPLOY -c tbot"
        echo "  kubectl logs -n ai-agents deployment/$DEPLOY -c ${DEPLOY//-/_}"
    }
done

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "=== Setup Complete ==="
echo ""
echo "Watch orchestrator init:  kubectl logs -n ai-agents deployment/orchestrator -c discover-agents"
echo "Watch orchestrator tbot: kubectl logs -n ai-agents deployment/orchestrator -c tbot -f"
echo "Watch orchestrator:      kubectl logs -n ai-agents deployment/orchestrator -c orchestrator -f"
echo "Watch agent-db init:     kubectl logs -n ai-agents deployment/agent-db -c discover-databases"
echo "Watch agent-db tbot:     kubectl logs -n ai-agents deployment/agent-db -c tbot -f"
echo "Watch agent-db:          kubectl logs -n ai-agents deployment/agent-db -c agent-db -f"
echo "Watch agent-ssh tbot:    kubectl logs -n ai-agents deployment/agent-ssh -c tbot -f"
echo "Watch agent-ssh:         kubectl logs -n ai-agents deployment/agent-ssh -c agent-ssh -f"
echo "Port-forward orch:       kubectl port-forward -n ai-agents svc/orchestrator 9000:9000"
echo "Port-forward agent-db:   kubectl port-forward -n ai-agents svc/agent-db 8080:8080"
echo "Port-forward agent-ssh:  kubectl port-forward -n ai-agents svc/agent-ssh 8080:8080"
echo ""
echo "Test:"
echo "  curl -s http://localhost:9000/.well-known/agent-card.json | jq .name"
echo ""
echo "Cleanup:"
echo "  ./infra/k8s/cleanup.sh"
echo ""
