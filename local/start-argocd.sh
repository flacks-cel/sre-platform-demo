#!/usr/bin/env bash
set -euo pipefail

ARGOCD_NS="argocd"

echo "================================================="
echo "ARGOCD - INSTALACAO"
echo "================================================="

echo "==> Verificando cluster..."
kubectl cluster-info >/dev/null

echo "==> Adicionando repo Helm..."
helm repo add argo https://argoproj.github.io/argo-helm 2>/dev/null || true
helm repo update >/dev/null

echo "==> Instalando ArgoCD..."
if helm status argocd -n "$ARGOCD_NS" &>/dev/null; then
  echo "ArgoCD já instalado."
else
  helm install argocd argo/argo-cd \
    --namespace "$ARGOCD_NS" \
    --create-namespace \
    --set configs.params."server\.insecure"=true \
    --wait --timeout 5m
fi

echo "==> Aguardando pods..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=argocd-server \
  -n "$ARGOCD_NS" --timeout=120s

echo "==> Aplicando Application jobs-api..."
kubectl apply -f infra/argocd/application.yaml

echo "==> Aguardando sync..."
for i in {1..30}; do
  STATUS=$(kubectl get application jobs-api -n "$ARGOCD_NS" \
    -o jsonpath='{.status.sync.status}' 2>/dev/null || echo "Unknown")
  HEALTH=$(kubectl get application jobs-api -n "$ARGOCD_NS" \
    -o jsonpath='{.status.health.status}' 2>/dev/null || echo "Unknown")
  echo "  status: $STATUS / $HEALTH"
  if [[ "$STATUS" == "Synced" && "$HEALTH" == "Healthy" ]]; then
    echo "ArgoCD: Synced + Healthy"
    break
  fi
  sleep 10
done

echo "==> Abrindo port-forward..."
pkill -f "kubectl.*port-forward.*8080" 2>/dev/null || true
sleep 1
kubectl port-forward svc/argocd-server 8080:80 -n "$ARGOCD_NS" >/tmp/pf-argocd.log 2>&1 &

ARGOCD_PASSWORD=$(kubectl -n "$ARGOCD_NS" get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" 2>/dev/null | base64 -d 2>/dev/null || echo "não encontrado")

echo
echo "================================================="
echo "ARGOCD PRONTO"
echo "================================================="
echo "UI:    http://localhost:8080"
echo "User:  admin"
echo "Pass:  ${ARGOCD_PASSWORD}"
echo "================================================="