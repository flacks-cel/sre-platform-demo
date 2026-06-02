# Architecture — sre-platform-demo

> **Status:** v1.0 — baseline architecture  
> **Last updated:** 2026-06  
> **Author:** Platform/SRE Portfolio Project

---

## 1. Objetivo do Projeto

Demonstrar a construção de uma **plataforma DevOps/SRE completa e operável**, incluindo provisionamento de infraestrutura, deploy em Kubernetes, observabilidade end-to-end, segurança e resiliência — usando uma aplicação de processamento de jobs como carga de trabalho de referência.

> O foco não é a aplicação. O foco é a plataforma que a suporta.

---

## 2. Visão Geral da Arquitetura

```
┌─────────────────────────────────────────────────────────────────┐
│                        GitHub Repository                        │
│                                                                 │
│  push / PR  ──►  GitHub Actions Pipeline                        │
│                  │                                              │
│                  ├── lint + tests                               │
│                  ├── docker build (multi-stage)                 │
│                  ├── trivy scan (image vulnerabilities)         │
│                  └── push → GitHub Container Registry (GHCR)   │
└─────────────────────────────────────────────────────────────────┘
                                │
                    (manual deploy via Helm)
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Local Environment (Kind)                      │
│                                                                 │
│  Terraform  ──►  Kind Cluster  ──►  Namespaces + RBAC          │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Namespace: app                                          │   │
│  │                                                          │   │
│  │   ┌──────────────────────────────┐                       │   │
│  │   │   Deployment: jobs-api       │                       │   │
│  │   │   (FastAPI — Python 3.12)    │                       │   │
│  │   │                              │                       │   │
│  │   │   /health    /ready          │                       │   │
│  │   │   /metrics   /jobs           │                       │   │
│  │   │   /jobs/{id}                 │                       │   │
│  │   │   /simulate/error            │                       │   │
│  │   │   /simulate/latency          │                       │   │
│  │   │                              │                       │   │
│  │   │   liveness probe  → /health  │                       │   │
│  │   │   readiness probe → /ready   │                       │   │
│  │   └──────────────────────────────┘                       │   │
│  │                                                          │   │
│  │   HPA: min=1  max=5  target CPU=70%                      │   │
│  │   Strategy: RollingUpdate (maxSurge=1, maxUnavailable=0) │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Namespace: observability                                │   │
│  │                                                          │   │
│  │   Prometheus  ──►  scrape /metrics (jobs-api)            │   │
│  │   Grafana     ──►  dashboards (latência, erros, jobs)    │   │
│  │   Loki        ──►  logs agregados dos pods               │   │
│  │   Promtail    ──►  coleta logs → Loki                    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Componentes

### 3.1 Aplicação — `jobs-api`

| Item | Detalhe |
|---|---|
| Runtime | Python 3.12 |
| Framework | FastAPI |
| Porta | 8000 |
| Métricas | `prometheus-fastapi-instrumentator` |
| Estado dos jobs | In-memory (dict) — sem banco de dados, intencional |

**Rotas:**

| Método | Rota | Propósito |
|---|---|---|
| GET | `/health` | Liveness — retorna 200 se o processo está vivo |
| GET | `/ready` | Readiness — retorna 200 se a app está pronta para receber tráfego |
| GET | `/metrics` | Endpoint Prometheus (formato text/plain) |
| POST | `/jobs` | Cria um job com payload JSON |
| GET | `/jobs/{id}` | Consulta o status de um job |
| GET | `/simulate/error` | Força um erro 500 (simula falha para teste de alerta) |
| GET | `/simulate/latency` | Introduz latência artificial (simula degradação) |

**Decisão de design — sem banco de dados:**  
O estado dos jobs é mantido em memória. Isso é intencional: o objetivo é gerar métricas operacionais (throughput, latência, erros), não demonstrar persistência. Um banco de dados adicionaria complexidade sem agregar valor ao posicionamento SRE.

---

### 3.2 Infraestrutura — Terraform + Kind

| Item | Detalhe |
|---|---|
| Provider | `tehcyx/kind` |
| Cluster | 1 control-plane + 1 worker (Kind local) |
| Recursos provisionados | Cluster, namespaces (`app`, `observability`), RBAC básico |
| Backend Terraform | Local (`terraform.tfstate`) |

**Decisão de design — Kind em vez de cloud:**  
Kind foi escolhido para garantir que o ambiente seja 100% reproduzível, sem custo e sem dependência de credenciais de cloud. O `README.md` documenta explicitamente essa escolha e seus trade-offs.

---

### 3.3 Deploy — Helm

| Item | Detalhe |
|---|---|
| Chart | Custom (`helm/jobs-api`) |
| Versioning | `appVersion` alinhado com a tag da imagem Docker |
| Estratégia | `RollingUpdate` — zero downtime |
| Rollback | `helm rollback <release> <revision>` — documentado no runbook |

Recursos Kubernetes gerados pelo chart:

- `Deployment`
- `Service` (ClusterIP)
- `HorizontalPodAutoscaler`
- `ConfigMap` (configurações não-sensíveis)
- `Secret` (referenciado via `secretKeyRef` — valor injetado externamente)

---

### 3.4 Observabilidade

#### Prometheus
- Deploy via `kube-prometheus-stack` (Helm)
- `ServiceMonitor` configurado para scrape da `jobs-api` a cada 15s
- Alertas: error rate > 5%, latência p99 > 2s, pod down

#### Grafana
- Dashboard customizado para a `jobs-api` com os painéis:
  - Request rate (req/s)
  - Latência (p50, p95, p99)
  - HTTP error rate (4xx, 5xx)
  - Jobs criados (contador acumulado)
  - Pod availability

#### Loki + Promtail
- Promtail coleta logs de todos os pods como DaemonSet
- Loki armazena e indexa os logs
- Grafana conectado ao Loki como datasource adicional

---

### 3.5 CI/CD — GitHub Actions

Pipeline acionado em push para qualquer branch e em pull requests para `main`:

```
lint (ruff)
    │
    ▼
tests (pytest)
    │
    ▼
docker build (multi-stage)
    │
    ▼
trivy scan (HIGH + CRITICAL)
    │
    ▼
push para GHCR  ← apenas em merge para main
```

**Deploy não é automatizado na v1:**  
O deploy é executado manualmente via `helm upgrade` após o pipeline validar a imagem. Essa decisão está documentada e o processo está descrito no `runbook.md`. Deploy automatizado é listado como evolução futura.

---

### 3.6 Segurança

| Prática | Implementação |
|---|---|
| Scan de imagem | Trivy no pipeline (bloqueia em HIGH/CRITICAL) |
| Secrets | Kubernetes `Secret` — nunca em ConfigMap ou variável de ambiente em plaintext |
| RBAC | `ServiceAccount` dedicado para a `jobs-api` com permissões mínimas |
| Imagem | Non-root user no Dockerfile, imagem slim |
| Network | Sem `hostNetwork`, sem `privileged` |

---

## 4. Estrutura do Repositório

```
sre-platform-demo/
├── app/
│   └── api/
│       ├── main.py              # entrypoint FastAPI
│       ├── routers/             # rotas separadas por domínio
│       │   ├── health.py
│       │   ├── jobs.py
│       │   └── simulate.py
│       ├── models.py            # Pydantic models
│       ├── metrics.py           # configuração Prometheus
│       └── tests/
│           ├── test_health.py
│           └── test_jobs.py
│
├── infra/
│   ├── terraform/
│   │   ├── main.tf              # Kind cluster
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   └── namespaces.tf        # namespaces + RBAC
│   │
│   ├── helm/
│   │   └── jobs-api/
│   │       ├── Chart.yaml
│   │       ├── values.yaml
│   │       └── templates/
│   │           ├── deployment.yaml
│   │           ├── service.yaml
│   │           ├── hpa.yaml
│   │           ├── serviceaccount.yaml
│   │           └── servicemonitor.yaml
│   │
│   └── kubernetes/
│       ├── rbac.yaml            # ClusterRole, RoleBinding
│       └── secrets/
│           └── README.md        # instrução — nunca commitar secrets reais
│
├── observability/
│   ├── prometheus/
│   │   └── values.yaml          # override do kube-prometheus-stack
│   ├── grafana/
│   │   └── dashboards/
│   │       └── jobs-api.json    # dashboard exportado
│   └── loki/
│       └── values.yaml          # override do loki-stack
│
├── .github/
│   └── workflows/
│       └── ci.yaml              # lint → test → build → scan → push
│
├── docs/
│   ├── architecture.md          # este arquivo
│   ├── runbook.md               # como operar, simular falhas, rollback
│   └── sre-practices.md        # decisões técnicas e trade-offs
│
├── docker-compose.yml           # execução local sem Kubernetes
├── Dockerfile                   # multi-stage, non-root
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

---

## 5. Fluxo de Deploy (v1 — manual)

```
0. git clone https://github.com/flacks-cel/sre-platform-demo.git
   cd sre-platform-demo

1. terraform init && terraform apply
   └── cria o Kind cluster, namespaces e RBAC

2. helm repo add prometheus-community ...
   helm install kube-prometheus-stack ...    (namespace: observability)
   helm install loki-stack ...               (namespace: observability)

3. helm install jobs-api ./infra/helm/jobs-api \
     --namespace app \
     --set image.tag=<versão>

4. kubectl port-forward svc/grafana 3000:80 -n observability
   └── acesso ao Grafana: http://localhost:3000
```

---

## 6. Decisões Técnicas e Trade-offs

| Decisão | Alternativa considerada | Motivo da escolha |
|---|---|---|
| Kind como cluster local | Minikube, k3s | Kind é o mais usado em CI, melhor documentação para portfólio |
| Terraform para Kind | Script bash / Makefile | IaC desde o início sinaliza maturidade de processo |
| Estado in-memory na API | PostgreSQL, Redis | Reduz complexidade sem prejudicar as métricas operacionais |
| Deploy manual na v1 | ArgoCD, Flux | Evita over-engineering na fase inicial; CD é evolução documentada |
| kube-prometheus-stack | Instalação manual | Stack completa, production-grade, padrão do mercado |
| Helm chart próprio | Kustomize | Helm é o padrão para portfólio SRE; demonstra versionamento de release |

---

## 7. Evoluções Futuras (fora do escopo v1)

- [ ] Deploy automático via GitHub Actions (ArgoCD ou `helm upgrade` no pipeline)
- [ ] Testes de carga com k6
- [ ] Chaos Engineering com Chaos Mesh ou LitmusChaos
- [ ] Policy enforcement com OPA/Gatekeeper
- [ ] Multi-environment (staging / production) com values diferentes no Helm

---

## 8. Referências

- [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
- [Loki Stack](https://grafana.com/docs/loki/latest/setup/install/helm/)
- [Kind — Kubernetes in Docker](https://kind.sigs.k8s.io/)
- [Terraform Kind Provider](https://registry.terraform.io/providers/tehcyx/kind/latest/docs)
- [prometheus-fastapi-instrumentator](https://github.com/trallnag/prometheus-fastapi-instrumentator)
- [Trivy](https://aquasecurity.github.io/trivy/)
