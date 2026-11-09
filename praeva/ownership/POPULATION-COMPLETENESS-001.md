# POPULATION-COMPLETENESS-001 — Contrato de Pré-Registração
## Composição da prova de completude populacional

> Status: **seção 5 fechada (opção B) antes de RED; plano de testes a completar.**
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

## 5. Decisão de policy — opção B, fechada antes de RED

**Decisão:** a prova deve cobrir todos os timestamps que sustentam as
afirmações universais que a regra pode utilizar, e as famílias de evidência
necessárias a essas afirmações. Não se exige automaticamente todo o
envelope adquirido se parte dele não sustenta nenhuma dessas afirmações.

### 5.1 O escopo não depende do resultado observado

O conjunto exigido vem de **requisitos declarativos, versionados da regra**
e da grade de avaliação dos resumos Verify, **não** de
`evidence_refs`, `risk_level`, `classification_basis`, máximos observados
ou da trajetória contingente de execução do Risk.

Nesta versão, o portão recebe um único `PROVEN_COMPLETE`, sem carimbo
de nível. Consequentemente a prova escalar deve cobrir a **união conservadora**
dos requisitos universais de todas as conclusões não-`CRITICAL` que ela
poderá destravar (`HIGH`, `MEDIUM`, `LOW`); não pode calcular uma
prova restrita a `HIGH` e reutilizar o mesmo valor para `LOW`.

Uma futura prova por nível/família exige emenda explícita do contrato do
portão, não é inferida aqui. É permitido apresentar diagnósticos por
família internamente, mas o resultado escalar exige a conjunção de
**todos** os requisitos declarados.

### 5.2 Grade universal e suporte histórico não são a mesma coisa

Para uma família `rate()` exigida universalmente, **todos os pontos de
avaliação esperados no domínio daquele resumo Verify** contam, inclusive
os pontos sem fato ou sem série. Nunca limitar a verificação a
`max_timestamp`, à presença de witnesses ou aos timestamps observados:
isso converteria perda de série em falsa completude.

A cada avaliação `T` exigida, a enumeração `O(T)` precisa ser resolvida,
a comparação com `V(T,família)` precisa cobrir todos os membros do alvo,
e os sumários relevantes precisam de `domain=COMPLETE` e fatos
atribuíveis/usáveis segundo `ATTRIBUTION-SUMMARY-PROOF-001`.
`OMISSION`, `FOREIGN`, `UNKNOWN` ou domínio incompleto impedem
`PROVEN_COMPLETE`. Não confundir `ENUMERATED` sozinho com completude.

A atribuição de cada fato `rate()` em `T` exige, separadamente, o
suporte histórico conservador `[T-W,T]`, como definido por
`ATTRIBUTION-FACT-INPUT-001`: nenhuma falha na continuidade de UID,
janela de suporte, boundary ou ownership pode ser mascarada por
`O(T)=V(T)`. O domínio da série é a grade de avaliações; o suporte
é histórico. A prova deve respeitar **ambos**, sem ampliar
automaticamente a exigência de *enumeração populacional* para
timestamps históricos não consumidos.

Para famílias auxiliares com `domain=NOT_APPLICABLE`, como o witness
pontual de `cpu_limit`, **não** inventar um quantificador universal:
aplicar sua exigência de witness/suporte somente onde a regra o
consome, conforme contrato do summary proof. Isso não autoriza
ignorar evidência indispensável nem transformar witness ausente em
usável.

### 5.3 Consequência operacional e caso distintivo

Na CHANGE-RISK-001 atual, as conclusões não-`CRITICAL` consomem
domínios universais de CPU e CFS ao longo das respectivas grades
Verify. **Uma lacuna dentro desses domínios não é descartável
pela opção B.** Uma lacuna fora de todo domínio e suporte
realmente exigidos não pode, por si só, bloquear a conclusão.

O caso 6 de testes deverá colocar a lacuna *realmente fora do
suporte de todas as afirmações universais e fatos necessários*.
Não basta dizer que é fora do `max_timestamp`: os demais pontos
da série continuam necessários para uma afirmação universal.

**Não é permitido escolher o conjunto exigido por inspeção do
resultado do Risk**, nem aceitar seletor, regex, `CALLER_ASSERTED`
ou o campo já preenchido `population_completeness` como prova.

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

## 8. Plano de teste — fechado após a decisão B

| # | Cenário | Esperado |
|---|---|---|
| 1 | `V(T) = O(T)` em toda a grade, domínios `COMPLETE` | `PROVEN_COMPLETE` |
| 2 | Pod do alvo nunca observado | `UNPROVEN(population_omission)`, nomeando o pod |
| 3 | Pod observado que o alvo não possui | `UNPROVEN(population_foreign_pod)` |
| 4 | Enumeração `UNKNOWN` em timestamp exigido | `UNPROVEN(population_enumeration_unknown)` |
| 5 | Membro de `O(T)` sem série de família exigida | `UNPROVEN(population_evidence_missing)` |
| 6 | Lacuna **fora** de todo domínio e suporte exigidos | `PROVEN_COMPLETE` — §5.3 |
| 7 | `universal_requirements` vazio | erro de input |
| 8 | `identity_assertion` ou `population_completeness` na entrada | nunca aceito como prova |
| 9 | Mesma entrada, duas execuções | saída idêntica |
| 10 | Captura real do rollout de 05/11 | procedimento de laboratório |

### 8.1 Regressões exigidas pela decisão

| # | Cenário | Esperado | Por quê |
|---|---|---|---|
| 11 | Lacuna em ponto **não-máximo** da série | `UNPROVEN(population_evidence_missing)` | §5.2: limitar a verificação ao `max_timestamp` converteria perda de série em falsa completude |
| 12 | Fato com suporte histórico `[T−W,T]` incompleto, `O(T) = V(T)` | `UNPROVEN(population_evidence_missing)` | §5.2: igualdade de conjuntos não mascara falha de suporte ou de continuidade de UID |
| 13 | Declaração só com os requisitos de `HIGH` | **erro de input** | §5.1: prova escalar exige a união de `HIGH`, `MEDIUM` e `LOW`; não se calcula prova restrita e se reutiliza |
| 14 | Declaração com rung desconhecido | erro de input | o escopo é declarativo e versionado, não extensível em runtime |
| 15 | `cpu_limit`, de domínio `NOT_APPLICABLE`, ausente da declaração | não exigido universalmente | §5.2: não inventar quantificador para família auxiliar |

Os casos 11, 12 e 13 são os que distinguem esta implementação de uma leitura frouxa da opção B.

---

## 9. Checklist do gate

- [x] Seção 5 decidida por Flavio — opção B, com união conservadora para o portão escalar
- [ ] Plano de teste completado conforme a decisão
- [ ] Nenhum seletor, regex ou declaração do chamador entre as entradas
- [ ] Ausência de evidência nunca produz `PROVEN_COMPLETE`
- [ ] Omissão e pod estrangeiro reportados distintamente
- [ ] Nenhuma alteração em Risk, Join, Verify, Analyze ou Attribution
- [ ] Testes escritos e **falhando** antes da primeira linha
