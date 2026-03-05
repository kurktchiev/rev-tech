#!/usr/bin/env bash
# Cleanup: Remove orchestrator deployment and Teleport resources
#
# This script removes:
#   - Kubernetes resources (deployment, service, configmap, SA, namespace)
#   - Teleport resources (bot, role, join token)
#   - Local generated token file
#
# Usage:
#   ./infra/k8s/cleanup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$SCRIPT_DIR"
TELEPORT_DIR="$K8S_DIR/teleport-resources"
TOKEN_FILE="$TELEPORT_DIR/orchestrator-bot-token.yaml"

echo "=== AI Agents Orchestrator Cleanup ==="
echo ""
echo "This will remove:"
echo "  - Kubernetes: ai-agents namespace (deployment, service, configmap, SA)"
echo "  - Teleport:   orchestrator-bot, orchestrator-app-access role, join token"
echo "  - Local:      generated token file"
echo ""

# Check cluster connection
if ! kubectl cluster-info &>/dev/null; then
    echo "WARNING: Cannot connect to Kubernetes cluster, skipping K8s cleanup"
else
    echo "Kubernetes cluster: $(kubectl config current-context)"
fi
echo ""

read -p "Continue with cleanup? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Cleanup cancelled"
    exit 0
fi

# ---------------------------------------------------------------------------
# Phase 1: Kubernetes resources
# ---------------------------------------------------------------------------
echo ""
echo "--- Phase 1: Kubernetes Resources ---"

if kubectl get namespace ai-agents &>/dev/null; then
    echo "Deleting ai-agents namespace (all resources)..."
    kubectl delete namespace ai-agents --timeout=60s || echo "WARNING: namespace deletion timed out"
    echo "Waiting for namespace to be fully deleted..."
    kubectl wait --for=delete namespace/ai-agents --timeout=120s 2>/dev/null || echo "WARNING: namespace may still be terminating"
else
    echo "No ai-agents namespace found, skipping"
fi

# ---------------------------------------------------------------------------
# Phase 2: Teleport resources
# ---------------------------------------------------------------------------
echo ""
echo "--- Phase 2: Teleport Resources ---"

if command -v tctl &>/dev/null && tctl status &>/dev/null; then
    echo "Deleting join token..."
    tctl rm token/orchestrator-bot-k8s-join 2>/dev/null || echo "  Token not found or already deleted"

    echo "Deleting bot..."
    tctl bots rm orchestrator-bot 2>/dev/null || echo "  Bot not found or already deleted"

    echo "Deleting role..."
    tctl rm role/orchestrator-app-access 2>/dev/null || echo "  Role not found or already deleted"
else
    echo "WARNING: tctl not available or not authenticated"
    echo "To manually clean up Teleport resources, run:"
    echo "  tctl rm token/orchestrator-bot-k8s-join"
    echo "  tctl bots rm orchestrator-bot"
    echo "  tctl rm role/orchestrator-app-access"
fi

# ---------------------------------------------------------------------------
# Phase 3: Local generated files
# ---------------------------------------------------------------------------
echo ""
echo "--- Phase 3: Local Generated Files ---"

if [ -f "$TOKEN_FILE" ]; then
    rm -f "$TOKEN_FILE"
    echo "Deleted $TOKEN_FILE"
else
    echo "No generated token file found"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=== Cleanup Complete ==="
echo ""
echo "Remaining namespaces:"
kubectl get namespaces 2>/dev/null | grep -E 'ai-agents' || echo "  No ai-agents namespace found"
echo ""
echo "To redeploy: ./infra/k8s/setup.sh"
echo ""
