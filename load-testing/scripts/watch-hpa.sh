#!/usr/bin/env bash

set -euo pipefail

NAMESPACE="${NAMESPACE:-app}"
HPA_NAME="${HPA_NAME:-jobs-api}"
INTERVAL="${INTERVAL:-5}"

echo "================================================="
echo "HPA MONITOR"
echo "================================================="
echo "Namespace: ${NAMESPACE}"
echo "HPA:       ${HPA_NAME}"
echo "Interval:  ${INTERVAL}s"
echo
echo "Pressione Ctrl+C para encerrar."
echo "================================================="

while true; do
  clear

  echo "HPA STATUS - $(date '+%Y-%m-%d %H:%M:%S')"
  echo

  kubectl get hpa "${HPA_NAME}" \
    -n "${NAMESPACE}" \
    -o wide

  echo
  echo "PODS"
  echo

  kubectl get pods \
    -n "${NAMESPACE}" \
    -l app.kubernetes.io/name=jobs-api \
    -o wide 2>/dev/null ||
  kubectl get pods \
    -n "${NAMESPACE}" \
    -l app=jobs-api \
    -o wide

  echo
  echo "RESOURCE USAGE"
  echo

  kubectl top pods \
    -n "${NAMESPACE}" \
    --containers 2>/dev/null ||
  echo "Metrics ainda não disponíveis."

  sleep "${INTERVAL}"
done