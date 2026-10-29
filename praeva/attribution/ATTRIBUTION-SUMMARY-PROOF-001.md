# ATTRIBUTION-SUMMARY-PROOF-001 — Contrato de Pré-Registração
## Projeção de fatos pontuais para capacidades de prova dos resumos Verify

> Status: **pré-registração fechada antes da implementação.**
> Branch: `praeva/attribution-summary-proof-001`.
> Base: `main` em `1beb1ebf3050418088ca9f868f200b911fd9b8ab`.
> Depende de ATTRIBUTION-FACT-INPUT-001 e ATTRIBUTION-DECISION-001/002.
> **Sem wiring de produto:** este slice não altera Analyze, Join, Verify, Ownership nem Risk.

---

## 1. Pergunta

> Como projetar decisões de atribuição pointwise nos resumos que Verify já publica sem colapsar provas existenciais e universais em um único booleano `summary_attributed`?

O problema aparece porque Verify reduz séries em resumos como:

- `max` + `max_timestamp` para CPU;
- `any_positive` + `max_rate` + `max_timestamp` + `coverage_complete` para CFS throttling;
- `cpu_limit_ratio.max` + `max_timestamp` para o witness de limite efetivo usado pelo Join.

ATTRIBUTION-FACT-INPUT-001, por outro lado, produz um fato por ponto observado.

A ponte correta não é:

```text
point facts -> summary_attributed: bool
```

porque o mesmo resumo pode sustentar claims com quantificadores diferentes.

A ponte normativa é:

```text
point facts + point attribution + Verify summaries
                    ↓
ATTRIBUTION-SUMMARY-PROOF-001
                    ↓
witness usability + domain completeness
```

---

## 2. Terceira aparição da assimetria EXISTS / FORALL

A assimetria já apareceu em:

1. censura: presença positiva versus prova de ausência;
2. população: witness CRITICAL versus exclusão de witness escondido;
3. agora, dentro de uma única série.

Para um resumo `max`:

```text
max > threshold
```

é uma claim existencial. Basta o fato do argmax ser utilizável.

Já:

```text
max <= threshold
```

é uma claim universal sobre o domínio avaliado. Exige que o domínio relevante esteja completo e atribuível.

Portanto **`max` não possui uma única semântica de atribuição**.

---

## 3. Capabilities normativas

Cada resumo suportado publica separadamente:

```text
witness
    status = USABLE | UNUSABLE | NOT_APPLICABLE | UNAVAILABLE

domain
    status = COMPLETE | INCOMPLETE | NOT_APPLICABLE | UNAVAILABLE
```

### 3.1 `witness`

Responde somente:

> O witness específico selecionado pelo resumo pode ser usado como fato atribuído?

`USABLE` não afirma que a série inteira está completa.

### 3.2 `domain`

Responde somente:

> O universo de pontos necessário para uma claim universal sobre este resumo está completo e atribuível?

`COMPLETE` não afirma que algum predicate de Risk é verdadeiro ou falso.

### 3.3 Proibição

Este slice não publica:

```text
summary_attributed = true | false
```

porque esse booleano perderia a distinção entre witness existencial e domínio universal.

---

## 4. Interface pública

```python
project_summary_proof(
    *,
    verify_report: dict,
    fact_input: dict,
    attribution_projection: dict,
) -> dict
```

A função é pura e sem I/O.

### 4.1 `verify_report`

É o output atual de `praeva.verify.cpu_evidence.build_report(...)`.

### 4.2 `fact_input`

É o output de `ATTRIBUTION-FACT-INPUT-001`.

Dele vêm:

- conjunto exato de fatos observados por `(pod, evidence_family)`;
- `fact_id` determinístico;
- timestamps observados.

### 4.3 `attribution_projection`

É o output de `project_attribution_decision(...)`.

Para este slice, a parte autoritativa é:

```text
attribution_projection.facts[fact_id]
```

Cada `fact_id` de `fact_input.facts` deve possuir exatamente uma decisão correspondente.

Facts ausentes da projeção são erro estrutural; facts extras na projeção também são erro estrutural. O adapter e a projeção devem falar do mesmo conjunto pointwise.

---

## 5. Domínio de uma série

O **domínio da série** não é `support.required_timestamps` de um fato.

São conjuntos diferentes:

```text
series domain
    = evaluation points observados/esperados para uma família no intervalo de análise

fact support
    = pontos históricos de ownership necessários para atribuir um único fato em T
```

Confundi-los é erro semântico.

### 5.1 Expected evaluation points

Para o intervalo Verify:

```text
A = verify_report.acquisition.start
E = verify_report.acquisition.end
S = verify_report.acquisition.step
```

então:

```text
expected_points = floor((E - A) / S) + 1
```

com os mesmos requisitos de decimal exato já usados no wire.

### 5.2 Domain COMPLETE

Para uma família rate por Pod:

```text
domain = COMPLETE
```

somente se:

1. o resumo Verify é `VALID`;
2. `summary.points == expected_points`;
3. o número de fatos pointwise de `(pod, family)` é exatamente `summary.points`;
4. todos esses fatos possuem decisão `ATTRIBUTED`.

Caso contrário:

```text
domain = INCOMPLETE
```

com razões determinísticas.

Para throttling, `summary.coverage_complete` também deve ser `true` e sua coverage declarada deve ser consistente com os contadores.

`coverage_complete` continua significando cobertura da grade de resultados da query, **não raw-sample support**.

---

## 6. CPU short / long — resumo `max`

Famílias:

```text
cpu_short
cpu_long
```

Verify publica, quando `VALID`:

```text
max
max_timestamp
query_key
points
```

### 6.1 Witness

O witness é:

```text
fact_id = <family>:<pod>:<max_timestamp>
```

Se esse fato é `ATTRIBUTED`:

```text
witness.status = USABLE
```

Caso contrário:

```text
witness.status = UNUSABLE
```

com referência ao fact e à classe de não atribuição.

### 6.2 Domain

É calculado independentemente do witness conforme seção 5.

Consequência normativa:

```text
argmax ATTRIBUTED + outro ponto UNATTRIBUTED
    => witness USABLE
    => domain INCOMPLETE
```

Isso permite usar o mesmo `max` como witness de contradição sem permitir que ele prove sozinho ausência de contradição.

---

## 7. CFS throttling — `any_positive`

Famílias:

```text
cfs_throttled_short
cfs_throttled_long
```

### 7.1 `any_positive = true`

Como `max_rate > 0`, `max_timestamp` identifica um witness positivo.

Se o fato em `max_timestamp` é `ATTRIBUTED`:

```text
witness.status = USABLE
```

A domain pode ser `INCOMPLETE` e o witness positivo continuar utilizável.

### 7.2 `any_positive = false`

Não existe witness positivo.

Portanto:

```text
witness.status = NOT_APPLICABLE
```

A prova de ausência depende exclusivamente de:

```text
domain.status = COMPLETE
```

### 7.3 Coverage

Para uma claim negativa de throttling:

```text
coverage_complete = true
```

é necessário, mas não suficiente.

Todos os fatos observados da série também devem estar `ATTRIBUTED`.

---

## 8. `cpu_limit_ratio.max` — witness composto

Verify calcula `cpu_limit_ratio` a partir de pares alinhados:

```text
cpu_short(T) / cpu_limit(T)
```

O Join usa o denominador no `max_timestamp` como `effective_limit_witness`.

Este slice preserva a provenance composta da seleção.

Para um `cpu_limit_ratio` `VALID` em T:

```text
witness_components = [
    cpu_short:<pod>:T,
    cpu_limit:<pod>:T,
]
```

O witness composto é `USABLE` somente se **ambos** os componentes são `ATTRIBUTED`.

Se qualquer componente estiver ausente ou `UNATTRIBUTED`:

```text
witness.status = UNUSABLE
```

Este slice **não** conclui que o limite é constante no tempo e não transforma esse witness em uma prova universal de `MATCH` entre declarado e efetivo.

### 8.1 Domain do ratio

O downstream atual usa o ratio para selecionar um witness, não para provar um bound universal sobre o ratio.

Portanto nesta versão:

```text
domain.status = NOT_APPLICABLE
```

Se um consumidor futuro precisar afirmar algo sobre o máximo do ratio como máximo global da série, deverá pré-registrar a exigência universal correspondente.

---

## 9. Resumos UNKNOWN

Se um resumo Verify é `UNKNOWN`, este slice não inventa fatos nem reconstrói um summary alternativo.

Publica:

```text
witness.status = UNAVAILABLE
domain.status = UNAVAILABLE
```

preservando, quando presente, `reason_code` do Verify.

Isso é diferente de:

```text
VALID summary + UNATTRIBUTED witness
```

que produz `UNUSABLE`, não `UNAVAILABLE`.

---

## 10. Shape mínimo de output

```json
{
  "summary_proof_id": "ATTRIBUTION-SUMMARY-PROOF-001",
  "pods": {
    "pod-a": {
      "cpu_short": {
        "witness": {
          "status": "USABLE",
          "fact_refs": ["cpu_short:pod-a:600"]
        },
        "domain": {
          "status": "COMPLETE",
          "observed_fact_count": 21,
          "expected_point_count": 21,
          "unusable_fact_refs": []
        }
      },
      "cfs_throttled_short": {
        "witness": {
          "status": "NOT_APPLICABLE",
          "fact_refs": []
        },
        "domain": {
          "status": "COMPLETE",
          "observed_fact_count": 21,
          "expected_point_count": 21,
          "unusable_fact_refs": []
        }
      },
      "cpu_limit_ratio": {
        "witness": {
          "status": "USABLE",
          "fact_refs": [
            "cpu_short:pod-a:600",
            "cpu_limit:pod-a:600"
          ]
        },
        "domain": {
          "status": "NOT_APPLICABLE"
        }
      }
    }
  }
}
```

O output não repete:

- values das séries;
- support descriptors;
- `required_timestamps` de ownership;
- PromQL.

Esses dados continuam pertencendo às camadas produtoras.

---

## 11. Razões determinísticas

`UNUSABLE` / `INCOMPLETE` podem publicar `blocked_by` usando apenas este vocabulário inicial:

```text
summary_unknown
witness_fact_missing
witness_fact_unattributed
series_point_count_incomplete
series_fact_unattributed
coverage_incomplete
composite_witness_component_missing
composite_witness_component_unattributed
```

A classe detalhada de um point fact (`support_predates_pod`, `identity_discontinuity`, etc.) permanece no `attribution_projection`; este slice referencia o `fact_id` e não duplica toda a taxonomia diagnóstica.

---

## 12. Invariantes estruturais

É erro de input se:

- `fact_input.fact_input_id != ATTRIBUTION-FACT-INPUT-001`;
- o conjunto de `fact_id` de `fact_input` e `attribution_projection.facts` divergir;
- houver fact duplicado para `(pod, family, evaluated_at)`;
- um resumo `VALID` apontar `max_timestamp` sem fact correspondente da família;
- `summary.query_key` não corresponder à família esperada;
- `summary.points` divergir da quantidade de fatos observados da série;
- acquisition start/end/step forem inválidos ou floats;
- contadores de throttling forem inconsistentes entre `points`, `coverage` e `coverage_complete`.

Gaps reais de série, por outro lado, não são erro estrutural: produzem `domain=INCOMPLETE` quando os contadores são internamente consistentes.

---

## 13. Relação com CHANGE-RISK-001

Este slice **não conhece thresholds, margin ou risk levels**.

Ele publica capacidades que um wiring posterior poderá usar:

| Claim futura | Capability necessária |
|---|---|
| `cpu_long max > proposed` | `cpu_long.witness = USABLE` |
| nenhum `cpu_long > proposed` antes de HIGH | `cpu_long.domain = COMPLETE` |
| `cpu_short max > proposed` | `cpu_short.witness = USABLE` |
| nenhuma contradição CPU para MEDIUM/LOW | domains CPU short + long completos |
| `any_positive = true` | throttling witness `USABLE` |
| `any_positive = false` confiável | throttling domain `COMPLETE` |
| effective-limit witness | `cpu_limit_ratio.witness = USABLE` |

A tabela descreve proof-shape, não altera CHANGE-RISK-001 neste slice.

---

## 14. Publicação canônica — decisão de fronteira

`ATTRIBUTION-FACT-INPUT-001` continua sendo **adapter intermediário**, não camada canônica por si só.

O contrato antigo de PRAEVA-ANALYZE-001 exige que uma camada publicada seja íntegra; ele não exige que todo objeto intermediário vire uma camada publicada.

Portanto este slice congela apenas esta fronteira:

```text
fact_input expandido
    != camada canônica obrigatória
```

No wiring futuro, a camada canônica de attribution deve publicar as decisões autoritativas necessárias para auditoria, mas não precisa repetir em cada fact os `required_timestamps` já usados para construir a decisão.

A forma final dessa camada canônica será pré-registrada separadamente antes de alterar PRAEVA-ANALYZE-001.

Não é permitido resolver tamanho publicando apenas "facts usados" e descartando silenciosamente os demais. Qualquer compactação futura deve ser lossless e versionada.

---

## 15. Plano de teste — RED antes do GREEN

| # | Cenário | Esperado |
|---|---|---|
| 1 | CPU max fact ATTRIBUTED, série completa | witness USABLE, domain COMPLETE |
| 2 | CPU argmax UNATTRIBUTED | witness UNUSABLE, domain INCOMPLETE |
| 3 | CPU argmax ATTRIBUTED, outro fact UNATTRIBUTED | witness USABLE, domain INCOMPLETE |
| 4 | CPU gap com todos os facts observados ATTRIBUTED | witness pode ser USABLE, domain INCOMPLETE |
| 5 | CPU short e long independentes | capability separada por família |
| 6 | throttling `any_positive=true`, witness ATTRIBUTED, gap alheio | witness USABLE, domain INCOMPLETE |
| 7 | throttling `any_positive=false`, série completa atribuída | witness NOT_APPLICABLE, domain COMPLETE |
| 8 | throttling `any_positive=false`, um fact UNATTRIBUTED | domain INCOMPLETE |
| 9 | throttling coverage incompleta | domain INCOMPLETE |
| 10 | ratio witness com CPU + limit ATTRIBUTED | composite witness USABLE |
| 11 | ratio witness com limit UNATTRIBUTED | composite witness UNUSABLE |
| 12 | summary UNKNOWN | witness/domain UNAVAILABLE |
| 13 | max_timestamp sem fact correspondente | erro estrutural |
| 14 | fact set diverge da projection | erro estrutural |
| 15 | summary.points diverge do fact count | erro estrutural |
| 16 | query_key incompatível | erro estrutural |
| 17 | gap internamente consistente | INCOMPLETE, não exception |
| 18 | mesma entrada duas vezes | output byte-equivalent após serialização determinística |

---

## 16. No-goals

Este slice não:

- reconstrói população alvo;
- calcula selector omission;
- altera `effective_population_evidence`;
- chama Risk;
- altera thresholds ou a ladder de CHANGE-RISK-001;
- substitui `CALLER_ASSERTED`;
- modifica Join;
- modifica Verify;
- modifica Analyze;
- decide application version;
- transforma evaluation-grid coverage em raw-sample support;
- muda ainda o schema canônico de PRAEVA-ANALYZE-001.

---

## 17. Gate

- [x] `summary_attributed` rejeitado antes da implementação
- [x] witness usability separado de domain completeness
- [x] series domain separado de fact support
- [x] CPU max EXISTS/FORALL congelado
- [x] throttling positivo/negativo congelado
- [x] composite `cpu_limit_ratio` witness congelado
- [x] fact-input definido como intermediário, não camada canônica automática
- [ ] testes 1–18 commitados e RED antes do GREEN
- [ ] implementação pura, sem I/O
- [ ] nenhuma alteração em Analyze/Join/Verify/Ownership/Risk
- [ ] suíte completa verde
