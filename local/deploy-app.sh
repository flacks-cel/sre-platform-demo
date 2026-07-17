#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

CLUSTER_NAME="${CLUSTER_NAME:-sre-platform}"
NAMESPACE="${APP_NS:-app}"
DEPLOYMENT="${DEPLOYMENT:-jobs-api}"

COMPOSE_SERVICE="${COMPOSE_SERVICE:-jobs-api}"
LOCAL_CONTAINER="${LOCAL_CONTAINER:-jobs-api}"
LOCAL_IMAGE="${LOCAL_IMAGE:-sre-platform-demo-jobs-api}"
KIND_IMAGE="${KIND_IMAGE:-jobs-api:local}"

TAR_FILE="$(mktemp -t jobs-api-local-XXXXXX.tar)"

cleanup() {
  rm -f "${TAR_FILE}"
}

trap cleanup EXIT

cd "${PROJECT_ROOT}"

echo "================================================="
echo "DEPLOY JOBS API TO KIND"
echo "================================================="

require_command docker
require_command kind
require_command kubectl

log "Verificando Docker"

docker info >/dev/null 2>&1 ||
  die "Docker Engine não está disponível."

log "Verificando cluster Kind"

kind get clusters | grep -qx "${CLUSTER_NAME}" ||
  die "Cluster Kind '${CLUSTER_NAME}' não encontrado."

kubectl config use-context "kind-${CLUSTER_NAME}" >/dev/null
wait_for_kubernetes_api

log "Garantindo namespace ${NAMESPACE}"

kubectl create namespace "${NAMESPACE}" \
  --dry-run=client \
  -o yaml |
  kubectl apply -f - >/dev/null

log "Rebuild da aplicação via Docker Compose"

docker compose up -d --build "${COMPOSE_SERVICE}"

log "Aguardando container local"

for attempt in {1..30}; do
  status="$(
    docker inspect "${LOCAL_CONTAINER}" \
      --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      2>/dev/null || true
  )"

  if [[ "${status}" == "healthy" || "${status}" == "running" ]]; then
    success "Container local pronto: ${status}"
    break
  fi

  if [[ "${attempt}" -eq 30 ]]; then
    docker compose ps
    die "Container local não ficou pronto."
  fi

  sleep 2
done

log "Criando tag ${KIND_IMAGE}"

docker image inspect "${LOCAL_IMAGE}" >/dev/null 2>&1 ||
  die "Imagem local não encontrada: ${LOCAL_IMAGE}"

docker tag "${LOCAL_IMAGE}" "${KIND_IMAGE}"

log "Exportando imagem"

docker save "${KIND_IMAGE}" -o "${TAR_FILE}"

log "Importando imagem nos nodes do Kind"

mapfile -t KIND_NODES < <(
  kind get nodes --name "${CLUSTER_NAME}"
)

[[ "${#KIND_NODES[@]}" -gt 0 ]] ||
  die "Nenhum node encontrado no cluster ${CLUSTER_NAME}."

for node in "${KIND_NODES[@]}"; do
  echo "  -> ${node}"

  docker exec -i "${node}" \
    ctr -n k8s.io images import \
    --all-platforms \
    --digests \
    - \
    <"${TAR_FILE}"
done

log "Reiniciando Deployment"

kubectl get deployment "${DEPLOYMENT}" \
  -n "${NAMESPACE}" >/dev/null 2>&1 ||
  die "Deployment ${NAMESPACE}/${DEPLOYMENT} não encontrado."

kubectl rollout restart \
  "deployment/${DEPLOYMENT}" \
  -n "${NAMESPACE}"

wait_for_deployment \
  "${NAMESPACE}" \
  "${DEPLOYMENT}" \
  300s

log "Estado da aplicação"

kubectl get pods \
  -n "${NAMESPACE}" \
  -l app="${DEPLOYMENT}" \
  -o wide

echo
echo "================================================="
echo "DEPLOY CONCLUÍDO"
echo "================================================="
echo "Imagem:      ${KIND_IMAGE}"
echo "Deployment:  ${NAMESPACE}/${DEPLOYMENT}"
echo "================================================="