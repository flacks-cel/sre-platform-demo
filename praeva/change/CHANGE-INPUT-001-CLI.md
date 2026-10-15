# CHANGE-INPUT-001 — CLI adapter contract

> Status: **pré-registração fechada antes da implementação da CLI.**
> Core `analyze_change(...)`: GREEN. Este documento congela somente o adapter de arquivos/argumentos.

## 1. Comando

```text
praeva change cpu \
  --current CURRENT.yaml \
  --proposed PROPOSED.yaml \
  --api-group apps \
  --kind Deployment \
  --namespace app \
  --name jobs-api \
  --container jobs-api \
  [--container-space containers]
```

`--current`, `--proposed`, `--api-group`, `--kind`, `--namespace`, `--name` e `--container` são obrigatórios.
`--container-space` é opcional e usa `containers` por padrão.

Neste slice não há stdin, descoberta de workload, renderização Helm/Kustomize, acesso ao cluster ou Prometheus.

## 2. Responsabilidade do adapter

A CLI faz somente quatro coisas:

1. parseia argumentos;
2. lê os dois arquivos como UTF-8;
3. chama `praeva.change.cpu_limit.analyze_change(...)` com os textos e argumentos explícitos;
4. serializa **exatamente** o dicionário retornado pelo core como JSON determinístico.

A CLI não reimplementa parsing de Kubernetes, normalização de CPU, cálculo de `direction`, cálculo de `change_ratio` ou qualquer regra semântica do core.

## 3. Output

Em sucesso:

- exit code `0`;
- stdout contém exatamente um documento JSON seguido de newline;
- JSON usa chaves ordenadas e separadores compactos;
- stderr vazio;
- não há wrapper adicional em torno do resultado do core.

O output continua sem risco, recommendation, `LOW/MEDIUM/HIGH/CRITICAL`, `UNKNOWN`, `worst_pod` ou comparação com evidência observada.

## 4. Erros

São erros de CLI/input:

- argumento obrigatório ausente;
- arquivo atual ou proposto inexistente/ilegível;
- qualquer `ChangeInputError` levantado pelo core.

Em qualquer desses casos:

- exit code non-zero (`2` neste adapter);
- stdout vazio;
- mensagem diagnóstica em stderr;
- nenhum JSON parcial.

Erros de parse de argumentos não são convertidos em resultado semântico.

## 5. Preservação da seleção explícita

A CLI encaminha sem inferência:

```text
api_group
kind
namespace
name
container
container_space
```

`--container-space initContainers` deve procurar somente em `initContainers`; o adapter não faz fallback para `containers` nem o contrário.

Conteúdo Kubernetes legítimo como `$(VAR_NAME)` dentro do manifesto deve chegar intacto ao core e continuar válido.

## 6. Plano RED

Antes de criar `praeva/change/cli.py`, os testes congelam:

1. happy path 500m → 250m produz JSON `DECREASE` com ratio `{1,2}`;
2. output é JSON único, compacto, determinístico e sem vocabulário de risco;
3. arquivo inexistente produz non-zero, stderr e stdout vazio;
4. manifesto não renderizado propaga `ChangeInputError` como erro de CLI, sem JSON parcial;
5. argumento obrigatório ausente produz non-zero e stdout vazio;
6. `--container-space initContainers` é respeitado explicitamente;
7. `$(VAR_NAME)` legítimo não é filtrado pelo adapter.

Os testes devem falhar por ausência de `praeva.change.cli` antes da primeira linha de implementação da CLI.
