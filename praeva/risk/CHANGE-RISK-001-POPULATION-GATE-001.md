# CHANGE-RISK-001-POPULATION-GATE-001 — Contrato de Pré-Registração
## Bloqueio dos níveis que dependem de população completa

> Status: **pré-registração — seção 8 fechada antes de RED.**
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
que é a verdade do estado atual. Uma futura integração de attribution poderá preencher
este campo **somente por um produtor de prova confiável e auditável**, definido em contrato
separado. A regra pura recebe o campo como input; a mera string `PROVEN_COMPLETE`
não constitui evidência de origem por si só, e este slice **não** autoriza flag CLI,
`CALLER_ASSERTED` nem uma inferência de `VERIFIED` como substituto. A ligação efetiva
do produtor ao `joined` será trabalho futuro e pode demandar adaptar o wiring/Join em
outro slice; ela não ocorre automaticamente aqui.

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

Razões preexistentes permanecem em sua ordem e a razão populacional é acrescentada
**uma única vez ao final**. Uma conversão de `CLASSIFIED` para `UNKNOWN` retira
`risk_level` e `classification_basis`, mantém os `evidence_refs`, `policy`
e `provenance` preexistentes, e valida o resultado com
`validate_risk_result`. O portão não sintetiza referências a uma prova que não existe.

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

**Exceção obrigatória: regressão histórica do S9.** O teste
`experiments/praeva/spike-003/tests/test_risk_population.py`
não é um teste ordinário do degrau `HIGH`: ele materializa a omissão de `pod-c`.
**Nunca** atribuir `PROVEN_COMPLETE` ao subconjunto `{pod-a,pod-b}` para
preservar artificialmente a expectativa antiga `HIGH`. A nova expectativa contra
a regra corrigida é `UNKNOWN(population_completeness_unproven)` para o subconjunto;
para a população `{pod-a,pod-b,pod-c}`, `CRITICAL` continua demonstrável.
O resultado **pré-gate** `HIGH` fica registrado como achado histórico do SPIKE-003,
não como comportamento ainda aceito. Não modificar a fixture bruta/sintética para
esconder a regressão corrigida.

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

## 8. Decisões fechadas antes de RED

### 8.1 Nome e forma do campo — fechado

Usar campo simples `identity_assertion.population_completeness` com valor positivo
exato `PROVEN_COMPLETE`. Ausente, `null`, string desconhecida, outro tipo ou
qualquer outro valor = **não provada** (fail-closed, sem erro de input). Nenhum
bloco `population` novo é antecipado neste slice. O contrato do produtor
de prova e seu wiring futuro ficam fora do escopo.

Não confundir este campo com `workload_to_pod_selector_relation`, que prova
pertencimento, não completude. Um `CRITICAL` continua condicionado às
pré-condições preexistentes do witness e da identidade declarada; este
gate **não resolve atribuição falsa** ou verifica identidade.

### 8.2 Razão e precondição — fechado

Quando a população não está provada e o gate bloqueia níveis, usar:

```text
code = population_completeness_unproven
precondition = proven_complete_target_population
```

Razões já existentes permanecem e esta é acrescentada ao fim, apenas uma vez.

### 8.3 Local do portão — fechado

Implementar função pura separada **no mesmo**
`praeva/risk/cpu_limit_insufficiency.py`, aplicada a um único resultado
da escada, mantendo a API pública
`evaluate_cpu_limit_insufficiency(*, joined, margin)`.
A escada atual contém retornos antecipados: refatorar apenas a fronteira
entre avaliação do candidato e pós-processamento, sem alterar os limiares
nem a ordem normativa das decisões.

O gate deve preservar `CRITICAL` e `NOT_APPLICABLE`; bloquear `HIGH`,
`MEDIUM` e `LOW` não provados; acumular a razão em `UNKNOWN` não provado;
preservar evidência e provenance existentes; validar o resultado
`CLASSIFIED/UNKNOWN` após o pós-processamento.
O teste do S9 histórico é exceção explícita à migração automática
das fixtures de `HIGH` (seção 6).

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
| 13 | Cenário S9, subconjunto observado `{A,B}` sem prova | `UNKNOWN(population_completeness_unproven)`, **nunca** `HIGH` |
| 14 | Cenário S9, população `{A,B,C}` com prova simulada na fixture | `CRITICAL`; nenhuma prova de completude é inferida a partir do subconjunto |

O par 13/14 compartilha a mesma **fixture-base sintética**, mas NÃO a mesma população observada: no 13 usa `{A,B}`, no 14 usa `{A,B,C}`. A correção bloqueia `HIGH` no subconjunto sem prova; a população completa contém witness long de `CRITICAL`.

Os casos 10 e 11 travam a interpretação de ausência: um campo que falta nunca vira prova.

---

## 10. Checklist do gate

- [x] Seção 8 resolvida e commitada antes de RED
- [ ] Nenhuma alteração em Attribution, Join, Verify, Analyze ou Ownership
- [ ] Nenhum limiar, margem ou degrau da escada alterado
- [ ] Ausência de prova nunca tratada como prova
- [ ] `workload_to_pod_selector_relation` **não** usado como prova de população
- [ ] Testes ordinários de `HIGH`/`MEDIUM`/`LOW` migrados fornecendo a prova, sem trocar a expectativa
- [ ] Regressão S9 histórica migra para `UNKNOWN` no subconjunto **sem jamais inventar prova**
- [ ] Testes do plano 9 escritos e **falhando** antes da primeira linha de implementação
- [ ] Limitação conhecida do S9 no contrato da CHANGE-RISK-001 atualizada para apontar este slice
