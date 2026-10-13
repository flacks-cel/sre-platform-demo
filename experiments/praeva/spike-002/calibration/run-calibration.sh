#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="praeva-load"
JOB_NAME="praeva-calibration"
SCRIPT_CONFIGMAP="praeva-calibration-script"
PARAMS_CONFIGMAP="praeva-calibration-params"

RATE="${1:-}"
DURATION="${2:-2m}"
ITERATIONS="${3:-1000000}"
TIME_UNIT="${TIME_UNIT:-1s}"
PRE_ALLOCATED_VUS="${PRE_ALLOCATED_VUS:-20}"
MAX_VUS="${MAX_VUS:-100}"
BASE_URL="${BASE_URL:-http://jobs-api.app.svc.cluster.local:8000}"
SAMPLE_SECONDS="${SAMPLE_SECONDS:-15}"

usage() {
  cat <<'EOF'
Usage:
  ./experiments/praeva/spike-002/calibration/run-calibration.sh RATE [DURATION] [ITERATIONS]

Examples:
  ./experiments/praeva/spike-002/calibration/run-calibration.sh 1 2m 1000000
  ./experiments/praeva/spike-002/calibration/run-calibration.sh 3 3m 1000000

Environment overrides:
  TIME_UNIT=1s
  PRE_ALLOCATED_VUS=20
  MAX_VUS=100
  BASE_URL=http://jobs-api.app.svc.cluster.local:8000
  SAMPLE_SECONDS=15
EOF
}

if [[ -z "${RATE}" ]]; then
  usage >&2
  exit 2
fi

for command in kubectl awk; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command}" >&2
    exit 1
  }
done

kubectl get hpa jobs-api -n app >/dev/null 2>&1 || {
  echo "ERROR: app/jobs-api HPA not found" >&2
  exit 1
}

kubectl get svc jobs-api -n app >/dev/null 2>&1 || {
  echo "ERROR: app/jobs-api Service not found" >&2
  exit 1
}

kubectl create namespace "${NAMESPACE}" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

kubectl delete job "${JOB_NAME}" -n "${NAMESPACE}" \
  --ignore-not-found --wait=true >/dev/null
kubectl delete configmap "${SCRIPT_CONFIGMAP}" "${PARAMS_CONFIGMAP}" \
  -n "${NAMESPACE}" --ignore-not-found >/dev/null

kubectl create configmap "${SCRIPT_CONFIGMAP}" \
  -n "${NAMESPACE}" \
  --from-file=calibration.js="${SCRIPT_DIR}/calibration.js" >/dev/null

kubectl create configmap "${PARAMS_CONFIGMAP}" \
  -n "${NAMESPACE}" \
  --from-literal=BASE_URL="${BASE_URL}" \
  --from-literal=RATE="${RATE}" \
  --from-literal=TIME_UNIT="${TIME_UNIT}" \
  --from-literal=DURATION="${DURATION}" \
  --from-literal=ITERATIONS="${ITERATIONS}" \
  --from-literal=PRE_ALLOCATED_VUS="${PRE_ALLOCATED_VUS}" \
  --from-literal=MAX_VUS="${MAX_VUS}" >/dev/null

kubectl apply -f "${SCRIPT_DIR}/job.yaml" >/dev/null

echo "================================================="
echo "PRAEVA SPIKE 002 - CALIBRATION"
echo "================================================="
echo "rate:              ${RATE}/${TIME_UNIT}"
echo "duration:          ${DURATION}"
echo "iterations/request:${ITERATIONS}"
echo "preAllocatedVUs:   ${PRE_ALLOCATED_VUS}"
echo "maxVUs:            ${MAX_VUS}"
echo "target:            ${BASE_URL}"
echo "sample interval:   ${SAMPLE_SECONDS}s"
echo "================================================="

max_replicas=0
max_node_cpu_pct=0
sample=0

while true; do
  sample=$((sample + 1))
  now="$(date -Iseconds)"

  current_replicas="$(kubectl get hpa jobs-api -n app -o jsonpath='{.status.currentReplicas}' 2>/dev/null || echo 0)"
  desired_replicas="$(kubectl get hpa jobs-api -n app -o jsonpath='{.status.desiredReplicas}' 2>/dev/null || echo 0)"

  [[ "${current_replicas}" =~ ^[0-9]+$ ]] || current_replicas=0
  [[ "${desired_replicas}" =~ ^[0-9]+$ ]] || desired_replicas=0

  if (( current_replicas > max_replicas )); then
    max_replicas="${current_replicas}"
  fi
  if (( desired_replicas > max_replicas )); then
    max_replicas="${desired_replicas}"
  fi

  node_cpu_pct="$(
    kubectl top nodes --no-headers 2>/dev/null |
      awk '{gsub(/%/, "", $3); if ($3+0 > m) m=$3+0} END {print m+0}'
  )"
  [[ "${node_cpu_pct}" =~ ^[0-9]+$ ]] || node_cpu_pct=0

  if (( node_cpu_pct > max_node_cpu_pct )); then
    max_node_cpu_pct="${node_cpu_pct}"
  fi

  echo
  echo "--- sample=${sample} time=${now} ---"
  kubectl get hpa jobs-api -n app
  kubectl get pods -n app -l app=jobs-api \
    -o custom-columns='NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,NODE:.spec.nodeName' \
    --no-headers
  kubectl top nodes

  succeeded="$(kubectl get job "${JOB_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.succeeded}' 2>/dev/null || true)"
  failed="$(kubectl get job "${JOB_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.failed}' 2>/dev/null || true)"

  if [[ "${succeeded}" == "1" ]]; then
    break
  fi

  if [[ -n "${failed}" && "${failed}" != "0" ]]; then
    echo "ERROR: calibration Job failed" >&2
    kubectl logs -n "${NAMESPACE}" "job/${JOB_NAME}" --all-containers=true || true
    exit 1
  fi

  sleep "${SAMPLE_SECONDS}"
done

echo
echo "===== K6 OUTPUT ====="
kubectl logs -n "${NAMESPACE}" "job/${JOB_NAME}" --all-containers=true

echo
echo "===== CALIBRATION SUMMARY ====="
echo "rate=${RATE}/${TIME_UNIT}"
echo "duration=${DURATION}"
echo "iterations=${ITERATIONS}"
echo "max_replicas_observed=${max_replicas}"
echo "max_node_cpu_pct_observed=${max_node_cpu_pct}"
echo
kubectl get hpa jobs-api -n app
kubectl get pods -n app -l app=jobs-api -o wide
kubectl top nodes

echo
echo "Calibration is non-evidential: use this result only to choose N and arrival rate."
