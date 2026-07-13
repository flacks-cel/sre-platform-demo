#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="sre-platform"
NAMESPACE="app"
DEPLOYMENT="jobs-api"
COMPOSE_SERVICE="jobs-api"
LOCAL_CONTAINER="jobs-api"
LOCAL_IMAGE="sre-platform-demo-jobs-api"
KIND_IMAGE="jobs-api:local"
TAR_FILE="$(mktemp -t jobs-api-local-XXXXXX.tar)"

cleanup() {
  rm -f "${TAR_FILE}"
}
trap cleanup EXIT

echo "================================================="
echo "DEPLOY JOBS API TO KIND"
echo "================================================="

echo "==> Verificando Docker..."
docker info >/dev/null

echo "==> Verificando cluster Kind..."
if ! kind get clusters | grep -qx "${CLUSTER_NAME}"; then
  echo "ERRO: cluster Kind '${CLUSTER_NAME}' não encontrado."
  exit 1
fi

echo "==> Verificando acesso ao Kubernetes..."
kubectl cluster-info --context "kind-${CLUSTER_NAME}" >/dev/null

echo "==> Rebuild da aplicação via Docker Compose..."
docker compose up -d --build "${COMPOSE_SERVICE}"

echo "==> Aguardando container local ficar saudável..."
for attempt in {1..30}; do
  status="$(
    docker inspect "${LOCAL_CONTAINER}"       --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}'       2>/dev/null || true
  )"

  if [[ "${status}" == "healthy" || "${status}" == "running" ]]; then
    echo "Container local pronto: ${status}."
    break
  fi

  if [[ "${attempt}" -eq 30 ]]; then
    echo "ERRO: container local não ficou pronto."
    docker compose ps
    exit 1
  fi

  sleep 2
done

echo "==> Criando tag ${KIND_IMAGE}..."
docker tag "${LOCAL_IMAGE}" "${KIND_IMAGE}"

echo "==> Exportando imagem para arquivo temporário..."
docker save "${KIND_IMAGE}" -o "${TAR_FILE}"

echo "==> Importando imagem nos nodes do Kind..."
mapfile -t KIND_NODES < <(kind get nodes --name "${CLUSTER_NAME}")

if [[ "${#KIND_NODES[@]}" -eq 0 ]]; then
  echo "ERRO: nenhum node encontrado no cluster '${CLUSTER_NAME}'."
  exit 1
fi

for node in "${KIND_NODES[@]}"; do
  echo "    -> ${node}"
  docker exec -i "${node}"     ctr -n k8s.io images import --all-platforms --digests -     < "${TAR_FILE}"
done

echo "==> Reiniciando Deployment..."
kubectl rollout restart "deployment/${DEPLOYMENT}" -n "${NAMESPACE}"

echo "==> Aguardando rollout..."
kubectl rollout status "deployment/${DEPLOYMENT}"   -n "${NAMESPACE}"   --timeout=180s

echo "==> Pods atuais..."
kubectl get pods   -n "${NAMESPACE}"   -l app="${DEPLOYMENT}"   -o wide

echo
echo "================================================="
echo "DEPLOY CONCLUÍDO"
echo "================================================="
echo "Imagem:      ${KIND_IMAGE}"
echo "Deployment:  ${NAMESPACE}/${DEPLOYMENT}"
echo
echo "Para validar pelo Service Kubernetes:"
echo
echo "  kubectl port-forward -n ${NAMESPACE} svc/${DEPLOYMENT} 8081:8000"
echo
echo "Em outro terminal:"
echo
echo "  curl \"http://localhost:8081/simulate/cpu?seconds=2\""
echo "=========================================================="