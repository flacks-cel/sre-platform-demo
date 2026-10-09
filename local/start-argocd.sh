#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

ARGOCD_NS="${ARGOCD_NS:-argocd}"
ARGOCD_CHART_VERSION="${ARGOCD_CHART_VERSION:-10.6.4}"
ARGOCD_TARGET_REVISION="${ARGOCD_TARGET_REVISION:-HEAD}"
APPLICATION_FILE="${PROJECT_ROOT}/infra/argocd/application.yaml"
APPLICATION_NAME="${APPLICATION_NAME:-jobs-api}"

RENDERED_APPLICATION_FILE="$(mktemp -t jobs-api-application-XXXXXX.yaml)"
EXPECTED_REVISION=""

cleanup() {
  rm -f "${RENDERED_APPLICATION_FILE}"
}

trap cleanup EXIT

cd "${PROJECT_ROOT}"

echo "================================================="
echo "ARGOCD - INSTALAÇÃO"
echo "================================================="

require_command kubectl
require_command helm
require_command python
require_command git
require_file "${APPLICATION_FILE}"

validate_revision_source() {
  local local_revision
  local upstream_revision
  local current_branch

  local_revision="$(git rev-parse HEAD)"
  current_branch="$(git branch --show-current)"
  upstream_revision="$(git rev-parse '@{u}' 2>/dev/null || true)"

  [[ -n "${current_branch}" ]] ||
    die "HEAD está detached; faça checkout da branch que será testada."

  [[ -n "${upstream_revision}" ]] ||
    die "Branch ${current_branch} não possui upstream remoto. Faça push com -u antes do bootstrap."

  [[ "${local_revision}" == "${upstream_revision}" ]] ||
    die "HEAD local (${local_revision}) difere do upstream (${upstream_revision}). Há commits não enviados ou a branch local está desatualizada."

  if [[ "${ARGOCD_TARGET_REVISION}" != "HEAD" &&
        "${ARGOCD_TARGET_REVISION}" != "${current_branch}" &&
        "${ARGOCD_TARGET_REVISION}" != "${local_revision}" ]]; then
    die "ARGOCD_TARGET_REVISION=${ARGOCD_TARGET_REVISION} não corresponde à branch atual (${current_branch}) nem ao commit local."
  fi

  if [[ -n "${EXPECTED_GIT_REVISION:-}" &&
        "${EXPECTED_GIT_REVISION}" != "${local_revision}" ]]; then
    die "EXPECTED_GIT_REVISION=${EXPECTED_GIT_REVISION} difere do HEAD local ${local_revision}."
  fi

  EXPECTED_REVISION="${EXPECTED_GIT_REVISION:-${local_revision}}"

  success "Revisão Git pronta: ${current_branch} @ ${EXPECTED_REVISION}"
}

render_application() {
  log "Renderizando Application para revisão ${ARGOCD_TARGET_REVISION}"

  python - \
    "${APPLICATION_FILE}" \
    "${RENDERED_APPLICATION_FILE}" \
    "${ARGOCD_TARGET_REVISION}" <<'PY'
import json
import re
import sys
from pathlib import Path

source_path = Path(sys.argv[1])
destination_path = Path(sys.argv[2])
target_revision = sys.argv[3]

content = source_path.read_text(encoding="utf-8")
pattern = re.compile(r"^(\s*targetRevision:\s*).+$", re.MULTILINE)
rendered, replacements = pattern.subn(
    lambda match: f"{match.group(1)}{json.dumps(target_revision)}",
    content,
    count=1,
)

if replacements != 1:
    print(
        f"ERRO: esperado exatamente um targetRevision em {source_path}; "
        f"encontrados {replacements}.",
        file=sys.stderr,
    )
    raise SystemExit(1)

destination_path.write_text(rendered, encoding="utf-8")
PY
}

validate_revision_source
render_application
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
  --version "${ARGOCD_CHART_VERSION}" \
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

log "Aplicando Application ${APPLICATION_NAME} na revisão ${ARGOCD_TARGET_REVISION}"

kubectl apply -f "${RENDERED_APPLICATION_FILE}"

log "Aguardando aplicação ficar Synced/Healthy na revisão esperada"

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

  sync_revision="$(
    kubectl get application "${APPLICATION_NAME}" \
      -n "${ARGOCD_NS}" \
      -o jsonpath='{.status.sync.revision}' \
      2>/dev/null || true
  )"

  echo "  ${attempt}/60 - ${sync_status} / ${health_status} / revision=${sync_revision:-Unknown}"

  if [[ "${sync_status}" == "Synced" &&
        "${health_status}" == "Healthy" &&
        "${sync_revision}" == "${EXPECTED_REVISION}" ]]; then
    application_ready=true
    break
  fi

  sleep 5
done

if [[ "${application_ready}" == true ]]; then
  success "ArgoCD: Synced e Healthy em ${EXPECTED_REVISION}"
else
  kubectl get application "${APPLICATION_NAME}" \
    -n "${ARGOCD_NS}" \
    -o wide || true

  actual_revision="$(
    kubectl get application "${APPLICATION_NAME}" \
      -n "${ARGOCD_NS}" \
      -o jsonpath='{.status.sync.revision}' \
      2>/dev/null || true
  )"

  die "Application não ficou Synced/Healthy na revisão esperada ${EXPECTED_REVISION}. Revisão observada: ${actual_revision:-indisponível}."
fi

log "Comprovando revisão sincronizada"

echo "  targetRevision: ${ARGOCD_TARGET_REVISION}"
echo "  git HEAD:       ${EXPECTED_REVISION}"
echo "  ArgoCD revision: $(
  kubectl get application "${APPLICATION_NAME}" \
    -n "${ARGOCD_NS}" \
    -o jsonpath='{.status.sync.revision}'
)"

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
