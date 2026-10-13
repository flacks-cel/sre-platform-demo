#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(git rev-parse --show-toplevel)"
ROUND_B_PY="${SPIKE_DIR}/evidence/round_b.py"
NAMESPACE="praeva-load"
JOB_NAME="praeva-evidential"
CONFIGMAP="praeva-evidential-script"
PROM_URL="${PROM_URL:-http://localhost:19091}"
PROM_LOCAL_PORT="${PROM_LOCAL_PORT:-19091}"
SAMPLE_SECONDS="15"
NODE_SATURATION_PCT="90"
NODE_SATURATION_CONSECUTIVE="2"

cd "${PROJECT_ROOT}"

for command in git kubectl python curl awk sort ls head; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command}" >&2
    exit 1
  }
done

BRANCH="$(git branch --show-current)"
HEAD="$(git rev-parse HEAD)"
UPSTREAM="$(git rev-parse '@{u}')"

if [[ -z "${BRANCH}" ]]; then
  echo "ERROR: detached HEAD is not allowed" >&2
  exit 1
fi

if [[ "${HEAD}" != "${UPSTREAM}" ]]; then
  echo "ERROR: local HEAD must equal upstream before an evidential round" >&2
  echo "HEAD:     ${HEAD}" >&2
  echo "upstream: ${UPSTREAM}" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: working tree must be clean before an evidential round" >&2
  git status --short >&2
  exit 1
fi

BASELINE_JSON="${BASELINE_JSON:-}"
if [[ -z "${BASELINE_JSON}" ]]; then
  BASELINE_JSON="$(ls -1t "${HOME}"/spike002-round-a-*-evidence.json 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "${BASELINE_JSON}" || ! -f "${BASELINE_JSON}" ]]; then
  echo "ERROR: Round A baseline JSON not found." >&2
  echo "Set BASELINE_JSON=/path/to/spike002-round-a-...-evidence.json" >&2
  exit 1
fi

echo "Using Round A baseline: ${BASELINE_JSON}"

PF_PID=""
cleanup() {
  if [[ -n "${PF_PID}" ]]; then
    kill "${PF_PID}" 2>/dev/null || true
    wait "${PF_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if curl -fsS "${PROM_URL}/-/ready" >/dev/null 2>&1; then
  echo "OK: reusing Prometheus at ${PROM_URL}"
else
  echo "==> Starting Prometheus port-forward on ${PROM_LOCAL_PORT}"
  kubectl -n observability \
    port-forward svc/kube-prometheus-stack-prometheus "${PROM_LOCAL_PORT}:9090" \
    >"${HOME}/spike002-round-b-prometheus-pf.log" 2>&1 &
  PF_PID=$!
  sleep 3
  curl -fsS "${PROM_URL}/-/ready" >/dev/null || {
    echo "ERROR: Prometheus port-forward did not become ready" >&2
    exit 1
  }
fi

echo "================================================="
echo "PRAEVA SPIKE 002 - ROUND B"
echo "================================================="
echo "branch:     ${BRANCH}"
echo "revision:   ${HEAD}"
echo "HPA:        min=1 max=3"
echo "load:       3 requests / 4s (0.75 RPS)"
echo "work:       1,000,000 iterations/request"
echo "duration:   8m"
echo "baseline:   ${BASELINE_JSON}"
echo "Prometheus: ${PROM_URL}"
echo "================================================="

echo
echo "==> Waiting for Round B k=1 stable gate"
python -u "${ROUND_B_PY}" preflight-b \
  --prometheus-url "${PROM_URL}" \
  --expected-revision "${HEAD}" \
  --wait-seconds 900 \
  --poll-seconds 15 \
  --stable-polls 4

echo
echo "==> Preparing evidential k6 Job"
kubectl create namespace "${NAMESPACE}" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl delete job "${JOB_NAME}" -n "${NAMESPACE}" \
  --ignore-not-found --wait=true >/dev/null
kubectl delete configmap "${CONFIGMAP}" -n "${NAMESPACE}" \
  --ignore-not-found >/dev/null
kubectl create configmap "${CONFIGMAP}" \
  -n "${NAMESPACE}" \
  --from-file=load.js="${SCRIPT_DIR}/load.js" >/dev/null

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
K6_LOG="${HOME}/spike002-round-b-${RUN_ID}-k6.log"
EVIDENCE_JSON="${HOME}/spike002-round-b-${RUN_ID}-evidence.json"

T0="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "T0=${T0}"
kubectl apply -f "${SCRIPT_DIR}/job.yaml" >/dev/null

saturation_streak=0
sample=0
invalid_reason=""

while true; do
  sample=$((sample + 1))
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "--- sample=${sample} time=${now} ---"
  kubectl get hpa jobs-api -n app
  kubectl get pods -n app -l app=jobs-api \
    -o custom-columns='NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,AGE:.metadata.creationTimestamp,NODE:.spec.nodeName' \
    --no-headers

  mapfile -t APP_NODES < <(
    kubectl get pods -n app -l app=jobs-api \
      -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort -u
  )

  max_app_node_cpu=0
  for node in "${APP_NODES[@]}"; do
    [[ -n "${node}" ]] || continue
    line="$(kubectl top node "${node}" --no-headers 2>/dev/null || true)"
    echo "${line}"
    pct="$(echo "${line}" | awk '{gsub(/%/, "", $3); print $3+0}')"
    [[ "${pct}" =~ ^[0-9]+$ ]] || pct=0
    if (( pct > max_app_node_cpu )); then
      max_app_node_cpu="${pct}"
    fi
  done

  if (( max_app_node_cpu >= NODE_SATURATION_PCT )); then
    saturation_streak=$((saturation_streak + 1))
  else
    saturation_streak=0
  fi

  if (( saturation_streak >= NODE_SATURATION_CONSECUTIVE )); then
    invalid_reason="node CPU >= ${NODE_SATURATION_PCT}% for ${NODE_SATURATION_CONSECUTIVE} consecutive samples"
  fi

  restart_sum="$(
    kubectl get pods -n app -l app=jobs-api \
      -o jsonpath='{range .items[*]}{range .status.containerStatuses[*]}{.restartCount}{"\n"}{end}{end}' |
      awk '{s += $1} END {print s+0}'
  )"
  if (( restart_sum > 0 )); then
    invalid_reason="pod restart observed during load"
  fi

  metrics_available="$(
    kubectl get apiservice v1beta1.metrics.k8s.io \
      -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null || true
  )"
  if [[ "${metrics_available}" != "True" ]]; then
    invalid_reason="Metrics API unavailable during scheduled collection"
  fi

  pending_count="$(
    kubectl get pods -n app -l app=jobs-api \
      --field-selector=status.phase=Pending --no-headers 2>/dev/null | wc -l | tr -d ' '
  )"
  if [[ "${pending_count}" =~ ^[0-9]+$ ]] && (( pending_count > 0 )); then
    invalid_reason="jobs-api pod Pending during load"
  fi

  if [[ -n "${invalid_reason}" ]]; then
    echo "ERROR: Round B invalid: ${invalid_reason}" >&2
    kubectl delete job "${JOB_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
    exit 1
  fi

  succeeded="$(kubectl get job "${JOB_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.succeeded}' 2>/dev/null || true)"
  failed="$(kubectl get job "${JOB_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.failed}' 2>/dev/null || true)"

  if [[ "${succeeded}" == "1" ]]; then
    break
  fi
  if [[ -n "${failed}" && "${failed}" != "0" ]]; then
    echo "ERROR: evidential k6 Job failed" >&2
    kubectl logs -n "${NAMESPACE}" "job/${JOB_NAME}" --all-containers=true | tee "${K6_LOG}" || true
    exit 1
  fi

  sleep "${SAMPLE_SECONDS}"
done

T1="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "T1=${T1}"

echo
echo "===== K6 OUTPUT ====="
kubectl logs -n "${NAMESPACE}" "job/${JOB_NAME}" --all-containers=true | tee "${K6_LOG}"

echo
echo "==> Collecting and segmenting Round B evidence"
python -u "${ROUND_B_PY}" collect-b \
  --prometheus-url "${PROM_URL}" \
  --start "${T0}" \
  --end "${T1}" \
  --baseline-json "${BASELINE_JSON}" \
  --output "${EVIDENCE_JSON}"

echo
echo "================================================="
echo "ROUND B COMPLETE"
echo "================================================="
echo "revision: ${HEAD}"
echo "T0:       ${T0}"
echo "T1:       ${T1}"
echo "k6 log:   ${K6_LOG}"
echo "evidence: ${EVIDENCE_JSON}"
echo "================================================="
