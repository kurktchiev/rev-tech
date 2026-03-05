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
TOKEN_TEMPLATE="$TELEPORT_DIR/orchestrator-bot-token.yaml.template"
TOKEN_FILE="$TELEPORT_DIR/orchestrator-bot-token.yaml"

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

if [ ! -f "$TOKEN_TEMPLATE" ]; then
    echo "ERROR: Token template not found: $TOKEN_TEMPLATE"
    exit 1
fi

# ---------------------------------------------------------------------------
# Phase 1: Teleport resources
# ---------------------------------------------------------------------------
echo "--- Phase 1: Teleport Resources ---"

# Create role (idempotent with --force)
echo "Creating orchestrator-app-access role..."
tctl create -f "$TELEPORT_DIR/orchestrator-role.yaml" --force
echo ""

# Create bot (skip if already exists)
echo "Creating orchestrator-bot..."
if tctl bots ls | grep -q "orchestrator-bot"; then
    echo "  Bot orchestrator-bot already exists, skipping"
else
    tctl bots add orchestrator-bot --roles=orchestrator-app-access
fi
echo ""

# Generate join token from template with cluster JWKS and audience
echo "Extracting cluster JWKS..."
JWKS=$(kubectl get --raw /openid/v1/jwks)
if [ -z "$JWKS" ]; then
    echo "ERROR: Failed to extract JWKS from cluster"
    exit 1
fi
echo "  JWKS extracted successfully"

echo "Generating join token from template..."
cp "$TOKEN_TEMPLATE" "$TOKEN_FILE"
ESCAPED_JWKS=$(echo "$JWKS" | sed 's/"/\\"/g')
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s|'PASTE_JWKS_HERE'|'$ESCAPED_JWKS'|" "$TOKEN_FILE"
else
    sed -i "s|'PASTE_JWKS_HERE'|'$ESCAPED_JWKS'|" "$TOKEN_FILE"
fi
echo "  Generated $TOKEN_FILE"

echo "Creating join token in Teleport..."
tctl create -f "$TOKEN_FILE" --force
echo ""

# Verify
echo "Verifying Teleport resources..."
echo "  Bot:   $(tctl bots ls | grep orchestrator-bot | awk '{print $1}' || echo 'NOT FOUND')"
echo "  Token: $(tctl get token/orchestrator-bot-k8s-join --format=text 2>/dev/null | head -1 || echo 'NOT FOUND')"
echo ""

# ---------------------------------------------------------------------------
# Phase 2: Kubernetes resources
# ---------------------------------------------------------------------------
echo "--- Phase 2: Kubernetes Resources ---"

echo "Creating namespace and service account..."
kubectl apply -f "$K8S_DIR/namespace.yaml"

export ORCHESTRATOR_IMAGE="${ORCHESTRATOR_IMAGE:-registry.ellin.net/orchestrator:latest}"
export ORCHESTRATOR_TSH_DISCOVERY_QUERY="${ORCHESTRATOR_TSH_DISCOVERY_QUERY:-${TSH_DISCOVERY_QUERY:-labels[\"app-type\"] == \"specialist\" && labels[\"demo\"] == \"ai-agents\"}}"
ENVSUBST_VARS='${TELEPORT_PROXY} ${LLM_PROVIDER} ${OPENAI_MODEL} ${OPENAI_BASE_URL} ${OPENAI_API_KEY} ${ORCHESTRATOR_TSH_DISCOVERY_QUERY} ${ORCHESTRATOR_IMAGE}'

echo "Applying tbot init config..."
envsubst "$ENVSUBST_VARS" < "$K8S_DIR/orchestrator-tbot-init-config.yaml.template" | kubectl apply -f -

echo "Applying discovery script..."
kubectl apply -f "$K8S_DIR/orchestrator-discover-script.yaml"

echo "Applying orchestrator deployment..."
envsubst "$ENVSUBST_VARS" < "$K8S_DIR/orchestrator-deployment.yaml.template" | kubectl apply -f -

# ---------------------------------------------------------------------------
# Phase 3: Wait for rollout
# ---------------------------------------------------------------------------
echo ""
echo "--- Phase 3: Waiting for rollout ---"
kubectl rollout status deployment/orchestrator -n ai-agents --timeout=180s || {
    echo ""
    echo "WARNING: Deployment not ready within 180s"
    echo "Check logs:"
    echo "  kubectl logs -n ai-agents deployment/orchestrator -c discover-agents"
    echo "  kubectl logs -n ai-agents deployment/orchestrator -c tbot"
    echo "  kubectl logs -n ai-agents deployment/orchestrator -c orchestrator"
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "=== Setup Complete ==="
echo ""
echo "Watch init:         kubectl logs -n ai-agents deployment/orchestrator -c discover-agents"
echo "Watch tbot:         kubectl logs -n ai-agents deployment/orchestrator -c tbot -f"
echo "Watch orchestrator: kubectl logs -n ai-agents deployment/orchestrator -c orchestrator -f"
echo "Port-forward:       kubectl port-forward -n ai-agents svc/orchestrator 9000:9000"
echo ""
echo "Test:"
echo "  curl -s http://localhost:9000/.well-known/agent-card.json | jq .name"
echo ""
echo "Cleanup:"
echo "  ./infra/k8s/cleanup.sh"
echo ""
