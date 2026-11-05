# ATTRIBUTION-COMPOSE-001 — Pré-registração
## Costura pura entre as camadas já implementadas (sem wiring de produto)

> Status: **contrato congelado antes de RED/GREEN**.
> Base: `main @ 7b359b9aeaa13c6ce6ef27949a58531c31f0d058` (PR #26).
> Branch: `praeva/attribution-compose-001`.
> Depende de WORKLOAD-OWNERSHIP-001, ATTRIBUTION-FACT-INPUT-001, ATTRIBUTION-DECISION-001/002 e ATTRIBUTION-SUMMARY-PROOF-001.

## 1. Pergunta

Podemos compor **as quatro implementações reais** em um caminho puro, determinístico e auditável, usando somente evidências explicitamente fornecidas, antes de modificar `praeva analyze`?

O resultado deste slice **não é** uma nova regra e **não é** um veredito atribuível de Risk.

## 2. Fronteira e sequência

```text
normalized evidence (pré-Verify) + creation_by_pod_uid
              |
              v
build_attribution_fact_inputs
              |--- facts[] + required_timestamps_by_pod
              |--- ownership_acquisition: [start-Wmax arredondado à grade, end], step
              v
ownership evidence já adquirido no intervalo exato da etapa anterior
              |
              v
build_ownership_report(target_workload, required_timestamps_by_pod)
              |
              v
project_attribution_decision(
    target_domain_status, facts, population_evidence, level_requirements
)
              |
              + verify_report (referente ao MESMO normalized evidence)
              v
project_summary_proof
```

O compositor recebe o **output normalizado** de ownership, não um transporte nem Prometheus URL. Não consulta Prometheus, Kubernetes, relógio ou arquivos. A aquisição de ownership deve ser planejada *a partir do fact input*; a futura orquestração I/O fará esse estágio fora desta função.

### API pública

```python
compose_attribution(
    *,
    normalized_evidence: dict,
    verify_report: dict,
    ownership_evidence: dict,
    creation_by_pod_uid: dict,
    target_workload: dict,
    target_domain_status: str,
    population_evidence: dict,
    level_requirements: dict,
) -> dict
```

`target_domain_status` é **obrigatório e explícito** (`DETERMINED | UNDETERMINABLE`). O compositor não adivinha domínio-alvo nem populações. `population_evidence` e `level_requirements` também são inputs obrigatórios e não são derivados de `coverage_complete`.

### Output, exclusivamente interno

```json
{
  "compose_id": "ATTRIBUTION-COMPOSE-001",
  "fact_input": "...documento íntegro...",
  "ownership": "...WORKLOAD-OWNERSHIP-001 íntegro...",
  "attribution": "...ATTRIBUTION-DECISION íntegro...",
  "summary_proof": "...ATTRIBUTION-SUMMARY-PROOF-001 íntegro..."
}
```

Esse return serve para testes e composição **interna**. Não altera `PRAEVA-ANALYZE-001` nem obriga que o JSON canônico publique `fact_input` expandido. A política de publicação/versionamento do futuro Analyze exige slice próprio; nenhuma camada será silenciosamente filtrada.

## 3. Consistência obrigatória entre fios

Antes de chamar o resolver, exigir:

1. `verify_report` pertence ao **mesmo normalized evidence**: `windows.short/long`, `acquisition` (namespace, container, pod_selector, start, end, step) e `queries` são os mesmos, sem perder query provenance. Comparações de timestamps/step são numéricas exatas (Decimal; sem float), não string-frágeis. **Emenda de review antes do RED correspondente:** também validar, por recomputação determinística do Verify core, `pods`, `selectors`, `status` e `unknown_reasons`. Comparar só metadados permitiria substituir `max_timestamp` por outro ponto existente, alterando o witness silenciosamente. A recomputação é validação interna, não uma segunda fonte de verdade e não publica outra camada.
2. `ownership_evidence.acquisition` corresponde **exatamente** ao `fact_input.ownership_acquisition`: namespace, start, end e step. Não aceitar intervalo menor, grade deslocada, outro namespace, nearest neighbor ou preenchimento oportunista.
3. `target_workload` é validado pelo resolver contra o namespace da evidência. Apenas `apps/Deployment` conforme WORKLOAD-OWNERSHIP-001.
4. `fact_input.facts` e `attribution.facts` têm IDs 1:1 — validado pelo summary-proof. Fato não atribuível não é removido.
5. Dados estruturalmente incompatíveis causam erro de input (`AttributionComposeInputError` para incompatibilidades de fios; erros tipados dos componentes podem propagar). Ausência de ownership **dentro de uma aquisição válida** é evidência semântica UNKNOWN, não erro estrutural.

`coverage_complete` do Verify prova apenas cobertura de pontos retornados, jamais suporte amostral cru. `support.boundary_proven=false` não é promovido a true por haver uma grade de ownership.

## 4. Semântica preservada

- Fato pointwise `(pod, evidence_family, evaluated_at, support)` continua unidade de atribuição.
- `creation_by_uid` é dado do produtor, nunca escolhido por nome de Pod.
- `TARGET_DIFFERS` continua `UNATTRIBUTED(foreign_workload)`, sem degradar população-alvo.
- Existencial/witness pode continuar utilizável com domain incompleto; universal exige domain completo.
- `target_domain_status=UNDETERMINABLE` permanece `INADMISSIBLE`, não erro de execução.
- Nem `application_version_relation` nem `CALLER_ASSERTED` são promovidos.
- Nenhum predicate/limiar/ordem de `CHANGE-RISK-001` muda.

## 5. O que o slice NÃO resolve

- aquisição real de `kube_pod_created` / `creation_by_pod_uid` (produtor ainda ausente);
- reconstrução da população alvo `O(T)` e prova per-family de selector omissions / derived missing;
- escolha do produtor de `target_domain_status` e do `level_requirements` de cada regra;
- wiring no Analyze/Join/Risk ou alteração da versão do JSON canônico;
- prova contínua event-time ou raw sample support.

Essas são dependências reais do wiring futuro; neste slice o chamador deve **fornecê-las explicitamente**, sem inventar defaults nem alegar que já existe produto live/replay novo.

## 6. Testes pré-registrados — RED antes de GREEN

1. Caminho íntegro: fact input → ownership real → decisão → summary proof, com witness de CPU e ratio composto utilizável.
2. Mesma entrada produz saída byte-identical; entrada não sofre mutação.
3. Aquisição ownership correta, inclusive extensão conservadora `Wmax`.
4. Ownership adquirido em intervalo menor → erro estrutural (não `UNKNOWN`).
5. Mesmo intervalo, mas step ou origem de grade diferente → erro estrutural.
6. Verify de outra janela/namespace/query provenance → erro estrutural.
7. Fato fora de ownership resolvido → `UNATTRIBUTED`, preservado no output, sem exclusão.
8. Domínio incompleto não bloqueia witness existencial e bloqueia nível que exige FORALL.
9. `UNDETERMINABLE` não vira erro de execução; devolve analysis INADMISSIBLE.
10. Famílias independentes e ratio composto não aceitam componente ausente.
11. Não alterar nem importar `praeva.analyze.orchestrator`, Join ou Risk na implementação.
12. Review: `max_timestamp` de CPU ou `cpu_limit_ratio` adulterado, embora aponte para fato existente e mantenha provenance igual, é incompatibilidade estrutural do Verify e deve falhar antes de qualquer decisão.

**Gate:** registrar testes RED contra módulo inexistente, implementar GREEN e validar CI completo; só depois avaliar PR Ready for review. Merge somente com autorização explícita.
