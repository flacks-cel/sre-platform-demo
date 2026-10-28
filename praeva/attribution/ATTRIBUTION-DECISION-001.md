# ATTRIBUTION-DECISION-001 — Contrato de Pré-Registração
## Projeção de diagnósticos de atribuição para superfície de decisão

> Status: **pré-registração fechada.**
> Gate: **nenhuma linha de implementação antes deste contrato commitado.**
> Branch: `praeva/attribution-decision-001`. Módulo futuro: `praeva/attribution/projection.py`.
> Base: SPIKE-003 encerrado (PR #22). Herda ADR-001 a ADR-008, RISK-VOCABULARY-001 e
> WORKLOAD-OWNERSHIP-001.
> **Sem wiring.** Não altera Analyze, Join, Verify nem Risk neste slice.

---

## 1. Pergunta

> Dados os diagnósticos de atribuição produzidos sobre a evidência histórica, quais fatos podem ser
> usados, quais níveis de risco ainda são demonstráveis, e a análise como um todo é admissível?

O SPIKE-003 produziu diagnósticos ricos de ownership, continuidade de identidade, suporte,
selector scope, evidência derivada e completude populacional. O consumidor precisa de uma superfície
menor. Este contrato é **o mapeamento entre as duas coisas** — e nada além disso.

### 1.1 Vocabulário

Diz-se **demonstrável**, nunca "provável". O Praeva não estima probabilidade. Um nível é demonstrável
quando a evidência adquirida satisfaz a forma lógica daquele degrau; caso contrário, não é
 demonstrável.

---

## 2. Três escopos, não um

| Escopo | Saída | Pergunta |
|---|---|---|
| **Análise** | `ADMISSIBLE` \| `INADMISSIBLE(reason)` | o domínio alvo é determinável? |
| **Fato** | `ATTRIBUTED` \| `UNATTRIBUTED(class)` | este fato pertence ao alvo? |
| **Escada** | subconjunto dos níveis declarados pela regra | quais degraus continuam demonstráveis? |

Um diagnóstico pode alimentar mais de um escopo, e diagnósticos diferentes podem produzir a mesma
consequência. O mapeamento não é bijetivo; por isso ele merece contrato próprio.

---

## 3. Atribuição, cobertura e censura são portas independentes

| Porta | Pergunta | Dona |
|---|---|---|
| **Atribuição** | este valor é do workload alvo? | esta camada |
| **Cobertura** | este valor está bem formado/utilizável como série? | Verify |
| **Censura** | este valor pode sustentar não-contradição? | regra de Risk |

Um fato pode ser atribuído e ter cobertura parcial. Pode ter cobertura completa e não ser atribuído.
Pode ser atribuído e bem formado, mas censurado por throttling.

Esta camada responde **apenas à atribuição**. Ela não altera, rebaixa, compensa nem reinterpreta
cobertura ou censura.

### 3.1 Ler metadados de cobertura não autoriza inferir suporte amostral

O wire atual do Verify publica cobertura como contagem de pontos de resultado da `query_range`
(`observed_points` versus `expected_points`). Esse campo **não prova** quais amostras cruas dentro de
um range vector foram usadas pelo Prometheus para calcular `rate(...[W])` em um timestamp T.

Portanto:

- `coverage_complete=true` não implica `observed_sample_support == nominal_support`;
- `coverage_complete=false` não define a extensão do suporte amostral;
- esta camada nunca promove contagem de pontos de resultado a prova de event-time/raw-sample support.

Cobertura continua propriedade do Verify e permanece inalterada na saída.

---

## 4. Suporte nominal e suporte amostral observado

O SPIKE-003/R2 mostrou que um rate pode continuar aparecendo depois que o Pod deixa de resolver como
membro atual da população em T. Ao mesmo tempo, o wire atual não expõe os timestamps das amostras
cruas realmente usadas pelo `rate()`.

São conceitos distintos:

| Conceito | Definição |
|---|---|
| **`nominal_support`** | envelope conservador declarado pelo fato; para `rate(...[W])` em T, `(T-W, T]` |
| **`observed_sample_support`** | faixa efetivamente usada pelas amostras, somente quando um produtor a prova explicitamente |

### 4.1 Regra de escolha do suporte

1. Se `observed_sample_support` vier explicitamente provado por uma camada produtora, a atribuição é
   avaliada sobre ele.
2. Se não vier, a atribuição usa conservadoramente `nominal_support`.
3. A extensão do suporte nunca é inferida de lookback, staleness ou de `coverage_complete`.

O envelope nominal é conservador: se o mesmo UID resolve `TARGET_MATCH` em todo o envelope, então
qualquer subconjunto de amostras realmente usado dentro dele pertence ao alvo. O inverso não vale.

### 4.2 Consequência para rate residual

Filiação a `O(T)` no instante T **não é condição necessária nem suficiente** para atribuição.
Entretanto, com o wire atual, um rate residual cujo `nominal_support` contém pontos de ownership não
resolvidos permanece:

```text
UNATTRIBUTED(attribution_unproven)
```

Isso não acontece porque o Pod está fora de `O(T)` em T. A razão é mais específica: falta prova de
que todo o suporte relevante utilizado pelo fato pertenceu ao alvo.

Um futuro producer que publique `observed_sample_support` explicitamente pode recuperar o mesmo fato
como `ATTRIBUTED` se esse suporte provado estiver inteiramente no domínio do alvo.

### 4.3 Critério de atribuição

Para o suporte escolhido pela §4.1, um fato é `ATTRIBUTED` se, e somente se, para todo ponto requerido
da grade de ownership dentro desse suporte:

1. o nome do Pod resolve para UID não ambíguo;
2. o UID é o mesmo em todos os pontos requeridos;
3. esse UID resolve `TARGET_MATCH` em todos os pontos requeridos;
4. `created(uid) <= support_start`;
5. nenhuma fronteira necessária de suporte fica sem observação quando a geometria exige prova naquela
   fronteira.

Falha de prova não vira atribuição por plausibilidade.

---

## 5. A forma lógica dos degraus é entrada, não conhecimento da camada

Para saber que um nível com componente universal cai quando a população é incompleta, a projeção
precisa conhecer a **forma lógica declarada**, não a semântica concreta de uma regra.

**Decisão:** a regra chamadora passa à projeção uma declaração genérica da forma lógica de cada
degrau. A projeção não importa, não referencia e não nomeia nenhuma regra.

Regra genérica:

> Um degrau com componente `forall` só é demonstrável quando o domínio da quantificação está completo.
> Degraus puramente existenciais podem sobreviver à incompletude.

Para CHANGE-RISK-001, a declaração conceitual que a regra passaria é:

| Degrau | Forma |
|---|---|
| `CRITICAL` | `exists` witness longo com contradição |
| `HIGH` | `exists` witness curto com contradição **and** `forall` longas sem contradição |
| `MEDIUM` / `LOW` | `forall` sem contradição na população relevante |

Com população incompleta, apenas níveis cuja prova não depende de universal sobre esse domínio
permanecem demonstráveis. Isso transforma o S9 em invariante genérico, sem codificar
`cpu_limit_insufficiency` nesta camada.

---

## 6. Mapeamento congelado

A coluna da esquerda é diagnóstico rico; a direita é a superfície de decisão que o consumidor pode
usar. O diagnóstico original continua disponível para auditoria e ação humana.

| Diagnóstico | Escopo | Projeção |
|---|---|---|
| Pod estrangeiro selecionado, `VALID/TARGET_DIFFERS` | Fato | `UNATTRIBUTED(foreign_workload)`, excluído dos witnesses |
| Domínio alvo declarado indeterminável | Análise | `INADMISSIBLE(target_domain_undeterminable)` |
| Ownership `UNKNOWN` em ponto requerido do suporte | Fato | `UNATTRIBUTED(attribution_unproven)` |
| Ambiguidade de identidade em ponto requerido | Fato | `UNATTRIBUTED(attribution_unproven)` |
| Troca de UID dentro do suporte | Fato | `UNATTRIBUTED(identity_discontinuity)` |
| `created(uid) > support_start` | Fato | `UNATTRIBUTED(support_predates_pod)` |
| Fronteira necessária fora da grade de ownership | Fato | `UNATTRIBUTED(support_boundary_unproven)` |
| Suporte relevante não provado pelo wire disponível | Fato | `UNATTRIBUTED(attribution_unproven)` |
| Omissão do selector, `O(T) - S_target(T)` | Escada | `population_evidence_incomplete` |
| Evidência derivada ausente, `S_target(T) - V_q(T)` | Escada | `population_evidence_incomplete` |

### 6.1 Pod estrangeiro é fato, não análise

Um Pod selecionado que resolve `TARGET_DIFFERS` não torna automaticamente o domínio alvo
indeterminável. Como a população alvo pode ser reconstruída pelo ownership independentemente do
regex, esse fato é excluído dos witnesses e reportado como `foreign_workload`.

Não há exclusão silenciosa: o diagnóstico original continua visível para mostrar que o selector
arrastou evidência de outro workload.

### 6.2 Fronteira fora da grade é fato, não análise

Uma janela não divisível pelo step não torna a pergunta inteira malformada. Ela deixa uma fronteira
de suporte sem prova na grade de ownership e degrada os fatos afetados com
`support_boundary_unproven`.

Uma futura aquisição explícita naquela fronteira pode eliminar essa degradação sem mudar a semântica
desta projeção.

### 6.3 S5 e S6 projetam no mesmo lugar

Selector omission e derived evidence missing têm causas e remédios diferentes, mas a mesma
consequência lógica: existe membro da população relevante sem evidência suficiente para sustentar
afirmações universais.

A regra não precisa conhecer a taxonomia diagnóstica para decidir. A distinção permanece disponível na
provenance para acionabilidade humana.

### 6.4 O que não entra nesta projeção

- `coverage_complete`, sample count e demais metadados de cobertura: Verify;
- `any_positive` e demais fatos de throttling/censura: regra de Risk;
- `application_version_relation`: continua `UNVERIFIED`; ownership prova workload, não revisão;
- falhas de transporte ou schema: erro de execução, fora desta superfície.

---

## 7. `INADMISSIBLE` é eixo próprio

`INADMISSIBLE` significa que o domínio alvo não pôde ser determinado. Não significa telemetria
insuficiente para um workload já conhecido.

Permanece eixo próprio com **exit code 0**. É um resultado semântico da análise, não erro sintático nem
falha de transporte. A renderização humana deve dizer "não foi possível determinar o workload alvo",
e não "evidência insuficiente".

---

## 8. Fechamento

| # | Item | Decisão |
|---|---|---|
| 1 | `INADMISSIBLE` | eixo próprio, exit 0 |
| 2 | Forma lógica dos degraus | argumento genérico passado à projeção; a camada não conhece regras |
| 3 | Granularidade do fato | `(pod, evidence_family, evaluated_at, support_descriptor)` |
| 4 | Módulo | `praeva/attribution/projection.py` |
| 5 | Suporte sem prova amostral explícita | usar `nominal_support` conservadoramente |
| 6 | `coverage_complete` | nunca prova raw-sample support |

### 8.1 Critério de `target_domain_undeterminable`

A projeção **não infere** `target_domain_undeterminable` a partir de:

- `O(T)` vazio;
- ausência de série em um fato;
- ownership `UNKNOWN` de Pods individuais;
- `TARGET_DIFFERS` de um Pod estrangeiro;
- população parcial em um timestamp.

Ela recebe um diagnóstico explícito de uma camada produtora com estado equivalente a:

```text
target_domain_status = DETERMINED | UNDETERMINABLE
```

Quando recebe `UNDETERMINABLE`, projeta:

```text
INADMISSIBLE(target_domain_undeterminable)
```

Quando recebe `DETERMINED`, a análise permanece `ADMISSIBLE`, ainda que a população determinada seja
vazia ou contenha fatos individualmente não atribuíveis.

**População vazia e domínio desconhecido são estados distintos.** Definir como a aquisição prova
`DETERMINED` versus `UNDETERMINABLE` pertence ao contrato da camada de reconstrução populacional, não
a este slice.

### 8.2 Granularidade do fato

`(pod, evidence_family, evaluated_at, support_descriptor)` evita supor que CPU, throttling e limit
efetivo compartilham atribuição só porque pertencem ao mesmo Pod ou à mesma janela.

Uma família pode ter suporte distinto ou prova de suporte diferente de outra. Atribuição de uma nunca
contamina automaticamente a outra.

---

## 9. Plano de teste — RED antes de GREEN

Os cenários do SPIKE-003 viram casos da projeção. O que se testa é o mapeamento, não a aquisição.

| # | Entrada | Esperado |
|---|---|---|
| 1 | R1 estável, nominal support inteiramente target-match | `ADMISSIBLE`, fatos `ATTRIBUTED`, escada completa |
| 2 | S2 young Pod | `UNATTRIBUTED(support_predates_pod)`; análise admissível |
| 3 | S3 UID change | `UNATTRIBUTED(identity_discontinuity)` mesmo com `TARGET_MATCH` por ponto |
| 4 | S4/S7 Pod estrangeiro | `UNATTRIBUTED(foreign_workload)`; excluído; análise admissível |
| 5 | S5 selector omission | admissível; níveis com universal sobre população ficam não demonstráveis |
| 6 | S6 derived evidence missing | mesma projeção de completude que o caso 5 |
| 7 | S9 população incompleta | níveis existenciais podem sobreviver; níveis dependentes de universal ficam bloqueados |
| 8 | S10 fronteira fora da grade | `UNATTRIBUTED(support_boundary_unproven)` no fato; análise admissível |
| 9 | R2 rate residual com wire atual e ownership não provado no nominal support | `UNATTRIBUTED(attribution_unproven)` |
| 10 | Mesmo residual, mas producer fornece `observed_sample_support` explícito e todo target-match | `ATTRIBUTED` |
| 11 | `coverage_complete=true` sem sample support explícito | não encurta nem redefine o suporte; regra da §4.1 permanece |
| 12 | Mesma janela, CPU e throttling com support descriptors diferentes | atribuições independentes por família |
| 13 | `target_domain_status=UNDETERMINABLE` | `INADMISSIBLE(target_domain_undeterminable)`, exit 0 |
| 14 | `target_domain_status=DETERMINED` com população vazia | `ADMISSIBLE`; não confundir vazio com desconhecido |

Os casos 9 e 10 travam a correção principal do R2: membership instantânea em T não decide, mas a
camada também não inventa suporte amostral para promover o fato.

Os casos 5, 6 e 7 travam a projeção por quantificador. O caso 11 impede que `coverage_complete` ganhe
semântica que o wire atual não publica. Os casos 13 e 14 separam domínio desconhecido de população
vazia.

---

## 10. Checklist do gate

- [x] Seção 8 resolvida
- [x] Pré-registração commitada antes de implementação
- [ ] Nenhuma referência a `cpu_limit_insufficiency`, ou a qualquer regra concreta, no código da projeção
- [ ] Nenhum vocabulário de diagnóstico do SPIKE-003 cruza para o consumidor além do mapeamento deste contrato
- [ ] Atribuição nunca altera cobertura nem censura
- [ ] `coverage_complete` nunca é usado como prova de raw-sample support
- [ ] Extensão de suporte nunca é inferida de lookback ou staleness
- [ ] Filiação a `O(T)` não aparece como critério de atribuição
- [ ] Testes do plano 9 escritos e **falhando** antes da primeira linha de `projection.py`
- [ ] Nenhuma alteração em Analyze, Join, Verify ou Risk neste slice
