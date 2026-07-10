#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="sre-platform"
OBS_NS="observability"

echo "================================================="
echo "SRE PLATFORM DEMO - START AUTOMATICO"
echo "================================================="

echo "==> Verificando Docker..."
docker info >/dev/null

echo "==> Verificando cluster Kind..."
if ! kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
  pushd infra/terraform >/dev/null
  terraform init
  terraform apply -auto-approve
  popd >/dev/null
else
  echo "Cluster ${CLUSTER_NAME} encontrado."
fi

kubectl cluster-info --context "kind-${CLUSTER_NAME}" >/dev/null

echo "==> Criando namespace observability..."
kubectl create namespace "$OBS_NS" --dry-run=client -o yaml | kubectl apply -f -

echo "==> Ajustando Prometheus para manter namespace=app..."
cat > observability/prometheus/prometheus.yml <<EOF
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: "jobs-api"
    metrics_path: "/metrics"
    static_configs:
      - targets: ["jobs-api:8000"]
        labels:
          namespace: "app"
EOF

echo "==> Subindo Docker Compose..."
docker compose up -d --build
docker compose restart prometheus

echo "==> Instalando Loki e Promtail..."
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null

helm upgrade --install loki grafana/loki \
  -n "$OBS_NS" \
  --set deploymentMode=SingleBinary \
  --set loki.auth_enabled=false \
  --set loki.commonConfig.replication_factor=1 \
  --set loki.storage.type=filesystem \
  --set loki.schemaConfig.configs[0].from="2024-01-01" \
  --set loki.schemaConfig.configs[0].store=tsdb \
  --set loki.schemaConfig.configs[0].object_store=filesystem \
  --set loki.schemaConfig.configs[0].schema=v13 \
  --set loki.schemaConfig.configs[0].index.prefix=loki_index_ \
  --set loki.schemaConfig.configs[0].index.period=24h \
  --set singleBinary.replicas=1 \
  --set read.replicas=0 \
  --set write.replicas=0 \
  --set backend.replicas=0 \
  --set gateway.enabled=false

helm upgrade --install promtail grafana/promtail \
  -n "$OBS_NS" \
  --set "config.clients[0].url=http://loki.${OBS_NS}.svc.cluster.local:3100/loki/api/v1/push"

kubectl rollout status statefulset/loki -n "$OBS_NS" --timeout=300s || true
kubectl rollout status daemonset/promtail -n "$OBS_NS" --timeout=300s || true

echo "==> Limpando port-forwards antigos..."
if command -v pkill >/dev/null 2>&1; then
    pkill -f "kubectl.*port-forward" || true
else
    taskkill //F //IM kubectl.exe > /dev/null 2>&1 || true
fi
sleep 2

echo "==> Abrindo Loki em localhost:3102..."
kubectl port-forward -n "$OBS_NS" svc/loki 3102:3100 >/tmp/loki-port-forward.log 2>&1 &

echo "==> Aguardando API..."
for i in {1..30}; do
  if curl -s http://localhost:8000/health >/dev/null; then
    echo "API OK."
    break
  fi
  sleep 2
done

echo "==> Gerando Request Rate..."
for i in {1..120}; do
  curl -s http://localhost:8000/health >/dev/null || true
  curl -s http://localhost:8000/ready >/dev/null || true
  curl -s http://localhost:8000/metrics >/dev/null || true
  sleep 0.1
done

echo "==> Gerando Jobs Created..."
for i in {1..10}; do
  curl -s -X POST http://localhost:8000/jobs \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"demo-job-$i\",\"payload\":{\"source\":\"interview-demo\"}}" >/dev/null || true
  sleep 0.2
done

echo "==> Gerando Error Percentage..."
for i in {1..10}; do
  curl -s http://localhost:8000/simulate/error >/dev/null || true
  sleep 0.2
done

echo "==> Gerando Latency p99..."
for i in {1..8}; do
  curl -s "http://localhost:8000/simulate/latency?seconds=1" >/dev/null || true
done

echo "==> Aguardando Prometheus coletar..."
sleep 15

echo "==> Métricas principais:"
curl -s http://localhost:8000/metrics | grep -E "jobs_created_total|http_requests_total|http_request_duration_seconds_bucket" || true

echo
echo "================================================="
echo "AMBIENTE PRONTO"
echo "================================================="
echo "Grafana:    http://localhost:3000"
echo "Prometheus: http://localhost:9090"
echo "API:        http://localhost:8000"
echo "Loki:       http://localhost:3102"
echo
echo "No Grafana: Refresh + Last 5 minutes ou Last 15 minutes"
echo "================================================="