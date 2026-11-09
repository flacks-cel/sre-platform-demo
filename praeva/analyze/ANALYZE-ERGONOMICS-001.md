# ANALYZE-ERGONOMICS-001 — Contrato de Pré-Registração
## Tempo relativo, arquivo de identificação e perfis de policy

> Status: **pré-registração v2 — decisões fechadas, pronta para commit e RED.**
> Base: `main @ 7b359b9`. Altera `praeva/analyze/cli.py` e as **entradas** de `orchestrator.py`,
> mais o bloco `invocation` do documento canônico.
> **Não altera a semântica de Analyze, Join, Verify, Risk nem Attribution.**
> Emenda explícita ao PRAEVA-ANALYZE-001 §3 (defaults temporais) e §5 (documento canônico).

---

## 1. Pergunta

> Como reduzir a digitação necessária para rodar uma análise sem introduzir nenhuma decisão
> implícita que afete o veredito?

Hoje são dezesseis argumentos obrigatórios, incluindo três timestamps crus. Sete deles identificam
o alvo e praticamente nunca mudam entre execuções. O custo disso não é estético: é o motivo pelo
qual o Praeva não é usado.

---

## 2. O princípio: explícito não é o mesmo que verboso

O PRAEVA-ANALYZE-001 §3 proibiu defaults temporais porque uma janela escolhida pelo código é policy
invisível. A proibição é sobre **implícito**, não sobre **conveniente**.

`--last 6h` continua sendo o usuário declarando a janela. O que não pode existir é comportamento
quando nada é declarado.

### 2.1 Invariante: reconstituição da invocação

> **O documento de saída permite reconstituir exatamente qual invocação foi executada.**

Isto é, e **não é**, o seguinte:

| Garantido | Não garantido |
|---|---|
| recuperar todos os parâmetros efetivos, venham de CLI, arquivo ou perfil | que reexecutar produza o mesmo resultado |
| saber qual arquivo de configuração e qual perfil foram usados, e com que conteúdo | que o Prometheus ainda tenha a mesma evidência |
| saber quais manifestos foram lidos, e com que conteúdo | que os arquivos no disco não tenham mudado |
| inspecionar a evidência observada, preservada nas `layers` | reprodução byte a byte de uma nova execução |

Reprodução exata exige captura imutável da evidência — é o que a fixture de replay do
PRAEVA-ANALYZE-001 faz, e continua sendo o mecanismo para isso. Este contrato não o substitui e não
o estende.

A identidade do conteúdo é registrada por SHA-256 do arquivo de configuração **e dos dois
manifestos**, de modo que uma divergência posterior seja detectável em vez de silenciosa.

**SHA-256 identifica, não preserva.** Ele permite afirmar que um arquivo mudou desde a execução;
não permite recuperar os bytes originais. Replay exato continua dependendo das capturas de
evidência e das fixtures, nunca dos hashes.

---

## 3. Tempo

### 3.1 Formas aceitas

| Forma | Semântica |
|---|---|
| `--start T0 --end T1 --step S` | absoluta, como hoje |
| `--last <duração> --step S` | relativa, resolvida na invocação |

**Mutuamente exclusivas. Uma das duas é obrigatória.** Nenhuma presente é erro de input — não
existe default.

Gramática de `<duração>`: inteiro positivo seguido de `s`, `m`, `h` ou `d`. Fracionário (`0.5h`),
composto (`1h30m`) e textual (`6 hours`) são erro de input.

### 3.2 Alinhamento à grade

O projeto exige timestamps coincidindo **exatamente** com a grade, sem tolerância. O SPIKE-003 S10
demonstrou a consequência de uma fronteira fora dela: `support_boundary_unproven`, por fato.

Com `--start/--end` digitados à mão, os valores saíam alinhados sem que isso fosse percebido como
requisito. Com `--last`, o instante de resolução é arbitrário e `now` quase nunca é múltiplo de
`step`. **Toda execução relativa produziria fronteira fora da grade** — a ergonomia introduziria em
silêncio o defeito que o S10 catalogou.

**Decisão:**

```
end   = floor(now / step) * step
start = end − duração
```

A duração precisa ser múltipla de `step`. Se não for, é **erro de input** (§8). `--last 100m --step 15`
é válido: 6.000 s são 400 passos exatos. `--last 61s --step 15` não é.

### 3.3 Relógio injetável

A resolução de `now` acontece na CLI, com relógio injetado — real em produção, fixo nos testes. O
orquestrador **não lê relógio**.

### 3.4 O ponto final não recua

Recuar um `step` para evitar um último ponto possivelmente raspado pela metade seria policy
escondida dentro da ergonomia. Cobertura é eixo próprio do Verify e aparece no documento: se o
último ponto está parcial, o documento diz. A ergonomia não compensa, não protege e não suaviza.

---

## 4. Arquivo de identificação

### 4.1 Estrutura e escopo

```yaml
# raiz: identificação do alvo
prometheus_url: ...
namespace: ...
api_group: ...
kind: ...
name: ...
container: ...
container_space: ...
pod_regex: ...

# bloco separado: policy, só por seleção explícita (§5)
profiles:
  lab: { ... }
```

A **raiz** aceita exclusivamente as oito chaves de identificação acima. `rule`, `margin`, janelas,
`step`, `start`, `end`, `last` e parâmetros de regra na raiz são **erro de input**.

`profiles` é o único bloco adicional permitido na raiz.

**Chave desconhecida, em qualquer nível, é erro de input**, nomeando a chave. Ignorar silenciosamente
um `namesapce` digitado errado faria o Praeva analisar outro alvo sem avisar.

### 4.2 Sem descoberta automática

O arquivo é indicado por `--config <caminho>`. Não há busca no diretório corrente, no `$HOME` nem em
caminho convencional. `praeva.yaml` é convenção de documentação, não comportamento do código.

Arquivo encontrado por mágica é entrada invisível: duas pessoas no mesmo repositório obteriam
resultados diferentes sem nada na linha de comando explicar por quê.

### 4.3 Precedência

Por chave: **CLI sobrepõe perfil, perfil sobrepõe raiz**. Sobrescrever uma chave não descarta as
demais. Chave ausente em todas as fontes é erro de input, nomeando a chave.

---

## 5. Perfis de policy

```yaml
profiles:
  lab:
    step: 15
    short_window: 2m
    long_window: 5m
    rule: CHANGE-RISK-001
    rule_params:
      margin: 11/10
```

Um perfil só é aplicado quando **selecionado explicitamente** por `--profile <nome>`. Sem
`--profile`, nenhum bloco de perfil é lido, mesmo existindo no arquivo.

**O perfil precisa ser completo** para os parâmetros de policy da regra que ele seleciona: todos os
que aquela regra exige. Um perfil parcial é erro de input, nomeando o que falta.

Perfil completo torna `--profile lab` auditável — o nome significa um conjunto inteiro, não um
fragmento que depende do que mais foi digitado. Isso não torna `lab` universal: o caminho do arquivo
e o seu SHA-256 continuam parte da identidade da execução.

`--profile` sem `--config` é erro de input. `--profile` nomeando bloco inexistente é erro de input,
listando os nomes disponíveis.

A CLI ainda pode sobrescrever uma chave individual do perfil; o valor efetivo é o que aparece no
documento.

---

## 6. Documento canônico: quem emite `invocation`

Isto é mudança do contrato de saída, mesmo sem alterar nenhuma regra, e por isso é decidido aqui.

**O orquestrador emite o bloco; a CLI apenas resolve.** `analyze()` passa a receber os valores já
resolvidos mais um registro de proveniência da resolução, e os publica.

Resolver é tratamento de entrada — pertence à CLI, e é lá que o relógio vive (§3.3). Emitir o
documento canônico é responsabilidade do orquestrador, e precisa continuar sendo de um só lugar: se
a CLI acrescentasse o bloco, chamar `analyze()` programaticamente produziria um documento de forma
diferente, e passariam a existir dois documentos canônicos.

```
invocation:
  time_source           EXPLICIT | RELATIVE
  last_spec             a duração digitada, quando RELATIVE
  resolved_at           instante de resolução, quando RELATIVE
  start, end, step      valores absolutos efetivos, sempre
  config_path           caminho, quando usado
  config_sha256         conteúdo, quando usado
  profile_name          quando usado
  current_manifest_sha256
  proposed_manifest_sha256
  effective_params      todos os valores efetivos, com a origem de cada um
```

Chamada programática sem proveniência de resolução produz `invocation` com `time_source=EXPLICIT` e
sem os campos de arquivo — mesma forma, campos opcionais ausentes.

`--summary` continua sendo só renderização e não ganha campo novo.

Replay usa `start`/`end` absolutos registrados e nunca reexecuta a resolução relativa.

---

## 6.1 Módulo de resolução

A resolução vive em `praeva/analyze/invocation.py`, separada da CLI e do orquestrador, para ser
testável sem subprocess e sem Prometheus:

```
InvocationInputError(ValueError)
resolve_time_range(*, last, start, end, step, now) -> dict
load_config(path) -> dict
resolve_invocation(*, cli_values, config, profile, rule_id, now, ...) -> dict
```

A CLI chama `resolve_invocation` e passa o resultado a `analyze()`. O orquestrador publica.

---

## 6.2 Evolução explícita de schema e replay legado

A adição de `invocation` ao documento canônico é alteração de wire format. Para o
documento novo, `schema_version = PRAEVA-ANALYZE-002`; esse identificador é a versão
do schema composto, **não** a renomeação deste slice de implementação
(`ANALYZE-ERGONOMICS-001`). `PRAEVA-ANALYZE-001` continua sendo a versão histórica.

O replay histórico congelado de `jobs-api-live-001` não pode perder sua
referência original:

- Antes de regenerar, copiar o `expected.json` atual, sem modificar sequer um
  byte, para `expected.v1.json` dentro da mesma fixture. O novo `expected.json`
  representa o schema `PRAEVA-ANALYZE-002`.
- Regenerar o novo golden deterministicamente usando **as mesmas respostas brutas
  do Prometheus**, os mesmos manifests e os mesmos parâmetros absolutos. Não
  executar novas consultas live para substituir a fixture.
- Registrar no gate do replay a migração de schema, a identidade do golden legado,
  a identidade do novo golden e a explicação de por que a identidade antiga do
  documento não corresponde mais ao novo wire.
- Manter o SHA-256 histórico
  `e767c6e2c4c6f99f23acff2d82e87f5ed777af83bff1249d7980896b2b5e7cf4`
  como evidência da primeira saída canônica observada. Ele **não** é substituído
  pelo SHA-256 da saída nova, e não se deve assumir que o hash de `expected.v1.json`
  incluindo seu possível newline final seja idêntico ao hash do wire original.
- Testar tanto a igualdade byte a byte de duas execuções no **novo** golden quanto
  a igualdade semântica do novo documento projetado sem `invocation` e com
  `schema_version` histórico contra o golden v1. Em caso de divergência além
  desses campos contratados, barrar GREEN e investigar: não atualizar o golden
  para esconder mudança de veredito.

O `container_space=containers` pré-existente na CLI permanece somente para
retrocompatibilidade neste slice. Se nenhum `--container-space` ou `--config`
fornecer o campo, sua origem em `effective_params` deve ser marcada como
`LEGACY_DEFAULT`, **não** como entrada `CLI`. Configuração explícita sobrepõe
esse default pré-existente; a CLI explicitamente informada sobrepõe a configuração.

---

## 7. Fora de escopo

Entrada vinda do Git · descoberta automática de workload · segundo hazard · qualquer alteração na
lógica de `analyze()` além de receber parâmetros já resolvidos e publicar `invocation` · wiring de
attribution · gate do S9 · saída colorida ou interativa.

---

## 8. Decisões fechadas

| # | Questão | Decisão |
|---|---|---|
| 1 | Duração não múltipla de `step` | **Erro de input.** Nenhum arredondamento silencioso |
| 2 | Configuração | `--config <caminho>`; `praeva.yaml` é só convenção de nome, sem descoberta automática |
| 3 | Perfil parcial | **Completo obrigatório** para os parâmetros de policy da regra selecionada; CLI sobrescreve por chave |
| 4 | Chaves desconhecidas | Erro de input, em qualquer nível |
| 5 | Precedência | Por chave: CLI > perfil > raiz; sobrescrever uma não descarta as demais |
| 6 | Quem emite `invocation` | O orquestrador; a CLI só resolve |
| 7 | Invariante da §2.1 | Reconstituição da **invocação**, não reprodução do **resultado** |
| 8 | Formato canônico com `invocation` | Bump para `PRAEVA-ANALYZE-002`; preservar golden v1 e verificar equivalência semântica |
| 9 | `container_space` implícito legado | Preservar para retrocompatibilidade, origem `LEGACY_DEFAULT` auditável; config explícita vence |

---

## 9. Plano de teste — RED antes de GREEN

**Resolução de parâmetros** — determinismo pleno, independente de evidência:

| # | Cenário | Esperado |
|---|---|---|
| 1 | `--start/--end` como hoje | comportamento idêntico ao atual; `time_source=EXPLICIT` |
| 2 | Nem `--last` nem `--start/--end` | erro de input — **não** há default |
| 3 | `--last` junto com `--start` | erro de input, mutuamente exclusivos |
| 4 | `--last 6h --step 15`, relógio fixo | `end` múltiplo de 15; `start = end − 21600` |
| 5 | `--last 6h` com `now` fora da grade | `end` truncado para baixo; **nunca** `now` cru |
| 6 | `--last 100m --step 15` | **válido** — 6.000 s são 400 passos |
| 7 | `--last 61s --step 15` | erro de input — duração não múltipla de `step` |
| 8 | `--last 0.5h`, `--last 1h30m`, `--last "6 hours"` | erro de input |
| 9 | Dois relógios distintos | cada resolução conferida **independentemente** pela fórmula: `end = floor(now/step)*step`, `start = end − duração` |

> O caso 9 testa **a resolução**, não o documento inteiro: intervalos diferentes consultam amostras
> diferentes e podem mudar witnesses e veredito legitimamente.
>
> Cada relógio é verificado pela fórmula, nunca pelo deslocamento entre os dois resultados:
> `floor(a/s)·s − floor(b/s)·s` **não** é igual a `floor((a−b)/s)·s`. Com `step` 15, relógios em
> 100 e 110 resolvem para 90 e 105 — deslocamento de 15 para uma diferença de 10.

**Determinismo da análise** — sobre evidência fixa:

| # | Cenário | Esperado |
|---|---|---|
| 10 | Mesma fixture, relógio fixo, duas execuções | documento idêntico byte a byte |
| 11 | Mesma fixture, `--start/--end` absolutos, duas execuções | documento idêntico byte a byte |

**Configuração e perfis:**

| # | Cenário | Esperado |
|---|---|---|
| 12 | `--config` com as oito chaves de identidade | invocação válida sem repetir nenhuma delas |
| 13 | `margin` ou `short_window` na raiz do arquivo | erro de input — chave não permitida na raiz |
| 14 | Chave desconhecida na raiz ou em um perfil | erro de input, nomeando a chave |
| 15 | Sem `--config`, arquivo presente no diretório | **não** é lido |
| 16 | `--namespace` na CLI e no arquivo | vence a CLI; origem registrada em `effective_params` |
| 17 | `--profile lab` | valores do perfil ecoados campo a campo |
| 18 | Perfil no arquivo, sem `--profile` | **não** é aplicado |
| 19 | `--profile` sem `--config` | erro de input |
| 20 | `--profile` nomeando bloco inexistente | erro de input, listando os disponíveis |
| 21 | Perfil sem um parâmetro de policy exigido pela regra | erro de input, nomeando o que falta |
| 22 | `--rule-param margin=...` junto de perfil que define `margin` | vence a CLI; demais chaves do perfil preservadas |

**Documento canônico:**

| # | Cenário | Esperado |
|---|---|---|
| 23 | Qualquer execução | `invocation` presente, com `start`/`end`/`step` absolutos |
| 24 | Execução com `--config` | `config_path` e `config_sha256` registrados |
| 25 | Qualquer execução | SHA-256 dos dois manifestos registrado |
| 26 | `analyze()` chamado programaticamente, sem CLI | mesma forma de documento; `invocation` presente, campos de arquivo ausentes |
| 27 | Novo documento canônico | `schema_version=PRAEVA-ANALYZE-002` |
| 28 | Replay congelado migrado | golden v1 preservado byte a byte; novo golden byte-idêntico em duas execuções; remoção de `invocation` + restauração do schema v1 equivale semanticamente ao golden v1 |
| 29 | `container_space` ausente de CLI/config | valor legado `containers`, origem `LEGACY_DEFAULT`; config explícita vence |

Os casos 5 e 15 são os que distinguem este contrato de uma ergonomia ingênua: tempo relativo não
pode produzir fronteira fora da grade, e conveniência não pode virar entrada invisível. O 26 é o que
impede dois documentos canônicos.

---

## 10. Checklist do gate

- [ ] Pré-registração commitada, sozinha, antes de qualquer teste
- [ ] Nenhum default temporal em lugar nenhum
- [ ] Nenhum arredondamento silencioso de duração ou de fronteira
- [ ] Relógio na CLI, nunca dentro do orquestrador
- [ ] `invocation` emitido só pelo orquestrador
- [ ] Nenhuma mudança na lógica de `analyze()` além de receber resolvido e publicar `invocation`
- [ ] Nenhum parâmetro que afete o veredito lido de arquivo sem `--profile` explícito
- [ ] Chave desconhecida nunca ignorada
- [ ] Testes do plano 9 escritos e **falhando** antes da primeira linha de implementação
- [ ] Migração de schema + golden histórico protegidos e documentados antes de declarar GREEN
- [ ] CI completo na branch do PR #28; resultado GREEN local de outro clone não substitui CI
