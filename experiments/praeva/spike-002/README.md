# Spike 002 — Distribuição da Evidência de CPU sob Carga Concorrente

> Status: **especificação v4.2 — gate evidencial preenchido.**
> Base: `main @ b8bd49c` (pós PR #7, #8 e #9).
> A calibração é **não-evidencial**. As rodadas evidenciais são A (baseline) e B (principal).

## 1. Pergunta

> Com carga concorrente distribuída pelo Service e HPA ativo, como a evidência de CPU se
> distribui por pod — inclusive nos pods criados durante a rodada — e o pior pod observado
> representa carga real ou um artefato de cobertura, amostragem ou inicialização?

O Spike 001 não respondeu isso porque o `port-forward` concentrou a carga em um único pod.

## 2. Escopo

A ADR-003 estabelece evidência **por pod/container, sem somar réplicas**. Este spike verifica se o
pior pod continua sendo uma representação operacional válida sob scale-out ou se pods jovens podem
parecer artificialmente piores por cobertura parcial.

Fora de escopo: risk engine, recommendation engine, sizing automático e IA/LLM.

## 3. Grandezas

### `cpu_cost_rate(t)`

```text
cpu_rate(t)      = rate(container_cpu_usage_seconds_total{pod}[janela])
request_rate(t)  = rate(http_requests_total{pod}[janela])
cpu_cost_rate(t) = cpu_rate(t) / request_rate(t)
```

Unidade: CPU-seconds/request. É uma estimativa local por janela e pode sofrer extrapolação quando a
série começa dentro da janela.

### `span_cost(pod)`

```text
span            = intersection(pod_lifetime, analysis_phase)
Δcpu_seconds    = último − primeiro contador de CPU no span
Δrequests       = último − primeiro contador de requests no span
span_cost(pod)  = Δcpu_seconds / Δrequests
```

Sem extrapolação de `rate()`. Leitura cruzada:

| `cpu_cost_rate` | `span_cost` | Conclusão |
|---|---|---|
| anômalo | normal | artefato de rate/cobertura |
| anômalo | anômalo | custo real de inicialização |
| normal | anômalo | pico fora da janela local; investigar |

## 4. Rodadas

| | Calibração | A — Baseline | B — Principal |
|---|---|---|---|
| Natureza | não-evidencial | evidencial | evidencial |
| HPA | ativo | `min=max=N` | `min=1`, `max=N` |
| Réplicas | 1 → ? | fixas em `N` | 1 → `N` |
| Objetivo | escolher carga reproduzível e válida | custo entre pods maduros | distribuição sob scale-out |

A calibração não precisa descobrir o equilíbrio natural exato do HPA. Ela só precisa selecionar uma
carga que provoque scale-out sem node saturation, `dropped_iterations`, erro HTTP ou restart.

**Decisão:** `N=3` é um **teto imposto**, não equilíbrio natural observado. A usa as mesmas 3 réplicas
e a mesma taxa de B, preservando a comparação A×B.

## 5. Sequência

### A — antes de `T0(A)`

Exigir simultaneamente:

1. 3 pods `Ready`;
2. zero restarts;
3. 3 endpoints elegíveis no EndpointSlice;
4. coverage da janela longa `>=80%` para todos os pods;
5. Metrics API disponível;
6. ServiceMonitor em 15s;
7. ArgoCD `Synced` + `Healthy` na revisão esperada.

O baseline descarta os **primeiros 120s** da carga. Isso é intencional: a janela curta é de 2m, então
a primeira amostra de baseline não pode carregar tráfego anterior a `T0(A)` no `rate()`.

### A → B

```text
termina A
  → commita/sincroniza B (min=1,max=3)
  → espera scale-down observado até k=1
  → confirma k=1 estável
  → T0(B)
```

Nada de `kubectl edit/scale`: configuração é Git-driven porque ArgoCD usa `selfHeal`.

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

A contagem de requests filtra exclusivamente `handler="/simulate/cpu-work"`; probes e scrapes não
entram na distribuição.

## 7. Regras de validade

| Condição | Veredito |
|---|---|
| CPU do node do app `>=90%` em 2 coletas consecutivas | inválida |
| restart de pod durante carga | contaminada |
| pod Pending por falta de recurso | inválida |
| `http_req_failed > 0` | inválida |
| `dropped_iterations > 0` | inválida |
| Metrics API indisponível em coleta programada | inválida |
| scrape diferente de 15s | inválida |
| A sem maturação completa | inválida |
| B sem `k=1` antes de T0 | inválida |
| B não atinge `N=3` | inconclusiva para A×B; análise interna de B ainda vale |

## 8. `k(t)`, fases e intervalos transicionais

Origem primária do conjunto elegível: `kube_endpointslice_endpoints` com `ready="true"`,
`serving="true"` e `terminating="false"`. `kube_pod_status_ready` é conferência auxiliar.

Se o conjunto elegível mudar dentro de um intervalo, o intervalo é **transicional** e fica fora da
análise de distribuição.

Fases de B:

| Fase | Definição |
|---|---|
| `pre-scale` | T0 até primeiro scale |
| `scale-up` | primeiro scale até início de steady-state |
| `steady-state` | primeiro intervalo com `k` estável e todos os pods com coverage `>=80%`, até fim da carga |

## 9. Distribuição de requests

Para intervalo não-transicional:

```text
esperado(t) = n(t) / k(t)
σ(t)        = sqrt(n(t)/k(t) * (1 - 1/k(t)))
faixa(t)    = esperado(t) ± 3σ(t)
```

Com 0,75 RPS, `n` por intervalo de 15s é pequeno. Logo:

- no `scale-up`, não fazer pooling entre `k` diferentes; A1/A2 são o foco;
- no `steady-state`, `k` é constante por definição e as requests são acumuladas sobre **toda a fase**;
  C/D usam a faixa multinomial calculada com o `n` pooled da fase.

## 10. Evidência coletada

| Evidência | Origem |
|---|---|
| CPU rate 2m/5m | Prometheus |
| contador de CPU | Prometheus |
| CPU limit histórico | `kube_pod_container_resource_limits` |
| throttling 2m | CFS metrics |
| coverage | `count_over_time` |
| criação/owner/restarts | kube-state-metrics |
| backends elegíveis | EndpointSlice/KSM |
| requests por pod | `http_requests_total{handler="/simulate/cpu-work"}` |
| node CPU | Prometheus; `kubectl top` auxiliar |
| HPA/Metrics API | Kubernetes |
| dropped iterations | k6 |

Prometheus histórico e snapshot live nunca são tratados como o mesmo instante (ADR-006).

Coverage:

```text
coverage = observed_samples / expected_samples
expected_samples ~= rate_window / scrape_interval
```

Piso: **80%**. Na janela de 5m com scrape de 15s existem ~20 amostras esperadas; 80% evita aceitar
uma série jovem/esparsa como madura, sem exigir scrape perfeito.

Limit ausente no mesmo instante é `UNKNOWN`, nunca zero. `UNKNOWN` não entra em mediana nem na escolha
do pior pod e é contado na saída.

## 11. Matriz

`cov` = coverage do pior pod; `req` = contagem vs faixa multinomial; `cpu/req` = `cpu_cost_rate` vs
baseline; `custo` = `span_cost` vs baseline.

| # | `cov` | `req` | `cpu/req` | `custo` | Decisão |
|---|---|---|---|---|---|
| A1 | abaixo | dentro | — | normal | artefato de cobertura; ADR-008 |
| A2 | abaixo | dentro | — | anômalo | custo real de startup; ADR-009; não filtrar |
| B | abaixo | acima | — | — | inconclusivo |
| C | completa | dentro | dentro | — | ADR-003 permanece válida |
| D | completa | acima | dentro | — | pior pod recebeu mais tráfego real |
| E | completa | dentro | acima | — | assimetria real; investigar |
| F | — | pior ~= mediana | dentro | — | distribuição uniforme |

Faixas robustas de baseline:

```text
robust_sigma = 1.4826 * MAD
faixa = max(0, mediana - 3 * robust_sigma) .. mediana + 3 * robust_sigma
```

## 12. Parâmetros travados

Mudar qualquer parâmetro abaixo invalida a comparação A×B e exige novo gate.

| Parâmetro | Valor | Justificativa |
|---|---|---|
| k6 | `grafana/k6:2.3.0` | pinado |
| endpoint | `/simulate/cpu-work?iterations=1000000` | trabalho fixo |
| taxa | **0,75 RPS** (`3/4s`) | scale-out limpo na calibração |
| VUs | `20 / 100` | capacidade, não carga |
| `N` | **3** | teto imposto e simétrico em A/B |
| duração A/B | **8m** | tempo para scale-out e coverage amadurecer |
| warm-up descartado em A | **120s** | cobre integralmente a janela curta de 2m |
| janela curta | **2m** | sinal rápido |
| janela longa | **5m** | estabilidade/maturação |
| scrape | **15s** | observado |
| coleta | **15s** | alinhada ao scrape |
| coverage floor | **80%** | ~16/20 amostras na janela longa |
| erro HTTP | **0%** | qualquer falha contamina |
| node saturation | **>=90% por 2 coletas consecutivas** | evita falso headroom |
| baseline `cpu_cost_rate` | preencher após A | antes de B |
| baseline `span_cost` | preencher após A | antes de B |
| revisão | SHA registrada por rodada | sincronização exata do ArgoCD |

**Gate aberto.**

## 13. Limitações pré-registradas

1. `N=3` é teto, não equilíbrio natural; CPU absoluta deve carregar esse contexto.
2. C/D têm pouco poder no `scale-up`; pooling é permitido só no `steady-state` com `k` constante.
3. O busy loop pesado pode diluir custo fixo de startup. A1 vale para este workload, não para todos os serviços.
4. B observa apenas dois pods jovens (`1→2→3`), portanto `n=2` para A1/A2.
5. O lab tende a agendar os pods do app no mesmo worker; não inferir assimetria entre nodes.

## 14. Checklist

**Gate**

- [x] KSM necessário confirmado
- [x] EndpointSlice histórico confirmado
- [x] endpoint determinístico criado/testado
- [x] calibração encerrada; N/taxa escolhidos
- [x] parâmetros preenchidos antes de A/B
- [x] coverage floor justificado
- [x] limitações pré-registradas

**A/B**

- [x] A configurada por commit (`min=max=3`)
- [ ] ArgoCD sincronizado no SHA atual
- [ ] A madura antes de T0
- [ ] A executada e baseline registrado
- [ ] B configurada por commit (`min=1,max=3`)
- [ ] B inicia em `k=1`
- [ ] B executada e matriz aplicada por fase
