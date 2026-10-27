# CHANGE-RISK-001 — CPU limit insufficiency

> Status: **implementação GREEN confirmada; aguardando merge.**
> Base: `main @ 79ce50a`.
> Pré-requisitos cumpridos: RISK-VOCABULARY-001, CHANGE-JOIN-001, VERIFY-THROTTLING-001 e CHANGE-JOIN-THROTTLING-001.
> Hazard fixo deste contrato: `cpu_limit_insufficiency`.

---

## 1. Pergunta

> Dado um output do CHANGE-JOIN-001, o CPU limit declarado proposto contradiz a evidência histórica observada sob o perigo de insuficiência de CPU?

Esta é a primeira regra real de change risk do Praeva.

Ela classifica **grau de contradição**, não probabilidade de incidente e não impacto de negócio.

---

## 2. Interface pura

A implementação viverá em:

```text
praeva/risk/cpu_limit_insufficiency.py
```

API congelada:

```python
evaluate_cpu_limit_insufficiency(
    *,
    joined: dict,
    margin: dict,
) -> dict
```

`margin` é obrigatório e não possui default.

Formato:

```json
{"numerator": 11, "denominator": 10}
```

Regras estruturais de `margin`:

- numerator e denominator são inteiros positivos;
- boolean não é inteiro válido;
- `numerator > denominator`, portanto `margin > 1`;
- `float` não é aceito;
- comparação é feita por multiplicação cruzada exata;
- ausência ou formato inválido é `ChangeRiskInputError`, não `UNKNOWN`.

`margin > 1` é uma **escolha de policy desta regra**, não apenas validação de sanidade. Esta versão exige folga positiva para separar `MEDIUM` de `LOW`; uma margem exatamente igual a `1` — isto é, sem folga adicional além da não contradição estrita — é deliberadamente inexpressável neste contrato.

Nenhum valor de margem é embutido na regra.

---

## 3. Hazard

Todo resultado aplicável usa:

```text
hazard_id = cpu_limit_insufficiency
```

Semântica:

> risco de o CPU limit declarado proposto ser insuficiente diante da CPU historicamente observada para os pods selecionados.

Este hazard não cobre:

- pressão de nó por aumento de limit;
- consumo irrestrito após remoção de limit;
- custo;
- disponibilidade de negócio;
- probabilidade futura.

---

## 4. Aplicabilidade

`applicability` é um eixo da regra, separado de `classification_status`.

Direções:

```text
DECREASE     -> APPLICABLE
INCREASE     -> APPLICABLE
LIMIT_ADDED  -> APPLICABLE
LIMIT_REMOVED -> NOT_APPLICABLE
UNCHANGED     -> NOT_APPLICABLE
```

Um aumento pode continuar insuficiente. Exemplo conceitual: aumentar de 100m para 200m não elimina contradição se a evidência sustentada observada está em 500m.

Quando `NOT_APPLICABLE`:

- `hazard_id` permanece presente;
- `classification_status` fica ausente;
- `risk_level` fica ausente;
- `not_applicable_reason` é nomeada.

Razões desta versão:

```text
limit_removed
limit_unchanged
```

`NOT_APPLICABLE` não é `UNKNOWN` e não entra no enum do RISK-VOCABULARY-001.

---

## 5. Unidade e representação

O limit proposto vem de:

```text
joined.change_facts.proposed_declared_cpu_limit
```

em milicores declarados.

CPU histórica vem de:

```text
joined.pods[pod].windows.<short|long>.observed_cpu.value_millicores
```

como string decimal exata.

A regra usa `Decimal` internamente e não converte por `float`.

O limit proposto `ABSENT` é inconsistente com uma direção aplicável e é input inválido.

Limit proposto igual a zero continua sendo um fato válido rio acima, mas esta primeira regra não atribui semântica operacional a zero. Portanto:

```text
classification_status = UNKNOWN
code = non_positive_proposed_limit
precondition = positive_proposed_limit
```

---

## 6. Censura por CFS

CPU observada sob throttling é evidência censurada pelo limit efetivo vigente: o valor observado pode ser menor que a demanda real.

A assimetria é normativa:

- **contradição positiva** continua válida sob censura: se o observado já excede o proposto, demanda real maior não desfaz a contradição;
- **não contradição** não pode ser afirmada com evidência censurada ou com ausência de prova de não censura.

Consequência:

- `HIGH` e `CRITICAL` não exigem ausência de throttling;
- `MEDIUM` e `LOW` exigem, em todo pod e nas duas janelas, throttling `VALID`, `any_positive=false` e `coverage_complete=true`.

Qualquer `any_positive=true` bloqueia `MEDIUM/LOW` com:

```text
code = censored_evidence
precondition = uncensored_evidence_for_noncontradiction
```

Throttling `UNKNOWN`, não adquirido, ou zero com coverage incompleta bloqueia `MEDIUM/LOW` com:

```text
code = uncensored_evidence_unproven
precondition = uncensored_evidence_for_noncontradiction
```

Não existe threshold mínimo de throttling nesta versão. Qualquer witness positivo conta como censura observada.

---

## 7. Duas janelas, avaliadas independentemente

A regra não assume `long <= short` e não tenta provar relação matemática entre as janelas.

Para cada pod:

```text
S_pod = observed CPU da janela short
L_pod = observed CPU da janela long
P     = proposed declared CPU limit
```

A relação é estrita:

```text
P < observado  -> contradição
P == observado -> não é contradição estrita
```

As janelas têm funções diferentes na escada:

- witness de contradição na janela long pode sustentar `CRITICAL`;
- witness de contradição apenas na janela short pode sustentar `HIGH`.

Caso `long > short` é permitido e avaliado literalmente. Exemplo: `P=450`, `short=400`, `long=500` produz witness long e portanto `CRITICAL`.

---

## 8. Regra de decisão por witness e completude

A ordem abaixo é normativa.

### 8.1 Precondição: divergência declared × effective conhecida

Antes de classificar, a regra examina:

```text
pods[pod].current_declared_effective_relation
```

Um witness `VALID` com:

```text
DIFFERS
DECLARED_ABSENT_EFFECTIVE_PRESENT
```

bloqueia a classificação inteira:

```text
classification_status = UNKNOWN
code = declared_effective_divergence
precondition = no_known_declared_effective_divergence
```

Motivo: há evidência positiva de que o valor declarado atual não corresponde ao limit efetivo observado; classificar o valor proposto declarado como se fosse necessariamente o futuro valor efetivo seria misturar domínios da ADR-008.

Uma relation `UNKNOWN` **não é convertida em MATCH e não prova ausência de mutation**. Porém, sem witness positivo de divergência, ela também não inventa mutation. Permanece visível na provenance/evidência e não modula o nível por si só.

### 8.2 Sem pods

Se `joined.pods` está vazio:

```text
classification_status = UNKNOWN
code = no_pod_evidence
precondition = pod_evidence_present
```

### 8.3 CRITICAL: witness long é suficiente

Se existir pelo menos um pod com janela long `observed_cpu.status=VALID` e:

```text
P < L_pod
```

resultado:

```text
risk_level = CRITICAL
classification_basis = sustained_window_contradiction
```

Um witness long suficiente não é rebaixado por:

- throttling positivo;
- throttling UNKNOWN;
- CPU short UNKNOWN em outro pod;
- CPU long UNKNOWN em outro pod.

Não há nível acima de `CRITICAL` que a evidência faltante possa esconder.

### 8.4 HIGH: witness short exige long completo

Se não existe witness long de `CRITICAL`, mas existe pelo menos um pod com short `VALID` e:

```text
P < S_pod
```

`HIGH` só pode ser emitido se **todas as janelas long de todos os pods forem VALID** e nenhuma contradizer P.

Essa exigência é deliberadamente mais estrita do que apenas encontrar um witness short: se alguma janela long está `UNKNOWN`, ainda pode existir um witness sustentado de `CRITICAL` escondido pela evidência ausente. Emitir `HIGH` nesse estado seria subestimar o nível máximo que a própria regra ainda poderia demonstrar; por isso a saída correta é `UNKNOWN`, não `HIGH` atenuado.

Se alguma long está UNKNOWN, o resultado é:

```text
classification_status = UNKNOWN
code = long_window_cpu_incomplete
precondition = long_window_complete_before_high
```

Com long completo e sem witness long:

```text
risk_level = HIGH
classification_basis = short_window_only_contradiction
```

Throttling não modula esse `HIGH`.

#### Limitação conhecida — completude de `joined.pods` não é provada

A frase “todas as janelas long de todos os pods” acima é quantificada apenas sobre os pods presentes em `joined.pods`. A implementação atual não prova que esse conjunto contém toda a população histórica atribuível ao Deployment alvo.

Enquanto `identity_assertion.status=CALLER_ASSERTED` e `workload_to_pod_selector_relation=UNVERIFIED`, um selector pode omitir um pod real do workload sem que `CHANGE-RISK-001` perceba a omissão.

O SPIKE-003, cenário sintético `S9-population-incomplete-high`, demonstrou essa limitação contra a implementação real de `CHANGE-RISK-001`:

```text
proposed = 350m

subset observado:
A: short=400m, long=300m
B: short=300m, long=300m
=> HIGH / short_window_only_contradiction

população completa adiciona C:
C: short=300m, long=500m
=> CRITICAL / sustained_window_contradiction
```

Portanto, a versão atual pode subestimar `CRITICAL` como `HIGH` quando `joined.pods` é uma população incompleta do Deployment. Isso é uma limitação conhecida da integração atual, não uma mudança da escada `CHANGE-RISK-001`: `CRITICAL` continua existencial, enquanto emitir `HIGH` com segurança exige excluir contradição long na população relevante completa.

Até existir uma prova de atribuição/completude populacional integrada antes desta regra, um resultado `HIGH` depende implicitamente da suposição de que `joined.pods` representa toda a população relevante. O SPIKE-003 está investigando a camada que deve tornar essa precondição explícita.

### 8.5 Antes de MEDIUM/LOW, CPU precisa ser completa

Se não existe contradição short/long conhecida, `MEDIUM` ou `LOW` só podem ser emitidos se short e long forem `VALID` para todos os pods.

Caso contrário:

```text
classification_status = UNKNOWN
code = cpu_evidence_incomplete
precondition = all_cpu_windows_complete_for_noncontradiction
```

### 8.6 Antes de MEDIUM/LOW, não censura precisa ser demonstrada

Com CPU completa e nenhuma contradição, aplica-se a seção 6.

Qualquer throttling positivo -> `UNKNOWN(censored_evidence)`.

Qualquer throttling UNKNOWN, não adquirido ou zero parcial -> `UNKNOWN(uncensored_evidence_unproven)`.

### 8.7 MEDIUM e LOW

Depois de cumprir 8.5 e 8.6, define-se:

```text
M = máximo de todos os valores observados de CPU entre todos os pods e as duas janelas
```

Este `max` é uma operação explicitamente pré-registrada para a fronteira `MEDIUM/LOW`; ele não cria `worst_pod` genérico e não soma réplicas. A distinção é intencional: `M` é uma redução **nomeada, com métrica definida e finalidade única** — decidir a fronteira `MEDIUM/LOW`. O `worst_pod` rejeitado no Spike 002 era um seletor genérico cuja métrica de escolha não estava fixada e poderia mudar conforme o uso. Aqui nenhum pod ganha identidade especial e `M` não pode ser reutilizado como representante genérico do workload.

Como já não existe contradição:

```text
P >= M
```

Comparação exata da margem:

```text
P * margin.denominator < M * margin.numerator
```

Se verdadeiro:

```text
risk_level = MEDIUM
classification_basis = headroom_below_margin
```

Caso contrário, inclusive igualdade:

```text
risk_level = LOW
classification_basis = headroom_at_or_above_margin
```

Exemplo normativo com `margin=11/10` e `M=400`:

```text
P=430 -> MEDIUM
P=440 -> LOW
P=450 -> LOW
```

Portanto, qualquer versão anterior que associe `P=450`, `M=400`, `margin=11/10` a `MEDIUM` está incorreta; a fronteira exata é `440`.

---

## 9. Evidence quality é porta, nunca peso

Esta regra implementa o RISK-VOCABULARY-001 literalmente:

- evidence quality não reduz `CRITICAL` para `HIGH`;
- evidence quality não reduz `HIGH` para `MEDIUM`;
- evidence quality não transforma `LOW` em `MEDIUM`;
- uma precondição necessária satisfeita permite a classificação;
- uma precondição necessária não satisfeita produz `UNKNOWN`.

Em particular:

- short contradiction + throttling completo = `HIGH` quando long está completo e não contraditório;
- a mesma short contradiction + throttling não adquirido continua `HIGH`;
- cenário que seria `LOW` com prova completa de não censura vira `UNKNOWN`, nunca `MEDIUM`, se throttling zero tiver coverage parcial.

---

## 10. Provenance não altera o nível

O output preserva:

```text
provenance.identity_assertion
provenance.workload_to_pod_selector_relation
provenance.application_version_relation
```

copiados do CHANGE-JOIN-001.

`CALLER_ASSERTED` não é `VERIFIED`, mas não rebaixa nível.

`application_version_relation=UNVERIFIED` permanece visível; esta primeira regra não inventa freshness/version policy.

---

## 11. Output

### 11.1 Resultado classificado

```json
{
  "rule_id": "CHANGE-RISK-001",
  "hazard_id": "cpu_limit_insufficiency",
  "applicability": "APPLICABLE",
  "classification_status": "CLASSIFIED",
  "risk_level": "HIGH",
  "classification_basis": "short_window_only_contradiction",
  "policy": {
    "margin": {"numerator": 11, "denominator": 10}
  },
  "evidence_refs": [
    "change_facts.proposed_declared_cpu_limit",
    "pods.pod-a.windows.short.observed_cpu"
  ],
  "provenance": {
    "identity_assertion": "CALLER_ASSERTED",
    "workload_to_pod_selector_relation": "UNVERIFIED",
    "application_version_relation": "UNVERIFIED"
  }
}
```

Todo resultado `CLASSIFIED` deve passar por `validate_risk_result` do RISK-VOCABULARY-001.

### 11.2 Resultado UNKNOWN

```json
{
  "rule_id": "CHANGE-RISK-001",
  "hazard_id": "cpu_limit_insufficiency",
  "applicability": "APPLICABLE",
  "classification_status": "UNKNOWN",
  "unknown_reasons": [
    {
      "code": "censored_evidence",
      "precondition": "uncensored_evidence_for_noncontradiction"
    }
  ],
  "evidence_refs": ["pods.pod-a.windows.short.cfs_throttling"],
  "provenance": {}
}
```

`risk_level` fica ausente.

### 11.3 Resultado NOT_APPLICABLE

```json
{
  "rule_id": "CHANGE-RISK-001",
  "hazard_id": "cpu_limit_insufficiency",
  "applicability": "NOT_APPLICABLE",
  "not_applicable_reason": {
    "code": "limit_removed",
    "precondition": "hazard_applicable_direction"
  },
  "provenance": {}
}
```

`classification_status` e `risk_level` ficam ausentes.

---

## 12. Evidence refs

Toda classificação referencia explicitamente os fatos que a sustentam.

Formato desta versão: paths simbólicos estáveis dentro do join, por exemplo:

```text
change_facts.proposed_declared_cpu_limit
pods.pod-a.windows.long.observed_cpu
pods.pod-a.windows.short.cfs_throttling
pods.pod-a.current_declared_effective_relation
```

Não existe referência `worst_pod`.

Para `MEDIUM/LOW`, a regra pode referenciar todos os fatos CPU/throttling que formaram a decisão; não escolhe um pod representativo por conveniência.

---

## 13. Erro de input versus UNKNOWN

`ChangeRiskInputError` é usado para input estruturalmente inválido, por exemplo:

- `join_id` inesperado;
- `margin` ausente/inválido;
- direction desconhecida;
- tipo incompatível;
- status fora do contrato;
- campo obrigatório estrutural ausente.

`UNKNOWN` é usado quando a pergunta é válida, mas uma precondição semântica de evidência não pode ser satisfeita.

---

## 14. Exit code e CLI

Este slice implementa somente a função pura.

Não adiciona CLI nem altera exit code de processo.

O invariante do RISK-VOCABULARY-001 continua normativo para qualquer adapter futuro:

```text
CRITICAL -> exit code 0 por padrão
UNKNOWN  -> exit code 0 por padrão
```

Um gate de CI por veredito exigirá contrato próprio.

---

## 15. Não objetivos

Esta regra não implementa:

- recomendação de novo CPU limit;
- target CPU;
- alteração automática de Git/Kubernetes;
- score numérico;
- probabilidade;
- impacto de negócio;
- agregação entre hazards;
- ownership verificado Pod -> ReplicaSet -> Deployment;
- freshness threshold;
- P95;
- peak histórico genérico;
- threshold de throttling;
- `worst_pod`.

---

## 16. Plano RED

Antes da implementação, testes devem congelar pelo menos:

1. long contradiction -> `CRITICAL` mesmo com throttling UNKNOWN;
2. short-only contradiction + long completo -> `HIGH`;
3. short contradiction + long UNKNOWN -> `UNKNOWN`, nunca `HIGH`;
4. sem contradição + short/long incompleto -> `UNKNOWN`;
5. sem contradição + throttling positivo -> `UNKNOWN(censored_evidence)`;
6. sem contradição + throttling não adquirido -> `UNKNOWN(uncensored_evidence_unproven)`;
7. zero throttling com coverage parcial -> `UNKNOWN`, nunca nível vizinho;
8. `P=430`, `M=400`, margin 11/10 -> `MEDIUM`;
9. fronteira `P=440`, `M=400`, margin 11/10 -> `LOW`;
10. `long > short` é avaliado literalmente e pode produzir `CRITICAL`;
11. `INCREASE` continua aplicável e pode ser `CRITICAL`;
12. divergence declared×effective conhecida -> `UNKNOWN`;
13. `LIMIT_ADDED` + effective witness presente -> `UNKNOWN` por divergence conhecida;
14. `LIMIT_REMOVED` -> `NOT_APPLICABLE`;
15. `UNCHANGED` -> `NOT_APPLICABLE`;
16. proposed zero -> `UNKNOWN(non_positive_proposed_limit)`;
17. sem pods -> `UNKNOWN(no_pod_evidence)`;
18. margin inválida é input error, não `UNKNOWN`;
19. `CALLER_ASSERTED` é preservado e não impede classificação;
20. todo `CLASSIFIED` passa `validate_risk_result` e possui `evidence_refs`;
21. `UNKNOWN` nunca contém `risk_level`;
22. output não contém score, probability, recommendation, target CPU ou `worst_pod`.

---

## 17. Gate

- [x] RISK-VOCABULARY-001 mergeado
- [x] VERIFY-THROTTLING-001 mergeado
- [x] CHANGE-JOIN-THROTTLING-001 mergeado
- [x] hazard nomeado: `cpu_limit_insufficiency`
- [x] margin é parâmetro racional obrigatório sem default
- [x] censura CFS tratada assimetricamente
- [x] short/long avaliadas independentemente
- [x] witness versus completude pré-registrado
- [x] `NOT_APPLICABLE` permanece fora do vocabulário compartilhado
- [x] divergência declared×effective conhecida bloqueia classificação
- [x] nenhuma freshness policy inventada
- [x] testes RED escritos
- [x] RED confirmado localmente: Ruff passou; `25 failed, 151 passed`
- [x] implementação iniciada somente depois do RED
- [x] invariantes comportamentais aplicáveis do RISK-VOCABULARY-001 cobertos
- [x] GREEN local: Ruff passou; `176 passed`
- [x] CI #69: Ruff, Pytest e Docker build/push passaram
