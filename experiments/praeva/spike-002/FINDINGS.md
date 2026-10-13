# Spike 002 — Findings

> Status: **Rodada A concluída e válida; Rodada B pendente.**
> Este arquivo separa claramente resultados de calibração (não-evidenciais) dos achados de A/B.

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

Tamanho amostral do achado A1/A2: `n=2` pods jovens. Isso é suficiente para caracterizar a natureza
da evidência, mas não para estimar frequência populacional. Se A1/A2 ficar ambíguo, uma repetição com
N maior pode ser considerada depois — não antes.

### 2.4 Topologia do lab

Nas calibrações, os pods `jobs-api` foram agendados no mesmo worker. O Spike 002 não pretende inferir
assimetria entre nodes diferentes a partir deste lab.

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
invalidou A porque a regra de validade é saturação de node/restart/telemetria/carga, e A e B usam a
mesma carga, limits e `k=3` no steady-state comparável.

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

**Pendente.**

Registrar por fase (`pre-scale`, `scale-up`, `steady-state`) a primeira linha aplicável da matriz
A1/A2/B/C/D/E/F e a evidência que sustenta o veredito.

A comparação deve usar exatamente as faixas da seção 3; elas foram registradas **antes** de B.

## 5. Decisão final do Spike 002

**Pendente.**

Só será escrita depois da Rodada B. Nenhuma regra do Praeva será implementada com base apenas na
calibração ou no baseline A.
