# PRAEVA-ANALYZE-001 — Gate Record

Status: **GREEN local confirmado; primeira execução real e replay determinístico confirmados.**

## Pré-registração e RED

- Contrato `PRAEVA-ANALYZE-001` commitado antes da implementação.
- RED oficial confirmado antes de `orchestrator.py` / `cli.py` existirem.
- Ruff: passou.
- Pytest no RED: `16 failed, 176 passed`.
- As falhas eram a ausência esperada de `praeva.analyze.orchestrator` / `praeva.analyze.cli`.

## GREEN determinístico

Após implementação da orquestração, CLI e entrypoint executável:

- Ruff: passou.
- Pytest: `193 passed` antes da fixture live.
- `python -m praeva.analyze.cli --help`: executável confirmado.
- Working tree local: limpo.

## Primeira execução real

Ambiente testado:

- lab Kind `sre-platform`;
- ArgoCD sincronizado na mesma revisão do código testado;
- HPA com CPU ativa;
- Prometheus acessível por port-forward;
- workload `apps/Deployment app/jobs-api`, container `jobs-api`;
- relação workload → pods ainda `CALLER_ASSERTED` / `UNVERIFIED`, conforme contrato.

Caso versionado: `jobs-api-live-001`.

Parâmetros congelados antes da aquisição:

- current CPU limit: `500m`;
- proposed CPU limit: `250m`;
- rule: `CHANGE-RISK-001`;
- margin: `11/10`;
- start: `1792423770`;
- end: `1792424070`;
- step: `15`;
- short window: `2m`;
- long window: `5m`.

Resultado real:

- applicability: `APPLICABLE`;
- classification status: `UNKNOWN`;
- reason: `censored_evidence`;
- precondition: `uncensored_evidence_for_noncontradiction`;
- evidence ref: `pods.jobs-api-849859f688-z6zck.windows.long.cfs_throttling`;
- process exit code: `0`.

Nenhuma semântica de `CHANGE-RISK-001` foi alterada após observar o resultado.

## Replay

A mesma aquisição real foi capturada como respostas brutas do Prometheus em:

`praeva/analyze/tests/fixtures/replay/jobs-api-live-001/`

Foram versionadas as respostas raw de:

- `cpu_short`;
- `cpu_long`;
- `cpu_limit`;
- `cfs_throttled_short`;
- `cfs_throttled_long`.

O replay passa pelo adapter Prometheus real via `query_range` injetado e reproduziu a saída canônica **byte a byte**.

SHA-256 observado para live e replay:

`e767c6e2c4c6f99f23acff2d82e87f5ed777af83bff1249d7980896b2b5e7cf4`

A fixture foi promovida a teste permanente de CI.

## GREEN final local

Após adicionar o teste permanente da captura real:

- Ruff: passou.
- Pytest: `194 passed`.
- Working tree: limpo.

## Gate

- [x] pré-registração antes da implementação;
- [x] RED antes do GREEN;
- [x] nenhum default de regra, margem ou tempo;
- [x] transporte Prometheus injetado em `query_range`;
- [x] adapter real exercitado em replay;
- [x] falha de transporte separada de `UNKNOWN`;
- [x] primeira execução real concluída;
- [x] respostas Prometheus raw capturadas e versionadas;
- [x] live e replay idênticos byte a byte;
- [x] fixture real promovida a teste determinístico;
- [x] GREEN final local com `194 passed`;
- [ ] CI final no head deste gate.
