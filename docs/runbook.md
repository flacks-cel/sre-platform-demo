# Runbook — sre-platform-demo

> **Audiência:** Engenheiros de Platform / SRE operando o ambiente local do projeto  
> **Pré-requisitos:** Docker Desktop, Kind, Terraform, Helm, kubectl, Git Bash  
> **Repositório:** https://github.com/flacks-cel/sre-platform-demo

---

## Índice

1. [Subir o ambiente do zero](#1-subir-o-ambiente-do-zero)
2. [Recuperar cluster após reinício do Docker](#2-recuperar-cluster-após-reinício-do-docker)
3. [Acessar os serviços](#3-acessar-os-serviços)
4. [Simular falhas](#4-simular-falhas)
5. [Executar rollback](#5-executar-rollback)
6. [Verificar saúde do ambiente](#6-verificar-saúde-do-ambiente)
7. [Atualizar a aplicação](#7-atualizar-a-aplicação)
8. [Desligar o ambiente](#8-desligar-o-ambiente)

---

## 1. Subir o ambiente do zero

Use este procedimento quando o ambiente ainda não existe — primeira execução ou após destruição completa.

### 1.1 Provisionar o cluster

```bash
cd infra/terraform
terraform init
terraform apply
# digita: yes
```

Aguarda a mensagem `Apply complete! Resources: 6 added`.

Valida:

```bash
kubectl get nodes
# sre-platform-control-plane   Ready
# sre-platform-worker          Ready

kubectl get namespaces | grep -E "app|observability"
# app            Active
# observability  Active
```

### 1.2 Carregar a imagem Docker nos nodes

> O Kind não acessa registries externos por padrão. A imagem precisa ser importada manualmente.

```bash
cd /c/Particular/Flavio/sre-platform-demo

docker save jobs-api:local | docker exec -i sre-platform-control-plane ctr -n k8s.io images import -
docker save jobs-api:local | docker exec -i sre-platform-worker ctr -n k8s.io images import -
```

Valida:

```bash
docker exec sre-platform-control-plane ctr -n k8s.io images ls | grep jobs
# docker.io/library/jobs-api:local
```

### 1.3 Adicionar repositórios Helm

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

### 1.4 Instalar o stack de observabilidade

```bash
# Prometheus + Grafana + Alertmanager
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace observability \
  --set grafana.adminPassword=admin \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false

# Aguarda todos os pods ficarem Running
kubectl get pods -n observability -w
```

```bash
# Loki
helm install loki grafana/loki \
  --namespace observability \
  --set loki.auth_enabled=false \
  --set loki.commonConfig.replication_factor=1 \
  --set loki.storage.type=filesystem \
  --set deploymentMode=SingleBinary \
  --set singleBinary.replicas=1 \
  --set read.replicas=0 \
  --set write.replicas=0 \
  --set backend.replicas=0 \
  --set loki.useTestSchema=true \
  --set chunksCache.enabled=false \
  --set resultsCache.enabled=false

# Promtail
helm install promtail grafana/promtail \
  --namespace observability \
  --set config.clients[0].url=http://loki.observability.svc.cluster.local:3100/loki/api/v1/push
```

### 1.5 Instalar a jobs-api

```bash
# Instala sem ServiceMonitor (CRD ainda não está pronto)
helm install jobs-api ./infra/helm/jobs-api -n app --set serviceMonitor.enabled=false

# Aguarda o pod ficar Running
kubectl get pods -n app -w

# Habilita o ServiceMonitor
helm upgrade jobs-api ./infra/helm/jobs-api -n app --set serviceMonitor.enabled=true
```

### 1.6 Configurar datasource Loki no Grafana

1. Acessa `http://localhost:3000` (após port-forward — ver seção 3)
2. **Connections → Data sources → Add data source → Loki**
3. URL: `http://loki.observability.svc.cluster.local:3100`
4. **Save & test** → deve retornar `Data source connected`

### 1.7 Importar o dashboard

1. **Dashboards → New → Import**
2. Cola o conteúdo de `observability/grafana/dashboards/jobs-api.json`
3. **Load → Import**

---

## 2. Recuperar cluster após reinício do Docker

> O Kind não persiste entre reinicializações do Docker Desktop. Use este procedimento sempre que o cluster estiver inacessível.

**Sintoma:**
```
Unable to connect to the server: dial tcp 127.0.0.1:XXXXX: connectex: No connection could be made
```

### 2.1 Limpar o state do Terraform

```bash
cd infra/terraform

terraform state rm kind_cluster.this
terraform state rm 'kubernetes_namespace.namespaces["app"]'
terraform state rm 'kubernetes_namespace.namespaces["observability"]'
terraform state rm kubernetes_service_account.jobs_api
terraform state rm kubernetes_role.jobs_api
terraform state rm kubernetes_role_binding.jobs_api
```

### 2.2 Remover cluster Kind residual (se existir)

```bash
kind delete cluster --name sre-platform 2>/dev/null
```

### 2.3 Recriar o ambiente

Segue a partir da **seção 1.1** — o processo é idêntico ao primeiro boot.

---

## 3. Acessar os serviços

> Cada port-forward precisa de um terminal dedicado.

```bash
# Grafana — http://localhost:3000 (admin / admin)
kubectl port-forward svc/kube-prometheus-stack-grafana 3000:80 -n observability

# Prometheus — http://localhost:9090
kubectl port-forward svc/kube-prometheus-stack-prometheus 9090:9090 -n observability

# jobs-api — http://localhost:8000
kubectl port-forward svc/jobs-api 8000:8000 -n app

# Alertmanager — http://localhost:9093
kubectl port-forward svc/kube-prometheus-stack-alertmanager 9093:9093 -n observability
```

---

## 4. Simular falhas

> Use os endpoints de simulação para gerar dados nos dashboards e testar alertas.

### 4.1 Gerar tráfego normal

```bash
# Cria jobs
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"name": "demo-job", "payload": {"client": "test"}}'

# Consulta job criado
curl http://localhost:8000/jobs/<id>
```

### 4.2 Simular erros HTTP 500

```bash
curl http://localhost:8000/simulate/error
```

Observa no Grafana: painel **Error Percentage** deve subir.

### 4.3 Simular latência

```bash
# Latência de 3 segundos
curl "http://localhost:8000/simulate/latency?seconds=3"
```

Observa no Grafana: painel **Latency p99** deve subir.

### 4.4 Simular falha de pod

```bash
# Deleta o pod — o Deployment recria automaticamente
kubectl delete pod -l app=jobs-api -n app

# Acompanha a recriação
kubectl get pods -n app -w
```

Observa no Grafana: breve interrupção nas métricas seguida de recuperação automática.

### 4.5 Verificar logs da falha no Grafana

1. Acessa **Explore → Loki**
2. Query: `{namespace="app"}`
3. Filtra pelo período da falha

---

## 5. Executar rollback

### 5.1 Ver histórico de releases

```bash
helm history jobs-api -n app
```

Exemplo de output:
```
REVISION  STATUS      DESCRIPTION
1         superseded  Install complete
2         deployed    Upgrade complete
```

### 5.2 Rollback para revisão anterior

```bash
helm rollback jobs-api 1 -n app
```

### 5.3 Validar rollback

```bash
kubectl get pods -n app -w
# Pod recria com a versão anterior

curl http://localhost:8000/health
# {"status":"alive"}

helm history jobs-api -n app
# Revisão 3 aparece com descrição "Rollback to 1"
```

---

## 6. Verificar saúde do ambiente

### 6.1 Checklist rápido

```bash
# Cluster
kubectl get nodes

# Pods
kubectl get pods -n app
kubectl get pods -n observability

# Helm releases
helm list -n app
helm list -n observability

# ServiceMonitor
kubectl get servicemonitor -n app

# HPA
kubectl get hpa -n app
```

### 6.2 Saúde esperada

| Recurso | Status esperado |
|---|---|
| sre-platform-control-plane | Ready |
| sre-platform-worker | Ready |
| jobs-api pod | Running 1/1 |
| prometheus pod | Running 2/2 |
| grafana pod | Running 3/3 |
| loki pod | Running 2/2 |
| promtail pods | Running 1/1 (em cada node) |
| ServiceMonitor jobs-api | Present |
| HPA jobs-api | MINPODS=1, MAXPODS=5 |

---

## 7. Atualizar a aplicação

### 7.1 Build da nova imagem

```bash
docker build -t jobs-api:v2 .
```

### 7.2 Carregar nos nodes

```bash
docker save jobs-api:v2 | docker exec -i sre-platform-control-plane ctr -n k8s.io images import -
docker save jobs-api:v2 | docker exec -i sre-platform-worker ctr -n k8s.io images import -
```

### 7.3 Deploy via Helm (RollingUpdate)

```bash
helm upgrade jobs-api ./infra/helm/jobs-api -n app \
  --set image.tag=v2 \
  --set serviceMonitor.enabled=true
```

Acompanha o rolling update:

```bash
kubectl rollout status deployment/jobs-api -n app
```

### 7.4 Rollback se necessário

```bash
helm rollback jobs-api -n app
```

---

## 8. Desligar o ambiente

### 8.1 Parar o cluster (mantém o state)

Basta fechar o Docker Desktop. O cluster será destruído mas o `terraform.tfstate` permanece — **não** use `terraform destroy` se quiser preservar o histórico.

### 8.2 Destruição completa

```bash
cd infra/terraform
terraform destroy
# digita: yes
```

---

## Referências rápidas

| Serviço | URL local | Credenciais |
|---|---|---|
| Grafana | http://localhost:3000 | admin / admin |
| Prometheus | http://localhost:9090 | — |
| Alertmanager | http://localhost:9093 | — |
| jobs-api | http://localhost:8000 | — |
| API docs | http://localhost:8000/docs | — |

---

## 9. Instalar e operar o ArgoCD

### 9.1 Instalar o ArgoCD

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

helm install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --set configs.params."server\.insecure"=true
```

Aguarda os pods subirem:

```bash
kubectl get pods -n argocd -w
```

### 9.2 Obter a senha do admin

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d
```

### 9.3 Acessar a UI

```bash
kubectl port-forward svc/argocd-server -n argocd 8080:80
```

Acessa `http://localhost:8080` — usuário `admin`, senha do passo anterior.

### 9.4 Criar a Application da jobs-api

```bash
kubectl apply -f infra/argocd/application.yaml
```

Valida:

```bash
kubectl get application -n argocd
# NAME       SYNC STATUS   HEALTH STATUS
# jobs-api   Synced        Healthy
```

### 9.5 Forçar sync manual

```bash
kubectl patch application jobs-api -n argocd \
  --type merge \
  -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

Ou via UI: abre a aplicação e clica em **Sync**.

### 9.6 Verificar status após mudança no Git

Após qualquer `git push` para `main` com mudança em `infra/helm/jobs-api`, o ArgoCD detecta automaticamente e sincroniza. Verifica:

```bash
kubectl get application -n argocd
```

O campo `SYNC STATUS` muda para `OutOfSync` momentaneamente e volta para `Synced` após o deploy.

### 9.7 Saúde esperada do ArgoCD

| Recurso | Status esperado |
|---|---|
| argocd-application-controller | Running 1/1 |
| argocd-applicationset-controller | Running 1/1 |
| argocd-dex-server | Running 1/1 |
| argocd-notifications-controller | Running 1/1 |
| argocd-redis | Running 1/1 |
| argocd-repo-server | Running 1/1 |
| argocd-server | Running 1/1 |
| Application jobs-api | Synced + Healthy |