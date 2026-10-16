# RISK-VOCABULARY-001 — Contrato de Pré-Registração

> Status: **gate estrutural GREEN confirmado; vocabulário pronto para ser consumido pela primeira regra de risco.**
> Base: `main @ 9a671fd`.
> Herda ADR-001 a ADR-008.
> Este contrato define **significado e estrutura**, não limiares.

---

## 1. O que este contrato é

Um vocabulário, não uma regra. Ele fixa o que `LOW`, `MEDIUM`, `HIGH` e `CRITICAL` significam, o que nunca podem significar, e o que toda regra precisa carregar junto ao emiti-los.

Nenhuma regra existia quando este documento foi escrito. O vocabulário foi congelado antes da primeira regra para que as categorias não fossem moldadas pelo que a primeira regra conseguir afirmar.

---

## 2. Risco é sempre relativo a um perigo nomeado

`CRITICAL` sozinho não significa nada. Crítico para quê?

**Toda classificação de risco declara o perigo (`hazard`) a que se refere**, e o perigo é pré-registrado no contrato da regra, nunca inferido.

Isso não é formalidade. Os próprios valores de `direction` do CHANGE-INPUT-001 apontam para perigos diferentes:

| Mudança             | Perigo plausível                                    |
| ------------------- | --------------------------------------------------- |
| `DECREASE` no limit | insuficiência — throttling, degradação sob carga    |
| `INCREASE` no limit | pressão de nó, vizinho barulhento, desperdício      |
| `LIMIT_REMOVED`     | consumo irrestrito afetando o nó                    |
| `LIMIT_ADDED`       | insuficiência, contra uma demanda nunca restringida |

Uma regra que classificasse `DECREASE` e `LIMIT_REMOVED` na mesma escala sem nomear o perigo estaria somando coisas distintas — exatamente o erro que `direction` ser categórica e não ordinal já evitou rio acima.

**Comparabilidade:** dois níveis só são comparáveis sob o mesmo `hazard`. `HIGH` para insuficiência e `HIGH` para pressão de nó não são o mesmo `HIGH` e não se ordenam entre si.

---

## 3. As quatro categorias

A escala é **ordinal dentro de um mesmo perigo**:

```text
LOW < MEDIUM < HIGH < CRITICAL
```

O que cresce ao longo dela é o **grau de contradição entre a proposta e a evidência**, sob o perigo declarado — não probabilidade, não impacto de negócio.

| Nível      | Significado                                                                        |
| ---------- | ---------------------------------------------------------------------------------- |
| `LOW`      | a evidência disponível não contradiz a proposta sob o perigo declarado             |
| `MEDIUM`   | a evidência aproxima a proposta de uma fronteira que o perigo considera relevante  |
| `HIGH`     | a evidência contradiz a proposta em parte da janela observada                      |
| `CRITICAL` | a evidência contradiz a proposta no caso típico ou sustentado da janela observada  |

### 3.1 Por que não probabilidade nem impacto

Uma camada determinística sobre evidência histórica de CPU **não computa probabilidade**: não há modelo, não há distribuição preditiva, não há base para afirmar chance futura. E não conhece impacto de negócio: o Praeva não sabe se o workload é um batch noturno ou o caminho de pagamento.

Definir as categorias por contradição com a evidência é a leitura que esta camada consegue sustentar. `CRITICAL` aqui significa **“a evidência contradiz fortemente a proposta sob o perigo declarado”**, não “isto vai derrubar a produção”.

---

## 4. `UNKNOWN` não é um nível

`UNKNOWN` **não pertence à escala**. Não fica abaixo de `LOW`, não fica acima de `CRITICAL`, não é um quinto valor do mesmo enum.

Estruturalmente, são dois campos:

```text
classification_status   CLASSIFIED | UNKNOWN
risk_level              LOW | MEDIUM | HIGH | CRITICAL   (ausente quando UNKNOWN)
```

Um enum de cinco valores convidaria, mais cedo ou mais tarde, a um `max()` ou a um `>=` que trataria `UNKNOWN` como posição na escala. A separação em dois campos torna isso um erro estrutural, não uma questão de disciplina.

`UNKNOWN` nunca é `LOW` (ADR-005) e nunca é “provavelmente seguro”.

---

## 5. Qualidade da evidência não modula o nível

ADR-002, levada à sua consequência operacional.

**Proibido:** rebaixar ou elevar um nível porque a evidência é fraca. Não existe “`LOW` com baixa confiança”, nem “`HIGH` atenuado por cobertura parcial”. Isso dobraria os dois eixos num só.

**A relação correta é de porta, não de peso:** cada regra pré-registra as pré-condições de evidência que sua classificação exige. Satisfeitas, ela classifica. Não satisfeitas, o resultado é `UNKNOWN` — nunca um nível vizinho.

A qualidade da evidência viaja junto, em campo próprio, para quem lê julgar. Ela não entra no nível.

---

## 6. Proveniência viaja com a classificação

`CALLER_ASSERTED` nunca é `VERIFIED`.

Toda classificação carrega a proveniência das premissas que a sustentam, incluindo `identity_assertion` e `workload_to_pod_selector_relation` vindos do CHANGE-JOIN-001 quando a regra depende desse join.

**A proveniência não altera o nível.** Uma classificação sobre identidade asserida pelo chamador é uma classificação legítima — mas nunca pode ser apresentada como verificada. Rebaixar o nível por causa da proveniência seria a mesma dobra proibida na seção 5, com outra roupa.

---

## 7. Toda classificação cita a evidência que a sustenta

Nenhum nível é emitido sem referência explícita aos fatos que o produziram — fatos do CHANGE-JOIN-001 e/ou do Verify, nomeados pela regra.

Um nível sem evidência citada é opinião, e a camada determinística não emite opinião.

---

## 8. Risco não altera exit code

O Verify e o Change Input estabeleceram que exit code non-zero significa **falha de execução** — input inválido, transporte ou schema. `UNKNOWN` mantém exit code zero.

`CRITICAL` **também** mantém exit code zero. Um veredito é resultado, não erro.

Fazer `CRITICAL` sair non-zero misturaria veredito com transporte e tornaria indistinguíveis, para um pipeline de CI, “a mudança é arriscada” e “o Praeva quebrou”. Se um dia houver um modo de gate que falhe o pipeline por veredito, ele será uma opção explícita, pré-registrada, e nunca o padrão.

---

## 9. O que este contrato NÃO define

- **Limiares.** Cada regra pré-registra os seus, com justificativa própria.
- **Agregação entre regras.** Se duas regras classificarem o mesmo change sob perigos diferentes, não existe ainda operação definida entre elas. Nada de `max()` por conveniência.
- **Score numérico.** Não existe risco como número. A escala é ordinal e nominal, não métrica.
- **Mapeamento para severidade de incidente, SLO ou alerta.** Outro domínio.
- **Probabilidade futura.** Outro modelo seria necessário.
- **Impacto de negócio.** Outro domínio seria necessário.

---

## 10. Não normativo

As faixas antigas do roadmap do 0.1 — como `proposed > peak × 1.20 -> LOW` e `proposed < P95 -> CRITICAL` — **não são requisito, não são ponto de partida e não são herdadas**.

Nasceram antes das ADRs, antes do achado de churn, antes da separação risk × evidence quality e antes da distinção entre domínio declarado e efetivo-observado.

Quase todos os substantivos delas estão indefinidos: “peak” de qual pod, em qual janela, sob qual tratamento de throttling; “P95” sobre qual população e qual série. Se reaparecerem, entram em pré-registração nova, com o mesmo rigor dos demais slices, e provavelmente com outra forma.

---

## 11. Decisões estruturais do gate

### 11.1 Identificador do perigo

O output usa o campo:

```text
hazard_id
```

`hazard_id` é um **identificador simbólico estável**, não texto livre de apresentação e não um enum global fechado neste momento.

Regras:

- usa forma machine-readable estável em `lower_snake_case`;
- a primeira regra que introduz um `hazard_id` pré-registra sua definição semântica;
- regras posteriores só podem reutilizar o mesmo `hazard_id` por referência explícita à definição já existente;
- o mesmo texto humano com identificadores diferentes não autoriza comparação;
- identificadores iguais significam que as regras afirmam deliberadamente estar no mesmo domínio de perigo.

A ausência de enum global evita congelar antecipadamente todos os perigos possíveis; a ausência de string livre evita colisão semântica por descrição casual.

### 11.2 Vocabulário de `UNKNOWN`

`UNKNOWN` nunca é opaco.

Quando `classification_status == UNKNOWN`:

- `risk_level` está ausente;
- `unknown_reasons` é obrigatório e não vazio;
- cada item de `unknown_reasons` contém um `code` machine-readable e o nome da `precondition` que falhou;
- os `code` possíveis são pré-registrados pelo contrato da regra;
- texto humano adicional pode existir, mas nunca substitui `code + precondition`.

Estrutura conceitual:

```json
{
  "classification_status": "UNKNOWN",
  "hazard_id": "cpu_limit_insufficiency",
  "unknown_reasons": [
    {
      "code": "required_evidence_missing",
      "precondition": "short_window_cpu_valid"
    }
  ]
}
```

Mesmo quando não há nível, o `hazard_id` permanece: o resultado diz **qual pergunta de risco não pôde ser respondida**.

### 11.3 Onde o vocabulário vive no código

O vocabulário ganha um módulo próprio antes da primeira regra:

```text
praeva/risk/vocabulary.py
```

Esse módulo pode conter apenas artefatos estruturais compartilhados:

- `ClassificationStatus` como enum não ordenável;
- `RiskLevel` como enum não ordenável;
- validação da forma de `hazard_id`;
- validação da separação `CLASSIFIED` versus `UNKNOWN`;
- validação de `unknown_reasons` nomeados;
- validação de que classificação possui referência de evidência.

Ele **não** contém:

- limiares;
- hazard específico como policy;
- comparação entre hazards;
- score;
- agregação;
- regra de CPU.

A ordenação conceitual `LOW < MEDIUM < HIGH < CRITICAL` não será implementada com `IntEnum`, inteiro oculto ou operadores `<`, `>`, `min`, `max`. Uma futura operação que precise comparar níveis deverá receber contexto de `hazard_id` e ter contrato próprio.

Os testes estruturais vivem em:

```text
praeva/risk/tests/test_risk_vocabulary_contract.py
```

Os invariantes que dependem de executar uma regra concreta serão expostos como obrigações de contrato reutilizáveis e incorporados pela suíte de cada regra antes do GREEN dessa regra.

---

## 12. Plano de teste

O módulo compartilhado e toda regra futura devem preservar estes invariantes:

| # | Invariante                                                                                           |
| - | ---------------------------------------------------------------------------------------------------- |
| 1 | Nenhuma classificação sem `hazard_id` válido                                                        |
| 2 | `UNKNOWN` e `risk_level` nunca coexistem no mesmo resultado                                          |
| 3 | `UNKNOWN` não é ordenável contra nenhum nível                                                        |
| 4 | Mesma evidência, duas qualidades diferentes → ou o mesmo nível, ou `UNKNOWN`; nunca um nível vizinho |
| 5 | `identity_assertion = CALLER_ASSERTED` não altera o nível                                            |
| 6 | Toda classificação referencia ao menos um fato nomeado do join ou do Verify                          |
| 7 | `CRITICAL` mantém exit code zero                                                                     |
| 8 | Níveis sob `hazard_id` distintos não são comparados por nenhum caminho de código                     |
| 9 | `UNKNOWN` carrega ao menos uma razão nomeada com `code + precondition`                              |

Os invariantes estruturais independentes de regra são testados imediatamente no módulo de vocabulário. Os invariantes comportamentais que exigem uma regra concreta entram como suíte compartilhada/obrigatória antes do GREEN da primeira regra.

---

## 13. Checklist do gate

- [x] Seção 11 resolvida e commitada
- [x] Nenhum limiar, porcentagem ou score numérico normativo definido por este contrato
- [x] Nenhuma regra escrita antes deste commit
- [x] testes estruturais RED escritos
- [x] RED confirmado (`10 failed, 121 passed`; falhas apenas por módulo ainda inexistente)
- [x] módulo de vocabulário implementado somente depois do RED
- [x] GREEN estrutural confirmado localmente (`131 passed`, Ruff verde, working tree clean)
- [ ] invariantes comportamentais incorporados à suíte da primeira regra antes do GREEN dessa regra

O gate estrutural deste contrato está concluído. A primeira regra de risco pode agora ser pré-registrada, mas não pode atingir GREEN enquanto os invariantes comportamentais aplicáveis acima não estiverem incorporados à suíte da própria regra.
