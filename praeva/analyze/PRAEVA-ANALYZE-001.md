# PRAEVA-ANALYZE-001 — Contrato de Pré-Registração
## Orquestração end-to-end e CLI de produto

> Status: **pré-registração fechada — pronta para commit.**
> Gate: **commit deste contrato e RED antes de criar `orchestrator.py` ou `cli.py`.**
> Base: `main @ 908ba74`. Compõe CHANGE-INPUT-001, VERIFY (+WIRE, +THROTTLING), CHANGE-JOIN-001
> (+THROTTLING) e CHANGE-RISK-001. Herda ADR-001 a ADR-008 e RISK-VOCABULARY-001.

---

## 1. Pergunta

> Os quatro componentes, executados em sequência contra um manifesto real e um Prometheus real,
> produzem um resultado coerente de ponta a ponta?

Até aqui provamos `A`, `B`, `C` e `D` isoladamente, cada um contra fixtures que nós mesmos
construímos. **`A → B → C → D` nunca foi executado.** Este slice é o primeiro teste da costura.

Não é um slice de funcionalidade nova: nenhum componente ganha capacidade. É integração e interface.

---

## 2. Arquitetura: orquestração primeiro, CLI depois

```text
praeva/analyze/orchestrator.py     orquestração, sem terminal
praeva/analyze/cli.py              camada fina: parsing de argumentos e serialização
```

Nenhuma decisão — ordem, propagação de erro, composição do resultado — mora na camada de terminal.

### 2.1 Primeiro componente com I/O

Tudo até aqui era função pura. A orquestração consulta um Prometheus vivo.

**O ponto de injeção é `query_range`, não o coletor inteiro.** A CLI injeta o transporte real; os
testes injetam um transporte de replay. O **adapter real roda nos dois casos** — parsing, validação
de `resultType`, detecção de série duplicada, conversão para `Decimal`. Assim o teste end-to-end
exercita o adapter de verdade, e um defeito nele é pego pela replay em vez de ficar mascarado por
um coletor falso.

### 2.2 Fixture de replay

Respostas **brutas** do Prometheus, capturadas na primeira execução real contra o lab e versionadas
em:

```text
praeva/analyze/tests/fixtures/replay/<case>/
```

O Spike 001 já estabeleceu o precedente: replay com `T` fixo reproduziu os valores. A partir daqui
existe um teste de costura determinístico, sem cluster — o artefato mais durável deste slice, mais
que a própria CLI.

---

## 3. Parâmetros de tempo são obrigatórios

O Verify exige `--start`, `--end`, `--step`, `--short-window` e `--long-window`, e **nenhum tem
default.**

Um padrão como "última hora" seria um número de policy entrando pela porta dos fundos, como a margem
de 1,20 que foi expulsa. E não é inócuo: a janela de evidência determina o que a regra consegue
afirmar — dez minutos num horário calmo e 24 horas produzem vereditos diferentes sobre a mesma
proposta.

Ausência de qualquer um é **erro de input**, não `UNKNOWN`.

> Conveniência de janela, se vier, vem com pré-registro próprio e provavelmente como perfil nomeado
> em `praeva.yaml` — nunca como constante no código.

---

## 4. Interface

A unidade de execução é a **regra**, não o hazard.

```text
praeva analyze \
  --rule CHANGE-RISK-001 \
  --current current.yaml \
  --proposed proposed.yaml \
  --api-group apps \
  --kind Deployment \
  --namespace app \
  --name jobs-api \
  --container jobs-api \
  --pod-regex 'jobs-api-.*' \
  --prometheus-url http://localhost:9090 \
  --start ... --end ... --step 15 \
  --short-window 2m --long-window 5m \
  --margin 11/10
```

### 4.1 `--rule`, sem default

`hazard_id` continua sendo **propriedade semântica da regra**, não unidade de execução. Duas regras
podem tratar o mesmo hazard com desenhos diferentes, e selecionar por hazard tornaria essa escolha
implícita.

`--rule` ausente é erro de input. Não há regra padrão, pelo mesmo motivo que não há margem padrão.

### 4.2 Parâmetros específicos da regra

`--margin` pertence a CHANGE-RISK-001, não a `analyze`. Com o segundo hazard, a CLI não pode virar a
união das flags de todas as regras.

**Decisão:** a CLI coleta parâmetros de regra genericamente e os entrega à regra selecionada, que os
valida contra o seu próprio contrato. Margem ausente ou malformada é erro reportado **pela regra**,
não por uma validação central que precisaria conhecer todas elas.

Decidir na implementação apenas a sintaxe (`--margin 11/10` direto, ou `--rule-param margin=11/10`);
a semântica — validação na regra — está fechada aqui.

### 4.3 `--margin`

Apenas a forma racional `numerator/denominator`, inteiros positivos, `numerator > denominator`.
`1.1` é erro de input: float não entra nem pela linha de comando.

### 4.4 `--pod-regex` e a asserção de identidade

Enquanto o ownership não for verificado, este argumento materializa
`identity_assertion = CALLER_ASSERTED`. A ajuda da CLI diz em uma linha: o Praeva assume que esses
pods pertencem ao workload nomeado e **não verifica**.

Tornar a premissa visível onde o usuário a assume é metade do valor deste slice.

---

## 5. Saída

**O JSON composto completo é a saída canônica e o padrão.** `--summary` é apenas renderização
humana — nunca uma segunda fonte de verdade, nunca a forma que um script consome.

```text
schema_version            versão do documento composto

result                    veredito do CHANGE-RISK-001, íntegro
unknown_reasons           razões nomeadas, quando houver
evidence_refs             referências aos fatos que sustentam o resultado

layers:
  change_input            fatos, íntegros
  verify                  fatos e provenance, íntegros
  change_join             fatos cruzados, íntegros
  risk                    resultado da regra, íntegro
```

Nenhuma camada é resumida, filtrada ou reformatada. `unknown_reasons`, `evidence_refs` e `layers`
**são** a trilha de auditoria: um `UNKNOWN` é rastreável por eles até a evidência que faltou, sem
precisar de um campo que aponte a camada culpada.

`praeva_version` fica adiado até existir versionamento real de distribuição. `schema_version` entra
agora, porque o documento composto já é consumível e mudanças nele precisam ser detectáveis.

---

## 6. Erros e exit codes

| Situação | Exit code |
|---|---|
| Veredito, qualquer nível, inclusive `CRITICAL` | **0** |
| `UNKNOWN`, qualquer razão | **0** |
| `NOT_APPLICABLE` | **0** |
| Input inválido — arquivo, manifesto, `--rule`, `margin`, parâmetro de tempo ausente | non-zero |
| **Prometheus inalcançável, timeout, HTTP de erro, schema inesperado** | **non-zero** |

A última linha é o caso novo: **falha de transporte não é `UNKNOWN`.** "Não consegui perguntar" e
"perguntei e a evidência não sustenta" são coisas diferentes. Confundi-las tornaria o Praeva inútil
num pipeline — um Prometheus fora do ar viraria veredito silencioso.

### 6.1 Falha rápida

A orquestração para na primeira falha de execução e reporta qual etapa falhou. Change Input inválido
não dispara consulta ao Prometheus.

---

## 7. O resultado da primeira execução não autoriza mudar a regra

Congelado antes de rodar.

Se a primeira execução real devolver `UNKNOWN(censored_evidence)` — provável, dado que o jobs-api
vive perto do próprio teto de 500m —, a conclusão **não** é "a regra ficou conservadora demais". É:
*para aquela evidência, a regra não sustenta `LOW`/`MEDIUM`*.

Para observar um `LOW`, procura-se uma janela ou cenário legitimamente sem throttling. **Não se move
a régua depois de olhar o resultado.**

### 7.1 O que a primeira execução PODE mudar

A proibição é sobre **semântica**, não sobre encanamento. Permanecem corrigíveis, e são o propósito
deste slice:

- campo que uma camada emite e a seguinte não lê;
- nome ou forma divergente entre o output de uma e o input da outra;
- `provenance`, `query_key` ou timestamp perdido na composição;
- campo opcional ausente que quebra a camada seguinte;
- `ABSENT`/`UNKNOWN` propagado com o vocabulário errado;
- comportamento sob churn de pod no caminho real.

Qualquer alteração em limiar, escada, pré-condição ou vocabulário **é** mudança de semântica e exige
pré-registro novo.

---

## 8. Fora de escopo

Ownership verificado `Deployment → ReplicaSet → Pod` · segundo hazard · `praeva.yaml` · recomendação
de valor · memória · agregação entre hazards · perfis de janela · saída colorida ou interativa ·
qualquer mudança de semântica nos componentes compostos.

---

## 9. Decisões fechadas

| # | Decisão |
|---|---|
| 1 | Saída canônica é o JSON composto completo, por padrão; `--summary` é só renderização humana |
| 2 | Seleção explícita por **regra** (`--rule CHANGE-RISK-001`), sem default |
| 3 | `hazard_id` é propriedade semântica da regra, não unidade de execução |
| 4 | Replay usa respostas brutas do Prometheus, pelo adapter real, com `query_range` injetado |
| 5 | Fixtures em `praeva/analyze/tests/fixtures/replay/<case>/` |
| 6 | `schema_version` entra agora; `praeva_version` adiado até haver versionamento de distribuição |
| 7 | `unknown_origin` sai; `unknown_reasons` + `evidence_refs` + `layers` são a trilha autoritativa |
| 8 | Todos os parâmetros de tempo obrigatórios, sem default |
| 9 | Falha de transporte do Prometheus é erro de execução, non-zero, nunca `UNKNOWN` |
| 10 | A primeira execução real não autoriza alterar a semântica do CHANGE-RISK-001 |
| 11 | Parâmetros de regra são validados pela regra selecionada, não por validação central (4.2) |

---

## 10. Plano de teste — RED antes de GREEN

| # | Cenário | Esperado |
|---|---|---|
| 1 | Caminho feliz com transporte de replay | documento composto completo, veredito presente |
| 2 | Parâmetro de tempo ausente | erro de input, non-zero — **não** default silencioso |
| 3 | `--rule` ausente | erro de input, non-zero |
| 4 | `--rule` desconhecida | erro de input nomeando a regra |
| 5 | `--margin 1.1` | erro de input, reportado pela regra |
| 6 | `--margin 10/11` | erro de input — `numerator > denominator` |
| 7 | `--margin` ausente | erro de input, reportado **pela regra**, não por validação central |
| 8 | Prometheus inalcançável | **non-zero**, não `UNKNOWN` |
| 9 | Prometheus responde `resultType` inesperado | non-zero — o adapter real está no caminho (2.1) |
| 10 | Manifesto inválido | non-zero; Prometheus **não** é consultado |
| 11 | Veredito `CRITICAL` | exit **0** |
| 12 | `UNKNOWN(censored_evidence)` | exit 0; razão em `unknown_reasons`, rastreável por `layers` |
| 13 | Documento composto | as quatro camadas presentes e íntegras, sem resumo |
| 14 | Mesma fixture, duas execuções | saída idêntica byte a byte |
| 15 | `--summary` | renderização apenas; o JSON canônico não muda |
| 16 | `LIMIT_REMOVED` | `NOT_APPLICABLE` propagado ao topo, exit 0 |

O cenário 8 é o que distingue este contrato de uma composição ingênua: é a tentação mais natural
transformar falha de transporte em `UNKNOWN`, porque a camada de risco já tem esse vocabulário.

O cenário 9 só é possível porque a injeção é em `query_range`: com um coletor falso, o adapter nunca
seria exercitado e esse defeito passaria.

O cenário 14 é o que protege a fixture de replay de nascer inútil.

---

## 11. Checklist do gate

- [ ] Contrato commitado
- [ ] Declaração da seção 7 commitada **antes** da primeira execução real
- [ ] Nenhum default de tempo, margem ou regra em qualquer lugar do código
- [ ] Nenhuma lógica de produto em `cli.py`
- [ ] Injeção em `query_range`; adapter real no caminho de teste
- [ ] Validação de parâmetro de regra dentro da regra
- [ ] Falha de transporte nunca produz `UNKNOWN`
- [ ] Testes do plano 10 escritos e **falhando** antes de `orchestrator.py` ou `cli.py` existirem
- [ ] Após a primeira execução real: respostas brutas capturadas e versionadas em `fixtures/replay/`
