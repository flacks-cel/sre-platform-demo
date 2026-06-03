# SRE Platform Demo - Project Status

**Última atualização:** 03/06/2026

## Visão Geral

Repositório: https://github.com/flacks-cel/sre-platform-demo

Objetivo do projeto:

Construir uma plataforma demonstrando práticas modernas de SRE e Platform Engineering utilizando:

* FastAPI
* Docker
* Kubernetes
* Terraform
* Helm
* Prometheus
* Grafana
* Loki
* GitHub Actions

---

# Fase 1 - Foundation & Observability ✅

## Aplicação

Implementação da API utilizando FastAPI com arquitetura modular.

### Componentes

* FastAPI
* Pydantic Models
* Prometheus Instrumentator
* Health Checks
* Readiness Checks

### Routers

* health
* jobs
* simulate

---

## Qualidade

### Testes

* Pytest configurado
* 13 testes automatizados passando

### Lint

* Ruff configurado
* pyproject.toml criado

---

## Containerização

### Docker

* Dockerfile multi-stage
* Usuário non-root
* Healthcheck configurado

### Docker Compose

Stack criada contendo:

* jobs-api
* Prometheus
* Grafana

---

## Observabilidade

### Prometheus

* Métricas expostas em `/metrics`
* Scraping configurado

### Grafana

Dashboard criado contendo:

* Total HTTP Requests
* Requests per Second
* Jobs Created
* Failed Jobs

---

## GitHub

* README atualizado
* Architecture.md criado
* Estrutura inicial documentada

---

## LinkedIn

Projeto adicionado na seção Destaques do perfil.

---

# Fase 2 - Terraform + Kind ✅

## Ferramentas

* Terraform 1.9.8
* Kind v0.24.0
* kubectl v1.34.1

---

## Estrutura Terraform

```text
infra/terraform/
├── main.tf
├── variables.tf
├── outputs.tf
├── versions.tf
├── kind-config.yaml
└── .terraform.lock.hcl
```

## Provisionamento

Executado:

```bash
terraform init
terraform apply
```

---

## Cluster Kubernetes

Cluster criado com sucesso.

### Nodes

```text
sre-platform-control-plane
sre-platform-worker
```

Validação:

```bash
kubectl get nodes
```

Resultado:

```text
control-plane Ready
worker Ready
```

---

## Git

### Branch

```text
feature/terraform-kind
```

### Resultado

* PR criado
* Merge realizado
* Main atualizada

---

# Fase 3 - Helm Deployment ✅

## Helm

Instalado:

```text
Helm v4.1.4
```

---

## Estrutura do Chart

```text
infra/helm/jobs-api/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── deployment.yaml
    ├── service.yaml
    ├── serviceaccount.yaml
    ├── hpa.yaml
    └── servicemonitor.yaml
```

---

## Recursos Implementados

### Deployment

* RollingUpdate
* maxUnavailable: 0
* imagePullPolicy: Never

### Health Checks

* Liveness Probe → /health
* Readiness Probe → /ready

### HPA

```text
minReplicas: 1
maxReplicas: 5
targetCPUUtilizationPercentage: 70
```

### Service

```text
ClusterIP
Port 8000
```

### ServiceMonitor

Implementado e temporariamente desabilitado:

```bash
--set serviceMonitor.enabled=false
```

---

## Problema Resolvido

### Importação de imagem para o Kind

No Windows com Docker Desktop, o comando:

```bash
kind load docker-image
```

não funcionou corretamente.

Solução adotada:

```bash
docker save jobs-api:local | docker exec -i sre-platform-control-plane ctr -n k8s.io images import -

docker save jobs-api:local | docker exec -i sre-platform-worker ctr -n k8s.io images import -
```

---

## Validações

### Endpoints

```text
/health
/ready
/metrics
```

Todos respondendo corretamente.

### Pods

```bash
kubectl get pods -n app
```

Resultado:

```text
jobs-api Running 1/1
```

### Service

```bash
kubectl get svc -n app
```

Resultado:

```text
jobs-api ClusterIP 8000/TCP
```

### Nodes

```bash
kubectl get nodes
```

Resultado:

```text
control-plane Ready
worker Ready
```

---

# Próxima Fase - Observability on Kubernetes 🚧

## Branch

```bash
git checkout -b feature/observability
```

---

## Objetivos

### kube-prometheus-stack

Instalar no namespace:

```text
observability
```

### Loki Stack

Instalar no namespace:

```text
observability
```

### ServiceMonitor

Habilitar:

```bash
--set serviceMonitor.enabled=true
```

---

## Dashboards

Criar dashboards para:

* Kubernetes Cluster
* Jobs API
* Prometheus
* Aplicação

---

## Alertas Planejados

* Pod Down
* Error Rate
* High CPU Usage
* High Memory Usage
* High Latency (p99)

---

# Roadmap

## Concluído

* [x] FastAPI
* [x] Docker
* [x] Docker Compose
* [x] Prometheus
* [x] Grafana
* [x] Terraform
* [x] Kind
* [x] Kubernetes Cluster
* [x] Helm Deployment

## Próximas Etapas

* [ ] kube-prometheus-stack
* [ ] Loki
* [ ] ServiceMonitor
* [ ] Kubernetes Dashboards
* [ ] Alerting
* [ ] GitHub Actions CI/CD
* [ ] Runbooks
* [ ] Incident Simulation

---

# Observações

* `.terraform/` está no `.gitignore`
* `terraform.tfstate` está no `.gitignore`
* Para ambientes Windows + Docker Desktop utilizar `ctr -n k8s.io images import` ao invés de `kind load docker-image`
* O ServiceMonitor depende da instalação prévia do kube-prometheus-stack
