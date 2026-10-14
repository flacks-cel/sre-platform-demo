# RULE-001 — CPU limit ceiling predicate

> Status: **pré-registração commitada; implementação bloqueada até RED.** Base: Verify 001 (PR #11, merge `f9d3338`). Herda ADR-001 a ADR-007. Gate: nenhuma linha da regra é implementada antes dos testes de contrato falharem.

## 0. O que este contrato é

A regra é escrita **depois** que este documento estiver commitado. O objetivo é impedir decisões semânticas depois de observar o comportamento real, preservando o mesmo princípio usado nos Spikes e no Verify 001.

As seções 1 e 2 valem para qualquer rule layer construída sobre o Verify 001. A seção 3 fecha a semântica específica da RULE-001.

## 1. Decisões fechadas

### 1.1 Escopo temporal explícito

A regra declara antes de executar o que faz quando um pod tem CPU observável no intervalo, mas falta evidência dependente no mesmo intervalo.

### 1.2 Completude por dependência, não global

Um pod pode ser utilizável para `cpu_usage` e inutilizável para `cpu/limit`. A regra nomeia exatamente qual evidência exige. Não existe noção genérica de "pod íntegro" ou "pod corrompido".

### 1.3 Coverage sem número mágico

O piso de 80% do Spike 002 não é importado. Sem justificativa própria, coverage permanece metadata diagnóstica e não bloqueia a regra.

### 1.4 Divergência entre selectors não é erro por padrão

`max_cpu_usage_pod != max_cpu_limit_ratio_pod` não significa problema. Divergência só bloqueia se uma relação específica entre selectors for pré-registrada.

### 1.5 Risk e evidence quality permanecem separados

A regra não converte ausência de telemetria em segurança. Evidence quality e a conclusão da regra continuam separadas.

## 2. Semântica de completude parcial

### 2.1 B está descartada

"Válida só sobre o subconjunto completo" sem relatar exclusões é estritamente pior que relatar quem ficou de fora e por quê.

### 2.2 Exclusão por churn não é amostra aleatória

Pods excluídos por churn tendem a ser justamente os que nasceram e morreram durante eventos de escala. A perda de evidência pode portanto ter direção e não deve ser tratada como ruído aleatório.

### 2.3 Correção do teste de escape genérico

O teste "CPU bruta menor que todos os incluídos => exclusão conservadora" **não é válido em geral para uma regra de `cpu/limit`**.

Se o `limit` do pod excluído é desconhecido, CPU bruta menor não implica razão menor. Exemplo: um pod com CPU menor pode ter tido um limit muito menor e, portanto, uma razão `cpu/limit` maior.

Assim, C só é permitido quando a própria regra possui uma **prova monotônica suficiente** de que o pod excluído não pode falsificar a afirmação. Na ausência dessa prova, o resultado é A (`UNKNOWN` global).

CPU bruta, sozinha, nunca é usada como substituto de limit ou denominator ausente.

### 2.4 A resposta pode variar por regra

Uma regra direcionada pode tolerar exclusões apenas quando a direção lógica da afirmação torna a exclusão incapaz de falsificá-la. A prova precisa estar pré-registrada na seção específica da regra.

## 3. Específico da RULE-001

### 3.1 Afirmação

Dado um teto explícito `ceiling_ratio = θ`, a RULE-001 conclui se a evidência histórica sustenta uma destas afirmações:

- `EXCEEDS_CEILING`: existe pelo menos um pod com evidência completa de short-window CPU e limit histórico alinhado cuja razão `cpu/limit` excede `θ`;
- `WITHIN_CEILING`: todos os pods observáveis por short-window CPU possuem evidência completa de limit histórico alinhado e nenhum excede `θ`;
- `UNKNOWN`: não existe prova de exceedance e pelo menos um pod observável por CPU não pode ser avaliado em `cpu/limit`.

`θ` é entrada explícita de policy; RULE-001 não define valor default. Valor ausente, não numérico ou não positivo é erro de input, não evidence `UNKNOWN`.

### 3.2 A regra é direcionada?

- [x] **Direcionada.** Sentido: afirmar `WITHIN_CEILING` é a conclusão de folga relativa ao teto fornecido.
- Erro caro: afirmar `WITHIN_CEILING` quando um pod excluído poderia ter excedido `θ`.

A afirmação `EXCEEDS_CEILING` é existencial: um único witness completo acima de `θ` basta e não pode ser invalidado por outros pods incompletos.

### 3.3 Selectors utilizados

| Selector | Usado? | Evidência exigida | Se UNKNOWN, a regra… |
| --- | --- | --- | --- |
| `max_cpu_usage_pod` | Não para decisão | Short-window CPU; usado apenas como metadata diagnóstica já existente | Não bloqueia por si só |
| `max_cpu_limit_ratio_pod` | Sim | Short-window CPU + limit histórico positivo alinhado por timestamp | Não é suficiente sozinho para distinguir `EXCEEDS_CEILING` de `UNKNOWN`; RULE-001 exige também status per-pod de completude `cpu/limit` |
| `max_cpu_cost_rate_pod` | Não | Request telemetry é fora de escopo desta regra | Não bloqueia |

#### 3.3.1 Pré-requisito de evidência do Verify

O output atual do Verify 001 não expõe, para **cada pod**, o status de completude de `cpu/limit`; ele só expõe o selector agregado e o primeiro motivo de `UNKNOWN` encontrado.

RULE-001 não pode reimplementar join temporal ou inferir exclusões a partir de uma string de erro. Antes do GREEN da regra, o Verify deve expor genericamente por pod, no mínimo:

- status de `cpu_limit_ratio`: `VALID | UNKNOWN`;
- `max` e `max_timestamp` quando VALID;
- razão nomeada quando UNKNOWN (`missing_limit`, `timestamp_misalignment`, `non_positive_limit`, etc.);
- coverage/sample metadata já existente.

Esse enriquecimento pertence ao modelo de evidência, não à regra. Ele deve ser implementado em TDD separado e não altera a semântica da RULE-001.

### 3.4 Relação exigida entre selectors

Nenhuma.

Divergência entre `max_cpu_usage_pod` e `max_cpu_limit_ratio_pod` é esperada e não bloqueia a regra.

### 3.5 Coverage

- [x] Coverage permanece metadata; não bloqueia.
- [ ] A regra exige mínimo de coverage.

RULE-001 não cria threshold de coverage.

### 3.6 Semântica de completude parcial

- [x] **Outro, com justificativa direcional explícita:**

1. Se existir qualquer pod completo com `cpu/limit > θ`, resultado `EXCEEDS_CEILING`, mesmo que outros pods estejam incompletos. As exclusões são reportadas, mas não podem falsificar a afirmação existencial de que "houve exceedance".
2. Se nenhum pod completo exceder `θ` e **todos** os pods observáveis por short-window CPU forem completos para `cpu/limit`, resultado `WITHIN_CEILING`.
3. Se nenhum pod completo exceder `θ` e houver qualquer pod observável por CPU sem `cpu/limit` computável, resultado `UNKNOWN` global. Não existe escape por CPU bruta.
4. Se nenhum pod tiver `cpu/limit` computável, resultado `UNKNOWN`.

Essa assimetria substitui o teste genérico baseado em CPU bruta da versão inicial do contrato.

### 3.7 Condições de evidence quality que bloqueiam a conclusão

| # | Condição | Como é verificada | Resultado |
| --- | --- | --- | --- |
| 1 | Nenhum pod com short-window CPU utilizável | status per-pod de CPU / ausência de candidates | `UNKNOWN` |
| 2 | Nenhum witness completo acima de `θ` e existe pod CPU-observado com `cpu_limit_ratio=UNKNOWN` | status per-pod de `cpu_limit_ratio` | `UNKNOWN` global |
| 3 | Nenhum witness completo acima de `θ` e limit histórico ausente para qualquer pod CPU-observado | reason per-pod | `UNKNOWN` global |
| 4 | Nenhum witness completo acima de `θ` e timestamps CPU/limit não alinham para qualquer pod CPU-observado | reason per-pod | `UNKNOWN` global |
| 5 | Nenhum witness completo acima de `θ` e limit histórico é não positivo para qualquer pod CPU-observado | reason per-pod | `UNKNOWN` global |

Não bloqueiam RULE-001 por si só:

- `max_cpu_cost_rate_pod=UNKNOWN`;
- divergência entre selectors;
- coverage parcial, desde que a métrica dependente continue computável;
- restart presente;
- long-window CPU ausente;
- node/owner metadata ausente.

Esses fatos permanecem reportados quando disponíveis, mas não são dependências desta regra.

### 3.8 O que a regra NÃO produz

RULE-001 não produz:

- LOW / MEDIUM / HIGH;
- recommendation;
- novo CPU limit;
- alteração automática em Git ou Kubernetes;
- LLM/IA;
- verify de memória;
- `worst_pod` genérico;
- filtragem silenciosa de pods em churn;
- threshold default de `ceiling_ratio`;
- threshold de coverage.

## 4. Output

A regra devolve, no mínimo:

- `rule_id: RULE-001`;
- `ceiling_ratio`;
- `conclusion: WITHIN_CEILING | EXCEEDS_CEILING | UNKNOWN`;
- razão nomeada quando `UNKNOWN`;
- selectors consumidos e status de cada um;
- lista de pods excluídos da avaliação de `cpu/limit`, com razão por pod;
- witness de exceedance quando existir (`pod`, `ratio`, `timestamp`, `window`);
- coverage/sample metadata;
- nenhum `worst_pod`.

CLI: JSON puro em stdout. `UNKNOWN` é execução válida e mantém exit code 0. Erro de input/transport/schema permanece non-zero em stderr.

## 5. Plano de teste — RED antes de GREEN

Cada linha vira teste de contrato antes da implementação da regra.

| # | Cenário | Esperado |
| --- | --- | --- |
| 1 | Todos os pods completos e todos `cpu/limit <= θ` | `WITHIN_CEILING`, exclusões vazias |
| 2 | Todos os pods completos e um `cpu/limit > θ` | `EXCEEDS_CEILING` com witness nomeado |
| 3 | Pod em churn com CPU válida e limit ausente; nenhum pod completo excede `θ` | `UNKNOWN` global; pod excluído e razão nomeada |
| 4 | Pod em churn incompleto, mas outro pod completo excede `θ` | `EXCEEDS_CEILING`; exclusão continua reportada |
| 5 | Selectors apontam pods diferentes | conclusão normal; divergência não bloqueia |
| 6 | `max_cpu_cost_rate_pod=UNKNOWN` | conclusão de RULE-001 inalterada |
| 7 | Nenhum pod com `cpu/limit` completo | `UNKNOWN`, nunca headroom |
| 8 | Timestamp misalignment CPU/limit em um pod e nenhum exceedance witness completo | `UNKNOWN` global |
| 9 | Restart presente | não bloqueia; restart permanece metadata |
| 10 | Coverage parcial mas ratio computável | não bloqueia; coverage permanece metadata |
| 11 | `ceiling_ratio` ausente, não numérico ou <= 0 | erro de input, não `UNKNOWN` |
| 12 | Long-window CPU ausente, short CPU + limit suficientes | RULE-001 continua avaliável |

Os cenários 3 e 4 validam a assimetria lógica central: incompletude bloqueia a afirmação universal de headroom, mas não apaga um witness completo de exceedance.

## 6. Checklist do gate

- [x] Seções 3.1 a 3.8 preenchidas
- [x] 3.2 respondida antes de 3.6
- [x] 3.5 não importa threshold do Spike 002
- [x] 3.4 não exige convergência artificial entre selectors
- [x] Contrato commitado
- [ ] Pré-requisito per-pod do Verify exposto e testado
- [ ] Testes do plano 5 escritos e falhando (RED)
- [ ] Primeira linha da implementação da RULE-001 só depois dos itens acima
