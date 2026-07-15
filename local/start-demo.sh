#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

# =========================================================
# Configuração
# =========================================================

CLUSTER_NAME="${CLUSTER_NAME:-sre-platform}"

APP_NS="${APP_NS:-app}"
OBS_NS="${OBS_NS:-observability}"
ARGOCD_NS="${ARGOCD_NS:-argocd}"

GRAFANA_PORT="${GRAFANA_PORT:-3001}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9091}"
ARGOCD_PORT="${ARGOCD_PORT:-8080}"
API_PORT="${API_PORT:-8081}"
LOKI_PORT="${LOKI_PORT:-3102}"

DASHBOARDS_DIR="${PROJECT_ROOT}/observability/grafana/dashboards"

cd "${PROJECT_ROOT}"

# =========================================================
# Tratamento de erros
# =========================================================

handle_error() {
  local exit_code=$?
  local line_number="${1:-unknown}"

  echo
  echo "================================================="
  echo "SRE PLATFORM DEMO - FALHA NA INICIALIZAÇÃO"
  echo "================================================="
  echo "Linha:       ${line_number}"
  echo "Código:      ${exit_code}"
  echo "Cluster:     ${CLUSTER_NAME}"
  echo "Kubeconfig:  $(kubectl config current-context 2>/dev/null || echo 'indisponível')"
  echo
  echo "Comandos de diagnóstico:"
  echo
  echo "  kubectl get pods -A"
  echo "  kubectl get events -A --sort-by=.lastTimestamp"
  echo "  kubectl get hpa -n ${APP_NS}"
  echo "  helm list -A"
  echo "  helm status kube-prometheus-stack -n ${OBS_NS}"
  echo "  helm status loki -n ${OBS_NS}"
  echo "  helm status promtail -n ${OBS_NS}"
  echo
  echo "Logs dos port-forwards:"
  echo
  echo "  ls -la ${PROJECT_ROOT}/.runtime 2>/dev/null || true"
  echo "================================================="

  exit "${exit_code}"
}

trap 'handle_error ${LINENO}' ERR

# =========================================================
# Apresentação
# =========================================================

print_banner() {
  echo "================================================="
  echo "SRE PLATFORM DEMO"
  echo "Inicialização automática do ambiente local"
  echo "================================================="
  echo "Cluster: ${CLUSTER_NAME}"
  echo "Projeto: ${PROJECT_ROOT}"
  echo "================================================="
}

# =========================================================
# Dependências
# =========================================================

validate_dependencies() {
  log "Validando dependências"

  local commands=(
    docker
    kind
    terraform
    kubectl
    helm
    curl
    base64
    python
  )

  local command_name

  for command_name in "${commands[@]}"; do
    require_command "${command_name}"
  done

  docker info >/dev/null 2>&1 ||
    die "Docker Engine não está disponível."

  success "Dependências disponíveis"
}

# =========================================================
# Kubernetes
# =========================================================

ensure_kind_cluster() {
  log "Verificando cluster Kind"

  if kind get clusters | grep -qx "${CLUSTER_NAME}"; then
    success "Cluster ${CLUSTER_NAME} encontrado"
  else
    log "Cluster ${CLUSTER_NAME} não encontrado. Criando com Terraform"

    pushd "${PROJECT_ROOT}/infra/terraform" >/dev/null

    terraform init
    terraform apply -auto-approve

    popd >/dev/null

    success "Cluster ${CLUSTER_NAME} criado"
  fi

  kubectl config use-context "kind-${CLUSTER_NAME}" >/dev/null

  wait_for_kubernetes_api

  success "API Kubernetes disponível"
}

ensure_namespaces() {
  log "Garantindo namespaces"

  local namespaces=(
    "${APP_NS}"
    "${OBS_NS}"
    "${ARGOCD_NS}"
  )

  local namespace

  for namespace in "${namespaces[@]}"; do
    kubectl create namespace "${namespace}" \
      --dry-run=client \
      -o yaml |
      kubectl apply -f - >/dev/null
  done

  success "Namespaces disponíveis"
}

# =========================================================
# Helm
# =========================================================

configure_helm_repositories() {
  log "Configurando repositórios Helm"

  helm repo add prometheus-community \
    https://prometheus-community.github.io/helm-charts \
    --force-update \
    >/dev/null

  helm repo add grafana \
    https://grafana.github.io/helm-charts \
    --force-update \
    >/dev/null

  helm repo update >/dev/null

  success "Repositórios Helm atualizados"
}

# =========================================================
# Recuperação de releases Helm
# =========================================================

recover_helm_release() {
  local release_name="$1"
  local namespace="$2"
  local release_status

  release_status="$(
    helm status "${release_name}"       -n "${namespace}"       -o json       2>/dev/null |
      python -c 'import json,sys
try:
    data=json.load(sys.stdin)
    print(data.get("info",{}).get("status",""))
except Exception:
    pass'       2>/dev/null || true
  )"

  case "${release_status}" in
    pending-install|pending-upgrade|pending-rollback)
      warn "Release Helm ${namespace}/${release_name} está em ${release_status}."

      local deployed_revision
      deployed_revision="$(
        helm history "${release_name}"           -n "${namespace}"           -o json           2>/dev/null |
          python -c 'import json,sys
try:
    history=json.load(sys.stdin)
    deployed=[item for item in history if item.get("status")=="deployed"]
    if deployed:
        print(max(deployed,key=lambda item:int(item["revision"]))["revision"])
except Exception:
    pass'           2>/dev/null || true
      )"

      if [[ -n "${deployed_revision}" ]]; then
        log "Recuperando ${release_name} para a revisão ${deployed_revision}"

        helm rollback "${release_name}" "${deployed_revision}"           -n "${namespace}"           --wait           --timeout 10m

        success "Release ${release_name} recuperado"
      else
        warn "Nenhuma revisão deployed encontrada para ${release_name}."
        warn "Removendo release incompleto para permitir nova instalação."

        helm uninstall "${release_name}"           -n "${namespace}"           --wait           --timeout 5m || true
      fi
      ;;
  esac
}

# =========================================================
# Observabilidade
# =========================================================

install_kube_prometheus_stack() {
  log "Configurando Prometheus e Grafana"

  recover_helm_release kube-prometheus-stack "${OBS_NS}"

  helm upgrade --install kube-prometheus-stack \
    prometheus-community/kube-prometheus-stack \
    -n "${OBS_NS}" \
    --create-namespace \
    --reset-values \
    --set grafana.sidecar.dashboards.enabled=true \
    --set grafana.sidecar.dashboards.label=grafana_dashboard \
    --set-string grafana.sidecar.dashboards.labelValue=1 \
    --set grafana.sidecar.dashboards.searchNamespace="${OBS_NS}" \
    --set grafana.additionalDataSources[0].name=Loki \
    --set grafana.additionalDataSources[0].type=loki \
    --set grafana.additionalDataSources[0].uid=loki \
    --set grafana.additionalDataSources[0].access=proxy \
    --set grafana.additionalDataSources[0].url="http://loki.${OBS_NS}.svc.cluster.local:3100" \
    --set grafana.additionalDataSources[0].isDefault=false \
    --atomic \
    --cleanup-on-fail \
    --timeout 10m

  wait_for_deployment \
    "${OBS_NS}" \
    kube-prometheus-stack-operator

  wait_for_deployment \
    "${OBS_NS}" \
    kube-prometheus-stack-grafana

  wait_for_statefulset \
    "${OBS_NS}" \
    prometheus-kube-prometheus-stack-prometheus

  success "Prometheus e Grafana disponíveis"
}

install_loki() {
  log "Configurando Loki em modo SingleBinary"

  recover_helm_release loki "${OBS_NS}"

  helm upgrade --install loki grafana/loki \
    -n "${OBS_NS}" \
    --create-namespace \
    --reset-values \
    --set deploymentMode=SingleBinary \
    --set loki.auth_enabled=false \
    --set loki.commonConfig.replication_factor=1 \
    --set loki.storage.type=filesystem \
    --set "loki.schemaConfig.configs[0].from=2024-01-01" \
    --set "loki.schemaConfig.configs[0].store=tsdb" \
    --set "loki.schemaConfig.configs[0].object_store=filesystem" \
    --set "loki.schemaConfig.configs[0].schema=v13" \
    --set "loki.schemaConfig.configs[0].index.prefix=loki_index_" \
    --set "loki.schemaConfig.configs[0].index.period=24h" \
    --set singleBinary.replicas=1 \
    --set read.replicas=0 \
    --set write.replicas=0 \
    --set backend.replicas=0 \
    --set gateway.enabled=false \
    --set chunksCache.enabled=false \
    --set resultsCache.enabled=false \
    --atomic \
    --cleanup-on-fail \
    --timeout 10m

  # Remove objetos opcionais deixados por versões anteriores do chart.
  kubectl delete statefulset \
    loki-chunks-cache \
    loki-results-cache \
    -n "${OBS_NS}" \
    --ignore-not-found \
    >/dev/null 2>&1 || true

  kubectl delete service \
    loki-chunks-cache \
    loki-results-cache \
    -n "${OBS_NS}" \
    --ignore-not-found \
    >/dev/null 2>&1 || true

  wait_for_statefulset \
    "${OBS_NS}" \
    loki

  success "Loki disponível"
}

install_promtail() {
  log "Configurando Promtail"

  recover_helm_release promtail "${OBS_NS}"

  helm upgrade --install promtail grafana/promtail \
    -n "${OBS_NS}" \
    --create-namespace \
    --reset-values \
    --set "config.clients[0].url=http://loki.${OBS_NS}.svc.cluster.local:3100/loki/api/v1/push" \
    --atomic \
    --cleanup-on-fail \
    --timeout 5m

  wait_for_daemonset \
    "${OBS_NS}" \
    promtail

  success "Promtail disponível"
}

# =========================================================
# Aplicação e autoscaling
# =========================================================

deploy_jobs_api() {
  log "Executando deploy da Jobs API"

  bash "${PROJECT_ROOT}/local/deploy-app.sh"

  kubectl rollout status deployment/jobs-api \
    -n "${APP_NS}" \
    --timeout=5m

  success "Jobs API disponível"
}

validate_hpa() {
  log "Validando Metrics Server e HPA"

  wait_for_metrics_api

  kubectl get hpa jobs-api \
    -n "${APP_NS}" \
    >/dev/null 2>&1 ||
    die "HPA app/jobs-api não encontrado."

  success "Metrics Server e HPA disponíveis"
}

# =========================================================
# ArgoCD
# =========================================================

configure_argocd() {
  log "Configurando ArgoCD"

  bash "${PROJECT_ROOT}/local/start-argocd.sh"

  wait_for_kubernetes_api

  kubectl rollout status deployment/argocd-server \
    -n "${ARGOCD_NS}" \
    --timeout=5m

  success "ArgoCD disponível"
}

# =========================================================
# Dashboards
# =========================================================

provision_dashboards() {
  log "Validando e provisionando dashboards do Grafana"

  require_command python
  require_file "${DASHBOARDS_DIR}/jobs-api.json"
  require_file "${DASHBOARDS_DIR}/hpa-autoscaling.json"

  local dashboard_count=0
  local dashboard

  for dashboard in "${DASHBOARDS_DIR}"/*.json; do
    [[ -f "${dashboard}" ]] || continue

    if ! python - "${dashboard}" <<'PY'
import json
import sys
from pathlib import Path

dashboard_path = Path(sys.argv[1])

try:
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    print(f"JSON inválido: {dashboard_path}: {exc}", file=sys.stderr)
    raise SystemExit(1)

if dashboard.get("apiVersion") == "dashboard.grafana.app/v2":
    print(
        f"Dashboard Grafana v2 incompatível com file provisioning: {dashboard_path}",
        file=sys.stderr,
    )
    raise SystemExit(1)

required_fields = ("title", "panels", "schemaVersion")
missing_fields = [
    field for field in required_fields
    if field not in dashboard
]

if missing_fields:
    print(
        f"Dashboard clássico incompleto: {dashboard_path}. "
        f"Campos ausentes: {', '.join(missing_fields)}",
        file=sys.stderr,
    )
    raise SystemExit(1)

if not isinstance(dashboard["panels"], list):
    print(
        f"Campo 'panels' inválido em {dashboard_path}.",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
    then
      die "Falha na validação do dashboard: ${dashboard}"
    fi

    dashboard_count=$((dashboard_count + 1))
  done

  [[ "${dashboard_count}" -gt 0 ]] ||
    die "Nenhum dashboard JSON encontrado em ${DASHBOARDS_DIR}."

  kubectl create configmap sre-platform-demo-dashboards \
    -n "${OBS_NS}" \
    --from-file="${DASHBOARDS_DIR}" \
    --dry-run=client \
    -o yaml |
    kubectl apply -f - >/dev/null

  kubectl label configmap sre-platform-demo-dashboards \
    -n "${OBS_NS}" \
    grafana_dashboard="1" \
    --overwrite \
    >/dev/null

  DASHBOARD_COUNT="${dashboard_count}"

  success "${dashboard_count} dashboards provisionados"
}

# =========================================================
# Port-forwards
# =========================================================

start_local_endpoints() {
  log "Iniciando port-forwards"

  start_port_forward \
    grafana \
    "${OBS_NS}" \
    svc/kube-prometheus-stack-grafana \
    "${GRAFANA_PORT}:80"

  start_port_forward \
    prometheus \
    "${OBS_NS}" \
    svc/kube-prometheus-stack-prometheus \
    "${PROMETHEUS_PORT}:9090"

  start_port_forward \
    loki \
    "${OBS_NS}" \
    svc/loki \
    "${LOKI_PORT}:3100"

  start_port_forward \
    jobs-api \
    "${APP_NS}" \
    svc/jobs-api \
    "${API_PORT}:8000"

  start_port_forward \
    argocd \
    "${ARGOCD_NS}" \
    svc/argocd-server \
    "${ARGOCD_PORT}:80"

  success "Port-forwards iniciados"
}

validate_local_endpoints() {
  log "Validando endpoints locais"

  wait_for_url \
    Grafana \
    "http://localhost:${GRAFANA_PORT}/api/health"

  wait_for_url \
    Prometheus \
    "http://localhost:${PROMETHEUS_PORT}/-/ready"

  wait_for_url \
    Loki \
    "http://localhost:${LOKI_PORT}/ready"

  wait_for_url \
    "Jobs API" \
    "http://localhost:${API_PORT}/health"

  wait_for_url \
    ArgoCD \
    "http://localhost:${ARGOCD_PORT}"

  success "Endpoints locais disponíveis"
}

# =========================================================
# Tráfego inicial
# =========================================================

generate_initial_traffic() {
  log "Gerando tráfego inicial para métricas e logs"

  local index

  for index in {1..60}; do
    curl --silent \
      "http://localhost:${API_PORT}/health" \
      >/dev/null || true

    curl --silent \
      "http://localhost:${API_PORT}/ready" \
      >/dev/null || true

    curl --silent \
      "http://localhost:${API_PORT}/jobs" \
      >/dev/null || true

    curl --silent \
      "http://localhost:${API_PORT}/metrics" \
      >/dev/null || true

    if (( index % 10 == 0 )); then
      curl --silent \
        "http://localhost:${API_PORT}/not-found" \
        >/dev/null || true
    fi

    sleep 0.1
  done

  for index in {1..5}; do
    curl --silent \
      --request POST \
      "http://localhost:${API_PORT}/jobs" \
      --header "Content-Type: application/json" \
      --data \
      "{\"name\":\"demo-job-${index}\",\"payload\":{\"source\":\"start-demo\"}}" \
      >/dev/null || true
  done

  success "Tráfego inicial gerado"
}

# =========================================================
# Credenciais
# =========================================================

get_grafana_user() {
  kubectl get secret kube-prometheus-stack-grafana \
    -n "${OBS_NS}" \
    -o jsonpath='{.data.admin-user}' \
    2>/dev/null |
    base64 -d 2>/dev/null ||
    true
}

get_grafana_password() {
  kubectl get secret kube-prometheus-stack-grafana \
    -n "${OBS_NS}" \
    -o jsonpath='{.data.admin-password}' \
    2>/dev/null |
    base64 -d 2>/dev/null ||
    true
}

get_argocd_password() {
  kubectl get secret argocd-initial-admin-secret \
    -n "${ARGOCD_NS}" \
    -o jsonpath='{.data.password}' \
    2>/dev/null |
    base64 -d 2>/dev/null ||
    true
}

# =========================================================
# Resumo
# =========================================================

print_final_summary() {
  local grafana_user
  local grafana_password
  local argocd_password

  grafana_user="$(get_grafana_user)"
  grafana_password="$(get_grafana_password)"
  argocd_password="$(get_argocd_password)"

  echo
  echo "================================================="
  echo "SRE PLATFORM DEMO READY"
  echo "================================================="
  echo
  echo "Componentes:"
  echo
  echo "  ✔ Kubernetes Kind"
  echo "  ✔ Metrics Server"
  echo "  ✔ Jobs API"
  echo "  ✔ Horizontal Pod Autoscaler"
  echo "  ✔ Prometheus"
  echo "  ✔ Grafana"
  echo "  ✔ Loki"
  echo "  ✔ Promtail"
  echo "  ✔ ArgoCD"
  echo "  ✔ ${DASHBOARD_COUNT:-0} dashboards"
  echo
  echo "-------------------------------------------------"
  echo "ACESSOS"
  echo "-------------------------------------------------"
  echo
  echo "Grafana"
  echo "  URL:  http://localhost:${GRAFANA_PORT}"
  echo "  User: ${grafana_user:-admin}"
  echo "  Pass: ${grafana_password:-consulte o secret Kubernetes}"
  echo
  echo "Prometheus"
  echo "  URL:  http://localhost:${PROMETHEUS_PORT}"
  echo
  echo "ArgoCD"
  echo "  URL:  http://localhost:${ARGOCD_PORT}"
  echo "  User: admin"
  echo "  Pass: ${argocd_password:-consulte o secret Kubernetes}"
  echo
  echo "Jobs API"
  echo "  URL:  http://localhost:${API_PORT}"
  echo "  Docs: http://localhost:${API_PORT}/docs"
  echo
  echo "Loki"
  echo "  URL:  http://localhost:${LOKI_PORT}"
  echo
  echo "-------------------------------------------------"
  echo "DEMONSTRAÇÃO DO HPA"
  echo "-------------------------------------------------"
  echo
  echo "Terminal 1 - acompanhar autoscaling:"
  echo
  echo "  ./load-testing/scripts/watch-hpa.sh"
  echo
  echo "Terminal 2 - executar carga:"
  echo
  echo "  ./load-testing/scripts/run-hpa-test.sh"
  echo
  echo "Durante o teste:"
  echo
  echo "  1. Abra o dashboard executivo no Grafana"
  echo "  2. Observe CPU e número de réplicas"
  echo "  3. Acompanhe o HPA escalando a aplicação"
  echo "  4. Interrompa a carga e observe o scale-down"
  echo
  echo "-------------------------------------------------"
  echo "COMANDOS ÚTEIS"
  echo "-------------------------------------------------"
  echo
  echo "Status geral:"
  echo
  echo "  kubectl get pods -A"
  echo
  echo "HPA:"
  echo
  echo "  kubectl get hpa -n ${APP_NS}"
  echo
  echo "Réplicas da aplicação:"
  echo
  echo "  kubectl get deployment jobs-api -n ${APP_NS}"
  echo
  echo "Encerrar port-forwards:"
  echo
  echo "  ./local/stop-port-forwards.sh"
  echo
  echo "================================================="
}

# =========================================================
# Fluxo principal
# =========================================================

main() {
  print_banner

  validate_dependencies

  ensure_kind_cluster
  ensure_namespaces

  configure_helm_repositories

  install_kube_prometheus_stack
  install_loki
  install_promtail

  deploy_jobs_api
  validate_hpa

  configure_argocd
  provision_dashboards

  start_local_endpoints
  validate_local_endpoints

  generate_initial_traffic

  print_final_summary
}

main "$@"