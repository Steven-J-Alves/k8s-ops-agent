#!/usr/bin/env bash
# Local dev environment: kind cluster + k8s-ops-agent via docker compose
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

CLUSTER_NAME="k8s-ops-test"
KUBECONFIG_PATH="$HOME/.kube/config"

log() { echo -e "\033[1;34m[dev-setup]\033[0m $*"; }
ok()  { echo -e "\033[1;32m[ok]\033[0m $*"; }
err() { echo -e "\033[1;31m[err]\033[0m $*"; exit 1; }

# ── 1. Validate env file ─────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  err ".env not found — copy .env.example and fill in ANTHROPIC_API_KEY"
fi
if ! grep -q "ANTHROPIC_API_KEY=sk-" .env; then
  err "ANTHROPIC_API_KEY not set in .env"
fi

# ── 2. Kind cluster ──────────────────────────────────────────────────────────
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  log "Kind cluster '${CLUSTER_NAME}' already exists — reusing."
else
  log "Creating kind cluster '${CLUSTER_NAME}'…"
  kind create cluster --name "${CLUSTER_NAME}" --wait 60s
  ok "Cluster created."
fi

# ── 3. Merge kubeconfig ──────────────────────────────────────────────────────
log "Exporting kubeconfig to ${KUBECONFIG_PATH}…"
mkdir -p "$(dirname "$KUBECONFIG_PATH")"
kind get kubeconfig --name "${CLUSTER_NAME}" > /tmp/kind-kubeconfig
if [[ -f "$KUBECONFIG_PATH" ]]; then
  KUBECONFIG="$KUBECONFIG_PATH:/tmp/kind-kubeconfig" kubectl config view --flatten > /tmp/merged-kubeconfig
  mv /tmp/merged-kubeconfig "$KUBECONFIG_PATH"
else
  cp /tmp/kind-kubeconfig "$KUBECONFIG_PATH"
fi
chmod 600 "$KUBECONFIG_PATH"
kubectl config use-context "kind-${CLUSTER_NAME}"
ok "kubeconfig ready."

# ── 4. Deploy crashy test workloads ─────────────────────────────────────────
log "Deploying test workloads…"
kubectl apply -f k8s-test/crashloop-pod.yaml
ok "Test pods created in namespace 'production'."

log "Waiting for pods to start crashing…"
sleep 10
kubectl get pods -n production

# ── 5. Start the agent stack ─────────────────────────────────────────────────
log "Starting k8s-ops-agent + PostgreSQL via docker compose…"
docker compose up --build -d

log "Waiting for agent to be healthy…"
for i in $(seq 1 20); do
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    ok "Agent is up!"
    break
  fi
  sleep 3
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Dashboard : http://localhost:8000"
echo "  API docs  : http://localhost:8000/docs"
echo "  Logs      : docker compose logs -f k8s-ops-agent"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
