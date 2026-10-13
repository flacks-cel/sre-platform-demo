# Spike 002 — Distribuição da Evidência de CPU sob Carga Concorrente

> Status: **especificação v4.1 — gate evidencial preenchido.**
> Base: `main @ b8bd49c` (pós PR #7, #8 e #9).
> A calibração é **não-evidencial**. As rodadas evidenciais são A (baseline) e B (principal).

---

## 1. Pergunta

> Com carga concorrente distribuída pelo Service e HPA ativo, como a evidência de CPU se
> distribui por pod — inclusive nos pods criados durante a rodada — e o pior pod observado
> representa carga real ou um artefato de cobertura, amostragem ou inicialização?

A pergunta existe porque o Spike 001 não conseguiu respondê-la: o `port-forward` do Service
prendeu todo o tráfego em um único pod, então não houve distribuição para observar.

---

## 2. Escopo

A ADR-003 estabelece evidência **por pod/container, sem somar réplicas**. Este spike determina se
usar o pior pod como representante do serviço é robusto sob scale-out ou se pods jovens podem
produzir um falso pior caso por cobertura parcial.

Este spike **não** classifica risco, não recomenda CPU, não implementa recommendation engine e não
usa IA/LLM.

---

## 3. Duas grandezas de custo

### 3.1 `cpu_cost_rate(t)`

```text
cpu_rate(t)      = rate(container_cpu_usage_seconds_total{pod}[janela])
request_rate(t)  = rate(http_requests_total{pod}[janela])
cpu_cost_rate(t) = cpu_rate(t) / request_rate(t)
```

Unidade: CPU-seconds/request. É uma estimativa local por janela e pode sofrer extrapolação quando a
série começa dentro da janela.

### 3.2 `span_cost(pod)`

```text
span            = intersection(pod_lifetime, analysis_phase)
Δcpu_seconds    = último − primeiro valor do contador de CPU no span
Δrequests       = último − primeiro valor do contador de requests no span
span_cost(pod)  = Δcpu_seconds / Δrequests
```

Sem janela fixa e sem extrapolação. É usado para distinguir artefato de `rate()` de custo real de
startup.

Leitura cruzada:

| `cpu_cost_rate` | `span_cost` | Conclusão |
|---|---|---|
| anômalo | normal | artefato de rate/cobertura |
| anômalo | anômalo | custo real de inicialização |
| normal | anômalo | pico fora da janela local; investigar |

---

## 4. Rodadas

| | Calibração | A — Baseline | B — Principal |
|---|---|---|---|
| Natureza | não-evidencial | evidencial | evidencial |
| HPA | ativo | `minReplicas = maxReplicas = N` | `minReplicas = 1`, `maxReplicas = N` |
| Réplicas | 1 → ? | fixas em `N` | 1 → `N` |
| Objetivo | escolher uma carga reproduzível que provoque scale-out sem contaminar o lab | dispersão normal entre pods maduros | distribuição durante scale-out |
| Produz evidência? | não | sim | sim |

### 4.1 Critério de saída da calibração

A calibração não precisa descobrir o equilíbrio natural exato do HPA. Ela precisa escolher uma carga
que, de forma reproduzível:

1. provoque scale-out;
2. não sature o node;
3. não produza `dropped_iterations`;
4. não produza erro HTTP nem restart de pod.

`N` pode ser um **teto imposto** em B, desde que A use as mesmas `N` réplicas e a mesma taxa oferecida.
Nesse caso `N` não é descrito como equilíbrio natural observado.

A calibração foi encerrada com `N = 3` e `0,75 RPS`. A saída da calibração não entra na matriz de
decisão.

---

## 5. Sequência de execução

### 5.1 Rodada A — maturação antes de T0

Depois que o commit de A sincronizar, exigir antes de `T0(A)`:

1. exatamente `N` pods Ready;
2. zero restarts desde a sincronização;
3. todos os pods com `coverage >= piso` para a janela longa;
4. ArgoCD `Synced` + `Healthy` na revisão esperada.

Só então inicia a carga. O primeiro minuto de carga em A é aquecimento e não entra nas faixas de
baseline.

### 5.2 Transição A → B

```text
termina A
  → sincroniza commit de B (min=1, max=N)
  → espera scale-down observado até k=1
  → confirma k=1 estável
  → T0(B)
```

A espera é comprovada por consulta, não por um sleep fixo.

---

## 6. Gerador de carga

| Item | Decisão |
|---|---|
| Forma | Job k6 dentro do cluster |
| Namespace | `praeva-load` |
| Alvo | `http://jobs-api.app.svc.cluster.local:8000` |
| Imagem | `grafana/k6:2.3.0` |
| Executor | `constant-arrival-rate` |
| Conexões | `noConnectionReuse: true` |
| Endpoint | `GET /simulate/cpu-work?iterations=1000000` |

O endpoint executa quantidade fixa de trabalho por request. Requests de `/health`, `/ready` e
`/metrics` não entram na contagem do experimento; a métrica é filtrada pelo `handler` do endpoint de
carga.

---

## 7. Regras de validade

Rodada que falha nestas condições não é interpretada:

| Condição | Veredito |
|---|---|
| CPU do node que hospeda `jobs-api` >= 90% em duas coletas consecutivas | inválida |
| restart de pod durante a carga | contaminada |
| pod Pending por falta de recurso | inválida |
| qualquer erro HTTP da carga (`http_req_failed > 0`) | inválida |
| `dropped_iterations > 0` | inválida |
| Metrics API indisponível em alguma coleta programada | inválida |
| `scrape_interval` diferente de 15s | inválida |
| pré-condições de A não satisfeitas | inválida |
| `k != 1` antes de `T0(B)` | inválida |
| B não atinge `N=3` | inconclusiva para A×B; análise interna de B continua válida |

---

## 8. Fases e `k(t)`

`k(t)` é o conjunto de backends elegíveis no intervalo. A origem primária é
`kube_endpointslice_endpoints` com `ready="true"`, `serving="true"` e `terminating="false"`.
`kube_pod_status_ready` é usado como conferência histórica auxiliar.

Um intervalo no qual o conjunto elegível mudou é **transicional** e fica fora da análise de
distribuição.

Fases de B:

| Fase | Definição |
|---|---|
| `pre-scale` | de `T0(B)` até o primeiro evento de scale |
| `scale-up` | do primeiro scale até o início de `steady-state` |
| `steady-state` | primeiro intervalo em que `k` está estável e todos os pods incluídos têm coverage >= 80%, até o fim da carga |

---

## 9. Distribuição de requests

Quando `k` varia, a distribuição é analisada por intervalo não-transicional:

```text
esperado(t) = n(t) / k(t)
σ(t)        = sqrt(n(t)/k(t) * (1 - 1/k(t)))
faixa(t)    = esperado(t) ± 3σ(t)
```

A faixa vale para **contagem de requests**, não para CPU.

### 9.1 Pooling no steady-state

Com `0,75 RPS`, um intervalo de 15s contém poucas requests para `k=3`. Portanto a faixa multinomial
por intervalo tem pouco poder estatístico para separar C de D.

No `steady-state`, onde `k` é constante por definição, a contagem é acumulada sobre **toda a fase** e
a mesma faixa multinomial é calculada com `n` da fase inteira.

No `scale-up`, pooling entre diferentes `k` não é legítimo. C/D não serão distinguidas nessa fase com
estes parâmetros; A1/A2 continuam decidíveis porque dependem de coverage e `span_cost`.

---

## 10. Evidências

| Evidência | Origem primária |
|---|---|
| CPU rate curta/longa | Prometheus |
| contador de CPU para `span_cost` | Prometheus |
| CPU limit no mesmo instante | `kube_pod_container_resource_limits` |
| throttling | `container_cpu_cfs_throttled_periods_total` |
| coverage ratio | `count_over_time` |
| criação do pod | `kube_pod_created` |
| ReplicaSet/owner | `kube_pod_owner` |
| restarts | `kube_pod_container_status_restarts_total` |
| backends elegíveis | `kube_endpointslice_endpoints` |
| requests por pod | `http_requests_total{handler="/simulate/cpu-work"}` |
| CPU dos nodes | Prometheus; `kubectl top nodes` auxiliar |
| HPA | Kubernetes/Metrics API |
| dropped iterations | saída do k6 |

Prometheus histórico e snapshots live do Kubernetes nunca são apresentados como se fossem o mesmo
instante (ADR-006).

### 10.1 Coverage

```text
coverage = observed_samples / expected_samples
expected_samples ~= rate_window / scrape_interval
```

Piso escolhido: **80%**. Com janela longa de 5m e scrape de 15s, são ~20 amostras esperadas; o pod
precisa de pelo menos 80% dessa cobertura para ser tratado como maduro. O piso tolera falhas pontuais
de scrape sem aceitar série esparsa de pod recém-criado como evidência completa.

Limit ausente no mesmo instante é `UNKNOWN`, nunca zero. Pontos `UNKNOWN` ficam fora da mediana e da
escolha do pior pod, e são contados no relatório.

---

## 11. Matriz de decisão

Aplicada somente a rodadas válidas e por fase.

`cov` = coverage do pior pod; `req` = contagem vs. faixa multinomial; `cpu/req` = `cpu_cost_rate` vs.
baseline; `custo` = `span_cost` vs. baseline.

| # | `cov` | `req` | `cpu/req` | `custo` | Decisão |
|---|---|---|---|---|---|
| A1 | abaixo | dentro | — | normal | artefato de cobertura; filtro mínimo + ADR-008 |
| A2 | abaixo | dentro | — | anômalo | custo real de startup; não filtrar + ADR-009 |
| B | abaixo | acima | — | — | inconclusivo |
| C | completa | dentro | dentro | — | ADR-003 permanece válida |
| D | completa | acima | dentro | — | pior pod representa mais tráfego real |
| E | completa | dentro | acima | — | investigar assimetria real de custo |
| F | — | pior ~= mediana | dentro | — | distribuição uniforme; ADR-003 pouco sensível |

As linhas C/D são avaliadas no `steady-state` usando pooling da fase. No `scale-up`, o poder
estatístico da contagem é reconhecidamente baixo; A1/A2 são o foco.

Faixas robustas de baseline:

```text
robust_sigma = 1.4826 * MAD
faixa = max(0, mediana - 3 * robust_sigma) .. mediana + 3 * robust_sigma
```

Calculadas separadamente para `cpu_cost_rate` e `span_cost`.

---

## 12. Parâmetros travados antes das rodadas evidenciais

Mudar qualquer parâmetro abaixo invalida a comparação A×B e exige novo gate.

| Parâmetro | Valor | Justificativa |
|---|---|---|
| Versão da imagem k6 | `grafana/k6:2.3.0` | versão pinada usada na calibração |
| Endpoint único e payload | `GET /simulate/cpu-work?iterations=1000000` | trabalho fixo e homogêneo |
| Taxa de chegada | **0,75 RPS** (`3/4s`) | provocou scale-out sem node pressure, erro, restart ou dropped iteration |
| `preAllocatedVUs` / `maxVUs` | `20 / 100` | capacidade do gerador; não define a carga |
| `N` | **3** | teto imposto para manter A e B comparáveis; não é descrito como equilíbrio natural |
| Duração A e B | **8m** | permite scale-out e coverage de 5m amadurecer antes do fim |
| Aquecimento descartado em A | **60s** | remove custo inicial do processo de baseline; não se aplica a pods novos de B |
| Janela curta de rate | **2m** | sensível a mudança rápida; compatível com Spike 001 |
| Janela longa de rate | **5m** | referência de estabilidade e maturação |
| `scrape_interval` observado | **15s** | confirmado no ServiceMonitor vigente |
| Intervalo de coleta | **15s** | acompanha a cadência de scrape e limita intervalos transicionais |
| Piso de coverage ratio | **80%** | ~16/20 amostras na janela longa; evita série jovem/esparsa sem exigir perfeição |
| Limiar de erro HTTP | **0%** | workload local determinístico; qualquer erro contamina a rodada |
| Saturação de node | **>=90% por 2 coletas consecutivas** no node do app | evita falso headroom por competição de CPU do node |
| Baseline `cpu_cost_rate` | preenchido após A | precisa vir de A antes de B |
| Baseline `span_cost` | preenchido após A | precisa vir de A antes de B |
| Commit SHA | registrado por rodada | ArgoCD deve sincronizar exatamente a revisão esperada |

**Gate aberto:** os parâmetros estão preenchidos e commitados antes de qualquer rodada evidencial.

---

## 13. Limitações pré-registradas

1. `N=3` é teto experimental, não equilíbrio natural do HPA. Em B o HPA pode ficar limitado em 3;
   CPU absoluta deve ser lida nesse contexto. A comparação A×B continua simétrica porque A também usa 3.
2. Com 0,75 RPS, a análise multinomial por intervalo tem baixo poder para C/D durante `scale-up`.
   O pooling é permitido apenas no `steady-state` com `k` constante.
3. O busy loop de 1.000.000 iterações pode diluir custo fixo de startup. A1, se observado, vale para
   este workload e não deve ser generalizado automaticamente para serviços de requests baratos e startup caro.
4. B observa apenas dois eventos de nascimento (1→2→3). O tamanho amostral de pods jovens é `n=2`.
   Se A1/A2 ficar ambíguo, repetir com N maior passa a ser uma decisão posterior, não parte deste gate.
5. O lab atual tende a agendar todos os pods `jobs-api` no mesmo worker; o spike não mede assimetria
   entre nodes diferentes.

---

## 14. Checklist

**Antes do gate**

- [x] `kube_pod_owner`, `kube_pod_created`, `kube_pod_status_ready` confirmadas no KSM
- [x] `kube_endpointslice_endpoints` com `targetref_name`, readiness/serving/terminating confirmado
- [x] endpoint determinístico criado e testado
- [x] calibração executada; `N` e taxa escolhidos

**Gate**

- [x] seção 12 preenchida e commitada
- [x] piso de coverage justificado por escrito antes dos dados
- [x] limitações metodológicas pré-registradas

**Rodadas evidenciais**

- [ ] configuração por commit, não por `kubectl`
- [ ] `ARGOCD_TARGET_REVISION` fixado em revisão explícita
- [ ] A: `N=3`, maturação satisfeita antes de `T0(A)`
- [ ] A: baseline `cpu_cost_rate` e `span_cost` registrado antes de B
- [ ] A→B: commit de B sincronizado antes de esperar scale-down
- [ ] B: `k=1` observado e estável antes de `T0(B)`
- [ ] namespace `praeva-load` fora dos ServiceMonitors do app
- [ ] stash antigo não aplicado
