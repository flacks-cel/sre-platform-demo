# CHANGE-JOIN-THROTTLING-001 — Propagate CFS censorship evidence

> Status: **pré-registração v1 commitada; implementação bloqueada até RED.**
> Base: `main @ cf39169`.
> Pré-requisito: `VERIFY-THROTTLING-001` mergeado no PR #17.
> Este slice estende factual e aditivamente o CHANGE-JOIN-001; não classifica risco.

---

## 1. Pergunta

> Dado um report do Verify que pode ou não conter evidência de throttling CFS, como o CHANGE-JOIN-001 preserva essa evidência por pod e por janela sem inferir risco, demanda real ou ausência de censura?

A resposta continua no domínio de fatos cruzados. Este slice não define LOW/MEDIUM/HIGH/CRITICAL, não escolhe margem e não decide se uma mudança cabe.

---

## 2. Por que este slice existe

`VERIFY-THROTTLING-001` agora publica, por pod e por janela, fatos de `cfs_throttling`.

`CHANGE-RISK-001` será consumidor do join, não do Verify bruto. Portanto a evidência de censura precisa atravessar a fronteira do join de forma explícita, preservando:

- `VALID` versus `UNKNOWN`;
- `any_positive`;
- witness de máximo;
- coverage por janela;
- `coverage_complete`;
- `reason_code/reason`;
- `query_key` e `rate_window`.

O join não converte esses fatos em risco.

---

## 3. Local no output

Cada janela já existente do CHANGE-JOIN-001 ganha:

```text
pods[pod].windows.short.cfs_throttling
pods[pod].windows.long.cfs_throttling
```

Assim CPU observada, comparação proposta×observado e evidência de censura ficam no mesmo eixo `pod × window`, sem criar selector agregado.

---

## 4. Throttling adquirido e válido

Quando o Verify publica, para a janela correspondente:

```text
status = VALID
```

o join preserva deterministicamente:

```text
status
any_positive
max_rate
a max_timestamp
query_key
points
coverage
coverage_complete
rate_window
```

`max_rate` e `max_timestamp` continuam strings decimais exatas. Nenhum `float` é introduzido.

O join não interpreta a magnitude de `max_rate`. Para este slice, `any_positive` é apenas o fato já produzido pelo Verify.

---

## 5. Throttling adquirido mas UNKNOWN

Quando o Verify publica:

```text
status = UNKNOWN
```

o join preserva, quando presentes:

```text
reason_code
reason
coverage
```

mais o `rate_window` correspondente.

Exemplos de razões upstream:

```text
missing_throttling
non_finite_sample
negative_throttling_rate
```

O join não reescreve essas razões e não contamina CPU válida da mesma janela.

---

## 6. Throttling não adquirido

`VERIFY-THROTTLING-001` tornou a aquisição opcional. Um report antigo ou uma execução com `include_throttling=False` pode não conter:

```text
queries.cfs_throttled_short
queries.cfs_throttled_long
pods[pod].cfs_throttling
```

Isto não é o mesmo que série adquirida e vazia.

Nesse caso, o join produz explicitamente, por janela:

```text
status = UNKNOWN
reason_code = throttling_not_acquired
reason = CFS throttling evidence was not acquired
rate_window = <short|long window>
```

Assim o consumidor futuro não precisa inferir significado da ausência de campo.

---

## 7. Consistência estrutural quando a evidência existe

Se `pods[pod].cfs_throttling` existe, o join exige consistência com provenance:

- `queries.cfs_throttled_short` existe para a janela short;
- `queries.cfs_throttled_long` existe para a janela long;
- `query.rate_window` coincide com `windows.short/long`;
- `query.promql` é string não vazia;
- summary `window` coincide com a janela do report;
- summary `query_key`, quando `VALID`, coincide com a chave esperada;
- `max_rate` e `max_timestamp`, quando `VALID`, são strings decimais exatas;
- `any_positive` e `coverage_complete` são booleanos;
- `points` é inteiro não negativo;
- `coverage`, quando presente, contém contagens inteiras não negativas.

Contradição estrutural é `ChangeJoinInputError`, não `UNKNOWN` semântico.

---

## 8. Coverage parcial continua factual

Uma série legível com:

```text
coverage_complete = false
```

continua `VALID` no join.

O join não decide se essa incompletude basta ou não para uma conclusão de risco.

Consequência futura esperada, mas **não implementada aqui**:

- um witness positivo pode continuar útil mesmo com coverage parcial;
- zeros parciais não provam ausência de throttling.

Essa política pertence ao contrato da risk rule.

---

## 9. Independência das conclusões existentes

Este slice não altera:

- identidade `CALLER_ASSERTED`;
- `observed_cpu`;
- `comparison` proposed×observed;
- effective-limit witness;
- relação declared×effective;
- selectors do Verify;
- RULE-001;
- top-level status do Verify.

Uma falha somente na evidência de throttling não apaga fatos de CPU já válidos.

---

## 10. Provenance

O mapa `queries` já preservado pelo CHANGE-JOIN-001 continua sendo copiado integralmente.

Quando throttling foi adquirido, devem existir as chaves:

```text
cfs_throttled_short
cfs_throttled_long
```

Cada fato `VALID` referencia sua `query_key` e recebe explicitamente o `rate_window` do report.

Quando throttling não foi adquirido, nenhuma query é inventada.

---

## 11. Não objetivos

Este slice não implementa:

- classificação de risco;
- `cpu_limit_insufficiency`;
- margin/headroom;
- inferência de demanda real;
- score de throttling;
- throttled/total ratio;
- ownership verificado;
- freshness policy;
- agregação entre pods;
- `worst_pod`;
- alteração do CLI para habilitar throttling automaticamente.

A aquisição automática/flag de CLI pode ser integrada no caminho de produto depois; ausência continua auditável via `throttling_not_acquired`.

---

## 12. Plano RED

Antes da implementação, os testes congelam pelo menos:

1. report sem throttling adquirido produz `UNKNOWN(throttling_not_acquired)` em short e long sem alterar CPU/comparison;
2. zero completo `VALID` é preservado com `any_positive=false`;
3. witness positivo é preservado com `max_rate/max_timestamp/query_key` exatos;
4. coverage parcial `VALID` permanece válido e `coverage_complete=false`;
5. upstream `UNKNOWN(missing_throttling)` é preservado sem contaminar CPU válida;
6. `queries.cfs_throttled_*.rate_window` divergente é input error;
7. summary `VALID` com `query_key` divergente é input error;
8. summary com status fora de `VALID|UNKNOWN` é input error;
9. output continua sem `float` recursivamente;
10. output não ganha `risk`, `risk_level`, `recommendation` ou `worst_pod`.

---

## 13. Gate

- [x] VERIFY-THROTTLING-001 mergeado
- [x] contrato commitado antes da implementação
- [ ] testes RED escritos
- [ ] RED confirmado localmente
- [ ] implementação iniciada somente depois do RED
- [ ] GREEN com todos os testes anteriores preservados
- [ ] nenhuma regra de risco implementada neste slice
