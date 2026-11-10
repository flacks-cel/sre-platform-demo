# PRAEVA — Visão de Produto e Roadmap de Distribuição v0.1

> **Estado:** planejamento de produto, não especificação de regra de risco nem anúncio de release.  
> **Atualizado em:** 2026-11-10.  
> **Origem:** laboratório `sre-platform-demo`; **destino:** ferramenta PRAEVA independente.  
> **Marco-alvo:** primeira versão instalável e documentada para Linux, Windows e macOS.  
> **Data de lançamento:** não comprometida; depende dos critérios objetivos deste documento.

## 1. Visão

**PRAEVA** é uma ferramenta de avaliação preventiva de mudanças de infraestrutura. Compara uma configuração atual com uma proposta e usa telemetria histórica e evidências verificáveis para determinar se há contradição relevante para riscos **explicitamente modelados**.

O primeiro caso de uso é `CHANGE-RISK-001`: insuficiência do limite de CPU de uma aplicação Kubernetes. O resultado é auditável e pode ser `CLASSIFIED`, `UNKNOWN` ou `NOT_APPLICABLE` conforme os contratos da regra. Um nível de risco **não é probabilidade de incidente, garantia de segurança ou autorização automática de deploy**.

**Proposta de valor:** dar ao engenheiro uma conclusão delimitada pelas evidências, evidenciar o que não foi possível provar e reduzir decisões otimistas diante de telemetria incompleta.

### O que PRAEVA não é na v0.1

- Não é agente autônomo nem chatbot; o motor é determinístico, e IA não é requisito para classificar.
- Não aplica mudanças, não faz rollback e não modifica o cluster.
- Não promete prever incidentes nem cobrir riscos para os quais não há regras implementadas.
- Não depende de Docker, Kind, ArgoCD, Grafana ou do código da aplicação `jobs-api` como requisito de execução; precisa de fontes de evidência compatíveis para análises reais.

Uma camada futura de automação/agente poderá detectar mudanças e invocar o mesmo motor **sem poder dispensar as exigências de prova**.

## 2. Estado de partida — 2026-11-10

**Já disponível no projeto:**

- CLI Python `python -m praeva.analyze.cli analyze`, com `--config`, `--profile`, `--last` e saída canônica com `invocation`.
- Regra de risco de CPU, Join, Verify, aquisição Prometheus, tratamento explícito de evidência censurada e portão S9 de completude populacional.
- Componentes de Attribution, Ownership e enumeração; contratos e testes determinísticos com capturas de replay.
- Execuções reais realizadas no laboratório Kubernetes/Prometheus.

**Ainda não considerar entregue como produto instalável:**

- Integração de ponta a ponta da prova verificável de população e attribution no fluxo `praeva analyze` (validar separadamente a conclusão do trabalho em PRs).
- Distribuição versionada com comando `praeva` instalável fora da árvore do repositório.
- Binários e instaladores testados por sistema operacional.
- Manual de usuário e processo público de release/suporte.

O merge de um componente isolado não equivale à integração do produto. Este documento deve ser atualizado conforme evidência de CI, replay e testes reais.

## 3. Perfil da primeira versão

**Público:** engenheiros SRE, Platform e DevOps que revisam mudanças de recursos em Kubernetes.

**Escopo da v0.1:**

1. Ler manifesto atual e proposto de `apps/Deployment` compatível com a regra de CPU.
2. Acessar um Prometheus compatível, inclusive por URL remota autorizada, e coletar evidências exigidas.
3. Distinguir erro de entrada/transporte, `UNKNOWN`, `NOT_APPLICABLE` e classificação fundamentada.
4. Respeitar as exigências de attribution e prova populacional sem defaults de segurança implícitos.
5. Emitir resultado legível (`--summary`) e JSON canônico com parâmetros efetivos/proveniência, preservando a capacidade de replay.
6. Executar no computador do operador **sem exigir Python instalado**, uma vez entregue o binário para sua plataforma.

**Fora do escopo da v0.1:** interface web, agente autônomo, integração automática com GitHub/GitOps, análise de RAM/réplicas/armazenamento, múltiplas regras inéditas, operações de mutação e suporte universal a ambientes sem Kubernetes.

### Interface de referência

```bash
praeva analyze \
  --config praeva.yaml \
  --profile lab \
  --current current.yaml \
  --proposed proposed.yaml \
  --last 30m \
  --summary
```

O comando é uma **meta de distribuição**: hoje a entrada efetivamente verificada é `python -m praeva.analyze.cli analyze`. Os parâmetros e políticas seguem seus contratos: não introduzir seletores, janelas, margens ou provas implícitos no empacotamento.

## 4. Fases e entregáveis

### Fase A — Engine integrada / baseline funcional

**Objetivo:** congelar um comportamento verificável antes de empacotar.

- [ ] Completar wiring verificável de Ownership/Attribution/população para `praeva analyze`.
- [ ] Demonstrar que `PROVEN_COMPLETE` provém do produtor admitido e jamais de `CALLER_ASSERTED`, regex ou mera presença de série.
- [ ] Validar replay determinístico, incluindo S9 e casos com evidência ausente/ambígua.
- [ ] Executar smoke test read-only contra Prometheus real com caso positivo e negativo.
- [ ] Registrar capacidades e limitações efetivas da versão.

**Saída:** motor com interface congelável para empacotamento.

### Fase B — Alpha instalável

**Objetivo:** um comando distribuível, independente do checkout.

- [ ] Definir empacotamento Python e entrypoint `praeva`, isolados de `app/api` e do laboratório.
- [ ] Criar build automatizado reproduzível em CI para Windows x64, Linux x86-64, macOS arm64 e macOS x86-64 (matriz inicial, sujeita a validação).
- [ ] Escolher e validar ferramenta de bundling (ex.: PyInstaller), incluindo licenças, bibliotecas e conteúdo da distribuição.
- [ ] Publicar arquivos de release por plataforma, checksums SHA-256 e versão do binário.
- [ ] Confirmar `praeva --help` e `praeva analyze --help` sem Python instalado, mais um replay offline.
- [ ] Produzir guia curto de instalação e primeiro uso.

**Saída:** binários de Alpha testáveis; não equivalem a instaladores assinados.

### Fase C — Beta / instaladores e validação externa

**Objetivo:** instalação previsível, documentação completa e compatibilidade demonstrada.

- [ ] Definir formato de instalação por SO: Windows (instalador ou package manager), Linux (arquivo portátil e/ou pacote), macOS (pacote ou arquivo portátil), com desinstalação documentada.
- [ ] Executar testes de **instalação limpa**, execução e remoção nos sistemas/arquiteturas declarados.
- [ ] Validar acesso a Prometheus remoto, mensagens de erro, caminhos com espaços, permissões e ambientes restritos.
- [ ] Publicar manual de usuário em pt-BR e documentação básica em inglês.
- [ ] Documentar matriz de compatibilidade de Kubernetes, Prometheus, métricas obrigatórias e limitações.
- [ ] Definir política de versão, suporte, segurança, proteção de segredos e tratamento de issues.
- [ ] Avaliar assinatura de código no Windows e assinatura/notarização Apple para distribuição macOS sem avisos indevidos.

**Saída:** candidato a release para usuários fora do laboratório.

### Fase D — PRAEVA v0.1

**Objetivo:** primeira release pública, com escopo explícito e testado.

- [ ] Binários/instaladores publicados para as plataformas declaradas, com hashes verificáveis.
- [ ] Manual, exemplos, changelog, licença e limitações conhecidos publicados.
- [ ] CI e smoke tests aprovados no **commit/tag exato** da release.
- [ ] Exemplo completo de análise com entrada, saída e explicação das razões `UNKNOWN`.
- [ ] Separação clara entre ferramenta `praeva` e laboratório `sre-platform-demo`.
- [ ] Nenhum requisito de evidência ou classificação relaxado para cumprir prazo.

**Saída:** versão `v0.1.0` somente quando os gates acima forem satisfeitos.

## 5. Matriz de plataformas — alvo, não compatibilidade prometida

| Plataforma | Artefato inicial pretendido | Critério mínimo de aceitação |
| --- | --- | --- |
| Windows x64 | `praeva.exe` + distribuição/instalador | instalação limpa, help, replay, análise read-only |
| Linux x86-64 | executável `praeva` + `.tar.gz` e/ou pacote | idem; declarar compatibilidade de libc/distro |
| macOS arm64 | executável `praeva` + pacote | idem; validar assinatura/notarização na distribuição |
| macOS x86-64 | executável `praeva` + pacote | idem; testar em runner/máquina x86-64 |

**Não afirmar suporte** a sistema/arquitetura até testar. Builds nativos por plataforma são preferíveis à suposição de que um binário de Linux funcione em Windows ou macOS. O instalador é um artefato diferente do executável portátil.

Nenhum binário substitui o requisito operacional de **telemetria histórica suficiente**. O consumidor precisa de rede/permissões para a fonte remota, ou de dados congelados para replay. Docker/Kind são apenas a infraestrutura do laboratório de referência.

## 6. Manual do usuário — estrutura planejada

Criar `docs/praeva/user-manual.pt-BR.md` e, depois, sua versão `en` quando os comandos de distribuição estiverem estabilizados.

1. O que o PRAEVA faz e o que **não** conclui.
2. Pré-requisitos de observabilidade, RBAC e retenção; topologia suportada.
3. Download, checksum, instalação, atualização e desinstalação por plataforma.
4. Configuração `praeva.yaml`, perfis, precedência e exemplos seguros.
5. Exemplos completos de `praeva analyze` com arquivos realistas.
6. Semântica de `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `UNKNOWN` e `NOT_APPLICABLE`; ressalvas sobre risco e evidência.
7. Como ler `invocation`, referências de evidência, proveniência e JSON.
8. Erros comuns: Prometheus indisponível, série faltante, população não provada, censura, identidade ambígua.
9. Como reproduzir um replay com captura imutável; não confundir SHA de input com captura de evidência.
10. Segurança, privacidade, limitações, solução de problemas e coleta de diagnóstico.

Os contratos de implementação existentes **não substituem** esse manual.

## 7. Critérios de qualidade e governança

- **Semântica:** alterar regra/policy de risco exige pré-registro e decisão explícita; não degradar `UNKNOWN` para aprovação implícita.
- **Evidência:** requisitos de Attribution, histórico, UID, domínio populacional e suporte da métrica são parte do comportamento do produto.
- **Qualidade:** desenvolvimento com contrato → RED → GREEN → CI; teste de release no artefato publicado, não apenas no código-fonte.
- **Segurança:** princípio read-only; não embutir tokens, credenciais ou URLs privadas nos artefatos; documentar TLS/autenticação quando suportados.
- **Reprodutibilidade:** preservar fixtures históricas; versionar schema e descrever migrações, sem reescrever hashes antigos.
- **Distribuição:** gerar SBOM/proveniência de build e checksums quando definido o pipeline; validar requisitos legais/licenças do bundle.
- **Separação:** PRAEVA pode ser desenvolvido neste monorepo inicialmente; distribuição não pode exigir instalar o laboratório.

## 8. Próximas decisões e sequência

**Próximo trabalho executável:** `PRAEVA-DISTRIBUTION-001`, planejamento e spike de packaging separado do motor. Pode começar em paralelo com o wiring, mas **não** declarar release pronta antes dos testes e gates.

Decisões técnicas delegáveis à implementação: ferramenta de build, layout do pacote, nomes de tarefas de CI, formato inicial dos arquivos portáteis e organização do manual, desde que preservem o contrato do produto.

Decisões que requerem aprovação de produto: adicionar novos riscos, mudar admissibilidade, permitir mutação de infraestrutura, expandir suporte prometido ou alterar critérios de release.

**Quando?** Sem prazo fixado nesta etapa. O marco é orientado a evidências: Alpha após teste dos binários; Beta após instalação e análise real compatível; v0.1 após cumprir todos os gates de publicação.

---

**Relação com o projeto maior:** `sre-platform-demo` permanece como laboratório reprodutível de desenvolvimento e validação; **PRAEVA** é o produto que deverá poder operar fora dele.
