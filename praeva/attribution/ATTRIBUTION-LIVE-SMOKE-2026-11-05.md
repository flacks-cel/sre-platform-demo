# ATTRIBUTION — registro de laboratório real — 2026-11-05

> **Tipo:** evidência observacional de sessão (exploratória), não gate de produto.
> **Branch testada:** `praeva/attribution-compose-001`, HEAD `68fed678dbe5ad2d9be3a33988a6a231c30796cd`.
> **Ambiente:** Windows Git Bash, Docker Desktop / Kind `sre-platform`, Deployment `app/jobs-api`, Prometheus local `http://localhost:9091`.
> **Escopo:** smoke real da composição de attribution; depois um rollout Kubernetes controlado, **sem análise histórica pós-rollout ainda**.
> **Origem deste registro:** saídas de terminal fornecidas pelo operador na sessão; não substitui a captura bruta.

## 1. Pré-condições observadas

- Docker Engine: `29.5.3`.
- Cluster Kind `sre-platform` encontrado; `app/jobs-api` disponível (1/1).
- HPA `jobs-api`: 1 réplica atual, mínimo 1, máximo 5, alvo de CPU 70%.
- Prometheus: `/-/ready` respondeu `Prometheus Server is Ready.` após ativar o port-forward.
- O preflight `experiments/praeva/spike-003/preflight.py` para o **R1 congelado de 30 minutos** retornou `candidate_ready: false` por falta de cobertura histórica individual das séries. Por isso a sessão **não** executou nem declarou aprovação do R1 completo.
- Consultas instantâneas de diagnóstico retornaram CPU 2m e 5m, owner do Pod, owners de ReplicaSets e `kube_pod_created` com UID.

## 2. Smoke test real da composição — antes do rollout

Foi executado diretamente com os módulos do repositório:

```text
collect_normalized_evidence(include_throttling=True)
  -> build_report
  -> build_attribution_fact_inputs (para planejar a aquisição)
  -> collect_ownership_evidence (Prometheus real)
  -> query_range(kube_pod_created, com UID) [script exploratório]
  -> compose_attribution
```

Parâmetros usados (timestamps Unix UTC, grade exata):

| Propriedade | Valor |
|---|---|
| Verificação `start` | `1793904015` |
| Verificação `end` | `1793904075` |
| `step` | `15` segundos |
| Short/long | `2m` / `5m` |
| Ownership `start` | `1793903715` |
| Ownership `end` | `1793904075` |
| Namespace / workload / container | `app` / `jobs-api` / `jobs-api` |
| Pod observado | `jobs-api-68bc8467b5-wbd22` |
| UID observado | `676ccd6c-76eb-411b-98a7-b3f74f147fc5` |
| `kube_pod_created` (valor) | `1793035541` |
| Séries de ownership coletadas | 1 Pod + 3 ReplicaSets |

**Saída observada:**

```text
Fatos totais: 25
Decisoes: {'ATTRIBUTED': 25}
Classes nao atribuiveis: {}
Analise: {'status': 'INADMISSIBLE',
          'reason': 'target_domain_undeterminable'}

cpu_short          witness=USABLE          domain=COMPLETE
cpu_long           witness=USABLE          domain=COMPLETE
cfs_throttled_short witness=NOT_APPLICABLE domain=COMPLETE
cfs_throttled_long  witness=USABLE         domain=COMPLETE
cpu_limit_ratio     witness=USABLE         domain=NOT_APPLICABLE
```

**Interpretação exata:**

- Os 25 fatos observados tiveram atribuição àquele Deployment/UID **na grade temporal e sob o envelope nominal** usados no teste.
- `domain=COMPLETE` em `summary_proof` é completude **da série observada** para o resumo; **não** é completude da população do Deployment.
- `target_domain_status` foi passado explicitamente como `UNDETERMINABLE`, e `population_evidence` como `INCOMPLETE(population_not_proven)`. Esses estados **não foram descobertos/provados por um produtor de população**; são um limite conservador explícito do teste.
- O `cfs_throttled_long witness=USABLE` indica um testemunho positivo utilizável no resumo da série, **não** uma classificação de Risk.
- A consulta exploratória de `kube_pod_created` não é ainda um adaptador de produto para criação por UID, com gates de cobertura/consistência versionados.

A captura completa permaneceu no computador do operador em:

```text
.runtime/praeva-attribution-live-smoke.json
```

Esse caminho é local e ignorado pelo Git; **o conteúdo bruto não foi anexado a este commit**. Para instituir replay versionado, será necessário disponibilizar uma captura saneada/explicitamente revisada.

## 3. Controle negativo sobre a mesma captura real

Sem nova coleta, o operador repetiu `compose_attribution` com `creation_by_pod_uid={}`.

```text
Total: 25
Status: {'UNATTRIBUTED': 25}
Classes: {'attribution_unproven': 25}
PASSOU: nenhuma atribuição foi fabricada.
```

Essa verificação prova que a composição **não promoveu fatos observados à condição ATTRIBUTED sem creation evidence do UID**. Ela não prova a correção de todas as classes de churn, nem valida população.

## 4. Rollout real executado — análise histórica pós-rollout pendente

A seguir foi executado:

```bash
kubectl -n app rollout restart deployment/jobs-api
kubectl -n app rollout status deployment/jobs-api --timeout=180s
```

O Kubernetes retornou `deployment.apps/jobs-api restarted` e `deployment "jobs-api" successfully rolled out`.

Início registrado: **2026-11-05T18:50:41Z**. Snapshot `kubectl get pods` após `rollout status`:

| Papel no rollout | Pod | UID | created | Status no snapshot |
|---|---|---|---|---|
| Novo | `jobs-api-64884c6f89-9sz7m` | `54a7fd7e-b9b6-4d96-82eb-fff8302db56e` | `2026-11-05T18:50:42Z` | `Running` |
| Antigo | `jobs-api-68bc8467b5-wbd22` | `676ccd6c-76eb-411b-98a7-b3f74f147fc5` | `2026-11-02T17:25:41Z` | `Running` |

O snapshot ainda mostra os dois Pods `Running` após o sucesso do rollout; não concluir que o antigo já havia desaparecido nesse instante. A troca de ReplicaSet/nome/UID confirma que ocorreu substituição, mas **não é o cenário S3 de mesmo nome de Pod com UIDs diferentes**.

**Não houve coleta do Verify/ownership cobrindo a transição após o rollout, nem execução de `compose_attribution` nessa janela.** Portanto não existe, nesta sessão, resultado real pós-rollout de `support_predates_pod`, `identity_discontinuity`, `attribution_unproven` ou witnesses envolvendo os dois Pods. Esses resultados ficam para a próxima sessão, a partir de evidência histórica efetivamente adquirida.

## 5. Limites e pendências preservados

- Nenhum wiring de attribution no `praeva analyze`; `CHANGE-JOIN-001` continua com `CALLER_ASSERTED`.
- Nenhuma prova de população `O(T)`, completude por família, ou version relation.
- Nenhuma mudança na semântica de `CHANGE-RISK-001`. A limitação S9 (risco de `HIGH` ocultar `CRITICAL` sob população incompleta) permanece no caminho de produto.
- A mitigação conservadora de S9 discutida separadamente continua uma **proposta** e requer pré-registro e testes antes de qualquer alteração.
- Os resultados deste documento são apenas da execução fornecida pelo operador. Não são uma suíte automatizada de integração live nem prova event-time contínua.

## 6. Próxima sessão

1. Confirmar que Prometheus/Kind permanecem acessíveis e que o histórico cobre os instantes antes, durante e depois do rollout.
2. Coletar Verify/ownership/`kube_pod_created` com timestamps explícitos e grade preservada, capturando também os dois UIDs.
3. Executar `compose_attribution` nessa nova captura, sem alegar `population_evidence=COMPLETE` e sem hardcode de UID.
4. Publicar relatório pós-rollout distinto com resultados e limitações reais (mesmo se o output for `UNKNOWN`).
5. Avaliar merge do PR #27 separadamente, mediante aprovação explícita.
