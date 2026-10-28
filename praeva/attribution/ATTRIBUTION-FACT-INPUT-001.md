# ATTRIBUTION-FACT-INPUT-001 — Contrato de Pré-Registração
## Adapter de fatos pontuais para atribuição histórica

> Status: **pré-registração fechada antes da implementação.**
> Branch: `praeva/attribution-fact-input-001`.
> Base: `main` em `0cab03967ac81813e49c34a06b48ba2be1531566`.
> Depende de ATTRIBUTION-DECISION-001 + ATTRIBUTION-DECISION-002.
> **Sem wiring de produto:** este slice não altera Analyze, Join, Verify, Ownership nem Risk.

---

## 1. Pergunta

> Como transformar o wire normalizado pré-Verify em fatos pontuais honestamente atribuíveis, com suporte nominal e grade histórica de ownership suficientes para ATTRIBUTION-DECISION, sem atribuir semântica de população ou risco ao adapter?

O adapter produz somente:

```text
normalized evidence
      +
creation_by_pod_uid
      ↓
ATTRIBUTION-FACT-INPUT-001
      ↓
facts[] + ownership acquisition plan + required_timestamps_by_pod
```

Ele **não** chama WORKLOAD-OWNERSHIP-001 e **não** chama ATTRIBUTION-DECISION.

---

## 2. Por que o input é pré-Verify, não `build_report()`

`build_report()` resume séries:

- CPU short/long em `max` + `max_timestamp`;
- CFS throttling em `any_positive` + `max_rate` + `max_timestamp`.

Esses resumos não preservam todos os evaluation points usados pela prova.

Atribuir somente o timestamp do máximo seria insuficiente para provas negativas/universais. Exemplo:

```text
cpu_long max <= proposed
```

é usado por CHANGE-RISK-001 para provar ausência de contradição long em um Pod. Essa prova depende da série relevante estar utilizável como domínio, não apenas do ponto em que o máximo ocorreu.

Portanto este adapter consome o output de `collect_normalized_evidence(...)`, antes da redução de Verify, e emite **um fato por ponto observado**.

Depois, consumidores podem:

- usar o fato no `max_timestamp` como witness existencial;
- exigir todos os fatos relevantes atribuídos/completos para provas universais.

---

## 3. Famílias suportadas neste slice

O adapter emite fatos para:

```text
cpu_short
cpu_long
cfs_throttled_short
cfs_throttled_long
cpu_limit
```

Semântica de suporte:

| Família | Tipo | Suporte nominal |
|---|---|---|
| `cpu_short` | `rate()` | `(T-W_short, T]` |
| `cpu_long` | `rate()` | `(T-W_long, T]` |
| `cfs_throttled_short` | `rate()` | `(T-W_short, T]` |
| `cfs_throttled_long` | `rate()` | `(T-W_long, T]` |
| `cpu_limit` | gauge pontual | `{T}` |

`request_rate` e futuras famílias não são emitidas nesta versão.

`cpu_limit` é incluído como família auxiliar porque CHANGE-JOIN-001 usa o limite histórico no effective-limit witness. Este slice não define ainda como esse witness será gated no Join/Risk.

---

## 4. Granularidade normativa

Cada sample observado gera exatamente um fato:

```text
fact_id = <evidence_family>:<pod>:<evaluated_at>
```

Exemplo:

```text
cpu_long:jobs-api-abc:1000
```

Dois pontos da mesma série são dois fatos distintos.

Duas famílias com a mesma janela e timestamp continuam fatos distintos.

O adapter nunca converte:

```text
uma série -> um único fato-resumo
```

---

## 5. Input público

```python
build_attribution_fact_inputs(
    *,
    normalized_evidence: dict,
    creation_by_pod_uid: dict,
) -> dict
```

### 5.1 `normalized_evidence`

É o wire produzido por `praeva.verify.prometheus_adapter.collect_normalized_evidence`.

Campos necessários:

```text
pods
short_window
long_window
acquisition.namespace
acquisition.start
acquisition.end
acquisition.step
queries
```

Os pontos devem usar timestamps exatos; floats são proibidos.

### 5.2 `creation_by_pod_uid`

Shape:

```json
{
  "pod-a": {
    "uid-a": "100",
    "uid-b": "200"
  }
}
```

Regras:

- objeto obrigatório;
- Pod ausente equivale a mapa `{}` para os fatos daquele Pod;
- cada mapa por Pod pode conter zero, um ou vários UIDs;
- chaves Pod/UID devem ser strings não vazias;
- valores devem ser decimal exato em string ou inteiro;
- floats, NaN e infinitos são erro estrutural.

O adapter apenas copia esse mapa para os fatos do Pod. Ele não escolhe UID.

---

## 6. Duração suportada

Nesta versão, `short_window` e `long_window` devem usar uma duração simples inteira:

```text
<positive integer><unit>
```

Unidades suportadas:

```text
s | m | h | d | w
```

Conversão exata:

```text
s = 1
m = 60
h = 3600
d = 86400
w = 604800
```

Exemplos válidos:

```text
30s
2m
5m
1h
```

Durações compostas, fracionárias, `ms` e outras extensões Prometheus ficam fora deste slice e produzem erro estrutural em vez de aproximação.

---

## 7. Geometria da grade de ownership

Se:

```text
A = acquisition.start
E = acquisition.end
S = acquisition.step
Wmax = max(W_short, W_long)
```

então:

```text
extension_steps = ceil(Wmax / S)
ownership_start = A - extension_steps * S
ownership_end = E
ownership_step = S
```

Isso mantém a grade de ownership alinhada à grade Verify.

O output publica:

```json
{
  "ownership_acquisition": {
    "namespace": "app",
    "start": "...",
    "end": "...",
    "step": "..."
  }
}
```

O adapter não executa a aquisição.

---

## 8. Suporte de um fato rate

Para sample avaliado em `T` com janela `W`:

```text
nominal.start = T - W
nominal.end   = T
```

O envelope matemático de `rate()` permanece conceitualmente `(T-W, T]`; o descritor usa a fronteira `T-W` para uma prova conservadora de identidade.

`required_timestamps` são todos os pontos da grade de ownership dentro de:

```text
[T-W, T]
```

ordenados e sem duplicatas.

### 8.1 Boundary proof

```text
boundary_proven = true
```

somente quando `T-W` pertence exatamente à grade de ownership.

Caso contrário:

```text
boundary_proven = false
```

O adapter não arredonda a fronteira e não inventa prova adicional.

Isto preserva o finding S10.

### 8.2 Fato pontual `cpu_limit`

Para `cpu_limit` em `T`:

```text
nominal.start = T
nominal.end = T
required_timestamps = [T]
boundary_proven = true
```

`T` deve pertencer à grade de análise/ownership; caso contrário o input é estruturalmente inconsistente.

---

## 9. Sample timestamps

Todos os samples suportados devem estar na grade declarada:

```text
A + n*S
```

com:

```text
A <= T <= E
```

Sample:

- fora do intervalo;
- off-grid;
- duplicado na mesma família/Pod/timestamp;
- representado como float;

é erro estrutural.

O adapter não corrige, arredonda nem descarta silenciosamente esses casos.

---

## 10. Séries ausentes e gaps

O adapter emite fatos somente para pontos realmente presentes no normalized evidence.

Ele **não** cria:

```text
UNKNOWN fact
```

para timestamps ausentes.

Ausência de série/ponto pertence a uma camada posterior de population/derived-evidence completeness.

Portanto:

```text
missing point != UNATTRIBUTED fact
```

São diagnósticos de eixos diferentes.

---

## 11. Output mínimo

```json
{
  "fact_input_id": "ATTRIBUTION-FACT-INPUT-001",
  "ownership_acquisition": {
    "namespace": "app",
    "start": "700",
    "end": "1300",
    "step": "15"
  },
  "required_timestamps_by_pod": {
    "pod-a": ["700", "715", "...", "1000"]
  },
  "facts": [
    {
      "fact_id": "cpu_long:pod-a:1000",
      "pod": "pod-a",
      "evidence_family": "cpu_long",
      "evaluated_at": "1000",
      "support": {
        "nominal": {
          "start": "700",
          "end": "1000",
          "required_timestamps": ["700", "715", "...", "1000"],
          "boundary_proven": true
        },
        "observed_sample": null
      },
      "creation_by_uid": {
        "uid-a": "100"
      }
    }
  ]
}
```

`required_timestamps_by_pod[pod]` é a união determinística dos timestamps requeridos por todos os fatos emitidos para aquele Pod.

A ordem de `facts` é determinística por:

```text
pod, evidence_family, evaluated_at
```

---

## 12. Relação com ATTRIBUTION-DECISION

O output `facts` deve ser aceito diretamente por:

```python
project_attribution_decision(..., facts=output["facts"], ...)
```

sem tradução semântica adicional.

O `required_timestamps_by_pod` deve ser aceito diretamente por:

```python
build_ownership_report(..., required_timestamps_by_pod=...)
```

após a aquisição histórica correspondente.

Isto é uma compatibilidade estrutural; este slice não chama nenhuma das duas funções.

---

## 13. Plano de teste — RED antes do GREEN

| # | Cenário | Esperado |
|---|---|---|
| 1 | `5m`, step `15s`, rate em T alinhado | suporte T-300..T, 21 timestamps, boundary true |
| 2 | janela `125s`, step `15s` | boundary false; sem arredondamento |
| 3 | short e long no mesmo T | dois fatos independentes |
| 4 | três pontos CPU long | três fatos, não um summary |
| 5 | ponto CFS | fato próprio da família CFS |
| 6 | `cpu_limit` | suporte singleton `{T}` |
| 7 | Pod com dois UIDs em creation map | ambos copiados em cada fato do Pod |
| 8 | Pod sem creation map | `creation_by_uid={}` |
| 9 | sample off-grid | `AttributionFactInputError` |
| 10 | sample duplicado | `AttributionFactInputError` |
| 11 | timestamp float | `AttributionFactInputError` |
| 12 | duração não suportada | `AttributionFactInputError` |
| 13 | gap de série | nenhum fato sintético criado |
| 14 | união de required timestamps | determinística e sem duplicatas |
| 15 | `request_rate` presente | ignorado neste slice |
| 16 | output `facts` passa validação estrutural de ATTRIBUTION-DECISION-002 | compatível |

---

## 14. No-goals

Este slice não:

- coleta `kube_pod_created`;
- coleta ownership;
- reconstrói `O(T)`;
- calcula selector omissions;
- calcula derived evidence missing;
- produz `population_evidence`;
- infere `target_domain_status`;
- chama `project_attribution_decision`;
- substitui `CALLER_ASSERTED`;
- modifica CHANGE-JOIN-001;
- modifica CHANGE-RISK-001;
- altera Verify;
- prova application version;
- trata `coverage_complete` como raw-sample support.

---

## 15. Gate

- [x] input pré-Verify escolhido antes da implementação
- [x] granularidade pointwise congelada
- [x] famílias suportadas congeladas
- [x] geometria de suporte/ownership congelada
- [x] S10 preservado sem arredondamento
- [x] missing point separado de UNATTRIBUTED
- [x] criação por UID preservada sem escolha no adapter
- [ ] testes 1–16 commitados e falhando antes do GREEN
- [ ] implementação sem chamadas de rede
- [ ] output compatível com ATTRIBUTION-DECISION-002
- [ ] nenhuma alteração em Analyze/Join/Verify/Ownership/Risk
- [ ] suíte completa verde
