#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

NAMESPACE="${NAMESPACE:-app}"
SERVICE_NAME="${SERVICE_NAME:-jobs-api}"
SERVICE_PORT="${SERVICE_PORT:-8000}"
CPU_SECONDS="${CPU_SECONDS:-1}"

JOB_NAME="${JOB_NAME:-k6-hpa-test}"
CONFIGMAP_NAME="${CONFIGMAP_NAME:-k6-hpa-test-scripts}"
K6_DIR="${PROJECT_ROOT}/load-testing/k6"

cleanup() {
  if [[ "${KEEP_K6_RESOURCES:-false}" != "true" ]]; then
    kubectl delete job "${JOB_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
    kubectl delete configmap "${CONFIGMAP_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

cd "${PROJECT_ROOT}"

echo "================================================="
echo "K6 HPA SCALING TEST"
echo "================================================="
echo "Namespace:        ${NAMESPACE}"
echo "Service:          ${SERVICE_NAME}"
echo "Cluster endpoint: http://${SERVICE_NAME}.${NAMESPACE}.svc.cluster.local:${SERVICE_PORT}"
echo "CPU duration:     ${CPU_SECONDS}s"
echo "================================================="

echo
echo "[1/5] Validando dependências..."

command -v kubectl >/dev/null 2>&1 || {
  echo "ERRO: kubectl não encontrado."
  exit 1
}

[[ -f "${K6_DIR}/hpa-scaling-test.js" ]] || {
  echo "ERRO: arquivo não encontrado: ${K6_DIR}/hpa-scaling-test.js"
  exit 1
}

echo
echo "[2/5] Validando Kubernetes, Metrics Server e HPA..."

kubectl get nodes >/dev/null
kubectl get deployment metrics-server -n kube-system >/dev/null
kubectl get service "${SERVICE_NAME}" -n "${NAMESPACE}" >/dev/null
kubectl get hpa "${SERVICE_NAME}" -n "${NAMESPACE}"

kubectl top pods -n "${NAMESPACE}" >/dev/null || {
  echo "ERRO: métricas de CPU ainda não estão disponíveis."
  echo "Execute: kubectl top pods -n ${NAMESPACE}"
  exit 1
}

echo
echo "[3/5] Provisionando scripts do k6 no cluster..."

kubectl create configmap "${CONFIGMAP_NAME}"   -n "${NAMESPACE}"   --from-file="${K6_DIR}"   --dry-run=client   -o yaml |
kubectl apply -f - >/dev/null

kubectl delete job "${JOB_NAME}"   -n "${NAMESPACE}"   --ignore-not-found   --wait=true   >/dev/null

echo
echo "[4/5] Criando Kubernetes Job do k6..."

cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/name: k6
    app.kubernetes.io/part-of: sre-platform-demo
    app.kubernetes.io/component: load-testing
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 300
  template:
    metadata:
      labels:
        app.kubernetes.io/name: k6
        app.kubernetes.io/part-of: sre-platform-demo
        app.kubernetes.io/component: load-testing
    spec:
      restartPolicy: Never
      containers:
        - name: k6
          image: grafana/k6:latest
          imagePullPolicy: IfNotPresent
          args:
            - run
            - /scripts/hpa-scaling-test.js
          env:
            - name: BASE_URL
              value: http://${SERVICE_NAME}.${NAMESPACE}.svc.cluster.local:${SERVICE_PORT}
            - name: CPU_SECONDS
              value: "${CPU_SECONDS}"
          volumeMounts:
            - name: scripts
              mountPath: /scripts
              readOnly: true
      volumes:
        - name: scripts
          configMap:
            name: ${CONFIGMAP_NAME}
EOF

echo
echo "[5/5] Executando k6 dentro do cluster..."
echo
echo "Acompanhe o HPA em outro terminal:"
echo
echo "  ./load-testing/scripts/watch-hpa.sh"
echo

K6_POD=""

for attempt in {1..60}; do
  K6_POD="$(
    kubectl get pods \
      -n "${NAMESPACE}" \
      -l "job-name=${JOB_NAME}" \
      -o jsonpath='{.items[0].metadata.name}' \
      2>/dev/null || true
  )"

  if [[ -n "${K6_POD}" ]]; then
    echo "OK: Pod do k6 criado: ${K6_POD}"
    break
  fi

  if [[ "${attempt}" -eq 60 ]]; then
    echo
    echo "ERRO: o controlador do Job não criou o Pod do k6."
    kubectl describe job "${JOB_NAME}" -n "${NAMESPACE}" || true
    exit 1
  fi

  sleep 1
done

if ! kubectl wait \
  -n "${NAMESPACE}" \
  --for=condition=Ready \
  "pod/${K6_POD}" \
  --timeout=180s; then
  echo
  echo "ERRO: o Pod do k6 não ficou Ready."
  kubectl describe pod "${K6_POD}" -n "${NAMESPACE}" || true
  kubectl get events \
    -n "${NAMESPACE}" \
    --sort-by=.lastTimestamp \
    | tail -30 || true
  exit 1
fi

kubectl logs -n "${NAMESPACE}" -f "${K6_POD}"

if ! kubectl wait   -n "${NAMESPACE}"   --for=condition=complete   "job/${JOB_NAME}"   --timeout=15m; then
  echo
  echo "ERRO: teste k6 não concluiu com sucesso."
  kubectl describe job "${JOB_NAME}" -n "${NAMESPACE}" || true
  exit 1
fi

echo
echo "================================================="
echo "TESTE CONCLUÍDO"
echo "================================================="

kubectl get hpa "${SERVICE_NAME}" -n "${NAMESPACE}"
kubectl get deployment "${SERVICE_NAME}" -n "${NAMESPACE}"
kubectl get pods -n "${NAMESPACE}" -l app=jobs-api -o wide 2>/dev/null || true

echo
echo "O scale-down pode demorar alguns minutos devido"
echo "à janela de estabilização configurada no HPA."
echo "================================================="
