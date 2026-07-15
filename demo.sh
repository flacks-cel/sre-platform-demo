#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/local/lib/common.sh"

APP_NS="${APP_NS:-app}"
OBS_NS="${OBS_NS:-observability}"
ARGOCD_NS="${ARGOCD_NS:-argocd}"

GRAFANA_PORT="${GRAFANA_PORT:-3001}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9091}"
ARGOCD_PORT="${ARGOCD_PORT:-8080}"
API_PORT="${API_PORT:-8081}"
LOKI_PORT="${LOKI_PORT:-3102}"

cd "${PROJECT_ROOT}"

pause_menu() {
  echo
  read -r -p "Pressione Enter para continuar..." _
}

clear_screen() {
  clear 2>/dev/null || true
}

check_url() {
  curl --fail --silent --max-time 2 "$1" >/dev/null 2>&1 &&
    printf "READY" ||
    printf "OFFLINE"
}

check_kubernetes() {
  kubectl get nodes >/dev/null 2>&1 &&
    printf "READY" ||
    printf "OFFLINE"
}

check_jobs_api() {
  local replicas
  replicas="$(
    kubectl get deployment jobs-api \
      -n "${APP_NS}" \
      -o jsonpath='{.status.availableReplicas}' \
      2>/dev/null || true
  )"

  [[ -n "${replicas}" && "${replicas}" -gt 0 ]] &&
    printf "READY" ||
    printf "OFFLINE"
}

get_hpa_summary() {
  local current desired max

  current="$(
    kubectl get hpa jobs-api \
      -n "${APP_NS}" \
      -o jsonpath='{.status.currentReplicas}' \
      2>/dev/null || true
  )"
  desired="$(
    kubectl get hpa jobs-api \
      -n "${APP_NS}" \
      -o jsonpath='{.status.desiredReplicas}' \
      2>/dev/null || true
  )"
  max="$(
    kubectl get hpa jobs-api \
      -n "${APP_NS}" \
      -o jsonpath='{.spec.maxReplicas}' \
      2>/dev/null || true
  )"

  if [[ -n "${current}" && -n "${desired}" && -n "${max}" ]]; then
    printf "%s current / %s desired / %s max" \
      "${current}" "${desired}" "${max}"
  else
    printf "unavailable"
  fi
}

open_url() {
  local url="$1"

  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe \
      -NoProfile \
      -NonInteractive \
      -WindowStyle Hidden \
      -Command "Start-Process '${url}'" \
      >/dev/null 2>&1

    sleep 1
    return 0
  fi

  if command -v explorer.exe >/dev/null 2>&1; then
    explorer.exe "${url}" >/dev/null 2>&1 &
    sleep 1
    return 0
  fi

  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${url}" >/dev/null 2>&1 &
    sleep 1
    return 0
  fi

  if command -v open >/dev/null 2>&1; then
    open "${url}" >/dev/null 2>&1 &
    sleep 1
    return 0
  fi

  warn "Não foi possível abrir o navegador automaticamente."
  echo "Abra manualmente: ${url}"
  return 1
}

run_in_new_terminal() {
  local title="$1"
  local command_to_run="$2"

  if command -v mintty.exe >/dev/null 2>&1; then
    mintty.exe \
      -t "${title}" \
      /usr/bin/bash -lc \
      "cd '${PROJECT_ROOT}' && ${command_to_run}; echo; read -r -p 'Pressione Enter para fechar...' _" \
      >/dev/null 2>&1 &
    return 0
  fi

  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe \
      -NoProfile \
      -NonInteractive \
      -WindowStyle Hidden \
      -Command "Start-Process bash.exe -ArgumentList '-lc', 'cd \"${PROJECT_ROOT}\" && ${command_to_run}; echo; read -r -p \"Pressione Enter para fechar...\" _'" \
      >/dev/null 2>&1
    return 0
  fi

  if command -v x-terminal-emulator >/dev/null 2>&1; then
    x-terminal-emulator \
      -T "${title}" \
      -e bash -lc \
      "cd '${PROJECT_ROOT}' && ${command_to_run}; echo; read -r -p 'Pressione Enter para fechar...' _" &
    return 0
  fi

  if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal \
      --title="${title}" \
      -- bash -lc \
      "cd '${PROJECT_ROOT}' && ${command_to_run}; echo; read -r -p 'Pressione Enter para fechar...' _" &
    return 0
  fi

  if command -v open >/dev/null 2>&1; then
    open -a Terminal "${PROJECT_ROOT}"
    warn "Execute manualmente no novo terminal: ${command_to_run}"
    return 0
  fi

  warn "Não foi possível abrir um novo terminal."
  echo "Execute manualmente:"
  echo
  echo "  ${command_to_run}"
  return 1
}

show_menu() {
  clear_screen

  echo "========================================================="
  echo "                 SRE PLATFORM DEMO"
  echo "========================================================="
  echo
  printf "  Kubernetes ................. %s\n" "$(check_kubernetes)"
  printf "  Jobs API ................... %s\n" "$(check_jobs_api)"
  printf "  Grafana .................... %s\n" \
    "$(check_url "http://localhost:${GRAFANA_PORT}/api/health")"
  printf "  Prometheus ................. %s\n" \
    "$(check_url "http://localhost:${PROMETHEUS_PORT}/-/ready")"
  printf "  Loki ....................... %s\n" \
    "$(check_url "http://localhost:${LOKI_PORT}/ready")"
  printf "  ArgoCD ..................... %s\n" \
    "$(check_url "http://localhost:${ARGOCD_PORT}")"
  printf "  HPA ........................ %s\n" "$(get_hpa_summary)"
  echo
  echo "---------------------------------------------------------"
  echo "AÇÕES"
  echo "---------------------------------------------------------"
  echo
  echo "  [1] Iniciar plataforma"
  echo "  [2] Abrir dashboard principal"
  echo "  [3] Abrir dashboard HPA"
  echo "  [4] Executar demonstração do HPA"
  echo "  [5] Monitorar autoscaling"
  echo "  [6] Exibir status detalhado"
  echo "  [7] Exibir acessos e credenciais"
  echo "  [8] Encerrar port-forwards"
  echo "  [9] Abrir Jobs API Docs"
  echo "  [10] Abrir Prometheus"
  echo "  [11] Abrir ArgoCD"
  echo "  [0] Sair"
  echo
  echo "========================================================="
}

show_detailed_status() {
  clear_screen
  echo "========================================================="
  echo "STATUS DETALHADO"
  echo "========================================================="
  echo
  kubectl get nodes -o wide 2>/dev/null || true
  echo
  kubectl get pods -A 2>/dev/null || true
  echo
  kubectl get hpa -n "${APP_NS}" 2>/dev/null || true
  echo
  kubectl get applications -n "${ARGOCD_NS}" 2>/dev/null || true
  pause_menu
}

show_access_info() {
  clear_screen

  local grafana_user grafana_password argocd_password

  grafana_user="$(
    kubectl get secret kube-prometheus-stack-grafana \
      -n "${OBS_NS}" \
      -o jsonpath='{.data.admin-user}' \
      2>/dev/null |
      base64 -d 2>/dev/null ||
      true
  )"

  grafana_password="$(
    kubectl get secret kube-prometheus-stack-grafana \
      -n "${OBS_NS}" \
      -o jsonpath='{.data.admin-password}' \
      2>/dev/null |
      base64 -d 2>/dev/null ||
      true
  )"

  argocd_password="$(
    kubectl get secret argocd-initial-admin-secret \
      -n "${ARGOCD_NS}" \
      -o jsonpath='{.data.password}' \
      2>/dev/null |
      base64 -d 2>/dev/null ||
      true
  )"

  echo "========================================================="
  echo "ACESSOS"
  echo "========================================================="
  echo
  echo "Grafana"
  echo "  URL:  http://localhost:${GRAFANA_PORT}"
  echo "  User: ${grafana_user:-admin}"
  echo "  Pass: ${grafana_password:-indisponível}"
  echo
  echo "Prometheus"
  echo "  URL:  http://localhost:${PROMETHEUS_PORT}"
  echo
  echo "ArgoCD"
  echo "  URL:  http://localhost:${ARGOCD_PORT}"
  echo "  User: admin"
  echo "  Pass: ${argocd_password:-indisponível}"
  echo
  echo "Jobs API"
  echo "  URL:  http://localhost:${API_PORT}"
  echo "  Docs: http://localhost:${API_PORT}/docs"
  echo
  echo "Loki"
  echo "  URL:  http://localhost:${LOKI_PORT}"
  pause_menu
}

main() {
  require_command kubectl
  require_command curl

  while true; do
    show_menu
    read -r -p "Selecione uma opção: " option

    case "${option}" in
      1)
        clear_screen
        bash "${PROJECT_ROOT}/local/start-demo.sh"
        pause_menu
        ;;
      2)
        open_url "http://localhost:${GRAFANA_PORT}/d/jobs-api-observability"
        pause_menu
        ;;
      3)
        open_url "http://localhost:${GRAFANA_PORT}/d/sre-platform-demo-hpa"
        pause_menu
        ;;
      4)
        run_in_new_terminal \
          "SRE Platform Demo - HPA Load Test" \
          "./load-testing/scripts/run-hpa-test.sh"
        echo
        success "Teste HPA aberto em um novo terminal."
        pause_menu
        ;;
      5)
        run_in_new_terminal \
          "SRE Platform Demo - HPA Monitor" \
          "./load-testing/scripts/watch-hpa.sh"
        echo
        success "Monitor HPA aberto em um novo terminal."
        pause_menu
        ;;
      6)
        show_detailed_status
        ;;
      7)
        show_access_info
        ;;
      8)
        clear_screen
        bash "${PROJECT_ROOT}/local/stop-port-forwards.sh"
        pause_menu
        ;;
      9)
        open_url "http://localhost:${API_PORT}/docs"
        pause_menu
        ;;
      10)
        open_url "http://localhost:${PROMETHEUS_PORT}"
        pause_menu
        ;;
      11)
        open_url "http://localhost:${ARGOCD_PORT}"
        pause_menu
        ;;
      0)
        echo
        echo "Encerrando SRE Platform Demo."
        exit 0
        ;;
      *)
        warn "Opção inválida."
        pause_menu
        ;;
    esac
  done
}

main "$@"
