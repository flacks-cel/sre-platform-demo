#!/usr/bin/env bash

# Não usar set -e aqui. O arquivo será carregado por outros scripts.

COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${COMMON_DIR}/../.." && pwd)"

RUNTIME_DIR="${PROJECT_ROOT}/.runtime"
PORT_FORWARD_DIR="${RUNTIME_DIR}/port-forwards"

mkdir -p "${PORT_FORWARD_DIR}"

log() {
  echo
  echo "==> $*"
}

success() {
  echo "OK: $*"
}

warn() {
  echo "AVISO: $*" >&2
}

die() {
  echo
  echo "ERRO: $*" >&2
  exit 1
}

require_command() {
  local command_name="$1"

  command -v "${command_name}" >/dev/null 2>&1 ||
    die "Comando obrigatório não encontrado: ${command_name}"
}

require_file() {
  local file_path="$1"

  [[ -f "${file_path}" ]] ||
    die "Arquivo obrigatório não encontrado: ${file_path}"
}

wait_for_kubernetes_api() {
  local attempts="${1:-60}"
  local interval="${2:-2}"

  log "Aguardando Kubernetes API"

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if kubectl get nodes >/dev/null 2>&1; then
      success "Kubernetes API disponível"
      return 0
    fi

    sleep "${interval}"
  done

  docker ps -a --filter "name=${CLUSTER_NAME:-sre-platform}" || true
  die "Kubernetes API não respondeu após $((attempts * interval)) segundos."
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempts="${3:-60}"
  local interval="${4:-2}"

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl --fail --silent "${url}" >/dev/null 2>&1; then
      success "${name} respondeu em ${url}"
      return 0
    fi

    sleep "${interval}"
  done

  die "${name} não respondeu em ${url}"
}

wait_for_deployment() {
  local namespace="$1"
  local deployment="$2"
  local timeout="${3:-300s}"

  kubectl rollout status \
    "deployment/${deployment}" \
    -n "${namespace}" \
    --timeout="${timeout}"
}

wait_for_statefulset() {
  local namespace="$1"
  local statefulset="$2"
  local timeout="${3:-300s}"

  kubectl rollout status \
    "statefulset/${statefulset}" \
    -n "${namespace}" \
    --timeout="${timeout}"
}

wait_for_daemonset() {
  local namespace="$1"
  local daemonset="$2"
  local timeout="${3:-300s}"

  kubectl rollout status \
    "daemonset/${daemonset}" \
    -n "${namespace}" \
    --timeout="${timeout}"
}

wait_for_metrics_api() {
  local attempts="${1:-60}"
  local interval="${2:-3}"

  log "Aguardando Metrics Server"

  wait_for_deployment kube-system metrics-server 300s

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if kubectl top nodes >/dev/null 2>&1; then
      success "Metrics API disponível"
      return 0
    fi

    sleep "${interval}"
  done

  die "Metrics Server está Running, mas a Metrics API não respondeu."
}

stop_saved_port_forward() {
  local name="$1"
  local pid_file="${PORT_FORWARD_DIR}/${name}.pid"

  [[ -f "${pid_file}" ]] || return 0

  local pid
  pid="$(cat "${pid_file}" 2>/dev/null || true)"

  if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
    kill "${pid}" >/dev/null 2>&1 || true
    sleep 1
  fi

  rm -f "${pid_file}"
}

stop_process_on_port() {
  local port="$1"

  # Git Bash / Windows.
  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe \
      -NoProfile \
      -NonInteractive \
      -Command "\
        \$connections = Get-NetTCPConnection \
          -LocalPort ${port} \
          -State Listen \
          -ErrorAction SilentlyContinue; \
        foreach (\$connection in \$connections) { \
          Stop-Process \
            -Id \$connection.OwningProcess \
            -Force \
            -ErrorAction SilentlyContinue \
        }" \
      >/dev/null 2>&1 || true

    return 0
  fi

  # Linux/macOS.
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti tcp:"${port}" 2>/dev/null || true)"

    if [[ -n "${pids}" ]]; then
      kill ${pids} >/dev/null 2>&1 || true
    fi
  fi
}

start_port_forward() {
  local name="$1"
  local namespace="$2"
  local resource="$3"
  local mapping="$4"

  local local_port="${mapping%%:*}"
  local pid_file="${PORT_FORWARD_DIR}/${name}.pid"
  local log_file="${PORT_FORWARD_DIR}/${name}.log"

  wait_for_kubernetes_api 30 2
  stop_saved_port_forward "${name}"
  stop_process_on_port "${local_port}"

  kubectl port-forward \
    --address=0.0.0.0 \
    -n "${namespace}" \
    "${resource}" \
    "${mapping}" \
    >"${log_file}" 2>&1 &

  local pid=$!
  echo "${pid}" >"${pid_file}"

  sleep 2

  if ! kill -0 "${pid}" >/dev/null 2>&1; then
    echo
    echo "Falha ao iniciar port-forward ${name}:"
    cat "${log_file}" || true
    rm -f "${pid_file}"
    exit 1
  fi

  success "${name}: localhost:${local_port}"
}