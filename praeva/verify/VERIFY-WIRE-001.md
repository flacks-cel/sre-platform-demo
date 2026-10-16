# VERIFY-WIRE-001 — Exact Measurement Wire & Provenance

> Status: **GREEN local + CI; aguardando revisão final do PR #14.**
> Base: `main @ 7a0a112`.
> Escopo: Verify 001 + RULE-001 somente onde a mudança de wire exige adaptação.
> Gate RED confirmado antes da implementação: `10 failed, 94 passed`, Ruff verde.
> GREEN confirmado: `104 passed` localmente no Windows e no CI #47; Ruff verde.

## 1. Pergunta

> Como o Verify preserva exatamente os valores devolvidos pelo Prometheus através de aquisição, cálculo e JSON, e como publica provenance suficiente para um consumidor posterior saber de qual query, janela e instante cada evidência veio?

Este slice corrige uma garantia que o Verify original nunca prometeu. Não é trabalho do `CHANGE-JOIN-001` e não adiciona risco, recommendation, ownership de workload ou regra nova.

## 2. Motivação

A API do Prometheus devolve o valor da amostra como string decimal. O adapter atual convertia essa string para `float`; o core convertia novamente valores para `float`; RULE-001 também convertia o threshold e a razão observada para `float`.

Isso criava duas falhas de contrato para o próximo join:

1. a representação decimal original podia ser perdida antes de qualquer consumidor posterior;
2. o JSON do Verify não carregava provenance suficiente para reconstruir acquisition interval, query e origem de cada selector.

A correção pertence ao upstream que produz a evidência.

## 3. Fronteira do slice

### 3.1 Incluído

- wire exato para valores de medição do Prometheus;
- timestamps de avaliação serializados sem `float`;
- acquisition provenance (`namespace`, seletor de pods, container, `start`, `end`, `step`);
- query provenance para CPU short, CPU long, limit e request-rate opcional;
- coverage sem razão `float`;
- derived quotients (`cpu/limit`, `cpu/request-rate`) sem divisão aproximada;
- adaptação da RULE-001 para comparação exata de fronteira;
- testes de regressão das conclusões existentes.

### 3.2 Fora de escopo

- `Pod -> ReplicaSet -> Deployment`;
- `kube_replicaset_owner`;
- verificar se os pods pertencem ao Deployment de Change Input;
- `CHANGE-JOIN-001`;
- LOW/MEDIUM/HIGH/CRITICAL;
- recommendation ou novo CPU limit;
- freshness policy;
- escolha entre janela short e long;
- mudança automática em Git/Kubernetes;
- LLM/IA.

Ownership continuará sendo tratado por slice próprio. O primeiro join poderá usar `CALLER_ASSERTED`, mas este documento não implementa isso.

## 4. Regra de wire: medição é string decimal

Todo valor originado de uma amostra Prometheus permanece **string** no wire JSON do Verify.

Exemplo de input da API:

```json
[1792001149, "0.1491020848282956"]
```

Exemplo normalizado:

```json
{
  "timestamp": "1792001149",
  "value": "0.1491020848282956",
  "query_key": "cpu_short"
}
```

A string de `value` é preservada lexicalmente quando é uma amostra escolhida diretamente. Nenhum `float(...)` é permitido no caminho de medição.

Para comparação/aritmética interna, o código usa `Decimal` construído **a partir da string**, nunca a partir de `float`.

## 5. Timestamps e acquisition interval

Timestamps e os parâmetros temporais de acquisition são publicados como strings decimais canônicas no wire:

```json
{
  "acquisition": {
    "namespace": "app",
    "pod_selector": {
      "type": "regex",
      "value": "jobs-api-.*"
    },
    "container": "jobs-api",
    "start": "1792000000",
    "end": "1792000900",
    "step": "15"
  }
}
```

O adapter pode aceitar `int`, `Decimal` ou texto decimal nas APIs Python internas, mas não usa `float` como representação normativa. A CLI não deve transformar `--start`, `--end` e `--step` em `float` antes de chamar o adapter.

Alinhamento de timestamps continua exato; não há nearest-neighbor, interpolação ou reescrita para fazer joins passarem.

## 6. Query provenance

O normalized evidence e o relatório final carregam um mapa de queries:

```json
{
  "queries": {
    "cpu_short": {
      "promql": "...rate(...[2m])...",
      "rate_window": "2m"
    },
    "cpu_long": {
      "promql": "...rate(...[5m])...",
      "rate_window": "5m"
    },
    "cpu_limit": {
      "promql": "...kube_pod_container_resource_limits...",
      "rate_window": null
    }
  }
}
```

Request-rate opcional usa `query_key = request_rate`, preserva exatamente a PromQL fornecida pelo chamador e não tenta inferir a janela dela.

Cada point referencia uma `query_key`. Assim query completa não é duplicada em cada amostra, mas qualquer valor continua rastreável para:

- PromQL;
- timestamp;
- rate window quando conhecida;
- string de valor retornada.

Selectors e summaries preservam `query_key` e timestamp do ponto escolhido.

## 7. Coverage exato e não decisório

`coverage` deixa de ser uma razão `float`.

O wire passa a carregar:

```json
{
  "coverage": {
    "observed_points": 2,
    "expected_points": 3
  }
}
```

`sample_count` pode permanecer como inteiro por compatibilidade/legibilidade, embora seja igual a `observed_points` neste adapter.

Coverage continua metadata diagnóstica. Nenhum piso de 80% é introduzido.

## 8. Derived quotients sem divisão

O Verify ainda precisa representar `cpu_limit_ratio` e `cpu_cost_rate`, mas o wire não publica uma divisão arredondada como se fosse fato exato.

Em vez disso, o valor derivado é representado pelos operandos decimais exatos:

```json
{
  "numerator": "0.9",
  "denominator": "0.5"
}
```

A semântica é a razão `numerator / denominator`, mas nenhuma divisão é necessária para:

- comparar duas razões;
- escolher o máximo;
- comparar uma razão com um threshold decimal.

Comparações usam multiplicação cruzada em `Decimal`.

Para `cpu_limit_ratio`:

- numerator = CPU short-window no timestamp;
- denominator = historical effective-observed CPU limit no mesmo timestamp.

Para `cpu_cost_rate`:

- numerator = CPU short-window;
- denominator = request-rate no mesmo timestamp.

O campo continua contexto/evidência; não é permitido reconstruir `float` para decidir RULE-001.

## 9. RULE-001: conclusão exata, sem razão aproximada

RULE-001 mantém as mesmas conclusões semânticas:

```text
EXCEEDS_CEILING
WITHIN_CEILING
UNKNOWN
```

A decisão `cpu/limit > theta` passa a ser avaliada exatamente como:

```text
cpu > limit * theta
```

com `Decimal` construído de texto decimal exato.

### 9.1 Input de `ceiling_ratio`

O valor normativo de `ceiling_ratio` é texto decimal exato. Inteiros exatos também podem ser aceitos pela API Python e convertidos para texto decimal.

`float` é rejeitado como input de policy porque pode já carregar arredondamento binário antes de entrar na regra.

O output da regra publica `ceiling_ratio` como string decimal.

### 9.2 Fronteira pré-registrada

Os seguintes casos são obrigatórios:

```text
observed == theta                  -> WITHIN_CEILING
observed imediatamente > theta    -> EXCEEDS_CEILING
observed imediatamente < theta    -> WITHIN_CEILING
```

“Imediatamente” aqui significa uma diferença decimal representável no wire, inclusive além da resolução de binary float.

## 10. Valores especiais do Prometheus

`NaN`, `+Inf`, `-Inf`, `Inf` e equivalentes não são convertidos para número finito e não são tratados como transport failure quando vieram de uma resposta Prometheus válida.

Eles permanecem evidência recebida, mas tornam **UNKNOWN somente o summary/selector dependente** com `reason_code = non_finite_sample`.

Exemplos:

- CPU short contém `NaN` -> CPU short summary e selectors que dependem dessa série ficam UNKNOWN;
- limit contém `+Inf` -> usage selector pode continuar válido; limit-ratio dependente fica UNKNOWN;
- request rate contém `NaN` -> cost-rate fica UNKNOWN; usage/limit-ratio não são contaminados.

String numérica malformada que não seja um valor especial reconhecido continua erro de adapter/schema.

## 11. Compatibilidade e regressão

Este slice **quebra o schema de wire deliberadamente** onde números de medição eram JSON numbers/`float`.

Mudanças esperadas de representação:

- amostras Prometheus: number -> string;
- timestamps: number -> string;
- selector CPU usage `value`: number -> string;
- ratios/cost-rate: número calculado -> operandos estruturados;
- coverage: float -> `{observed_points, expected_points}`;
- `ceiling_ratio`: float -> string no output e string/int exato no input normativo.

A intenção semântica das conclusões não muda.

Uma mudança de conclusão é permitida **somente** se for causada pela remoção de arredondamento binário num caso de fronteira explicitamente coberto por teste. Não existe autorização genérica para mudar comportamento.

Todos os contratos existentes de missing telemetry, churn, selector independence, timestamp alignment, per-pod semantics e ADR-005 continuam válidos.

## 12. Provenance mínima — cerca de escopo

Este slice não transforma provenance em inventário infinito.

A cerca é:

- acquisition scope: namespace, pod selector, container, start/end/step;
- query: PromQL e rate window quando conhecida;
- point: query key, timestamp, raw decimal string;
- selector/summary: query key + timestamp do witness escolhido.

Não entram aqui image digest, Git SHA, Deployment revision, node ownership, ReplicaSet chain ou versão da aplicação.

## 13. Plano RED

Antes da primeira linha de implementação, os testes congelaram:

| # | Cenário | Esperado |
|---:|---|---|
| 1 | Prometheus devolve `"0.1491020848282956"` | normalized point preserva exatamente a string; nenhum float |
| 2 | aquisição 0..30 step 15 | acquisition provenance e timestamps saem como strings canônicas |
| 3 | 2 de 3 pontos | coverage = `{observed_points: 2, expected_points: 3}` |
| 4 | selector de CPU escolhe máximo | `value` é string exata e carrega query/timestamp/window |
| 5 | `cpu/limit = 1/3` | output derivado guarda operandos; não publica decimal arredondado |
| 6 | request cost-rate não terminante | output derivado guarda operandos; não publica float |
| 7 | CPU `NaN` em resposta válida | dependentes UNKNOWN com `non_finite_sample`, sem adapter transport error |
| 8 | RULE-001 em igualdade exata | `WITHIN_CEILING` |
| 9 | RULE-001 um decimal além de theta, invisível a binary float | `EXCEEDS_CEILING` |
| 10 | RULE-001 um decimal abaixo de theta | `WITHIN_CEILING` |
| 11 | `ceiling_ratio` fornecido como float | `RuleInputError` |
| 12 | conclusões existentes de churn/missing selector | permanecem semanticamente iguais |
| 13 | CLI Verify Prometheus | stdout JSON usa novo wire e preserva acquisition/query provenance |

Os testes 1, 5, 9 e 13 são os load-bearing: eles provam que a exatidão sobrevive aquisição, derivação, regra e serialização.

## 14. Checklist do gate

- [x] Wire de medição definido como string decimal
- [x] Timestamp/acquisition wire definidos sem float
- [x] Coverage exato definido sem razão float
- [x] Quotients derivados definidos sem divisão
- [x] RULE-001 fronteira exata definida
- [x] `float` de policy explicitamente rejeitado
- [x] Valores especiais têm semântica UNKNOWN por dependência
- [x] Provenance possui cerca explícita
- [x] Ownership continua fora de escopo
- [x] Testes RED escritos e falhando antes da implementação
- [x] Nenhuma implementação antes do RED confirmado
- [x] GREEN local no Windows: Ruff verde, `104 passed`
- [x] CI #47: Ruff verde, `104 passed`, Docker build/push verde

## 15. Relação com contratos anteriores

Este documento **não reescreve retroativamente** os contratos pré-registrados anteriores. Onde houver conflito puramente de representação, `VERIFY-WIRE-001` é o contrato mais novo e substitui somente o wire antigo.

Em particular:

- `PROMETHEUS_ADAPTER.md`: exemplos antigos com JSON number/`float` e coverage fracionário continuam como registro histórico da versão anterior; o wire atual usa strings decimais, provenance e contagens exatas de coverage definidos aqui;
- `PER_POD_LIMIT_RATIO.md`: a semântica de join e os `reason_code` anteriores permanecem; apenas a representação do ratio passa de número calculado para `{numerator, denominator}` exato e timestamps passam para texto decimal canônico;
- `RULE-001.md`: as conclusões e a lógica de completude parcial permanecem; a interface normativa de `ceiling_ratio` e a comparação numérica são substituídas pela seção 9 deste documento.

Nenhum desses supersessions introduz risk vocabulary, recommendation, ownership verificado ou policy de freshness.
