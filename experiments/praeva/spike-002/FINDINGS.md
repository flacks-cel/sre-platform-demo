# Spike 002 — Findings

> Status: **concluído.** Rodadas A e B executadas; decisão final registrada.
> Este arquivo separa claramente calibração (não-evidencial) de evidência produzida por A/B.

## 1. Calibração — não-evidencial

Objetivo: escolher uma carga que provoque scale-out de forma reproduzível sem saturar o node, sem
`dropped_iterations`, sem erro HTTP e sem restart de pod.

| Calibração | Taxa | Trabalho/request | Duração | Máx. réplicas | Máx. CPU node | Resultado |
|---|---:|---:|---:|---:|---:|---|
| 1 | 1,00 RPS | 1.000.000 iterações | 2m | 4 | 20% | scale-out forte; rodada curta demais para inferir equilíbrio |
| 2 | 0,50 RPS | 1.000.000 iterações | 4m | 1 | 10% | não provocou scale-out |
| 3 | 0,75 RPS | 1.000.000 iterações | 6m | 3 | 14% | scale-out limpo; após a carga fez 3→2→1 |
| 4 | 0,75 RPS | 1.000.000 iterações | 8m | 4 | 20% | mostrou que 3 não é equilíbrio natural garantido |

Todas as calibrações usadas para decisão tiveram zero erro HTTP, zero `dropped_iterations` e zero
restart durante a carga.

### Decisão de saída

Parâmetros evidenciais travados:

- `N = 3`;
- arrival rate = `0,75 RPS` (`3/4s`);
- workload = `GET /simulate/cpu-work?iterations=1000000`;
- duração = `8m`;
- A usa 3 réplicas fixas;
- B usa HPA `min=1`, `max=3`.

`N=3` é **teto imposto**, não equilíbrio natural observado. O objetivo da calibração não é reproduzir
a dinâmica natural completa do HPA; é criar A e B comparáveis com a mesma taxa e o mesmo `k` final.

## 2. Limitações pré-registradas

### 2.1 Poder estatístico da faixa multinomial

A `0,75 RPS`, cada intervalo de 15s tem cerca de 11 requests. Com `k=3`, a banda multinomial por
intervalo é larga demais para separar de forma útil as linhas C e D.

Decisão metodológica:

- no `scale-up`, não fazer pooling entre valores diferentes de `k`; A1/A2 são o foco;
- no `steady-state`, onde `k` é constante por definição, acumular as requests de toda a fase e aplicar
  a faixa multinomial ao `n` total da fase.

Consequência: C/D não são distinguíveis de forma robusta durante `scale-up` com estes parâmetros.

### 2.2 Workload sintético e startup

O busy loop de 1.000.000 iterações torna o custo por request homogêneo, mas pode diluir custos fixos
de startup (imports, runtime warm-up, GC inicial etc.).

Se A1 for observado, a conclusão vale para **este workload**. Não generalizar automaticamente para
serviços com requests baratos e startup caro; fazer isso seria extrapolar a evidência do spike.

### 2.3 Número de pods jovens

Com `maxReplicas=3`, B produz no máximo dois eventos de nascimento no scale-up: 1→2→3.

Tamanho amostral do achado sobre pods jovens: `n=2`. Isso é suficiente para caracterizar o sinal
observado, mas não para estimar frequência populacional.

### 2.4 Topologia do lab

Nas calibrações e nas rodadas A/B, os pods `jobs-api` foram agendados no mesmo worker. O Spike 002 não
pretende inferir assimetria entre nodes diferentes a partir deste lab.

## 3. Rodada A — Baseline

**Concluída e válida.**

- commit sincronizado: `75bfc8daf6db28e7336f29b0f83c77ae6bed96fb`;
- `T0 = 2026-10-13T18:29:26Z`;
- `T1 = 2026-10-13T18:37:32Z`;
- início da análise após warm-up de 120s: `2026-10-13T18:31:26Z`;
- `N=3` durante toda a rodada;
- zero restart durante a rodada;
- zero ponto com CPU limit desconhecido;
- todos os três pods com coverage acima do piso de 80%;
- o Job k6 concluiu sem violar os thresholds de erro HTTP ou `dropped_iterations`;
- nenhuma regra de invalidação do runner foi acionada.

### 3.1 Baseline de `cpu_cost_rate`

Faixa robusta calculada sobre 75 amostras válidas:

```text
median       = 0.1491020848282956 CPU-seconds/request
MAD          = 0.021464094120017208
robust_sigma = 0.031822665942337514
low          = 0.053634087001283054
high         = 0.24457008265530814
```

Por pod:

| Pod | amostras | mediana `cpu_cost_rate` | coverage mín. | throttling máx. |
|---|---:|---:|---:|---:|
| `jobs-api-849859f688-lfmnn` | 25 | 0.14834403238751048 | 105% | 13.24% |
| `jobs-api-849859f688-sgbd5` | 25 | 0.15203968710191532 | 95% | 21.49% |
| `jobs-api-849859f688-z6zck` | 25 | 0.1491020848282956 | 100% | 13.73% |

O throttling não foi zero no baseline e deve ser carregado como contexto ao comparar B; ele não
invalidou A porque A e B usam a mesma carga, limits e `k=3` no steady-state comparável.

### 3.2 Baseline de `span_cost`

```text
median       = 0.15332043333333333 CPU-seconds/request
MAD          = 0.005227980128205162
robust_sigma = 0.007751003338076973
low          = 0.1300674233191024
high         = 0.17657344334756425
```

Por pod:

| Pod | `span_cost` |
|---|---:|
| `jobs-api-849859f688-lfmnn` | 0.14633436046511628 |
| `jobs-api-849859f688-sgbd5` | 0.15854841346153847 |
| `jobs-api-849859f688-z6zck` | 0.15332043333333333 |

### 3.3 Distribuição de requests no baseline

No span analisado houve `n=280` requests entre `k=3` pods:

```text
esperado por pod ~= 93.33
faixa 3σ        ~= [69.67, 117.00]
```

Contagens observadas:

```text
lfmnn = 86
sgbd5 = 104
z6zck = 90
```

Todos ficaram dentro da faixa multinomial esperada. Portanto A fornece um baseline maduro e simétrico
adequado para interpretar B.

## 4. Rodada B — Principal

**Concluída e válida.**

- commit sincronizado: `688caa337545f52bd10af88da468675c4d5ce3b2`;
- `T0 = 2026-10-13T18:52:37Z`;
- `T1 = 2026-10-13T19:00:50Z`;
- k6: `361/361` checks, `http_req_failed=0`, `dropped_iterations=0`;
- o runner terminou sem acionar invalidação por restart, Pending, Metrics API ou saturação de node;
- B atingiu `N=3` e produziu `steady-state` com coverage completo.

### 4.1 `pre-scale`

O pod maduro `jobs-api-849859f688-z6zck` recebeu a carga concentrada antes do scale-out. Nessa fase:

- coverage = 105%;
- mediana de `cpu_cost_rate` = `0.359875`, acima da faixa de A;
- `span_cost = 0.236853`, também acima da faixa de A.

Isso é compatível com a carga ainda concentrada em uma réplica e não é usado como comparação A×B de
`k=3`.

### 4.2 `scale-up`: sinal de cobertura parcial existe, mas a linha A1 não dispara estritamente

Dois pods nasceram durante o scale-out:

| Pod jovem | idade no início da fase | coverage mediana | coverage no pior ponto de CPU | `cpu_cost_rate` máx. | `span_cost` | `span_cost` vs A |
|---|---:|---:|---:|---:|---:|---|
| `jobs-api-849859f688-4b79j` | 33s | 42.5% | 75% | 0.389731 | 0.160402 | dentro |
| `jobs-api-849859f688-c8nkw` | 33s | 45% | 40% | 0.436635 | 0.158728 | dentro |

Os dois pods jovens exibiram exatamente o **sub-sinal A1-compatible** esperado: `cpu_cost_rate`
calculado sobre série parcial pôde ultrapassar a faixa madura, enquanto o custo integral real
(`span_cost`) permaneceu dentro do baseline. Quando atingiram coverage suficiente, suas medianas
cobertas (`0.164799` e `0.146249`) também ficaram dentro da faixa de A.

Porém, a matriz foi pré-registrada com `cov = coverage do pior pod da fase`. O pior pod por pico de
CPU/limit no `scale-up` foi o pod maduro `jobs-api-849859f688-z6zck`:

- age no início da fase: `1697s`;
- coverage: `105%`;
- `cpu_limit_ratio_max = 17.10%`;
- mediana `cpu_cost_rate = 0.175536`, dentro do baseline;
- `span_cost = 0.153723`, dentro do baseline.

Portanto **A1/A2 não são acionadas estritamente para a fase**. A distribuição de requests durante
`scale-up` foi pré-registrada como de baixo poder e não pode ser usada para promover o resultado para
C/D. O veredito da fase é `UNKNOWN` pela matriz estrita, com evidência secundária de que coverage
parcial pode inflar `cpu_cost_rate` de pods jovens.

Consequência importante: **não criar ADR-008 nem ADR-009 a partir desta rodada**. O spike observou o
mecanismo de artefato, mas não demonstrou que ele corrompeu a seleção do pior pod.

### 4.3 `steady-state`: linha C

No `steady-state`, os três pods estavam com coverage completo e a distribuição pooled foi:

```text
n = 169
esperado por pod = 56.33
faixa 3σ = [37.95, 74.72]

4b79j = 58
c8nkw = 55
z6zck = 56
```

Todos ficaram dentro da faixa.

As medianas cobertas de `cpu_cost_rate` também ficaram dentro do baseline A:

| Pod | coverage mín. | mediana `cpu_cost_rate` | vs baseline A |
|---|---:|---:|---|
| `4b79j` | 80% | 0.122243 | dentro |
| `c8nkw` | 80% | 0.119469 | dentro |
| `z6zck` | 95% | 0.133173 | dentro |

Logo a primeira linha aplicável da matriz é **C**: distribuição de requests dentro do esperado e
custo por request dentro do baseline maduro.

## 5. Decisão final do Spike 002

1. **ADR-003 permanece válida.** No `steady-state`, a evidência por pod/container foi consistente: a
   distribuição pooled ficou dentro da faixa esperada e o custo por request de todos os pods ficou
   dentro do baseline A.
2. O pior pod observado durante `scale-up` **não foi um pod jovem com cobertura parcial**; foi o pod
   maduro original. Portanto o modo de falha que motivou o spike não foi reproduzido como erro de
   seleção do pior pod.
3. Pods jovens **podem** produzir valores locais de `cpu_cost_rate` inflados enquanto a cobertura da
   janela ainda é parcial. O `span_cost` mostrou que, nesta rodada, esse excesso era artefato de
   janela e não custo real de startup. Esse sinal deve permanecer visível como diagnóstico de
   coverage, mas o experimento não justifica ainda um filtro obrigatório de produção.
4. **ADR-008 e ADR-009 não são criadas.** A matriz pré-registrada não acionou A1 nem A2 estritamente.
5. Não é necessário um Spike 003 apenas para repetir estas queries. O próximo passo é a primeira
   fatia determinística de `verify`, carregando coverage, janela de rate e distinção entre evidência
   histórica e estado live como metadados explícitos.

O Spike 002 termina sem recommendation engine, sizing automático ou IA/LLM.