# SRE Practices — sre-platform-demo

> Este documento descreve as decisões técnicas, práticas de SRE e trade-offs aplicados na construção da plataforma.  
> O objetivo não é justificar escolhas — é demonstrar que cada decisão foi intencional.

---

## 1. Princípios Aplicados

### 1.1 Operabilidade desde o início

A aplicação foi construída com operabilidade como requisito, não como adição posterior:

- `/health` e `/ready` existem desde o primeiro commit — não foram adicionados quando o Kubernetes exigiu
- `/metrics` expõe métricas Prometheus desde o início — observabilidade não é opcional
- Logs estruturados em todas as rotas — cada request é rastreável

Esse princípio reflete a prática SRE de tratar a operação como parte do desenvolvimento, não como responsabilidade separada.

### 1.2 IaC desde o primeiro recurso

O cluster Kubernetes, os namespaces e o RBAC foram provisionados via Terraform antes de qualquer workload ser deployado. Não existe recurso criado manualmente no cluster que não esteja representado em código.

Isso garante que o ambiente é **reproduzível** — qualquer pessoa com o repositório consegue recriar o ambiente completo com `terraform apply`.

### 1.3 Imutabilidade de imagens

Cada versão da aplicação gera uma imagem Docker imutável tagueada com o SHA do commit. Nunca se usa a tag `latest` em deploy — isso tornaria o rollback ambíguo e o rastreamento impossível.

### 1.4 Falha como cenário planejado

O projeto inclui endpoints de simulação de falha (`/simulate/error`, `/simulate/latency`) e um procedimento documentado de rollback. A premissa é que falhas vão acontecer — o que importa é detectar rápido, entender o impacto e recuperar com controle.

---

## 2. Decisões de Infraestrutura

### 2.1 Kind em vez de cloud

**Decisão:** usar Kind (Kubernetes in Docker) como cluster local.

**Alternativas consideradas:** Minikube, k3s, GKE free tier, EKS.

**Motivo:**
- Zero custo — sem risco de esquecer recursos rodando
- 100% reproduzível — qualquer máquina com Docker consegue rodar
- Kind é o cluster mais usado em pipelines de CI — familiaridade com o ambiente de produção de pipelines
- O mesmo Terraform funciona em qualquer cloud trocando o provider — a decisão de Kind não limita o conhecimento demonstrado

**Trade-off aceito:** o cluster não persiste entre reinicializações do Docker. O procedimento de recuperação está documentado no `runbook.md`.

### 2.2 Terraform para provisionar Kind

**Decisão:** usar Terraform para criar o cluster, namespaces e RBAC.

**Alternativa considerada:** script bash, Makefile.

**Motivo:** IaC desde o início sinaliza maturidade de processo. Um script bash cria recursos mas não rastreia estado — não sabe o que já existe, não consegue destruir seletivamente, não produz um plan antes de aplicar. Terraform resolve esses três problemas.

**Trade-off aceito:** o provider `tehcyx/kind` é community, não oficial HashiCorp. Para produção usaríamos providers oficiais de cloud.

### 2.3 Namespace separado por domínio

O cluster tem dois namespaces com propósitos distintos:

| Namespace | Conteúdo | Motivo |
|---|---|---|
| `app` | jobs-api, ServiceAccount, RBAC | Isolamento da workload de negócio |
| `observability` | Prometheus, Grafana, Loki, Promtail | Isolamento da camada de operação |

Isso segue o princípio de separação de concerns: a plataforma de observabilidade não depende do ciclo de vida das aplicações que monitora.

---

## 3. Decisões de Deploy

### 3.1 Helm em vez de manifests avulsos

**Decisão:** Helm chart próprio para a `jobs-api`.

**Alternativa considerada:** Kustomize, manifests kubectl.

**Motivo:** Helm trata o deploy como um release versionado. Cada `helm upgrade` cria uma revisão, e `helm rollback` reverte para qualquer revisão anterior instantaneamente. Kustomize gerencia arquivos mas não tem conceito nativo de release ou rollback.

### 3.2 RollingUpdate com maxUnavailable=0

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0
```

**Motivo:** garante zero downtime em todo deploy. O Kubernetes só remove o pod antigo depois que o novo estiver Running e passando nas probes. O custo é ter temporariamente um pod extra (`maxSurge: 1`), o que é aceitável.

### 3.3 Probes configuradas corretamente

```yaml
livenessProbe:   # detecta processo travado — reinicia o pod
  httpGet:
    path: /health

readinessProbe:  # detecta processo não pronto — remove do load balancer
  httpGet:
    path: /ready
```

A distinção entre liveness e readiness é intencional:
- **Liveness** reinicia o container quando o processo trava mas não responde
- **Readiness** remove o pod do Service enquanto ele está inicializando ou sobrecarregado, sem reiniciá-lo

Usar o mesmo endpoint para os dois seria um erro — um pod sobrecarregado seria reiniciado em vez de apenas removido do tráfego.

### 3.4 HPA com target de CPU

```yaml
hpa:
  minReplicas: 1
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70
```

**Motivo:** o HPA garante que a plataforma escala automaticamente sob carga sem intervenção manual. O target de 70% deixa margem para picos antes de atingir o limite.

---

## 4. Decisões de Observabilidade

### 4.1 kube-prometheus-stack em vez de instalação manual

**Decisão:** usar o chart `kube-prometheus-stack` da prometheus-community.

**Motivo:** o chart instala Prometheus, Grafana, Alertmanager, kube-state-metrics e node-exporter em uma stack integrada e pré-configurada. Instalar cada componente manualmente produziria o mesmo resultado com muito mais esforço e mais superfície de erro.

Para portfólio, usar a stack padrão de mercado demonstra conhecimento do ecossistema — não apenas capacidade de configurar YAML.

### 4.2 ServiceMonitor em vez de scrape estático

O Prometheus descobre a `jobs-api` via `ServiceMonitor`, não via configuração estática no `prometheus.yml`.

**Motivo:** com ServiceMonitor, cada aplicação declara como quer ser monitorada no próprio chart Helm. O Prometheus Operator detecta automaticamente novos ServiceMonitors sem precisar de alteração na configuração central. Isso é o padrão para plataformas com múltiplas aplicações.

**Dependência:** o ServiceMonitor só pode ser criado após o kube-prometheus-stack instalar o CRD. Por isso o deploy da `jobs-api` usa `--set serviceMonitor.enabled=false` na primeira instalação e `helm upgrade` com `true` após o Prometheus Operator estar Running.

### 4.3 Loki em modo SingleBinary

**Decisão:** Loki em modo `SingleBinary` com storage filesystem.

**Alternativa considerada:** modo distribuído com object storage (S3/GCS).

**Motivo:** o cluster Kind local não tem recursos para rodar Loki em modo distribuído. O modo SingleBinary é adequado para ambiente de desenvolvimento e demonstração. Em produção, usaríamos object storage com retenção configurada.

**Trade-off aceito:** `useTestSchema=true` e cache desabilitado (`chunksCache.enabled=false`). Adequado para portfólio local, não para produção.

### 4.4 Métricas RED como base do dashboard

O dashboard da `jobs-api` é construído em torno das métricas RED (Rate, Errors, Duration) — o framework padrão para monitorar serviços:

| Métrica | Query | Significado |
|---|---|---|
| Rate | `sum(rate(http_requests_total[1m]))` | Throughput atual |
| Errors | `100 * sum(rate(...status="5xx"...)) / sum(rate(...))` | % de requisições com erro |
| Duration | `histogram_quantile(0.99, ...)` | Latência no percentil 99 |

O p99 em vez de média foi uma decisão intencional — a média esconde outliers. Em sistemas reais, um usuário que experimenta 10 segundos de latência não é consolado pelo fato de que a média é 200ms.

---

## 5. Decisões de Segurança

### 5.1 Non-root user no container

```dockerfile
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser
```

**Motivo:** containers rodando como root têm acesso privilegiado ao host em caso de escape de container. Non-root é o mínimo de segurança para qualquer imagem de produção.

### 5.2 RBAC com permissões mínimas

O ServiceAccount `jobs-api` tem permissões apenas para `get`, `list` e `watch` em `pods`, `services` e `endpoints`. Não tem permissão de escrita em nenhum recurso.

**Motivo:** princípio do menor privilégio. Um processo comprometido só pode ler o estado do cluster, não modificá-lo.

### 5.3 Trivy no pipeline como gate

O pipeline bloqueia em vulnerabilidades `HIGH` e `CRITICAL`. Uma imagem com vulnerabilidades conhecidas não chega ao registry.

**Motivo:** segurança é gate, não observação. Reportar vulnerabilidades sem bloquear o deploy cria uma falsa sensação de controle.

### 5.4 Secrets nunca em plaintext

Secrets são gerenciados via Kubernetes `Secret`, nunca em `ConfigMap` ou variáveis de ambiente hardcoded no código. O repositório tem um `secrets/README.md` documentando essa política.

---

## 6. Decisões de CI/CD

### 6.1 Pipeline de qualidade antes de deploy

O pipeline GitHub Actions valida cada PR antes de entrar na `main`:

```
lint → tests → build → trivy scan → push GHCR
```

O deploy não é automatizado na v1 — é executado manualmente via `helm upgrade` após o pipeline validar a imagem. Essa decisão foi intencional: evita over-engineering na fase inicial e mantém o controle explícito sobre o que vai para produção.

**Evolução planejada:** ArgoCD para GitOps com sync automático ou com aprovação manual configurável.

### 6.2 Branch por fase com PR

Cada fase do projeto foi desenvolvida em branch separada e mergeada via Pull Request com descrição do que foi feito e por quê. Isso constrói um histórico de decisões no GitHub — não apenas um histórico de código.

---

## 7. O que seria diferente em produção

| Aspecto | Implementação atual | Em produção |
|---|---|---|
| Cluster | Kind local | GKE, EKS ou AKS com node pools dedicados |
| Terraform state | Local (`terraform.tfstate`) | Remote backend (S3 + DynamoDB ou GCS) |
| Imagem registry | GHCR público | Registry privado com scanning contínuo |
| Loki storage | Filesystem local | Object storage (S3/GCS) com retenção configurada |
| Deploy | Manual via `helm upgrade` | GitOps com ArgoCD |
| Secrets | Kubernetes Secret manual | Vault ou AWS Secrets Manager |
| Testes de carga | Simulação manual | k6 com cenários automatizados no pipeline |
| Multi-environment | Single environment | staging / production com values separados no Helm |
| Alertas | Não configurados | PagerDuty ou Opsgenie integrado ao Alertmanager |

---

## 8. Lições aprendidas

**Kind não persiste entre reinicializações do Docker**  
O cluster é destruído quando o Docker reinicia. O procedimento de recuperação virou parte do runbook — que é exatamente onde esse conhecimento operacional deve estar.

**ServiceMonitor depende do CRD do Prometheus Operator**  
Instalar a aplicação com `serviceMonitor.enabled=true` antes do kube-prometheus-stack falha silenciosamente. A sequência de instalação importa e deve estar documentada.

**`kind load docker-image` não funciona no Windows com Docker Desktop**  
O workaround correto é importar via `ctr -n k8s.io images import`. Descoberto na prática, documentado no runbook para não precisar redescobrir.

**Loki 2.x é incompatível com Grafana 11**  
O chart `loki-stack` (deprecated) instala o Loki 2.6.1, que não conecta ao Grafana 11. A migração para o chart `grafana/loki` com modo SingleBinary resolveu o problema.