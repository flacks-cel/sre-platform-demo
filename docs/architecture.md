# Architecture — sre-platform-demo

> **Status:** v2.0 — with GitOps (ArgoCD)
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
                    ArgoCD monitora infra/helm/jobs-api
                    e sincroniza automaticamente
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Local Environment (Kind)                      │
│                                                                 │
│  Terraform  ──►  Kind Cluster  ──►  Namespaces + RBAC          │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Namespace: argocd                                       │   │
│  │                                                          │   │
│  │   ArgoCD  ──►  monitora GitHub  ──►  sincroniza app      │   │
│  └──────────────────────────────────────────────────────────┘   │
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

### 3.3 Deploy — Helm + ArgoCD (GitOps)

| Item | Detalhe |
|---|---|
| Chart | Custom (`infra/helm/jobs-api`) |
| Versioning | `appVersion` alinhado com a tag da imagem Docker |
| Estratégia | `RollingUpdate` — zero downtime |
| Rollback | `helm rollback <release> <revision>` — documentado no runbook |
| CD | ArgoCD com sync automático (`prune: true`, `selfHeal: true`) |

**Fluxo GitOps:**
```
git push main
    ↓
ArgoCD detecta mudança em infra/helm/jobs-api
    ↓
Sync automático no cluster
    ↓
RollingUpdate sem downtime
```

Recursos Kubernetes gerados pelo chart:

- `Deployment`
- `Service` (ClusterIP)
- `HorizontalPodAutoscaler`
- `ServiceMonitor`

---

### 3.4 GitOps — ArgoCD

| Item | Detalhe |
|---|---|
| Instalação | Helm chart `argo/argo-cd` no namespace `argocd` |
| Application | `infra/argocd/application.yaml` |
| Source | `infra/helm/jobs-api` no branch `HEAD` |
| Sync policy | Automated — prune + selfHeal |
| UI | `http://localhost:8080` (via port-forward) |

**Comportamento:**
- `prune: true` — remove do cluster recursos que foram deletados do Git
- `selfHeal: true` — reverte mudanças manuais feitas diretamente no cluster

---

### 3.5 Observabilidade

#### Prometheus
- Deploy via `kube-prometheus-stack` (Helm)
- `ServiceMonitor` configurado para scrape da `jobs-api` a cada 15s

#### Grafana
- Dashboard customizado para a `jobs-api` com os painéis:
  - Request rate (req/s)
  - Error percentage
  - Latência p99
  - Jobs criados (contador acumulado)
  - Application logs

#### Loki + Promtail
- Promtail coleta logs de todos os pods como DaemonSet
- Loki armazena e indexa os logs (SingleBinary mode)
- Grafana conectado ao Loki como datasource adicional

---

### 3.6 CI/CD — GitHub Actions

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
    │
    ▼
ArgoCD detecta nova imagem/chart e sincroniza
```

---

### 3.7 Segurança

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
│       ├── main.py
│       ├── routers/
│       │   ├── health.py
│       │   ├── jobs.py
│       │   └── simulate.py
│       ├── models.py
│       ├── metrics.py
│       └── tests/
│           ├── test_health.py
│           └── test_jobs.py
│
├── infra/
│   ├── terraform/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   └── versions.tf
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
│   └── argocd/
│       └── application.yaml       # ArgoCD Application manifest
│
├── observability/
│   ├── prometheus/
│   │   └── prometheus.yml
│   ├── grafana/
│   │   └── dashboards/
│   │       └── jobs-api.json
│   └── loki/
│
├── .github/
│   └── workflows/
│       └── ci.yaml
│
├── docs/
│   ├── architecture.md
│   ├── runbook.md
│   └── sre-practices.md
│
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

---

## 5. Fluxo de Deploy (GitOps)

```
0. git clone https://github.com/flacks-cel/sre-platform-demo.git
   cd sre-platform-demo

1. terraform init && terraform apply
   └── cria o Kind cluster, namespaces e RBAC

2. helm install kube-prometheus-stack ...    (namespace: observability)
   helm install loki ...                     (namespace: observability)
   helm install promtail ...                 (namespace: observability)

3. helm install argocd argo/argo-cd ...      (namespace: argocd)
   kubectl apply -f infra/argocd/application.yaml
   └── ArgoCD sincroniza jobs-api automaticamente

4. kubectl port-forward svc/argocd-server 8080:80 -n argocd
   └── ArgoCD UI: http://localhost:8080

5. kubectl port-forward svc/kube-prometheus-stack-grafana 3000:80 -n observability
   └── Grafana: http://localhost:3000
```

---

## 6. Decisões Técnicas e Trade-offs

| Decisão | Alternativa considerada | Motivo da escolha |
|---|---|---|
| Kind como cluster local | Minikube, k3s | Kind é o mais usado em CI, melhor documentação para portfólio |
| Terraform para Kind | Script bash / Makefile | IaC desde o início sinaliza maturidade de processo |
| Estado in-memory na API | PostgreSQL, Redis | Reduz complexidade sem prejudicar as métricas operacionais |
| ArgoCD para GitOps | Flux, deploy manual | GitOps fecha o ciclo CI/CD; ArgoCD é padrão de mercado |
| kube-prometheus-stack | Instalação manual | Stack completa, production-grade, padrão do mercado |
| Helm chart próprio | Kustomize | Helm é o padrão para portfólio SRE; demonstra versionamento de release |
| Loki SingleBinary | Modo distribuído | Recursos limitados no Kind local; adequado para portfólio |

---

## 7. Evoluções Futuras

- [ ] Testes de carga com k6
- [ ] Chaos Engineering com Chaos Mesh ou LitmusChaos
- [ ] Policy enforcement com OPA/Gatekeeper
- [ ] Multi-environment (staging / production) com values diferentes no Helm
- [ ] Alertas configurados no Alertmanager (PagerDuty / Opsgenie)
- [ ] Terraform remote backend (S3 + DynamoDB)

---

## 8. Referências

- [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
- [Loki](https://grafana.com/docs/loki/latest/setup/install/helm/)
- [ArgoCD](https://argo-cd.readthedocs.io/en/stable/)
- [Kind — Kubernetes in Docker](https://kind.sigs.k8s.io/)
- [Terraform Kind Provider](https://registry.terraform.io/providers/tehcyx/kind/latest/docs)
- [prometheus-fastapi-instrumentator](https://github.com/trallnag/prometheus-fastapi-instrumentator)
- [Trivy](https://aquasecurity.github.io/trivy/)