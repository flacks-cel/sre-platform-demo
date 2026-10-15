# CHANGE-INPUT-001 — Declared CPU change facts

> Status: **pré-registração v3 commitada; implementação bloqueada até RED.** Gate: nenhuma linha de implementação antes dos testes de contrato falharem. Base: `main @ 0c3a608`. Herda ADR-001 a ADR-008. Não depende do Verify nem do Prometheus. Após o gate: RED → GREEN.

## 1. Pergunta

> Dado um manifesto atual e um manifesto proposto, qual mudança **declarada** de CPU limit está sendo proposta para um workload/container específico?

Este slice é uma função pura dos dois manifestos renderizados e de uma identidade explícita de seleção. Não consulta cluster, Prometheus, Verify, admission controller, Helm ou ArgoCD. Todo o comportamento é testável sem lab.

## 2. Fora de escopo

Explicitamente **não** produz:

- risco;
- `LOW`, `MEDIUM`, `HIGH` ou `CRITICAL`;
- recomendação;
- novo valor de CPU;
- comparação com evidência observada;
- mudança em Git ou Kubernetes;
- LLM/IA.

Também ficam fora mudanças de `replicas`, HPA, memória, imagem, env e probes. Os manifestos podem conter essas mudanças; CHANGE-INPUT-001 as ignora e não afirma que sejam irrelevantes.

### 2.1 Onde este contrato para

Os fatos abaixo foram considerados e ficam fora deste slice:

| Fato | Por quê |
| --- | --- |
| `observed_cpu_evidence` | é output do Verify, não dos manifestos |
| `proposed_vs_observed` | é o join entre Change Input e Verify; pertence a um slice posterior |
| `declared_vs_effective` | exige contexto de admission/runtime; ADR-008 o mantém como domínio separado |

A futura camada de comparação consome **este** contrato e **o Verify**, sem refazer nenhum dos dois. Por ADR-008, esse join será entre `proposed-declared` e `effective-observed`, não entre dois valores de manifesto.

Um possível sinal futuro fica explicitamente parqueado: se `current_declared_cpu_limit` divergir do limit histórico efetivo observado para o mesmo workload/container mesmo sem mudança declarada, isso pode indicar mutação em admission. CHANGE-INPUT-001 não avalia esse sinal.

## 3. Entrada

### 3.1 Forma dos manifestos

A entrada são **manifestos renderizados** — YAML ou JSON contendo recursos Kubernetes concretos.

Chart Helm, overlay Kustomize ou outro template não renderizado não é entrada válida. A renderização é responsabilidade externa ao contrato. No lab, onde `jobs-api` vive em chart Helm reconciliado pelo ArgoCD, fixtures e chamadas reais usam o manifesto renderizado, não o chart cru.

Suportado:

- documento único;
- YAML multi-documento (`---`);
- objeto Kubernetes `List`.

A validação de “renderizado” é **estrutural**, não uma busca textual global. Conteúdo Kubernetes legítimo como `$(VAR_NAME)` em `command`/`args` é permitido e não pode ser rejeitado como template. Se o documento não puder ser parseado ou os campos estruturais necessários à seleção/resolução não forem concretos, a execução falha como erro de input e orienta que o manifesto seja renderizado antes.

### 3.2 Identidade do workload e seleção explícita

CHANGE-INPUT-001 exige seleção explícita na invocação:

```text
--api-group apps
--kind Deployment
--namespace app
--name jobs-api
--container jobs-api
```

A identidade é a tupla:

```text
(apiVersion.group, kind, namespace, name)
```

No primeiro slice, o único workload suportado é:

```text
api-group = apps
kind      = Deployment
```

A ampliação para outros kinds exige contrato próprio para seus caminhos de PodSpec; não há busca genérica por “workload parecido”.

Cada bundle — atual e proposto — deve resolver **exatamente um** recurso para a identidade explicitamente solicitada. Zero matches ou mais de um match em qualquer lado é erro de input.

Divergência de identidade entre atual e proposto é erro de input, nunca uma mudança de CPU reportável. Renomear um Deployment não é interpretado como alteração de limit.

`metadata.namespace` ausente no manifesto não implica `default`. O namespace explícito da invocação pode fornecer o contexto de identidade. Sem namespace explícito na invocação, a entrada é inválida.

### 3.3 Resolução do container

O container é **sempre explícito** na invocação. Não existe inferência nem mesmo quando o PodSpec contém um único container.

A invocação também declara o espaço de nomes de container; o padrão é `containers`.

| Situação | Resultado |
| --- | --- |
| Container nomeado existe no espaço escolhido nos dois manifestos | resolvido |
| Container nomeado falta no atual | erro de input nomeando `current` |
| Container nomeado falta no proposto | erro de input nomeando `proposed` |
| `--container` ausente | erro de input, mesmo com um único container |
| Nome existe apenas em `initContainers` mas espaço escolhido é `containers` | erro de input |
| Espaço explicitamente escolhido como `initContainers` e nome existe nos dois | resolvido |

`containers`, `initContainers` e `ephemeralContainers` são espaços distintos. Não há fallback silencioso entre eles.

## 4. Normalização de CPU

Quantidades declaradas de CPU são normalizadas para **milicores inteiros**, usando aritmética decimal/integer exata, nunca ponto flutuante binário.

| Entrada | Milicores |
| --- | ---: |
| `"500m"` | 500 |
| `"0.5"` | 500 |
| `"1"` | 1000 |
| `"1500m"` | 1500 |
| `"1e3"` | 1000000 |
| `"0"` ou `"0m"` | 0 |

Precisão mais fina que `1m`, incluindo valores como `"0.0005"` ou `"500u"`, é erro de input. Não há arredondamento silencioso.

Valor negativo, sufixo desconhecido, infinito, NaN ou conteúdo não numérico é erro de input.

Zero declarado é preservado como **fato declarado numérico**. Este contrato não afirma o que um limit zero significa depois de admission/runtime. Para `change_ratio`, zero em qualquer extremo torna a razão `UNDEFINED` conforme 6.1.

## 5. Semântica de ausência declarada

ADR-008 separa estado declarado, estado efetivo admitido e estado histórico observado.

No manifesto, ausência de campo é um fato completo sobre o **estado declarado**: o campo não foi declarado. Ela **não** significa que o Pod efetivo ficará sem limit/request, porque admission pode aplicar defaults ou mutações.

| Situação | Valor CHANGE-INPUT-001 | Natureza |
| --- | --- | --- |
| `resources.limits.cpu` presente | milicores | fato declarado |
| `resources`/`limits`/`cpu` ausente | `ABSENT` | fato declarado |
| `resources.requests.cpu` presente | milicores | fato declarado |
| `resources`/`requests`/`cpu` ausente | `ABSENT` | fato declarado |
| parse/seleção/container inválidos | — | erro de input |

Não existe `UNKNOWN` neste slice. `UNKNOWN` pertence à evidência observada quando a informação necessária não está disponível. Aqui, ou o manifesto declara/omite um campo de forma válida, ou a entrada falha.

CHANGE-INPUT-001 também não calcula defaults implícitos do Kubernetes ou de LimitRange. `ABSENT` significa apenas “não declarado neste manifesto”.

## 6. Fatos produzidos

```text
workload_identity
  group
  kind
  namespace
  name

container
  name
  space                containers | initContainers | ephemeralContainers

current_declared_cpu_limit     milicores | ABSENT
proposed_declared_cpu_limit    milicores | ABSENT
direction                      DECREASE | INCREASE | UNCHANGED | LIMIT_ADDED | LIMIT_REMOVED
change_ratio                   {numerator: int, denominator: int} | UNDEFINED

current_declared_cpu_request   milicores | ABSENT
proposed_declared_cpu_request  milicores | ABSENT
```

Os requests são fatos auxiliares capturados no mesmo passe de parsing, mas **não participam da decisão de limit deste slice**.

### 6.1 Semântica de `direction` e `change_ratio`

Quando ambos os limits são valores declarados **estritamente positivos**, `change_ratio` representa exatamente:

```text
proposed_declared_cpu_limit / current_declared_cpu_limit
```

A representação é uma fração racional estruturada em forma reduzida:

```json
{"numerator": 1, "denominator": 3}
```

O denominador é sempre positivo e numerador/denominador são reduzidos pelo MDC. Não existe representação decimal aproximada no contrato.

| Current declarado | Proposed declarado | `direction` | `change_ratio` |
| --- | --- | --- | --- |
| 500m | 250m | `DECREASE` | `{numerator: 1, denominator: 2}` |
| 250m | 500m | `INCREASE` | `{numerator: 2, denominator: 1}` |
| 300m | 100m | `DECREASE` | `{numerator: 1, denominator: 3}` |
| 500m | 500m | `UNCHANGED` | `{numerator: 1, denominator: 1}` |
| `ABSENT` | 500m | `LIMIT_ADDED` | `UNDEFINED` |
| 500m | `ABSENT` | `LIMIT_REMOVED` | `UNDEFINED` |
| `ABSENT` | `ABSENT` | `UNCHANGED` | `UNDEFINED` |
| 0m | 500m | `INCREASE` | `UNDEFINED` |
| 500m | 0m | `DECREASE` | `UNDEFINED` |
| 0m | 0m | `UNCHANGED` | `UNDEFINED` |

`change_ratio` é `UNDEFINED` sempre que qualquer extremo é `ABSENT` **ou zero**. Ele nunca usa infinito, zero, `-1`, `NaN` ou outra sentinela numérica.

A orientação `proposed/current` é parte do contrato. Os testes RED incluem o par recíproco 500m → 250m e 250m → 500m justamente para impedir inversão silenciosa.

O campo é deliberadamente heterogêneo: **objeto racional ou a string `"UNDEFINED"`**. A alternativa `{defined: false}` foi rejeitada para não introduzir um segundo vocabulário de ausência num slice que já usa `ABSENT` para campo não declarado e `UNDEFINED` para operação matematicamente não definida.

Uma futura camada de risco deve comparar razões racionais por multiplicação cruzada inteira (`a/b` contra `c/d` => comparar `a*d` com `c*b`) e não reconstruir decimais aproximados.

### 6.2 `direction` não é ordinal

`DECREASE`, `INCREASE`, `UNCHANGED`, `LIMIT_ADDED` e `LIMIT_REMOVED` são categorias sem uma ordenação total compartilhada.

Em particular, `LIMIT_ADDED` e `LIMIT_REMOVED` não são codificados como “menor que” ou “maior que” `DECREASE`/`INCREASE`. A futura camada de risco deve tratá-los em ramos próprios e não por comparação ordinal ou numérica.

Essa propriedade faz parte do contrato do output e deve ser preservada rio abaixo.

### 6.3 Requests declarados como fato auxiliar

`current_declared_cpu_request` e `proposed_declared_cpu_request` são capturados porque uma mudança de request pode alterar semântica de HPA baseada em utilization mesmo quando o limit permanece igual.

Este slice apenas registra os valores declarados. Não consulta HPA, não infere request efetivo e não transforma ausência em default.

## 7. Erros versus resultado

| Classe | Exemplos | Exit code | Saída |
| --- | --- | ---: | --- |
| Resultado | qualquer combinação válida da seção 6 | 0 | JSON puro em stdout |
| Erro de input | parse, recurso não concreto, workload não resolvido unicamente, container não resolvido, precisão sub-milicore | non-zero | stderr, stdout vazio |

Contrato de CLI alinhado ao Verify 001: JSON puro em stdout; stderr só para erro; sem saída interativa; sem risk; sem `worst_pod`.

## 8. Plano de teste — RED antes de GREEN

Fixtures positivas são **manifestos renderizados versionados no repositório**. Os testes não executam `helm template`, Kustomize, ArgoCD ou qualquer renderer em runtime; isso evita acoplar a suíte à versão dessas ferramentas ou do chart. Entradas deliberadamente inválidas usadas em testes negativos podem ser versionadas separadamente ou construídas como texto de teste; elas não são tratadas como fixtures renderizados válidos.

O primeiro par de fixtures versionados é deliberadamente 300m → 100m para provar desde o início a representação racional não terminante `{1, 3}`, em vez de validar apenas frações decimais fáceis.

Cada cenário abaixo vira teste de contrato antes da implementação:

| # | Cenário | Esperado |
| ---: | --- | --- |
| 1 | 500m → 250m | `DECREASE`, ratio `{1, 2}` |
| 2 | `"0.5"` → `"500m"` | `UNCHANGED`, ratio `{1, 1}` — normalização equivalente |
| 3 | limit ausente → 500m | `LIMIT_ADDED`, ratio `UNDEFINED`, current `ABSENT` |
| 4 | 500m → limit ausente | `LIMIT_REMOVED`, ratio `UNDEFINED` |
| 5 | Helm/template não renderizado ou campo estrutural não concreto | erro de input mencionando renderização |
| 6 | Manifesto Kubernetes válido contém `$(VAR_NAME)` em `args` | parse normal; não é detectado como template |
| 7 | identidade/name não resolve o mesmo workload nos dois bundles | erro de input, nunca `UNCHANGED` |
| 8 | `--container` ausente mesmo com um único container | erro de input |
| 9 | multi-container com nome explícito válido | resolve exatamente o container nomeado |
| 10 | nome existe apenas em `initContainers` com espaço padrão `containers` | erro de input; sem fallback |
| 11 | `"0.0005"` ou `"500u"` | erro de input; sem arredondamento |
| 12 | mudança só no request, limit igual | limit `UNCHANGED`; requests declarados capturados |
| 13 | multi-documento com dois recursos casando a identidade | erro de input por ambiguidade |
| 14 | Kubernetes `List` resolve exatamente um Deployment alvo | resultado normal |
| 15 | namespace ausente no manifesto, mas fornecido explicitamente na seleção | usa contexto explícito; não assume `default` |
| 16 | 250m → 500m | `INCREASE`, ratio `{2, 1}`; trava orientação `proposed/current` junto ao cenário 1 |
| 17 | 300m → 100m | `DECREASE`, ratio reduzido `{1, 3}` |
| 18 | 0m → 500m | `INCREASE`, ratio `UNDEFINED` |
| 19 | 500m → 0m | `DECREASE`, ratio `UNDEFINED` |
| 20 | 0m → 0m | `UNCHANGED`, ratio `UNDEFINED` |
| 21 | `ABSENT` → `ABSENT` | `UNCHANGED`, ratio `UNDEFINED` |

Os cenários 1, 3, 4, 6, 7, 13, 16 e 17 são particularmente importantes: orientação da razão não pode inverter, ausência não vira “unlimited”, ratio indefinido não vira sentinela numérico, sintaxe legítima `$()` não vira falso positivo de template, identidade divergente não vira mudança, bundles ambíguos não são resolvidos por heurística e uma fração não terminante permanece exata.

## 9. Decisões fechadas antes do gate

### 9.1 Container único sem `--container`

- [ ] Resolve implicitamente quando há exatamente um container
- [x] **Sempre exige `--container`, mesmo com um só.** Não há inferência.

### 9.2 Requests capturados

- [x] **Sim.** Capturados como `current_declared_cpu_request` e `proposed_declared_cpu_request`; `ABSENT` significa apenas não declarado.
- [ ] Não; fica para outro slice.

### 9.3 ADR sobre domínios de estado

- [x] **ADR-008 criada agora.** Estado declarado, estado efetivo admitido e estado histórico observado são domínios distintos. A fonte de limit do Verify é effective-observed, não uma cópia do manifesto.
- [ ] Manter apenas neste contrato.

### 9.4 Nome definitivo do módulo e subcomando

```text
módulo Python: praeva.change.cpu_limit
CLI:           praeva change cpu
```

### 9.5 Seleção de workload

- [x] **Explícita.** Primeiro slice suporta apenas `apps/Deployment` e exige group/kind/namespace/name/container explícitos.
- [ ] Inferir workload quando houver um único candidato.

Não existe descoberta heurística.

### 9.6 Interface pura congelada

A API Python deste slice é:

```python
analyze_change(
    *,
    current_manifest: str,
    proposed_manifest: str,
    api_group: str,
    kind: str,
    namespace: str,
    name: str,
    container: str,
    container_space: str = "containers",
) -> dict
```

A função é pura. Os manifestos entram como texto YAML/JSON já renderizado. Erros de parse/seleção/normalização levantam `ChangeInputError`; eles não retornam `UNKNOWN`.

A CLI `praeva change cpu` é apenas adapter de arquivos/argumentos para esta função e deve preservar JSON puro em stdout em caso de resultado e stderr com exit non-zero em erro de input.

## 10. Checklist do gate

- [x] Seção 9 resolvida e commitada
- [x] ADR-008 criada e explícita sobre declared/effective/observed
- [x] Representação racional e orientação `proposed/current` congeladas antes dos testes
- [x] Zero declarado preservado como fato; ratio com zero é `UNDEFINED`
- [x] Nenhum vocabulário de risco aparece no output
- [x] Nenhuma dependência de Prometheus, cluster ou Verify
- [x] `proposed_vs_observed` permanece fora deste slice
- [x] Fixtures positivas serão manifestos renderizados versionados, não gerados em runtime
- [ ] Testes do plano 8 escritos e **falhando** (RED) antes da primeira linha de implementação
- [ ] Primeira linha de implementação apenas depois do RED confirmado
