# POPULATION-COMPLETENESS-001 — Contrato de Pré-Registração
## Composição da prova de completude populacional

> Status: **pré-registração — aguarda uma decisão de policy (seção 5).**
> Base: `main @ d9114fb`. Destino: `praeva/ownership/completeness.py`
> Compõe POPULATION-ENUMERATION-001, ATTRIBUTION-FACT-INPUT-001 e
> ATTRIBUTION-SUMMARY-PROOF-001. Função pura, sem consulta e sem rede.
> **Não altera** Risk, Join, Verify, Analyze nem Attribution. Sem wiring.

---

## 1. Pergunta

> A população observada é comprovadamente a população completa do Deployment alvo, para os fins
> das afirmações universais que a regra precisa sustentar?

É o produtor do valor `PROVEN_COMPLETE` que o portão da CHANGE-RISK-001 lê e que hoje nunca existe.

---

## 2. Duas coisas precisam ser verdadeiras

Completude não é só "temos todos os pods". É "temos todos os pods **e** temos a evidência de cada
um". As duas falham de formas diferentes e já foram catalogadas como cenários distintos do
SPIKE-003:

| Falha | Cenário | Significado |
|---|---|---|
| Pod do alvo não observado | S5 | o seletor omitiu um membro |
| Pod observado sem a evidência consumida | S6 | o membro existe, a série dele não |

A ATTRIBUTION-DECISION-001 §6.3 já estabeleceu que as duas projetam na **mesma** consequência —
nenhuma afirmação universal é demonstrável. Este slice as verifica separadamente e reporta qual
ocorreu, porque os remédios são opostos: corrigir o seletor versus investigar telemetria ausente.

---

## 3. Entradas

```
enumeration        saída de POPULATION-ENUMERATION-001
fact_input         saída de ATTRIBUTION-FACT-INPUT-001 — dá V(T) por família
summary_proof      saída de ATTRIBUTION-SUMMARY-PROOF-001 — dá usabilidade por pod
required_families  as famílias de evidência que a regra consome
```

`required_families` é parâmetro porque é propriedade da regra, não desta camada. A
CHANGE-RISK-001 consome `cpu_short`, `cpu_long`, `cfs_throttled_short`, `cfs_throttled_long` e
`cpu_limit`; uma regra futura consumirá outro conjunto.

**Não são entradas:** seletor, regex, `identity_assertion`, declaração do chamador. Aceitar
qualquer um deles reintroduziria o `CALLER_ASSERTED` um nível mais fundo.

---

## 4. `V(T)` vem dos fatos pontuais, não do relatório

O relatório do Verify é por pod com sumários por janela; não diz quais pods tinham amostra em `T`.
Os fatos pontuais do ATTRIBUTION-FACT-INPUT-001 dizem: `1 evaluation point = 1 attribution fact`.

Logo `V(T, família)` = conjunto de pods com fato daquela família naquele timestamp.

A comparação com `O(T)` é feita por nome, pela limitação já registrada na POPULATION-ENUMERATION-001
§5.1: as séries do cAdvisor não carregam UID.

---

## 5. Decisão de policy pendente — sobre quais timestamps a completude é exigida

Esta é a única questão em aberto, e é critério de admissibilidade: define o que conta como prova.
**Não implemento antes da sua decisão.**

| Opção | Exigência | Consequência |
|---|---|---|
| **A — grade inteira** | `COMPLETE` em todos os timestamps da aquisição | mais simples de explicar; um único buraco em qualquer canto da janela bloqueia tudo |
| **B — suporte das afirmações universais** | `COMPLETE` nos timestamps que sustentam os sumários universais que a regra consome | mais preciso; exige que esta camada saiba quais sumários são universais, informação que o `summary_proof` já computa |
| **C — por família** | completude avaliada e reportada por família de evidência | mais informativo; a regra passaria a receber um mapa, não um valor, o que muda o contrato do portão |

**Minha recomendação é B**, pelo mesmo raciocínio que já usamos duas vezes: a prova deve cobrir o
suporte do fato, não um envelope arbitrário maior. Exigir a grade inteira faria uma lacuna em
evidência que nenhuma conclusão usa bloquear uma conclusão legítima — é o oposto de "porta, não
peso".

Contra B: ela acopla a prova de completude ao caminho de decisão da regra, e foi exatamente a
objeção que levantei em 19/10 sobre `evidence_refs` deixar de ser trilha de auditoria para virar
entrada de cálculo. A diferença é que agora o `summary_proof` já faz essa distinção
explicitamente, então o acoplamento é a um contrato existente, não a uma inferência nova.

C muda o contrato do portão, que hoje lê um valor único. Se for o caminho, o
CHANGE-RISK-001-POPULATION-GATE-001 precisa de emenda antes.

---

## 6. Saída

```
completeness_id        POPULATION-COMPLETENESS-001
status                 PROVEN_COMPLETE | UNPROVEN
reason                 nomeado, quando UNPROVEN
evaluated_timestamps   os timestamps sobre os quais a prova foi avaliada
findings               por timestamp, apenas onde houve falha:
                         missing_pods, foreign_pods, pods_without_evidence
```

Códigos de `reason`, nenhum novo além do necessário:

| Código | Quando |
|---|---|
| `population_omission` | `O(T) ⊋ V(T)` em algum timestamp avaliado |
| `population_foreign_pod` | `V(T) ⊋ O(T)` em algum timestamp avaliado |
| `population_enumeration_unknown` | a enumeração não resolveu em algum timestamp avaliado |
| `population_evidence_missing` | membro de `O(T)` sem evidência usável para uma família exigida |

`PROVEN_COMPLETE` exige **nenhuma** dessas condições. Fail-closed: entrada ausente, malformada ou
indecidível produz `UNPROVEN`, nunca prova.

---

## 7. O que este slice NÃO faz

- Não escreve em `identity_assertion.population_completeness` — isso é wiring, próximo slice.
- Não decide consequência para a escada de risco; o portão já decide.
- Não enumera: consome a enumeração pronta.
- Não aceita nenhuma declaração do chamador como evidência.

---

## 8. Plano de teste — a escrever após a decisão da seção 5

Esboço, a completar quando a policy estiver fechada:

| # | Cenário | Esperado |
|---|---|---|
| 1 | `V(T) = O(T)` em todos os avaliados, evidência completa | `PROVEN_COMPLETE` |
| 2 | Um pod do alvo não observado | `UNPROVEN(population_omission)`, nomeando o pod |
| 3 | Um pod observado que o alvo não possui | `UNPROVEN(population_foreign_pod)` |
| 4 | Enumeração `UNKNOWN` em um timestamp avaliado | `UNPROVEN(population_enumeration_unknown)` |
| 5 | Membro de `O(T)` sem série de uma família exigida | `UNPROVEN(population_evidence_missing)` |
| 6 | Lacuna em timestamp **não** avaliado (só sob B) | `PROVEN_COMPLETE` — prova cobre o suporte, não o envelope |
| 7 | `required_families` vazio | erro de input — uma prova sobre nada não é prova |
| 8 | Entrada com `identity_assertion` | ignorada ou erro; nunca aceita como evidência |
| 9 | Mesma entrada, duas execuções | saída idêntica |
| 10 | Captura real do rollout de 05/11 | a definir conforme a policy escolhida |

O caso 6 só existe sob a opção B e é o que a distingue de A na prática.

---

## 9. Checklist do gate

- [ ] Seção 5 decidida por Flavio
- [ ] Plano de teste completado conforme a decisão
- [ ] Nenhum seletor, regex ou declaração do chamador entre as entradas
- [ ] Ausência de evidência nunca produz `PROVEN_COMPLETE`
- [ ] Omissão e pod estrangeiro reportados distintamente
- [ ] Nenhuma alteração em Risk, Join, Verify, Analyze ou Attribution
- [ ] Testes escritos e **falhando** antes da primeira linha
