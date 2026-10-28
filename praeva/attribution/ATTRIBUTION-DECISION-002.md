# ATTRIBUTION-DECISION-002 — Emenda de input de criação por UID

> Status: **pré-registração fechada.**
> Branch: `praeva/attribution-decision-002`.
> Base: `main` em `20b82960166da3a1ea206f78707c1fd5fb64afbd`.
> Herda ATTRIBUTION-DECISION-001 e altera somente a forma da evidência de criação.
> **Sem wiring:** não altera Analyze, Join, Verify, Ownership nem Risk neste slice.

---

## 1. Problema descoberto no desenho do wiring

ATTRIBUTION-DECISION-001 exige hoje um único:

```text
creation_timestamp
```

por fato.

Esse shape funciona em fixtures em que a identidade do Pod já é conhecida, mas não é construtível sem
escolha arbitrária quando o próprio objetivo da projeção é decidir se houve continuidade de UID.

Exemplo realista S3:

```text
pod-a em T0 -> uid-a
pod-a em T1 -> uid-a
pod-a em T2 -> uid-b
```

Um adapter de produção conhece dois UIDs plausíveis antes de chamar a projeção. Exigir um único
`creation_timestamp` força o adapter a escolher o timestamp de `uid-a` ou `uid-b` antes que a projeção
classifique corretamente:

```text
UNATTRIBUTED(identity_discontinuity)
```

Isso desloca semântica para o adapter e pode fabricar provenance.

---

## 2. Decisão normativa

O campo escalar é substituído por evidência de criação indexada por UID:

```json
{
  "creation_by_uid": {
    "uid-a": "100",
    "uid-b": "200"
  }
}
```

`creation_by_uid`:

- é obrigatório como objeto;
- pode ser vazio;
- aceita zero, um ou vários UIDs;
- chaves devem ser strings não vazias;
- valores devem ser timestamps exatos em string decimal ou inteiro;
- floats, NaN e infinitos são erro estrutural.

`creation_timestamp` deixa de fazer parte da interface normativa.

Como não existe wiring de produção ainda, esta mudança pode ser breaking sem camada de compatibilidade.

---

## 3. Ordem de decisão congelada

Para cada fato, a projeção mantém a ordem conceitual:

1. escolher `observed_sample_support` quando explicitamente provado; senão `nominal_support`;
2. validar fronteira de suporte;
3. resolver ownership nos timestamps requeridos;
4. exigir `evidence_status=VALID` nos pontos requeridos;
5. coletar os UIDs observados;
6. se houver mais de um UID, retornar `UNATTRIBUTED(identity_discontinuity)`;
7. exigir `TARGET_MATCH` para o UID único;
8. somente então consultar `creation_by_uid[uid]`;
9. se não houver creation evidence para o UID único, retornar
   `UNATTRIBUTED(attribution_unproven)`;
10. se `created(uid) > support_start`, retornar `UNATTRIBUTED(support_predates_pod)`;
11. caso contrário, retornar `ATTRIBUTED`.

A consequência principal é:

> **creation evidence nunca precisa ser escolhida antes de a identidade ficar única.**

---

## 4. Missing creation evidence é semântico, não estrutural

Um objeto vazio é input estrutural válido:

```json
{"creation_by_uid": {}}
```

Se ownership prova um UID único, mas não existe timestamp para esse UID, a projeção não inventa valor e
não lança erro de schema. O resultado é:

```text
UNATTRIBUTED(attribution_unproven)
```

Isso permite que aquisição incompleta degrade a prova sem transformar o run em falha de execução.

Um valor presente porém malformado continua sendo erro estrutural.

---

## 5. UID discontinuity não depende de creation evidence

Para:

```text
uids requeridos = {uid-a, uid-b}
creation_by_uid = {}
```

ou:

```text
creation_by_uid = {uid-a: ..., uid-b: ...}
```

o resultado permanece:

```text
UNATTRIBUTED(identity_discontinuity)
```

A classificação não pode mudar apenas porque creation evidence está ausente para um dos UIDs.

---

## 6. Completude populacional efetiva

Nenhuma regra de ATTRIBUTION-DECISION-001 muda.

Em particular:

- `identity_discontinuity` continua degradando o domínio efetivo do fato;
- `attribution_unproven` por creation evidence ausente também degrada o domínio efetivo;
- `support_predates_pod` continua degradando o domínio efetivo;
- `foreign_workload` continua sendo a exceção que não degrada a população alvo.

---

## 7. Interface resultante do fato

Forma mínima atualizada:

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
  "creation_by_uid": {
    "uid-a": "-1000"
  }
}
```

A assinatura pública de `project_attribution_decision(...)` permanece a mesma; muda apenas o shape de
cada item em `facts`.

---

## 8. Plano de teste — RED antes do GREEN

| # | Cenário | Esperado |
|---|---|---|
| 1 | UID único + creation presente e anterior ao suporte | `ATTRIBUTED` |
| 2 | UID único + creation ausente | `UNATTRIBUTED(attribution_unproven)` |
| 3 | UID único + creation depois do support start | `UNATTRIBUTED(support_predates_pod)` |
| 4 | UID A→B + `creation_by_uid` vazio | `UNATTRIBUTED(identity_discontinuity)` |
| 5 | UID A→B + timestamps para ambos UIDs | mesmo `identity_discontinuity` |
| 6 | valor float em `creation_by_uid` | `AttributionDecisionInputError` |
| 7 | chave UID vazia | `AttributionDecisionInputError` |
| 8 | apenas campo legado `creation_timestamp` | `AttributionDecisionInputError` |

Os testes existentes de ATTRIBUTION-DECISION-001 devem ser migrados para o novo shape sem mudar suas
expectativas semânticas.

---

## 9. No-goals

Este slice não:

- adquire `kube_pod_created`;
- constrói population evidence;
- infere `target_domain_status`;
- cria support descriptors a partir de Verify;
- altera `WORKLOAD-OWNERSHIP-001`;
- substitui `CALLER_ASSERTED` no Join;
- altera Analyze ou Risk;
- prova application version.

Esses itens pertencem aos slices de wiring posteriores.

---

## 10. Gate

- [x] problema de construtibilidade documentado antes da implementação
- [x] shape `creation_by_uid` congelado
- [x] ordem de decisão congelada
- [x] missing creation evidence definido como semântico
- [ ] testes 1–8 commitados e falhando antes do GREEN
- [ ] testes existentes migrados sem mudar semântica
- [ ] suíte completa verde
- [ ] nenhuma alteração fora de `praeva/attribution` neste slice
