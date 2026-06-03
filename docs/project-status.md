SRE Platform Demo — Histórico Consolidado (02/06 a 03/06/2026)
Fase 1 — Foundation & Observability ✅
Aplicação
FastAPI (Python 3.12)
Arquitetura modular
Routers:
health
jobs
simulate
Pydantic models
Prometheus Instrumentator
Qualidade
Pytest
13 testes passando
Ruff configurado
pyproject.toml
Containerização
Dockerfile multi-stage
Usuário non-root
Healthcheck Docker
Docker Compose
Observabilidade
Prometheus
Grafana
Dashboard criado contendo:
Total HTTP Requests
Requests per Second
Jobs Created
Failed Jobs
GitHub
README profissional
Architecture.md
Commits organizados
Projeto publicado
LinkedIn
Projeto adicionado na seção Destaques
Fase 2 — Terraform + Kind ✅
Ferramentas
Terraform 1.9.8
Kind v0.24.0
kubectl v1.34.1
Infraestrutura

Criados:

infra/terraform/
├── main.tf
├── variables.tf
├── outputs.tf
├── versions.tf
├── kind-config.yaml
└── .terraform.lock.hcl
Terraform

Executado:

terraform init
terraform apply
Resultado

Cluster criado com sucesso:

sre-platform-control-plane
sre-platform-worker

Validação:

kubectl get nodes

Resultado:

control-plane Ready
worker Ready
Git
Branch feature/terraform-kind
PR criado
Merge realizado para main
Fase 3 — Helm Deployment ✅
Helm

Instalado:

Helm v4.1.4
Chart criado
infra/helm/jobs-api/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── deployment.yaml
    ├── service.yaml
    ├── serviceaccount.yaml
    ├── hpa.yaml
    └── servicemonitor.yaml
Recursos implementados
Deployment
RollingUpdate
maxUnavailable: 0
imagePullPolicy: Never
Health Checks
Liveness Probe → /health
Readiness Probe → /ready
HPA
minReplicas = 1
maxReplicas = 5
CPU target = 70%
Service
ClusterIP
Port 8000
ServiceMonitor

Implementado mas desabilitado temporariamente:

--set serviceMonitor.enabled=false
Problema importante resolvido
Importação de imagens para Kind

Com Docker Desktop no Windows:

kind load docker-image

falhou.

Solução adotada:

docker save jobs-api:local \
| docker exec -i sre-platform-control-plane \
ctr -n k8s.io images import -

docker save jobs-api:local \
| docker exec -i sre-platform-worker \
ctr -n k8s.io images import -

Essa solução já fica documentada para futuras versões do projeto.

Estado atual do cluster
Pods
kubectl get pods -n app

Resultado:

jobs-api Running 1/1
Service
kubectl get svc -n app

Resultado:

jobs-api ClusterIP 8000/TCP
Nodes
kubectl get nodes

Resultado:

control-plane Ready
worker Ready
Endpoints validados
/health
/ready
/metrics

Todos respondendo corretamente dentro do Kubernetes.

Próxima Fase — Observability on Kubernetes
Branch
git checkout -b feature/observability
Instalar
kube-prometheus-stack

Namespace:

observability
Loki Stack

Namespace:

observability
Habilitar
--set serviceMonitor.enabled=true
Criar
Dashboard Grafana Kubernetes
Dashboard específico da jobs-api
Alertas
Alertas planejados
Pod Down
Error Rate
High Latency (p99)
High CPU
High Memory
Situação atual do projeto
Fase 1 ✅ Foundation & Observability
Fase 2 ✅ Terraform + Kind
Fase 3 ✅ Helm Deployment
Fase 4 ⏳ Kubernetes Observability
Fase 5 ⏳ GitHub Actions CI/CD
Fase 6 ⏳ Runbooks & Incident Simulation