# PROJECT_STATE.md

> Memória estrutural permanente do CHOQUE BGR.
> Para estado operacional, branch, testes e próxima ação, use `SESSION_HANDOFF.md`.
> Em qualquer divergência, o código e o estado real do repositório prevalecem.

## 1. Identidade do projeto

**Nome:** CHOQUE BGR — Sistema de Gestão

**Objetivo principal:** operar cadastro, identidade funcional, ponto, solicitações, carreira,
disciplina, treinamentos, recrutamento, tickets, unidades e administração de uma organização no
Discord, com Centro de Comando Web sobre as mesmas regras de domínio.

**Resultado esperado:** membros usam painéis, botões, seletores e formulários; decisões sensíveis
continuam humanas; toda mutação relevante é autorizada no backend, persistida com auditoria e
sincronizada com o Discord de forma recuperável.

**Status geral:** sistema amplo já operado em produção, com evolução local incremental. O código
local possui migrations até a versão 53. O último estado de produção registrado na documentação do
repositório é a migration 46; isso não foi revalidado ao vivo nesta inicialização.

## 2. Stack

### Backend e bot

- Python 3.12.
- `discord.py` para Gateway, componentes persistentes e integração com a guild.
- FastAPI/Uvicorn em `command_center/` para a API do Centro de Comando.
- Serviços de domínio assíncronos em `choque/`; adaptadores Discord em `cogs/`.
- Configuração por variáveis de ambiente com `python-dotenv`; valores reais nunca são versionados.

### Banco de dados

- SQLite via `aiosqlite`, com WAL, foreign keys, `busy_timeout`, lock de escrita e transações
  `BEGIN IMMEDIATE`.
- Migrations versionadas e transacionais em `choque/database.py`, com backup pré-migration.
- Auditoria e outbox são persistidas no mesmo commit da ação de domínio.
- SQLite pressupõe um único escritor/uma única instância do bot.
- PostgreSQL/Supabase é direção futura documentada para um corte único, sem dual-write.

### Frontend

- Next.js 16 App Router, React 19 e TypeScript estrito em `web/`.
- Auth.js/Discord OAuth, Server Components e BFF; o navegador não acessa banco ou Discord
  diretamente.
- Tailwind CSS 4, Vitest/Testing Library e Playwright.
- Antes de alterar `web/`, ler `web/AGENTS.md` e a documentação local da versão instalada do Next.js.

### Infraestrutura documentada

- Frontend preparado para Vercel.
- Bot, worker e FastAPI documentados no runtime combinado Railway.
- Empacotamento Discloud existe, mas a publicação definitiva permanece uma etapa controlada.
- GitHub Actions executa gates de segurança e qualidade.
- O estado ao vivo desses serviços não deve ser presumido sem verificação autorizada.

## 3. Arquitetura atual

O projeto é um monólito modular. Regras vivem no núcleo Python e são compartilhadas pelos dois
adaptadores de entrada:

```text
Discord -> cogs/ -> serviços em choque/ -> SQLite + auditoria/outbox -> worker Discord

Browser -> Next.js/Auth.js/BFF -> FastAPI -> serviços em choque/ -> SQLite + outbox
```

Componentes principais:

- `ChoqueBot.setup_hook`: composição, migrations, serviços, cogs, jobs e views persistentes.
- `choque/`: configuração, segurança, RBAC, banco e domínios transacionais.
- `cogs/`: interface Discord; não é fonte de autoridade para regras ou permissões.
- `command_center/`: API autenticada, anti-replay, rate limit e revalidação server-side.
- `web/`: portal público e Centro de Comando autenticado.
- Outboxes: separam commit de domínio de efeitos no Discord e permitem retry idempotente.

## 4. Estrutura importante do repositório

```text
/
├── BOOTSTRAP_PROMPT.md       # protocolo para assumir uma sessão
├── PROJECT_STATE.md          # estado estrutural permanente
├── SESSION_HANDOFF.md        # checkpoint operacional atual
├── PROJECT_HANDOFF.md        # registro histórico acumulado anterior
├── main.py                   # execução e check local sem Gateway
├── choque/                   # núcleo e serviços de domínio
├── cogs/                     # componentes e eventos Discord
├── command_center/           # API FastAPI
├── web/                      # frontend Next.js/BFF
├── tests/                    # suíte Python
├── scripts/                  # operação, validação, backup e provisionamento
├── docs/                     # ADRs, fila, ledger, segurança e relatórios
├── deploy/                   # artefatos de implantação
├── legacy/                   # módulos antigos não carregados
└── data/                     # bancos/backups locais ignorados pelo Git
```

Fontes operacionais complementares:

- `docs/PHASE_QUEUE.md`: fila oficial e fases.
- `docs/REQUEST_LEDGER.md`: cobertura dos pedidos recebidos.
- `docs/IMPLEMENTATION_REPORT.md`: evidências de implementação.
- `SECURITY.md`: gate e restrições de segurança.
- `docs/adr/`: decisões arquiteturais aceitas.

## 5. Decisões consolidadas

### D001 — Monólito modular

Manter um processo Python com núcleo em `choque/`, Discord em `cogs/` e composição explícita. Não
criar serviços ou módulos paralelos que dupliquem identidade, RBAC, auditoria ou regras existentes.

### D002 — Fonte transacional única

SQLite é a fonte de verdade atual. A interface Web e o Discord chamam o mesmo domínio; efeitos no
Discord seguem por outbox. Uma migração futura para PostgreSQL deve ocorrer por corte único e
reversível, nunca por dual-write improvisado.

### D003 — Autorização no backend

RBAC é deny-by-default e sempre revalidado no serviço/API. Visibilidade de botão, nome de canal ou
cargo apresentado pela interface não constitui autorização.

### D004 — Decisão humana em fluxos sensíveis

Recrutamento, punições, promoções, transferências e avaliações assistidas não podem produzir decisão
administrativa automática. Análises e indicadores são apenas evidência para um responsável humano.

### D005 — Identidade por IDs estáveis

Canais, cargos, patentes, painéis e configurações são localizados por IDs/registro canônico. Nome
visual nunca é chave de negócio.

### D006 — Continuidade reproduzível

Novas sessões começam por `PROJECT_STATE.md` e `SESSION_HANDOFF.md`, validam o mínimo contra Git e
continuam da próxima ação exata. Informações permanentes ficam aqui; o delta temporário fica no
handoff.

## 6. Regras e invariantes

- Não publicar slash commands, prefix commands ou comandos de texto na guild; a operação é visual.
- Não apagar históricos; ajustes e eventos relevantes são append-only ou versionados.
- Não executar efeitos externos antes do commit transacional correspondente.
- Não rodar duas instâncias contra o mesmo SQLite.
- Não inferir permissão, patente ou identidade por texto/nome visual.
- Não reduzir patente automaticamente nem aplicar punição/desligamento por indicador.
- Não representar dados simulados como produção.
- Não remover funções existentes em reformulações visuais.
- Alterações de schema exigem migration segura, backup e teste sobre cópia antes do rollout.
- Transferência usa protocolo estável, teto por guild e duas decisões humanas: aprovação do ticket
  cria somente uma ficha pendente; aprovação cadastral posterior aplica exatamente a patente
  autorizada. Legado não recebe patente inferida.

## 7. Padrões de implementação

### Código e banco

- Reutilizar serviços canônicos antes de criar novas tabelas ou fluxos.
- Garantir idempotência, concorrência segura e recuperação após restart.
- Persistir ação, auditoria e pedido de efeito externo na mesma transação quando aplicável.
- Manter contratos públicos e consumidores sincronizados.

### Discord e UI

- Componentes persistentes precisam ser restauráveis sem duplicar mensagens.
- Respostas pessoais são ephemeral; superfícies administrativas respeitam RBAC no backend.
- UX segue `ver -> entender -> agir`, com uma hierarquia clara e sem remover capacidades.

### Testes e qualidade

- Preferir TDD para regras de domínio e regressões.
- Gates Python: Ruff, pytest, compileall e `python main.py --check`.
- Gates Web: audit, typecheck, lint, Vitest e build; E2E quando pertinente.
- Executar scanner de segredos e `git diff --check` antes de considerar um corte pronto.

### Segurança

- Segredos só em gerenciadores/arquivos locais ignorados; nunca imprimir, copiar ou versionar.
- Token Discord, cookies, chaves internas, dumps, logs e PII não entram em prompts ou artefatos.
- O token exposto historicamente continua considerado comprometido até rotação comprovada.

## 8. Sistemas e módulos

- **Identidade e efetivo:** cadastro, patentes, cargos, apelidos, sincronização, Portaria e controle
  proativo de membros com `AGUARDANDO SET` pela Central de Tags canônica.
- **Ponto e operações:** sessões de voz, segmentos, viaturas, patrulhas e PTR.
- **Solicitações, carreira e disciplina:** fluxos humanos, histórico, recuperação e boletim durável
  de desligamento com motivo público fechado pelo perfil canônico do responsável.
- **Treinamentos e cursos:** catálogo, inscrições, resultados, requisitos e qualificações.
- **Recrutamento e análise:** candidatura versionada, OAuth e análise somente consultiva.
- **Tickets e transferências:** salas privadas, fila, protocolo, timeline e integração ao cadastro.
- **Unidades especiais:** candidaturas, vínculos e sincronização multi-servidor.
- **Configuração, status e segurança:** painéis persistentes, módulos, auditoria e readiness.
- **Centro de Comando Web:** superfícies públicas e administrativas sobre a API canônica.
- **Módulos antigos:** Farm, Caixa, Resgate, RH e Ausência ficam em `legacy/` e não são carregados.

## 9. Integrações e dependências

- Discord Gateway/API: painéis, cargos, apelidos, canais e OAuth.
- Vercel: destino do frontend Next.js.
- Railway: runtime combinado documentado para bot/API/worker.
- Supabase/PostgreSQL: destino futuro, ainda sujeito a ensaio e corte controlado.
- Providers externos de análise: desativados por padrão e sem autoridade decisória.
- MTA: integração futura, ainda fora do runtime atual.

## 10. Restrições importantes

- Neste computador, não acessar nem alterar produção, Discord real, banco remoto, Vercel, Railway ou
  Discloud; não fazer push/merge/deploy sem nova autorização explícita do proprietário.
- O diretório `C:\Users\mateu\OneDrive\Imagens\env` contém variáveis locais e não deve ser lido,
  impresso, copiado para o projeto ou enviado ao Git.
- Antes de qualquer rollout, trabalhar na máquina principal, identificar o escritor único, gerar
  backup verificável e testar migrations numa cópia.
- Preservar alterações do usuário e evitar ações destrutivas no Git ou no banco.

## 11. Dívida técnica conhecida

- O gate de segurança permanece `FAIL` até rotação de credenciais expostas e conclusão dos controles
  operacionais listados em `SECURITY.md`.
- SQLite limita o runtime a uma instância; a migração futura para PostgreSQL ainda precisa de ensaio,
  checksum, contagem, rollback e janela de corte.
- MFA/branch protection, monitoramento externo, DAST controlado, menor privilégio no Discord e testes
  humanos de sessão ainda dependem de validação externa do proprietário.
- O registro histórico `PROJECT_HANDOFF.md` é extenso; deve permanecer como evidência, mas novas
  sessões usam estes três arquivos compactos para não reler todo o histórico.

## 12. Estado macro

### Concluído e documentado

- Núcleo modular, migrations, RBAC, auditoria, outboxes, backup e recuperação.
- Operação visual Discord e Centro de Comando Web com os principais domínios.
- Unidades Especiais até a migration 46, documentadas como publicadas.
- Blocos locais ADV (migration 49), Cursos (migration 50), Transferências (migration 51) e Registro
  de Desligamentos (migration 52), sem rollout segundo o último checkpoint.

### Em desenvolvimento / validação

- Auditoria na máquina principal dos blocos locais, seguida de eventual rollout somente após gates e
  autorização explícita.
- A Fase 58 de identidade visual e design system foi concluída e publicada; a Fase 57 possui
  vinte e cinco cortes publicados do Centro de Comando e sua reformulação funcional restante continua
  ativa na fila oficial.

### Planejado

- Demais blocos do Prompt Master do ecossistema, respeitando a ordem de dependências da fila.
- Migração única e reversível de SQLite para PostgreSQL/Supabase quando operacionalmente aprovada.
- Empacotamento/publicação definitiva na Discloud somente no fim da fila autorizada.

## Regras para agentes

1. Ler `BOOTSTRAP_PROMPT.md` e executar a validação mínima descrita nele.
2. Não inventar estado de produção; diferenciar documentação histórica de verificação ao vivo.
3. Consultar código real quando um detalhe técnico for necessário.
4. Atualizar este arquivo só para mudanças duradouras de arquitetura, regra, stack ou estrutura.
5. Atualizar `SESSION_HANDOFF.md` nos checkpoints operacionais relevantes.
6. Não registrar raciocínio interno, conversa, secrets ou outputs extensos.
