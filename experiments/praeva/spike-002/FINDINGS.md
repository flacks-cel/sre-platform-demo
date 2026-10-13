# Spike 002 — Findings

> Status: **calibração encerrada; rodadas evidenciais ainda não executadas.**
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

**Pendente.**

Registrar aqui, antes de iniciar B:

- commit SHA sincronizado;
- timestamps `T0/T1`;
- validade da rodada;
- faixa robusta de `cpu_cost_rate`;
- faixa robusta de `span_cost`;
- throttling;
- node CPU;
- UNKNOWN count;
- intervalos transicionais;
- distribuição pooled do steady-state.

## 4. Rodada B — Principal

**Pendente.**

Registrar por fase (`pre-scale`, `scale-up`, `steady-state`) a primeira linha aplicável da matriz
A1/A2/B/C/D/E/F e a evidência que sustenta o veredito.

## 5. Decisão final do Spike 002

**Pendente.**

Só será escrita depois das rodadas A e B. Nenhuma regra do Praeva será implementada com base apenas
na calibração.
