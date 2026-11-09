# CHANGE-RISK-001-POPULATION-GATE-001 — Contrato de Pré-Registração
## Bloqueio dos níveis que dependem de população completa

> Status: **pré-registração — em preenchimento.**
> Gate: **nenhuma linha implementada antes da seção 8 resolvida e commitada.**
> Base: `main @ ac5607e`. Altera **apenas** `praeva/risk/cpu_limit_insufficiency.py`.
> Emenda deliberada de semântica da CHANGE-RISK-001 — não é correção de bug disfarçada.
> **Não toca** Attribution, Join, Verify, Analyze nem Ownership.

---

## 1. Pergunta

> Quando não há prova de que a população de Pods observada é a população completa do Deployment,
> quais níveis de risco a regra ainda pode emitir?

O SPIKE-003, cenário `S9-population-incomplete-high`, demonstrou contra a **implementação real** que
a CHANGE-RISK-001 pode devolver `HIGH` quando a população completa produziria `CRITICAL`. A
limitação está documentada no contrato da regra desde 26/10 e permanece ativa em produção.

Este slice não espera a cadeia de attribution. Ele impede, agora, a emissão de conclusões que
sabemos não estar suficientemente fundamentadas.

---

## 2. Por que CRITICAL sobrevive e os demais não

A forma lógica de cada degrau decide:

| Degrau | Forma | Sobrevive a população incompleta? |
|---|---|---|
| `CRITICAL` | `∃` witness longo com contradição | **Sim** — uma testemunha válida basta, e Pods não observados só poderiam piorar o quadro |
| `HIGH` | `∃` witness curto **∧** `∀` janelas longas sem contradição | Não — o componente universal foi avaliado sobre um subconjunto próprio |
| `MEDIUM` | `∀` sem contradição, proposta dentro da margem | Não |
| `LOW` | `∀` sem contradição, proposta acima da margem | Não |

É a mesma assimetria da censura por throttling, aplicada a outro eixo: **contradição precisa de uma
testemunha; não-contradição precisa do domínio completo.**

O erro que isso evita é na direção cara. `HIGH` emitido onde a verdade é `CRITICAL` subestima a
restrição exatamente quando ela mais importa.

---

## 3. De onde vem a prova de população

A regra lê o bloco `identity_assertion` que o CHANGE-JOIN-001 já publica:

```
joined["identity_assertion"]["population_completeness"]
```

| Valor | Significado |
|---|---|
| `PROVEN_COMPLETE` | a população observada é comprovadamente a população do alvo |
| ausente, `null`, ou qualquer outro valor | **não provada** |

**Nada no Join muda neste slice.** O campo não existe hoje, e ausência é tratada como não provada —
que é a verdade do estado atual. Quando a camada de attribution puder provar completude, ela
preenche o campo e o portão abre sozinho, sem nova alteração nesta regra.

Tratar ausência como prova seria o oposto da ADR-005.

### 3.1 Completude de população não é atribuição

`workload_to_pod_selector_relation = VERIFIED` provaria que os Pods observados **pertencem** ao
alvo. Nunca provaria que são **todos** os Pods do alvo.

São eixos distintos e este portão depende apenas do segundo. Ler o primeiro como se fosse o segundo
reintroduziria o S9 por outro caminho.

---

## 4. Comportamento

Avaliado depois da aplicabilidade e depois de computado o nível candidato pela escada atual.

| Nível candidato | População provada | Resultado |
|---|---|---|
| `CRITICAL` | qualquer | `CRITICAL`, inalterado |
| `HIGH` | `PROVEN_COMPLETE` | `HIGH` |
| `HIGH` | não provada | **`UNKNOWN(population_completeness_unproven)`** |
| `MEDIUM` | `PROVEN_COMPLETE` | `MEDIUM` |
| `MEDIUM` | não provada | **`UNKNOWN(population_completeness_unproven)`** |
| `LOW` | `PROVEN_COMPLETE` | `LOW` |
| `LOW` | não provada | **`UNKNOWN(population_completeness_unproven)`** |
| já `UNKNOWN` | não provada | `UNKNOWN`, com a razão **acrescentada** à lista |
| `NOT_APPLICABLE` | qualquer | inalterado — aplicabilidade vem de `direction`, não de evidência |

### 4.1 Razões acumulam, não substituem

`unknown_reasons` já é lista. Quando a evidência está censurada **e** a população não está provada,
as duas razões aparecem: são bloqueios independentes, com remédios diferentes — obter uma janela sem
throttling versus provar a população.

Substituir uma pela outra esconderia metade do trabalho que o usuário precisa fazer.

### 4.2 Nenhuma alteração na escada

Os limiares, a margem, o witness existencial, o tratamento de censura e as pré-condições de
evidência permanecem **exatamente** como estão. Este slice adiciona um portão depois da escada;
não mexe em nenhum degrau.

---

## 5. Consequência imediata, aceita conscientemente

Hoje `population_completeness` nunca vem preenchido. Logo, após este slice a regra emite, na
prática, **apenas `CRITICAL`, `UNKNOWN` ou `NOT_APPLICABLE`** até a camada de attribution provar
completude.

Combinado com o bloqueio de `LOW`/`MEDIUM` por censura, a escada de quatro degraus passa a se
comportar como um bit: há prova de contradição, ou não se sabe.

Isso é honesto e é melhor que `HIGH` subestimado. E muda a prioridade do que vem depois: os
produtores de população deixam de ser infraestrutura de rigor e passam a ser **o que devolve
expressividade ao produto**.

---

## 6. Migração dos testes existentes

A suíte atual tem asserções de `risk_level` em `HIGH` (4), `MEDIUM` (1) e `LOW` (5). Todas passam a
falhar sob o portão.

**A migração correta é fornecer a prova nas fixtures, não trocar a expectativa.** Cada teste que
hoje exercita um desses degraus passa a declarar `population_completeness = PROVEN_COMPLETE` no
`joined` de entrada, continuando a testar a escada.

Trocar a expectativa para `UNKNOWN` destruiria a cobertura dos três degraus, e a escada ficaria sem
teste justamente enquanto o produto não consegue alcançá-la.

Os testes novos cobrem o portão em si, com a prova ausente.

---

## 7. Opção considerada e rejeitada

Uma flag do tipo `--assume-population-complete`, permitindo ao usuário declarar que o seletor
descreve o workload inteiro.

**Rejeitada.** Seria o `CALLER_ASSERTED` um nível mais fundo: uma afirmação não verificada
destravando exatamente os níveis que o portão existe para proteger, e sem nenhum sinal distinguindo
um `LOW` provado de um `LOW` assumido.

Se vier a ser necessária, entra com pré-registro próprio, valor de proveniência distinto no
documento e justificativa escrita de por que o risco é aceitável.

---

## 8. Lacunas a resolver antes do gate

### 8.1 Nome e forma do campo

`identity_assertion.population_completeness` com enum `PROVEN_COMPLETE`, ou um bloco próprio
`population` com mais estrutura, antecipando o que a attribution vai publicar.

- [ ] Campo simples agora; estrutura quando a attribution definir a sua
- [ ] Bloco próprio desde já, acordado com o contrato de attribution

### 8.2 Código da razão

- [ ] `population_completeness_unproven` (recomendado — diz o que falta, não o que está errado)
- [ ] Outro: `[ preencher ]`

### 8.3 Onde o portão mora no código

- [ ] Dentro de `evaluate_cpu_limit_insufficiency`, após a escada
- [ ] Função separada no mesmo módulo, aplicada ao resultado da escada

---

## 9. Plano de teste — RED antes de GREEN

| # | Cenário | Esperado |
|---|---|---|
| 1 | Witness longo com contradição, população não provada | `CRITICAL` — **inalterado** |
| 2 | Witness longo com contradição, população provada | `CRITICAL` |
| 3 | Candidato `HIGH`, população não provada | `UNKNOWN(population_completeness_unproven)` |
| 4 | Candidato `HIGH`, população provada | `HIGH` |
| 5 | Candidato `MEDIUM`, população não provada | `UNKNOWN(population_completeness_unproven)` |
| 6 | Candidato `MEDIUM`, população provada | `MEDIUM` |
| 7 | Candidato `LOW`, população não provada | `UNKNOWN(population_completeness_unproven)` |
| 8 | Candidato `LOW`, população provada | `LOW` |
| 9 | Censura **e** população não provada | `UNKNOWN` com **as duas** razões na lista |
| 10 | `population_completeness` ausente do `joined` | tratado como não provada, sem erro |
| 11 | `population_completeness` com valor desconhecido | tratado como não provada, sem erro |
| 12 | `LIMIT_REMOVED` | `NOT_APPLICABLE` — o portão não se aplica |
| 13 | Cenário S9 do SPIKE-003, população não provada | `UNKNOWN`, **nunca** `HIGH` |
| 14 | Cenário S9, população provada sobre `{A,B,C}` | `CRITICAL` |

O par 13/14 é o que fecha o S9: a mesma evidência, com e sem prova, e em nenhum dos dois casos a
resposta é `HIGH`.

Os casos 10 e 11 travam a interpretação de ausência: um campo que falta nunca vira prova.

---

## 10. Checklist do gate

- [ ] Seção 8 resolvida e commitada
- [ ] Nenhuma alteração em Attribution, Join, Verify, Analyze ou Ownership
- [ ] Nenhum limiar, margem ou degrau da escada alterado
- [ ] Ausência de prova nunca tratada como prova
- [ ] `workload_to_pod_selector_relation` **não** usado como prova de população
- [ ] Testes existentes de `HIGH`/`MEDIUM`/`LOW` migrados fornecendo a prova, não trocando a expectativa
- [ ] Testes do plano 9 escritos e **falhando** antes da primeira linha de implementação
- [ ] Limitação conhecida do S9 no contrato da CHANGE-RISK-001 atualizada para apontar este slice
