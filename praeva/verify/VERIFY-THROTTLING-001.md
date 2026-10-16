# VERIFY-THROTTLING-001 — CFS Throttling Evidence

> Status: **pré-registração v1 commitada; implementação bloqueada até RED.**
> Base: `main @ 8b21767`.
> Herda ADR-001 a ADR-008 e VERIFY-WIRE-001.
> Este slice acrescenta evidência de censura por CFS; não classifica risco.

---

## 1. Pergunta

> Para cada pod/container e para cada janela de CPU já existente, existe evidência histórica legível de throttling CFS, e houve ao menos um período throttled no intervalo observado?

A resposta é factual. Não diz se uma mudança é segura, arriscada, LOW, HIGH ou CRITICAL.

---

## 2. Motivação

CHANGE-RISK-001 precisa distinguir uma observação de CPU não censurada de uma observação limitada por CFS. Hoje o Verify coleta CPU de janela curta, CPU de janela longa e CPU limit histórico, mas não coleta `container_cpu_cfs_throttled_periods_total`.

Sem esse fato, `throttling ausente` e `throttling igual a zero` seriam indistinguíveis. Isso não pode ser inferido por ausência de série.

---

## 3. Escopo

O slice altera somente o caminho de evidência do Verify:

1. aquisição Prometheus opcional de throttling CFS;
2. wire decimal exato, sem `float`;
3. resumo determinístico por pod e por janela;
4. provenance mínima e coverage própria da série de throttling.

Fora de escopo:

- risco;
- recommendation;
- thresholds de risco;
- ownership Pod -> ReplicaSet -> Deployment;
- alteração de selectors existentes;
- alteração de RULE-001;
- inferir throttling zero quando a série não existe.

---

## 4. Aquisição

`collect_normalized_evidence` ganha uma opção explícita:

```text
include_throttling: bool = False
```

`False` preserva o comportamento de aquisição anterior e não executa queries adicionais.

Quando `True`, duas queries adicionais são executadas, usando o mesmo namespace/pod/container e as mesmas janelas já registradas:

```promql
sum by (pod) (
  rate(container_cpu_cfs_throttled_periods_total{...}[SHORT_WINDOW])
)
```

```promql
sum by (pod) (
  rate(container_cpu_cfs_throttled_periods_total{...}[LONG_WINDOW])
)
```

Chaves de provenance:

```text
cfs_throttled_short
cfs_throttled_long
```

Nenhuma razão throttled/total é calculada neste slice. Para saber se houve censura, basta observar se a taxa de períodos throttled é positiva.

---

## 5. Wire

Cada ponto mantém o formato de VERIFY-WIRE-001:

```text
timestamp   string decimal exata
value       string decimal exata
query_key   string
```

Valores `float` são proibidos no wire novo.

Cada pod recebe, quando `include_throttling=True`:

```text
cfs_throttled_short   list[point]
cfs_throttled_long    list[point]
throttling_coverage
  short
    observed_points   int
    expected_points   int
  long
    observed_points   int
    expected_points   int
```

Série ausente é lista vazia com `observed_points = 0`; nunca é convertida em zero sem provenance.

---

## 6. Resumo no Verify

`build_report` continua produzindo todos os campos atuais sem mudança semântica. Quando os campos de throttling existem no pod normalizado, acrescenta:

```text
cfs_throttling
  short
  long
```

Cada janela tem uma das formas:

```text
status            VALID
window            2m | 5m | ...
any_positive      true | false
max_rate          string decimal exata
max_timestamp     string decimal exata
query_key         cfs_throttled_short | cfs_throttled_long
points            int
coverage
  observed_points int
  expected_points int
coverage_complete true | false
```

ou:

```text
status            UNKNOWN
window            ...
reason_code       missing_throttling | non_finite_sample | negative_throttling_rate
reason            texto diagnóstico
coverage          contagens quando conhecidas
```

`any_positive` significa literalmente: existe ao menos um sample com valor `> 0` na série daquela janela.

Nenhuma fração mínima é usada.

---

## 7. Semântica de missing, zero e parcial

- série completa e todos os valores `0` -> `VALID`, `any_positive=false`;
- série completa com qualquer valor `> 0` -> `VALID`, `any_positive=true`;
- série parcial, legível -> `VALID`, com `coverage_complete=false`;
- série ausente -> `UNKNOWN(missing_throttling)`;
- sample não finito -> `UNKNOWN(non_finite_sample)`;
- sample negativo -> `UNKNOWN(negative_throttling_rate)`.

Coverage parcial não é transformada em UNKNOWN neste upstream. O consumidor decide se completeness é uma pré-condição da conclusão que quer emitir.

---

## 8. Independência das conclusões existentes

A ausência ou incompletude de throttling **não altera**:

- `report.status` existente;
- `max_cpu_usage_pod`;
- `max_cpu_limit_ratio_pod`;
- `max_cpu_cost_rate_pod`;
- `cpu_limit_ratio` por pod;
- RULE-001.

O novo fato é dependency-granular. Um consumidor futuro pode exigir sua completude sem degradar fatos de CPU já válidos.

---

## 9. Provenance

`queries` recebe, quando a aquisição estiver habilitada:

```text
cfs_throttled_short
  promql
  rate_window

cfs_throttled_long
  promql
  rate_window
```

O resumo por pod referencia `query_key` e preserva timestamp do sample máximo.

---

## 10. Não objetivos

Este slice não afirma:

- que `any_positive=false` significa ausência de throttling fora do intervalo observado;
- que uma série parcial com zeros prova ausência de throttling;
- que throttling implica risco;
- que uma taxa maior implica risco maior;
- que CPU observada é igual à demanda real.

---

## 11. Plano de teste — RED antes de GREEN

1. aquisição antiga com `include_throttling=False` mantém três queries base e nenhuma chave nova;
2. `include_throttling=True` acrescenta exatamente as queries short/long de `container_cpu_cfs_throttled_periods_total`;
3. valores e timestamps continuam strings decimais exatas;
4. coverage de throttling é por query/window e não reutiliza coverage de CPU;
5. zeros completos -> `VALID`, `any_positive=false`;
6. qualquer valor positivo -> `VALID`, `any_positive=true` com witness determinístico;
7. série parcial -> `VALID`, `coverage_complete=false`;
8. série ausente -> `UNKNOWN(missing_throttling)` sem alterar conclusões existentes do Verify;
9. sample não finito -> `UNKNOWN(non_finite_sample)`;
10. sample negativo -> `UNKNOWN(negative_throttling_rate)`.

---

## 12. Gate

- [x] contrato commitado antes da implementação
- [ ] testes RED escritos
- [ ] RED confirmado localmente
- [ ] primeira linha de implementação somente depois do RED
- [ ] GREEN com todos os testes anteriores preservados
- [ ] nenhuma regra de risco implementada neste slice
