# ATTRIBUTION-DECISION-001 — Contrato de Pré-Registração
## Projeção de atribuição para superfície de decisão

> Status: **pré-registração fechada; review conceitual concluído antes do merge.**
> Branch: `praeva/attribution-decision-001`.
> Módulo: `praeva/attribution/projection.py`.
> Base: SPIKE-003 encerrado (PR #22).
> **Sem wiring:** não altera Analyze, Join, Verify nem Risk neste slice.

---

## 1. Pergunta

> Dados os diagnósticos históricos de ownership, suporte e população, quais fatos pertencem ao
> workload alvo, quais provas de nível permanecem elegíveis, e a análise é semanticamente admissível?

Esta camada não classifica risco. Ela projeta diagnósticos ricos para três respostas pequenas:

```text
analysis:          ADMISSIBLE | INADMISSIBLE(reason)
fact:              ATTRIBUTED | UNATTRIBUTED(class)
level eligibility: ELIGIBLE | BLOCKED
```

`ELIGIBLE` nunca significa “nível classificado”. Significa apenas que atribuição e completude de
população não impedem a regra chamadora de tentar demonstrar aquele nível.

---

## 2. Três escopos independentes

| Escopo | Pergunta |
|---|---|
| Análise | o domínio alvo é determinável? |
| Fato | este fato pertence ao alvo durante o suporte relevante? |
| Escada | o domínio necessário por cada quantificador está completo? |

Um diagnóstico pode afetar mais de um escopo, mas nenhum eixo substitui os outros.

Em particular:

- um fato `UNATTRIBUTED` não torna automaticamente a análise `INADMISSIBLE`;
- um nível `ELIGIBLE` ainda depende do predicate da regra;
- `INADMISSIBLE` não é falha de transporte nem erro sintático.

---

## 3. Atribuição, cobertura e censura são portas diferentes

| Porta | Dona |
|---|---|
| atribuição | ATTRIBUTION-DECISION-001 |
| cobertura/shape da série | Verify |
| censura por throttling | regra de Risk |

A projeção não altera `coverage_complete`, sample count, throttling ou application version.

### 3.1 `coverage_complete` não prova suporte amostral

No wire atual, coverage conta pontos de **resultado** de `query_range`. Não identifica as amostras
cruas efetivamente usadas por `rate(...[W])`.

Logo:

```text
coverage_complete=true
!= observed_sample_support provado
```

A projeção nunca usa coverage para encurtar ou redefinir suporte.

---

## 4. Suporte nominal e suporte amostral observado

Para um fato avaliado em `T`:

- `nominal_support`: envelope conservador declarado pelo producer;
- `observed_sample_support`: suporte mais preciso, somente quando um producer o prova explicitamente.

Para `rate(...[W])`, o envelope nominal conceitual é `(T-W, T]`. A aquisição de ownership pode usar
uma grade conservadora que inclua a fronteira esquerda para provar continuidade.

### 4.1 Escolha normativa

1. Se `observed_sample_support` existe, usa-se ele.
2. Caso contrário, usa-se `nominal_support`.
3. Nunca se infere suporte de lookback, staleness ou coverage.
4. `observed_sample_support` deve ser subconjunto temporal do `nominal_support`; fora dele é input
   estrutural inválido.
5. `required_timestamps` deve conter ao menos um ponto de prova.

### 4.2 Critério de atribuição

No suporte escolhido, um fato é `ATTRIBUTED` somente se:

1. cada timestamp requerido possui ownership resolvido;
2. o Pod resolve para UID não ambíguo;
3. o mesmo UID persiste em todos os pontos requeridos;
4. todos os pontos resolvem `TARGET_MATCH`;
5. `created(uid) <= support_start`;
6. toda fronteira necessária está provada.

Falha de prova não é promovida por plausibilidade.

### 4.3 Rate residual do R2

Membership instantânea em `O(T)` não decide atribuição.

Com o wire atual, se o `nominal_support` do rate residual contém ownership não resolvido, o fato é:

```text
UNATTRIBUTED(attribution_unproven)
```

Se um producer futuro fornecer `observed_sample_support` explicitamente e esse suporte estiver todo
`TARGET_MATCH`, o mesmo fato pode ser `ATTRIBUTED`.

---

## 5. Classes de fato

| Diagnóstico | Projeção |
|---|---|
| ownership ausente/UNKNOWN | `UNATTRIBUTED(attribution_unproven)` |
| identidade ambígua | `UNATTRIBUTED(attribution_unproven)` |
| troca de UID | `UNATTRIBUTED(identity_discontinuity)` |
| `created > support_start` | `UNATTRIBUTED(support_predates_pod)` |
| fronteira não provada | `UNATTRIBUTED(support_boundary_unproven)` |
| `VALID/TARGET_DIFFERS` | `UNATTRIBUTED(foreign_workload)` |
| todos os requisitos satisfeitos | `ATTRIBUTED` |

`foreign_workload` é especial: o fato foi demonstrado como pertencente a **outro** workload. Ele é
excluído dos witnesses do alvo, mas não prova incompletude da população alvo.

---

## 6. Domínio alvo

A projeção recebe explicitamente:

```text
target_domain_status = DETERMINED | UNDETERMINABLE
```

Ela não infere `UNDETERMINABLE` a partir de:

- `O(T)` vazio;
- uma série ausente;
- um Pod com ownership UNKNOWN;
- um Pod `TARGET_DIFFERS`;
- população parcial em um timestamp.

Resultado:

```text
DETERMINED     -> ADMISSIBLE
UNDETERMINABLE -> INADMISSIBLE(target_domain_undeterminable)
```

População vazia e domínio desconhecido são estados diferentes.

`INADMISSIBLE` permanece resultado semântico com exit code 0 quando futuramente integrado ao CLI.

---

## 7. Completude populacional efetiva

Esta seção é a emenda descoberta na revisão do PR #23.

### 7.1 Problema evitado

Não basta receber `population_evidence.cpu_long=COMPLETE` e depois marcar um fato `cpu_long` de um
membro alvo como `UNATTRIBUTED`.

Se esse fato for descartado e o domínio continuar `COMPLETE`, uma cláusula universal pode parecer
provada sobre um conjunto menor do que a população relevante — exatamente a classe de erro exposta
pelo S9.

### 7.2 Dois estágios

A entrada `population_evidence` representa completude antes da porta de atribuição, por domínio/família:

```json
{
  "cpu_long": {"status": "COMPLETE", "diagnostics": []}
}
```

A projeção produz também `effective_population_evidence`.

Para cada fato cuja `evidence_family` possui domínio declarado em `population_evidence`:

- `ATTRIBUTED`: não degrada o domínio;
- `UNATTRIBUTED(foreign_workload)`: não degrada o domínio alvo, pois o fato foi provado estrangeiro;
- qualquer outro `UNATTRIBUTED`: o domínio passa a `INCOMPLETE`.

A degradação adiciona diagnóstico auditável:

```text
unattributed_fact:<fact_id>:<class>
```

A entrada original é preservada em `population_evidence`; o gating usa apenas
`effective_population_evidence`.

### 7.3 Relação entre `evidence_family` e domínio

Todo domínio referenciado por `level_requirements` deve existir em `population_evidence`; referência a
domínio ausente é input inválido.

Uma família auxiliar pode aparecer em `facts` sem possuir domínio populacional próprio. Nesse caso o
fato ainda recebe `ATTRIBUTED/UNATTRIBUTED`, mas não participa de gating de nível.

Se uma regra futura quiser quantificar sobre essa família, ela deve primeiro declará-la em
`population_evidence`. Isso mantém famílias auxiliares desacopladas sem permitir universal sobre
conjunto sem contrato de completude.

---

## 8. Quantificadores e elegibilidade

A regra chamadora passa a forma lógica de cada nível:

```json
{
  "CRITICAL": [
    {"quantifier": "EXISTS", "domain": "cpu_long"}
  ],
  "HIGH": [
    {"quantifier": "EXISTS", "domain": "cpu_short"},
    {"quantifier": "FORALL", "domain": "cpu_long"}
  ]
}
```

Quantificadores permitidos nesta versão:

```text
EXISTS | FORALL
```

Regra genérica:

- `FORALL(domain)` exige `effective_population_evidence[domain] == COMPLETE`;
- `EXISTS(domain)` não é bloqueado **somente** por incompletude do domínio.

`EXISTS` elegível não significa witness encontrado. A regra ainda precisa encontrar um witness
`ATTRIBUTED` que satisfaça seu predicate.

Isso preserva o S9:

```text
cpu_long incompleto
CRITICAL (EXISTS cpu_long) -> ELIGIBLE
HIGH (FORALL cpu_long)     -> BLOCKED
```

A projeção não conhece nomes de níveis nem hazards; `PURPLE`, `ORANGE` ou qualquer futura regra usam a
mesma mecânica.

---

## 9. Interface pura

```python
project_attribution_decision(
    *,
    target_domain_status: str,
    ownership_report: dict,
    facts: list[dict],
    population_evidence: dict,
    level_requirements: dict,
) -> dict
```

Input estrutural inválido levanta `AttributionDecisionInputError`.

Floats são proibidos em timestamps e suportes.

### 9.1 Fato mínimo

```json
{
  "fact_id": "cpu_long:pod-a:100",
  "pod": "pod-a",
  "evidence_family": "cpu_long",
  "evaluated_at": "100",
  "support": {
    "nominal": {
      "start": "-200",
      "end": "100",
      "required_timestamps": ["-195", "-180", "100"],
      "boundary_proven": true
    },
    "observed_sample": null
  },
  "creation_timestamp": "-1000"
}
```

`ownership_report` é output de WORKLOAD-OWNERSHIP-001.

### 9.2 Output mínimo

```json
{
  "analysis": {"status": "ADMISSIBLE"},
  "facts": {
    "cpu_long:pod-a:100": {
      "status": "ATTRIBUTED",
      "support_source": "NOMINAL",
      "evidence_refs": []
    }
  },
  "population_evidence": {
    "cpu_long": {"status": "COMPLETE", "diagnostics": []}
  },
  "effective_population_evidence": {
    "cpu_long": {"status": "COMPLETE", "diagnostics": []}
  },
  "level_eligibility": {
    "CRITICAL": {"status": "ELIGIBLE", "blocked_by": []}
  }
}
```

Quando a atribuição degrada o domínio:

```json
{
  "effective_population_evidence": {
    "cpu_long": {
      "status": "INCOMPLETE",
      "diagnostics": [
        "unattributed_fact:cpu_long:pod-a:100:attribution_unproven"
      ]
    }
  }
}
```

---

## 10. Plano de teste — RED antes de GREEN

Casos originais do slice:

| # | Cenário | Esperado |
|---|---|---|
| 1 | R1 estável | fato ATTRIBUTED; níveis não bloqueados |
| 2 | S2 young Pod | `support_predates_pod` |
| 3 | S3 UID change | `identity_discontinuity` |
| 4 | S4/S7 estrangeiro | `foreign_workload`; análise admissível |
| 5 | S5 selector omission | FORALL do domínio bloqueado |
| 6 | S6 derived evidence missing | mesma consequência lógica do S5 |
| 7 | S9 cpu_long incompleto | CRITICAL elegível; HIGH bloqueado |
| 8 | S10 fronteira | `support_boundary_unproven` |
| 9 | R2 residual com wire atual | `attribution_unproven` |
| 10 | R2 residual com sample support provado | ATTRIBUTED |
| 11 | `coverage_complete` externo | não altera suporte |
| 12 | famílias com mesmo W | atribuições independentes |
| 13 | domínio indeterminável | INADMISSIBLE |
| 14 | domínio determinado e vazio | ADMISSIBLE |
| 15 | nomes arbitrários de nível | genericidade preservada |
| 16 | timestamp float | input error |

Regressões adicionadas após review, antes da correção GREEN:

| # | Cenário | Esperado |
|---|---|---|
| 17 | população de entrada COMPLETE + fato alvo `UNATTRIBUTED` | domínio efetivo INCOMPLETE; FORALL bloqueado; EXISTS elegível |
| 18 | fato `foreign_workload` | domínio alvo efetivo permanece como recebido |
| 19 | `observed_sample_support` fora do nominal | `AttributionDecisionInputError` |
| 20 | `required_timestamps=[]` | `AttributionDecisionInputError` |

---

## 11. Gate

- [x] pré-registração anterior à implementação inicial
- [x] RED inicial anterior a `projection.py`
- [x] testes do slice incluídos em `pyproject.toml` e efetivamente descobertos pelo CI
- [x] review conceitual executado antes do merge
- [x] emenda de completude efetiva registrada antes da correção GREEN
- [x] regressões 17–20 commitadas e falhando antes da correção (`CI #101`: 4 failed, 235 passed)
- [x] GREEN posterior às regressões (`CI #102`: suíte + build verdes)
- [x] nenhum nome de regra/hazard concreto no código
- [x] `coverage_complete` nunca usado como raw-sample support
- [x] membership instantânea em `O(T)` nunca usada como critério de atribuição
- [x] `foreign_workload` não degrada população alvo
- [x] fato alvo não atribuível degrada o domínio efetivo correspondente
- [x] nenhuma alteração em Analyze, Join, Verify ou Risk
