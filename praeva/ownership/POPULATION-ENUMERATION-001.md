# POPULATION-ENUMERATION-001 — Contrato de Pré-Registração
## Enumeração da população do workload a partir de telemetria histórica

> Status: **pré-registração — congelada antes de RED.**
> Base: `main @ b304dfc`. Destino: `praeva/ownership/population.py`
> Herda ADR-001 a ADR-008, WORKLOAD-OWNERSHIP-001 e ATTRIBUTION-DECISION-001/002.
> **Não altera** Risk, Join, Verify, Analyze nem Attribution.

---

## 1. Pergunta

> Em cada timestamp da grade, quais Pods o Deployment alvo possuía — enumerados a partir da
> telemetria histórica, sem seletor fornecido pelo chamador?

Esta é a metade que faltava. O `WORKLOAD-OWNERSHIP-001` responde "este Pod pertencia ao alvo?",
uma pergunta sobre um Pod que alguém já escolheu. Nenhuma quantidade de respostas dessas prova que
**não falta nenhum Pod** — foi o contraexemplo A da revisão de 20/10, e é o que o portão de
população da CHANGE-RISK-001 espera.

Enumerar exige percorrer a relação na direção oposta: do Deployment para os Pods.

---

## 2. Nenhuma consulta nova

O adapter do ownership já adquire, por `query_range`:

```
max by (namespace, pod, uid, owner_kind, owner_name, owner_is_controller) (
  kube_pod_owner{namespace="<ns>",owner_is_controller="true"}
)
max by (namespace, replicaset, owner_kind, owner_name, owner_is_controller) (
  kube_replicaset_owner{namespace="<ns>",owner_is_controller="true"}
)
```

As duas são **por namespace inteiro**, não filtradas por seletor. Logo a enumeração é **função pura
sobre evidência já adquirida**: sem consulta nova, sem rede, testável offline contra as capturas
existentes — inclusive a do rollout real de 05/11.

Isto também é a razão de a enumeração ser confiável: ela não pode ser estreitada por um regex
errado, porque não vê regex nenhum.

---

## 3. Enumeração, por timestamp

Para o Deployment alvo `D` no namespace `N`, em cada timestamp `T` da grade:

```
RS(T) = { rs : kube_replicaset_owner@T tem owner_kind=Deployment e owner_name=D }
O(T)  = { (pod, uid) : kube_pod_owner@T tem owner_kind=ReplicaSet e owner_name ∈ RS(T) }
```

Salto transitivo obrigatório: no Kubernetes um Pod de Deployment é sempre possuído por um
ReplicaSet, nunca pelo Deployment diretamente. Pods sob outro controller — Job, StatefulSet,
DaemonSet — ou sem controller simplesmente não entram em `O(T)`.

### 3.1 Identidades

| Entidade | Chave |
|---|---|
| Pod | `namespace` + `pod` + `uid` |
| ReplicaSet | `namespace` + `replicaset` |

O ReplicaSet não tem UID nesta série (WORKLOAD-OWNERSHIP-001) e o Praeva não inventa um. Dois
ReplicaSets homônimos no mesmo namespace não coexistem no mesmo instante, então nome + namespace é
chave segura **em um dado `T`** — e só em um dado `T`.

---

## 4. Conjunto vazio não é lacuna

A distinção central deste slice.

| Situação em `T` | Resultado |
|---|---|
| Amostras das duas séries presentes; nenhum ReplicaSet aponta para `D` | `ENUMERATED`, `O(T) = ∅` — o Deployment tinha zero Pods |
| Amostras das duas séries presentes; `RS(T)` ≠ ∅ e Pods resolvidos | `ENUMERATED`, `O(T)` com os membros |
| `kube_replicaset_owner` **sem nenhuma amostra** em `T` | `UNKNOWN(replicaset_series_absent_at_timestamp)` |
| `kube_pod_owner` **sem nenhuma amostra** em `T` | `UNKNOWN(pod_series_absent_at_timestamp)` |
| `T` fora do intervalo adquirido | `UNKNOWN(timestamp_outside_acquisition)` |

Um Deployment escalado a zero é um fato legítimo e enumerável. Uma lacuna do KSM é desconhecimento.
Colapsar os dois produziria o pior resultado possível: **`O(T) = ∅` por lacuna tornaria qualquer
conjunto observado "completo" por vacuidade**, fabricando exatamente a prova que o portão exige.

A diferença é observável: ausência de amostra para a consulta inteira — que cobre o namespace — é
lacuna; presença de amostras sem nenhuma casando com `D` é zero.

### 4.1 Ambiguidades

| Situação | Resultado |
|---|---|
| Mesmo nome de Pod com dois UIDs distintos em `T` | `UNKNOWN(pod_identity_ambiguous_at_timestamp)` |
| Pod com mais de um owner controller em `T` | `UNKNOWN(pod_controller_owner_ambiguous)` |
| ReplicaSet com mais de um owner controller em `T` | `UNKNOWN(replicaset_controller_owner_ambiguous)` |
| Amostra com valor não finito ou inválido | `UNKNOWN(owner_metric_invalid)` |

Vocabulário herdado do WORKLOAD-OWNERSHIP-001, sem códigos novos além dos três de ausência da
seção 4.

---

## 5. Comparação com o conjunto observado

A enumeração é uma coisa; comparar com o que o Verify observou é outra, e as duas moram neste slice
porque só juntas respondem algo útil.

Para um conjunto observado `V(T)`:

| Relação | Veredito | Natureza |
|---|---|---|
| `V(T) = O(T)` | `COMPLETE` | o observado é exatamente a população |
| `V(T) ⊊ O(T)` | `OMISSION` | faltam Pods do alvo — lista os ausentes |
| `V(T) ⊋ O(T)` | `FOREIGN` | há Pods observados que o alvo não possui — lista os estranhos |
| nem um nem outro | `OMISSION_AND_FOREIGN` | ambos, ambas as listas |
| `O(T)` é `UNKNOWN` | `UNKNOWN(<razão da enumeração>)` | não se compara contra desconhecido |

`OMISSION` e `FOREIGN` projetam em lugares diferentes (ATTRIBUTION-DECISION-001 §6): omissão
restringe degraus, Pod estrangeiro é fato não atribuído. Este slice os mantém separados e **não**
decide consequência — projeção é da camada de decisão.

### 5.1 Comparação por UID, não por nome

`V(T)` vem do Verify, cujas séries do cAdvisor **não têm UID** (contraexemplo B de 20/10). A
comparação é feita por `(namespace, pod)`, e o UID enumerado viaja no resultado como contexto para
quem precisar de continuidade de identidade.

Isso é registrado como limitação, não contornado: comparar por nome não distingue dois Pods
homônimos sequenciais, e o caso simultâneo já é `pod_identity_ambiguous_at_timestamp`.

---

## 6. O que este slice NÃO faz

- **Não produz `PROVEN_COMPLETE`.** Esse valor é composto depois, e exige mais do que enumeração:
  exige também que cada membro de `O(T)` tenha a evidência que a regra vai consumir (S6). Compor é
  trabalho do próximo slice.
- Não decide em quais timestamps a completude é exigida — isso é quantificador, e pertence à regra.
- Não toca Risk, Join, Verify, Analyze nem Attribution.
- Não aceita seletor, regex, `CALLER_ASSERTED` ou qualquer declaração do chamador como entrada da
  enumeração. O único parâmetro de alvo é a identidade do Deployment.

---

## 7. Saída

```
population_id          POPULATION-ENUMERATION-001
target                 (namespace, group, kind, name)
acquisition            intervalo e grade herdados da evidência de ownership

timestamps:
  <T>:
    status             ENUMERATED | UNKNOWN
    reason             código nomeado, quando UNKNOWN
    replicasets        nomes em RS(T), ordenados
    owned_pods         [{pod, uid}], ordenados por nome
    comparison         presente apenas quando um conjunto observado é fornecido
      verdict          COMPLETE | OMISSION | FOREIGN | OMISSION_AND_FOREIGN
      missing          Pods em O(T) ausentes de V(T)
      foreign          Pods em V(T) ausentes de O(T)
```

Determinístico: conjuntos ordenados, sem dependência de ordem de iteração.

---

## 8. Plano de teste — RED antes de GREEN

| # | Cenário | Esperado |
|---|---|---|
| 1 | Um RS do alvo, três Pods | `ENUMERATED`, três membros, ordenados |
| 2 | Dois RS do alvo (rollout), Pods de ambos | `ENUMERATED`, união dos dois |
| 3 | RS de outro Deployment no mesmo namespace | seus Pods **fora** de `O(T)` |
| 4 | Pod sob Job ou StatefulSet | fora de `O(T)` |
| 5 | Séries presentes, nenhum RS do alvo | `ENUMERATED` com `O(T) = ∅` |
| 6 | `kube_replicaset_owner` sem amostra em `T` | `UNKNOWN(replicaset_series_absent_at_timestamp)` — **não** `∅` |
| 7 | `kube_pod_owner` sem amostra em `T` | `UNKNOWN(pod_series_absent_at_timestamp)` — **não** `∅` |
| 8 | `T` fora da aquisição | `UNKNOWN(timestamp_outside_acquisition)` |
| 9 | Mesmo nome de Pod, dois UIDs em `T` | `UNKNOWN(pod_identity_ambiguous_at_timestamp)` |
| 10 | Pod com dois owners controller | `UNKNOWN(pod_controller_owner_ambiguous)` |
| 11 | RS com dois owners controller | `UNKNOWN(replicaset_controller_owner_ambiguous)` |
| 12 | `V(T) = O(T)` | `COMPLETE`, listas vazias |
| 13 | `V(T) ⊊ O(T)` | `OMISSION`, `missing` nomeando os ausentes |
| 14 | `V(T) ⊋ O(T)` | `FOREIGN`, `foreign` nomeando os estranhos |
| 15 | Ambos | `OMISSION_AND_FOREIGN`, as duas listas |
| 16 | Enumeração `UNKNOWN` com `V(T)` fornecido | comparação **ausente**; não se compara contra desconhecido |
| 17 | Mesma entrada, duas execuções | saída idêntica |
| 18 | Captura real do rollout de 05/11 | sobreposição antigo+novo enumerada; nenhum `∅` por lacuna |

Os casos 5, 6 e 7 são o trio que define o slice: zero é fato, lacuna é desconhecimento, e nenhum
dos dois vira o outro. O 18 valida contra telemetria real já capturada.

---

## 9. Checklist do gate

- [ ] Pré-registração commitada, sozinha
- [ ] Nenhuma consulta nova ao Prometheus
- [ ] Nenhum regex, seletor ou declaração do chamador na enumeração
- [ ] Conjunto vazio nunca produzido por ausência de amostra
- [ ] `OMISSION` e `FOREIGN` mantidos distintos, sem decidir consequência
- [ ] Nenhuma alteração em Risk, Join, Verify, Analyze ou Attribution
- [ ] Testes do plano 8 escritos e **falhando** antes da primeira linha
