#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

ARGOCD_NS="${ARGOCD_NS:-argocd}"
APPLICATION_FILE="${PROJECT_ROOT}/infra/argocd/application.yaml"
APPLICATION_NAME="${APPLICATION_NAME:-jobs-api}"

cd "${PROJECT_ROOT}"

echo "================================================="
echo "ARGOCD - INSTALAÇÃO"
echo "================================================="

require_command kubectl
require_command helm
require_file "${APPLICATION_FILE}"

wait_for_kubernetes_api

log "Configurando repositório Helm"

helm repo add argo \
  https://argoproj.github.io/argo-helm \
  >/dev/null 2>&1 || true

helm repo update >/dev/null

log "Instalando ou atualizando ArgoCD"

helm upgrade --install argocd argo/argo-cd \
  --namespace "${ARGOCD_NS}" \
  --create-namespace \
  --set configs.params."server\.insecure"=true \
  --timeout 10m

log "Aguardando componentes do ArgoCD"

wait_for_deployment \
  "${ARGOCD_NS}" \
  argocd-redis \
  300s

wait_for_deployment \
  "${ARGOCD_NS}" \
  argocd-repo-server \
  300s

wait_for_deployment \
  "${ARGOCD_NS}" \
  argocd-server \
  300s

wait_for_deployment \
  "${ARGOCD_NS}" \
  argocd-applicationset-controller \
  300s

kubectl rollout status \
  statefulset/argocd-application-controller \
  -n "${ARGOCD_NS}" \
  --timeout=300s

success "Componentes do ArgoCD disponíveis"

log "Aplicando Application ${APPLICATION_NAME}"

kubectl apply -f "${APPLICATION_FILE}"

log "Aguardando aplicação ficar Synced e Healthy"

application_ready=false

for attempt in {1..60}; do
  sync_status="$(
    kubectl get application "${APPLICATION_NAME}" \
      -n "${ARGOCD_NS}" \
      -o jsonpath='{.status.sync.status}' \
      2>/dev/null || echo "Unknown"
  )"

  health_status="$(
    kubectl get application "${APPLICATION_NAME}" \
      -n "${ARGOCD_NS}" \
      -o jsonpath='{.status.health.status}' \
      2>/dev/null || echo "Unknown"
  )"

  echo "  ${attempt}/60 - ${sync_status} / ${health_status}"

  if [[ "${sync_status}" == "Synced" &&
        "${health_status}" == "Healthy" ]]; then
    application_ready=true
    break
  fi

  sleep 5
done

if [[ "${application_ready}" == true ]]; then
  success "ArgoCD: Synced e Healthy"
else
  warn "Application não ficou Synced/Healthy dentro do prazo."

  kubectl get application "${APPLICATION_NAME}" \
    -n "${ARGOCD_NS}" \
    -o wide || true
fi

ARGOCD_PASSWORD="$(
  kubectl get secret argocd-initial-admin-secret \
    -n "${ARGOCD_NS}" \
    -o jsonpath='{.data.password}' \
    2>/dev/null |
    base64 -d 2>/dev/null ||
    true
)"

echo
echo "================================================="
echo "ARGOCD PRONTO"
echo "================================================="
echo "User: admin"

if [[ -n "${ARGOCD_PASSWORD}" ]]; then
  echo "Pass: ${ARGOCD_PASSWORD}"
else
  echo "Pass: secret inicial não encontrado ou já removido"
fi

echo "================================================="