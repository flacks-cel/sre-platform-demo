# CHANGE-JOIN-001 — Proposed declared CPU limit × historical observed CPU facts

> Status: **GREEN local + CI; aguardando revisão final do PR #15.**
> Base: `main @ 6933846`.
> Pré-requisito já cumprido: `VERIFY-WIRE-001` mergeado no PR #14.
> Gate RED confirmado antes da implementação: `17 failed, 104 passed`, Ruff verde.
> GREEN confirmado: `121 passed` localmente no Windows e no CI #51; Ruff verde; Docker build/push verde.

## 1. Pergunta

> Dado o output do `CHANGE-INPUT-001` e um report do Verify com wire exato/provenance, quais fatos cruzados podem ser afirmados deterministicamente sobre o CPU limit proposto versus a CPU histórica observada, sem classificar risco?

Este slice produz fatos. Ele não decide LOW/MEDIUM/HIGH/CRITICAL, não recomenda limit e não escolhe policy de janela ou freshness.

## 2. Fronteira de domínios

A relação continua explicitamente assim:

```text
proposed-declared
      ×
effective-observed historical evidence
```

O limit proposto ainda não passou por admission. O Verify descreve evidência histórica do estado efetivo observado. O join não colapsa esses domínios.

## 3. Identidade: primeira versão é CALLER_ASSERTED

Hoje o Verify seleciona pods por `namespace + pod regex + container`, mas não prova a cadeia:

```text
Pod -> ReplicaSet -> Deployment
```

`kube_pod_owner` sozinho não fecha o último salto; `kube_replicaset_owner` fica para slice posterior.

Por isso `CHANGE-JOIN-001` exige uma precondição explícita do chamador:

```python
identity_assertion="CALLER_ASSERTED"
```

Não existe default.

O output registra:

- `status = CALLER_ASSERTED`;
- identidade do workload do Change Input;
- scope de aquisição do Verify;
- namespace e container que foram comparados literalmente;
- relação `Deployment -> pod selector` como **não verificada**.

A assertion não pode sobrescrever contradição visível. Se namespace ou container diferirem entre Change Input e Verify, o join falha como input inválido.

O primeiro slice aceita somente `container.space == "containers"`. `initContainers` e `ephemeralContainers` exigem contrato posterior.

## 4. Interface pura

A implementação vive em `praeva.change.join` e expõe:

```python
join_change_evidence(
    *,
    change: dict,
    verify_report: dict,
    identity_assertion: str,
) -> dict
```

A função:

- não lê manifestos;
- não consulta Prometheus;
- não consulta Kubernetes;
- não escolhe threshold;
- não escolhe janela;
- não classifica risco.

Input estrutural inconsistente levanta `ChangeJoinInputError`; não vira `UNKNOWN` semântico.

## 5. Provenance exigida

O join exige do Verify:

- `acquisition.namespace`;
- `acquisition.pod_selector`;
- `acquisition.container`;
- `acquisition.start/end/step`;
- `queries.cpu_short` e `queries.cpu_long`;
- `windows.short` e `windows.long`;
- `pods` per-pod.

A janela declarada em `queries.*.rate_window` deve coincidir com `windows.short/long`. Inconsistência é erro de input.

O join preserva no output o interval e o mapa de queries. Não inventa idade máxima, freshness cutoff ou vínculo com versão da aplicação.

O output declara explicitamente:

```text
application_version_relation = UNVERIFIED
```

Isso é uma limitação de provenance, não `UNKNOWN` de risco.

## 6. O join não usa um selector agregado para decidir o pod

`max_cpu_usage_pod` do Verify é short-window. O join precisa preservar short e long sem escolher uma delas como policy.

Portanto este slice consome os summaries per-pod:

```text
pods[pod].cpu_usage.short
pods[pod].cpu_usage.long
```

Ele produz fatos cruzados **por pod e por janela**. Não cria:

- `worst_pod`;
- workload-wide CPU sum;
- um único pod representativo;
- um único valor para short + long.

Uma futura regra de risco poderá declarar como quantifica pods/janelas.

## 7. Unidade e representação exata

`CHANGE-INPUT-001` publica CPU limits declarados em milicores inteiros.

O Verify publica CPU observada em cores como string decimal exata.

O join converte CPU observada para milicores por multiplicação decimal exata:

```text
0.1491 cores -> 149.1 millicores
```

Toda grandeza calculada pelo join em milicores é serializada como **string decimal canônica**.

Não há `float` no output do join.

Exemplo:

```json
{
  "proposed_declared_cpu_limit_millicores": "100",
  "observed_cpu_millicores": "149.1",
  "delta_millicores": "-49.1"
}
```

`delta_millicores` significa sempre:

```text
proposed_declared_limit - observed_cpu
```

## 8. Nenhuma razão proposed / observed

O join não emite razão decimal.

Uma regra futura que precise comparar, por exemplo:

```text
proposed > observed * theta
```

pode fazê-lo exatamente com `Decimal`, sem publicar divisão arredondada.

O `change_ratio` exato já produzido pelo Change Input continua sendo apenas o ratio `proposed/current declared`; ele não é reinterpretado como proposed/observed.

## 9. Fato por pod e por janela

Para cada pod do Verify, o output contém `windows.short` e `windows.long`.

### 9.1 CPU observada válida

Quando o summary dependente é `VALID`:

```json
{
  "observed_cpu": {
    "status": "VALID",
    "value_millicores": "149.1",
    "timestamp": "1792001149",
    "query_key": "cpu_short",
    "rate_window": "2m"
  }
}
```

### 9.2 CPU observada UNKNOWN

Quando o summary dependente é `UNKNOWN`, somente o fato dessa janela permanece `UNKNOWN`, preservando `reason_code/reason` quando disponíveis.

`verify_report.status == UNKNOWN` não contamina automaticamente uma janela válida.

### 9.3 Comparação com proposed limit

A comparação é representada separadamente da evidence quality.

Se CPU observada e proposed limit numérico estão disponíveis:

```text
comparison.status = VALID
```

com delta exato.

Se `proposed_declared_cpu_limit == ABSENT`:

```text
comparison.status = UNDEFINED
reason_code = proposed_limit_absent
```

Isso **não** vira `UNKNOWN`, porque ausência no manifesto é fato declarado completo.

Se proposed limit é numérico mas a CPU dependente é `UNKNOWN`:

```text
comparison.status = UNKNOWN
```

com a razão herdada da evidência dependente.

Zero declarado continua valor numérico e permite delta; este slice não atribui semântica operacional a zero.

## 10. Declared × effective limit: witness per-pod, não agregado

O Verify não publica a série inteira de limit no report final, mas para cada `cpu_limit_ratio=VALID` publica operandos exatos no timestamp do máximo ratio:

```text
numerator   = short-window CPU
denominator = historical effective-observed CPU limit
```

`CHANGE-JOIN-001` pode portanto expor um **effective-limit witness** por pod, deixando claro que é o denominator naquele timestamp e não uma prova de constância do limit durante todo o intervalo.

Estrutura conceitual:

```json
{
  "effective_limit_witness": {
    "status": "VALID",
    "value_millicores": "500",
    "timestamp": "1792001149",
    "query_key": "cpu_limit"
  },
  "current_declared_effective_relation": {
    "status": "VALID",
    "relation": "MATCH"
  }
}
```

Relações permitidas quando o witness é válido:

```text
MATCH
DIFFERS
DECLARED_ABSENT_EFFECTIVE_PRESENT
```

Se o witness efetivo não é computável, a relação fica `UNKNOWN` e carrega o motivo do `cpu_limit_ratio` per-pod.

Nunca existe um único `effective_limit` agregado para o Deployment. Pods diferentes permanecem visíveis separadamente, inclusive quando seus limits efetivos diferem.

O join não conclui que `DIFFERS` significa admission mutation; ele apenas expõe o fato compatível com investigação posterior.

## 11. Metadata por pod

O join preserva separadamente metadata já publicada pelo Verify:

- short-window `coverage` por contagem;
- `sample_count`;
- `restart_delta`;
- `node`;
- `owner` quando existente.

Como coverage/sample_count atuais derivam do short-window CPU no adapter, o join não os rotula como coverage da janela long.

## 12. Output mínimo

O output contém, no mínimo:

```text
join_id = CHANGE-JOIN-001
identity_assertion
change_facts
historical_context
queries
pods
```

`change_facts` preserva:

- current declared CPU limit;
- proposed declared CPU limit;
- direction;
- `change_ratio` sem reinterpretá-lo.

`historical_context` preserva:

- start/end/step;
- short/long windows;
- `application_version_relation = UNVERIFIED`.

`pods` é um mapa ordenável/determinístico por nome de pod.

## 13. Não objetivos

Este slice não implementa:

- ownership verificado `Pod -> ReplicaSet -> Deployment`;
- `kube_replicaset_owner`;
- LOW/MEDIUM/HIGH/CRITICAL;
- recommendation;
- target CPU limit;
- threshold de headroom;
- freshness threshold;
- escolha short versus long;
- um selector de risco;
- agregação de replicas;
- automatic Git/Kubernetes change;
- LLM/IA;
- memória.

## 14. Plano RED

Antes da implementação, testes congelaram pelo menos:

1. `CALLER_ASSERTED` é obrigatório e aparece explicitamente no output;
2. namespace divergente falha como input inválido;
3. container divergente falha como input inválido;
4. container space diferente de `containers` falha neste slice;
5. short e long são produzidos separadamente para o mesmo pod;
6. conversão cores -> milicores e delta são decimais exatos, inclusive com precisão invisível a binary float;
7. nenhum `float` aparece recursivamente no output;
8. proposed limit `ABSENT` produz comparison `UNDEFINED`, não `UNKNOWN`;
9. uma janela Verify `UNKNOWN` torna só a comparação dependente `UNKNOWN`; outra janela válida permanece válida;
10. top-level Verify `UNKNOWN` não contamina fatos per-dependency válidos;
11. dois pods podem produzir `MATCH` e `DIFFERS` simultaneamente sem redução a um valor agregado;
12. current declared `ABSENT` + effective witness válido produz `DECLARED_ABSENT_EFFECTIVE_PRESENT`;
13. effective witness ausente produz relation `UNKNOWN` sem apagar CPU válida;
14. interval, queries e `application_version_relation=UNVERIFIED` são preservados;
15. divergência dos selectors agregados do Verify não altera o join per-pod;
16. output não contém `risk`, `recommendation`, `target_cpu_limit` ou `worst_pod`.

## 15. Gate

- [x] VERIFY-WIRE-001 mergeado
- [x] identidade não verificada nomeada explicitamente
- [x] `CALLER_ASSERTED` escolhido para a primeira versão
- [x] namespace/container contraditórios não podem ser asseridos
- [x] unidade/representação exata congeladas
- [x] nenhuma razão proposed/observed
- [x] short/long permanecem paralelos
- [x] effective limit permanece per-pod
- [x] risk/evidence quality continuam separados
- [x] testes RED escritos
- [x] RED confirmado localmente: Ruff verde, `17 failed, 104 passed`
- [x] implementação iniciada somente depois do RED
- [x] GREEN local no Windows: Ruff verde, `121 passed`
- [x] CI #51: Ruff verde, Pytest verde, Docker build/push verde
