# PROJECT HANDOFF

## Auditoria recuperada, requisito etário e status público — 2026-08-23

- A releitura dos pedidos recentes encontrou divergência entre a mensagem de Requisitos, que já
  dizia 15 anos, e a campanha real, que ainda exigia 16. A migration 27 alterou a campanha aberta
  para **15 anos fora do personagem**, preservou o valor anterior em auditoria e mudou o default de
  instalações novas. O backup pós-corte confirmou `quick_check=ok`, FK=0, v27 e 16 → 15.
- Os itens desnecessários “CNH categoria B” e “porte de arma regularizado” não aparecem no fluxo
  ativo. A mensagem vigente mantém somente idade, microfone, maturidade, disponibilidade, bases de
  RP, nível 10, Nick/ID BGR e dez questões de RP policial/códigos Q.
- `/status` deixou de informar Railway pausada/v23. A publicação agora mostra Discloud Diamond
  online, instância única, Gateway ativo e banco v27; o alias público respondeu 200 sem texto antigo.
- A fila ganhou uma decisão preservada: o usuário disse que a gestão de qualificações deveria ser
  “só eu”, enquanto o RBAC publicado concede a ação ao Alto Comando. Nada foi restringido por
  suposição; a escolha foi colocada no fim da fila, sem bloquear trabalhos seguros.
- Gates desta correção: **309 pytest**, **32 Vitest**, Ruff, compileall, `main.py --check`, scanner
  de segredos, ESLint, TypeScript e build. Discloud e Vercel voltaram online após o rollout.
- O estado consolidado foi enviado somente ao repositório privado `EoPaiva/CHOQUE-BGR`, commit
  `1fa51db`, após `SECRET_SCAN_OK` e revisão dos 38 arquivos. O remoto público não recebeu push.

## Medalhas removidas por decisão do proprietário — 2026-08-23

- O canal apagado não será recriado. `cogs.medals_system` saiu da lista explícita de cogs e os
  validadores tratam a ausência como decisão intencional, não como falha operacional.
- Os scripts de provisionamento e remodelação também deixaram de declarar o ID/chave de Medalhas,
  impedindo uma recriação acidental em manutenção estrutural. O código histórico e as sete
  definições permanecem apenas para consulta e rollback.
- Após backup e restart, a Discloud carregou 16 cogs, 21 views e zero comandos publicados; não houve
  novo alerta de canal de Medalhas nos logs. O validador vivo passou com o módulo desabilitado.

## Acabamento editorial do Recrutamento validado — 2026-08-23

- A direção visual final é **alistamento editorial militar contemporâneo**: grafite dominante,
  vermelho institucional, Barlow Condensed como voz de comando e IBM Plex Mono somente para dados
  operacionais. A diagonal vermelha atravessando o hero é a âncora visual reconhecível sem o logo.
- DFII da revisão: **13/15**. A composição usa assimetria, escala tipográfica e linhas de processo em
  vez de uma grade de cards genéricos; mantém animações mínimas, contraste textual e foco visível.
- A publicação foi inspecionada integralmente em 1440 px e 390 px. O formulário permanece linear,
  os requisitos e as três etapas são claros e não existe rolagem horizontal no mobile.
- O E2E antigo foi atualizado para o conteúdo real e agora verifica headings, CTAs, dez questões,
  privacidade, idioma, overflow e nome acessível em todos os controles visíveis. Chromium desktop,
  Chromium mobile e Firefox passaram contra o alias público; ESLint, TypeScript, 32 Vitest e build
  Next.js também permanecem verdes.
- O Lovable não expôs ferramenta callable nesta sessão. Nenhum dado real foi enviado a terceiros;
  a referência editorial já incorporada foi auditada pelos artefatos locais e pela publicação.

## Recrutas e Gestão de Carreira com dados reais — 2026-08-23

- A tela de Recrutas não reconhecia `ʀᴇᴄʀᴜᴛᴀ`, pois comparava a fonte Small Caps com o literal
  `RECRUTA`. A normalização central agora reduz rótulos visuais Unicode ao identificador canônico e
  funciona tanto com o nome quanto com o prefixo da patente.
- `GET /v1/career` passou a entregar o efetivo ativo, patente e tempo na patente, horas válidas,
  patrulhas, advertências e histórico real de movimentações formais ou sincronizadas. As páginas de
  Recrutas e Carreira exibem estados vazios úteis e caminhos alcançáveis, sem fabricar registros.
- A projeção de dossiê, elegibilidade e qualificações usa o estado bidirecional atual da migration
  26, evitando que concessões feitas pelo site ou Discord apareçam apenas na matriz administrativa.
- Produção: backup pré-corte preservado, Discloud online em instância única, migration 26,
  `CHECK_OK`, Gateway conectado, health 200 e rota de Carreira protegida (`401` sem sessão). O alias
  Vercel mantém Recrutamento público e redireciona Recrutas, Carreira e Patrulhas para login.
- A leitura do banco remoto confirmou **12 membros ativos**, **4 recrutas** e **14 movimentações de
  patente**. Gates finais: **307 pytest**, **32 Vitest**, Ruff, compileall, `main.py --check`, ESLint,
  TypeScript, build Next.js e `git diff --check`.

## Qualificações bidirecionais publicadas — 2026-08-23

- A migration 26 criou `qualification_changes`, histórico append-only de concessão/revogação
  com origem Web, Discord, treinamento ou sistema. A projeção combina o legado de treinamentos com
  a decisão manual mais recente sem reescrever resultados anteriores.
- O Alto Comando recebeu a permissão exclusiva `qualification.manage`. A matriz web agora permite
  conceder/remover por membro e curso; a API valida cadastro ativo e mapping do catálogo antes de
  gravar a decisão, auditoria e outbox na mesma transação.
- A outbox `QUALIFICATION_SYNC` adiciona ou remove somente o cargo Discord associado ao curso e
  revalida o estado mais recente antes da entrega. O listener de cargos registra alterações feitas
  no Discord sem reenfileirar a mesma ação, evitando loops.
- Produção: Discloud online em instância única, banco v26, rota protegida presente e health 200;
  Vercel publicou a matriz no alias principal. O backup pré-corte está em
  `data/backups/pre-qualifications-20260823/backup-choque-bgr-api.zip`.
- Gates: **306 pytest**, **32 Vitest**, Ruff, compileall, `main.py --check`, ESLint, TypeScript e
  build Next.js. Nenhum cargo de membro real foi alterado apenas para QA automatizado.

## Hotfix de Patrulhas e fila recuperada — 2026-08-23

- A presença na Patrulha Alfa era persistida corretamente, mas o `app.py` remoto ainda chamava a
  consulta de patrulhas formais. A rota passou a usar `active_patrol_overview()` e retornou a call
  ao vivo com um ocupante após reinício em instância única.
- `Database.fetchall_fresh()` usa conexão SQLite nativa curta em thread para leituras operacionais
  entre bot e API; escritas e demais serviços permanecem no `aiosqlite` central.
- O incidente revelou drift entre árvore local e runtime: o commit incremental ignorou arquivos da
  API. O backup remoto foi comparado com todos os Python/JSON ativos; `app.py` e `security.py` foram
  alinhados, inclusive o gate exclusivo de Comando e as chaves de canais do Recrutamento. Os hashes
  finais coincidem com a árvore local e o backup pré-paridade ficou fora do Git.
- A conversa foi auditada. A fila 32–42 preserva qualificações bidirecionais, telas vazias do site,
  acabamento visual, Robô Analista, domínio próprio, medalhas removidas, compactação adiada e dívida
  de segurança. Dependências humanas recuam sem serem descartadas.
- Evidência final: 302 testes, Ruff, compileall e `main.py --check` passaram; a rota assinada
  retornou `VOICE_ACTIVE`, `DISCORD_LIVE`, Patrulha Alfa e um ocupante depois do corte.

## Portaria segura, recrutamento público e presença ao vivo — 2026-08-23

- A Portaria deixou de oferecer `Realizar cadastro` e passou a exibir `Identificar vínculo`. Uma
  conta sem membro, candidatura ou cargo funcional reconhecido registra somente identidade de
  visitante; ela não cria `members`, não recebe patente e não entra na fila de aprovação de membro.
  Candidatura, membro legado e conformidade de patente/Companheiro continuam sujeitos às decisões
  humanas existentes.
- Os modais de decisão, correção de ID e vínculo agora confirmam a interação antes de permissão,
  consulta, sincronização e arquivamento. Um teste dedicado prova a ordem `defer -> permissão ->
  banco`, eliminando o timeout visual do Discord sem antecipar a decisão.
- Requisitos, painel, acompanhamento, aprovados e reprovados foram liberados para leitura pública;
  a Mesa de Análise continua privada. O canal privado `Setar tag` foi criado abaixo do Chat CHOQUE,
  com acesso do candidato aprovado e responsáveis. A aprovação entrega DM com as instruções e usa
  fallback privado quando a DM estiver bloqueada.
- O protocolo `AL-00005` foi reprocessado sem duplicação: quadro público e resultado aprovado
  reutilizaram as mensagens existentes, passaram a mencionar o candidato e a nova orientação foi
  entregue. O validador REST confirmou cinco canais públicos, Mesa privada, canal de setagem e as
  duas menções do protocolo.
- A migration 25 persiste snapshots de ocupação das calls de patrulha. O painel web combina
  patrulhas formais com ocupação real do Discord e atualiza a cada dez segundos sem criar histórico
  falso. A ocupação posterior da Patrulha Alfa foi observada no banco e no endpoint assinado,
  fechando a validação real que estava pendente.
- O Centro de Comando web passou a negar todo perfil abaixo de `COMANDO`; recrutamento público usa
  autenticação de candidato separada e não foi bloqueado. A Vercel publicou a versão no alias
  principal, `/recrutamento` respondeu 200 e `/patrols` permaneceu protegido por login.
- Produção: Discloud online em instância única, banco v25, Gateway conectado. Gates finais desta
  rodada: **300 pytest**, **32 Vitest**, Ruff, compileall, `main.py --check`, ESLint, TypeScript e
  build Next.js. Backups remotos e snapshots de overwrites foram preservados para rollback.

## Jornada intuitiva de recrutamento e recuperação preventiva — 2026-08-23

- O visitante encontra **Candidatar-me agora** diretamente na mensagem persistente `MEMBER`, na
  Recepção, sem precisar procurar a categoria de Recrutamento. O mesmo botão abre o portal em um
  único clique; `Realizar cadastro` ficou claramente reservado a aprovados, membros e vínculos já
  reconhecidos.
- A mensagem persistente `RECRUITMENT` foi editada no lugar com quatro passos objetivos, requisitos,
  explicação do resultado e três ações: candidatura direta, acompanhamento direto e requisitos. Os
  handlers antigos continuam registrados para compatibilidade com componentes anteriores.
- A DM de entrada agora separa os caminhos “quero entrar” e “já fui aprovado”, com links diretos para
  o recrutamento e para a Portaria. Falha de DM continua best-effort e nunca bloqueia o acesso.
- `scripts/validate_live_phase11.py` confirmou no Discord as duas mensagens originais, textos novos,
  três controles da Portaria, três ações do Recrutamento, sete configurações, módulos ativos e zero
  comandos publicados.
- O primeiro commit Discloud revelou que o pacote incluía indevidamente `data/*.db*` e sobrepôs o
  SQLite remoto com uma cópia local antiga enquanto havia WAL ativo. A aplicação foi parada assim que
  o erro foi detectado. O backup pré-deploy passou em `quick_check`, FK e migration 24, foi restaurado
  atomicamente antes do startup e o runtime confirmou `DATABASE_RECOVERY_OK` e `CHECK_OK`.
- `.discloudignore` agora exclui banco, WAL, SHM e candidato de recuperação. O launcher aceita um
  arquivo explícito `recovery-once`, valida-o antes da troca, isola os arquivos incidentados e recusa
  banco sem migrations ou com violação de integridade.
- Evidência final: aplicação `choque-bgr-api` online, health HTTP 200, Gateway conectado, SQLite
  `quick_check=ok`, FK=0, migration 24, **296 testes Python**, **29 testes web**, Ruff, compileall,
  `main.py --check`, ESLint, TypeScript e build aprovados.

## Recrutamento público em produção — 2026-08-23

- portal operacional: `https://web-plum-tau-82.vercel.app/recrutamento`, HTTP 200, campanha `OPEN`;
- runtime único `choque-bgr-api` na Discloud Diamond: bot + FastAPI, 1 GB, `/health` ok; instância
  local e aplicação Discloud anterior offline;
- teste sintético completou 24 perguntas, submeteu `AL-00001`, confirmou outbox `COMPLETED` no
  canal administrativo e depois marcou o registro como `WITHDRAWN` para sair da fila ativa;
- hotfix de produção: a notificação usava `branding.footer_text`, atributo inexistente. Agora usa
  `branding.footer`; retry concluiu sem evento duplicado e há teste de regressão;
- QA final desta rodada: 293 testes Python, 29 testes web, Ruff, compileall, `main.py --check`,
  ESLint, TypeScript e build aprovados;
- bloqueio restante do recrutamento: o Robô Analista está implementado, mas `provider_ready=false`.
  É necessária credencial externa de um provider OpenAI-compatible/NVIDIA antes de ativá-lo;
- item 29 concluído operacionalmente. O ZIP sanitizado pós-hotfix contém 107 entradas, 450.193
  bytes, zero caminho proibido e SHA-256
  `a453152690b8c183710ea4266c50da12857bf8f795507e40f465a9e75657d3cf`. A rotação das credenciais
  divulgadas continua obrigatória e o gate geral de segurança permanece `FAIL`.

## Verificação Discloud e funcional — 2026-08-22

- bot publicado na Discloud Diamond e conectado à guild oficial; instância local confirmada offline;
- alocação atual de 1 GB, com consumo observado próximo de 150 MB;
- backup remoto conferido: SQLite íntegro, zero violações de foreign key e migration 24;
- 15 validadores Discord ao vivo aprovados, além da sincronização de patentes contra o banco remoto;
- suíte final atual: 293 testes aprovados, Ruff e compilação aprovados; auditoria com zero callback ausente e zero `custom_id` duplicado;
- runtime combinado de site/API, healthcheck e pacote sanitizado final concluídos; a rotação de credenciais continua dívida de segurança.

> Fotografia técnica gerada em 2026-08-22 a partir da inspeção do código real.
> Este é um documento vivo: atualize as seções 27, 31, 39, 40, 41, 42, 46 e 47 ao concluir cada fase.
> Não inclua tokens, conteúdo da `.env`, dados pessoais de membros ou valores reais de configuração.

> **Estado operacional mais recente (2026-08-22):** bot local online em instância única, banco v24.
> Portaria, Central Administrativa categorizada, exoneração e migração Small Caps foram validadas ao
> vivo. Gerenciador de Cadastros, conformidade de 72 horas e auditoria das interfaces também foram
> concluídos. Railway permanece fora do caminho operacional; o próximo item é o pacote Discloud Diamond.

## 1. Resumo Executivo

CHOQUE - BGR é um bot de gestão de uma corporação em um servidor Discord. O sistema ativo é um
monólito modular em Python 3.12, `discord.py` e SQLite. A operação publicada na guild é feita por
mensagens persistentes, botões, selects e modais; embora 46 handlers de application commands ainda
existam no código, o startup remove os comandos da guild e os validadores confirmaram zero comandos
remotos de guild.

Estão funcionais: cadastro com aprovação, RBAC, bate-ponto por presença em calls, solicitações
administrativas, carreira, disciplina, treinamentos/cursos, atividade semanal, recrutamento,
transferência, denúncia privada, outros assuntos, auditoria/outbox, configuração visual e layout Discord persistido
por ID. Não existem frontend, painel web, backend HTTP, API, Supabase, PostgreSQL, RLS, Docker,
Railway ou Vercel no código ativo. O deploy preparado é Discloud.

Os Lotes 0 e 1 e as Fases 13–15 foram concluídos: além das correções de produção, estão ativos
RankSync, catálogo histórico, mínimo de patrulha e Operações Inteligentes com fila FIFO, formação,
prontidão, integridade, desenvolvimento do membro e administração visual. A fila prossegue pelo
Programa Centro de Comando Web. A ordem integral e suas fontes estão em
`docs/PHASE_QUEUE.md` e `docs/REQUEST_LEDGER.md`.

## 2. Arquitetura Geral

```text
Discord Desktop / Web / Mobile
              │
              │ Gateway + interactions + REST (discord.py)
              ▼
        main.py / ChoqueBot
              │
      ┌───────┴──────────────────────────────┐
      │ cogs/                                │
      │ painéis, botões, selects, modais,    │
      │ listeners e loops periódicos         │
      └───────┬──────────────────────────────┘
              │ bot.services
              ▼
      ┌──────────────────────────────────────┐
      │ choque/                              │
      │ regras de domínio e serviços         │
      └───────┬──────────────────────────────┘
              │ uma conexão aiosqlite
              ▼
      data/choque_bgr.db (SQLite, WAL)
              │
              ├── estado transacional
              ├── audit_logs (outbox)
              └── panels / guild_settings / registry de IDs
                         │
                         └── retry → canal de auditoria Discord
```

Não existe comunicação bot ↔ site: não há site. Não há serviço HTTP, worker separado ou message
broker. Jobs são `discord.ext.tasks` no mesmo processo. A arquitetura pressupõe uma única instância.

## 3. Stack Encontrada

- Python 3.12 (alvo do Ruff e requisito documentado).
- A instância local validada em 2026-08-22 está em Python 3.13.13 com `audioop-lts==0.2.2`; o alvo
  de compatibilidade do projeto continua Python 3.12.
- `discord.py[voice]==2.6.3`.
- `aiosqlite==0.21.0` sobre SQLite.
- `python-dotenv==1.1.1`.
- `tzdata==2025.2` e `zoneinfo` para `America/Sao_Paulo`.
- Testes: `pytest==8.4.1`, `pytest-asyncio==1.1.0`.
- Lint: `ruff==0.12.9`.
- Deploy declarado: Discloud (`discloud.config`).
- Não há `package.json` ativo, Node.js, TypeScript, frontend ou build web.

## 4. Estrutura do Repositório

```text
BotDiscordOasisCustom/
├── main.py                         # entrypoint e --check
├── choque/                         # domínio, banco e composição de serviços
│   ├── bot.py                      # ChoqueBot, intents, cogs, sync/clear de comandos
│   ├── database.py                 # migrations 1–15 e conexão SQLite
│   ├── services.py                 # container explícito de serviços
│   ├── shifts.py                   # máquina de estados do ponto
│   ├── members.py                  # cadastro e aprovação
│   ├── personnel.py                # carreira, punições, afastamentos e ranking
│   ├── requests.py                 # solicitações administrativas
│   ├── discipline.py               # ocorrências, advertências e suspensões
│   ├── training.py                 # treinamentos, inscrições e qualificações
│   ├── activity.py                 # atividade semanal e relatórios
│   ├── tickets.py                  # candidatura, transferência, denúncia e outros assuntos
│   ├── rank_sync.py                # patente/cargo/nickname e histórico de sync
│   ├── operations.py               # patrulha, prontidão, integridade e administração inteligente
│   ├── audit.py                    # auditoria transacional e outbox
│   ├── settings.py                 # configuração, painéis, calls e RBAC
│   ├── rbac.py                     # perfis e permissões
│   ├── module_flags.py             # onze feature flags + manutenção por módulo
│   └── channel_names.py            # formatação visual central
├── cogs/                           # adaptadores Discord e UI
├── scripts/                        # runtime local, layout e validações ao vivo
├── tests/                          # 141 testes locais no último estado validado
├── docs/                           # ADRs, fases e especificações da fila
├── legacy/                         # módulos antigos preservados e não carregados
├── data/                           # banco, PID e backups; ignorado pelo Git
├── logs/                           # stdout/stderr local; ignorado pelo Git
├── requirements*.txt
├── pyproject.toml
├── discloud.config
├── .env.example
└── README.md
```

`legacy/` contém Farm, Caixa, Resgate, RH, ausência e cadastro antigos. Esses arquivos não pertencem
a `COGS` e não devem ser reativados sem migração explícita. O banco atual ainda preserva tabelas
legadas (`absences`, `cash_control`, `farm_deliveries`, `farm_tickets`) sem uso pelo runtime novo.

## 5. Como o Projeto Inicializa

### Bot

1. `main.py` carrega `AppConfig`, configura logging JSON UTC e cria `ChoqueBot`.
2. `ChoqueBot.setup_hook()` abre o banco, executa migrations, importa `config.json` uma vez quando
   aplicável, instancia os serviços e carrega 15 cogs explícitos.
3. As views persistentes são registradas nos construtores dos cogs antes do ready.
4. Em runtime, a árvore da guild é limpa e sincronizada para publicar zero comandos.
5. `on_ready` dos cogs restaura/edita painéis e recupera sessões de ponto.

Entrypoints suportados:

```powershell
python main.py
python main.py --check
.\scripts\start_bot.ps1
.\scripts\status_bot.ps1
.\scripts\stop_bot.ps1
```

`scripts/start_bot.ps1` usa `data/bot.pid`, valida que o PID pertence a este `main.py`, prefere o
Python de `.venv` e inicia uma janela
oculta e redireciona para `logs/bot.out.log` e `logs/bot.err.log`. Isso evita duplicidade apenas na
máquina local; não impede uma instância simultânea na Discloud.

### Frontend, API, workers externos

NÃO IMPLEMENTADO. Não existem entrypoints ou scripts correspondentes.

## 6. Arquitetura do Discord Bot

### Cliente e intents

`choque/bot.py` define `ChoqueBot(commands.Bot)`. Usa `discord.Intents.default()` com
`members=True` e `voice_states=True`. Não há partials configurados. `Server Members Intent` precisa
estar habilitado no Developer Portal. O command prefix existe como `commands.when_mentioned`, mas
não há prefix commands implementados.

### Loader

`COGS` é uma tupla explícita com 12 extensões:

1. `cogs.shift_commands`
2. `cogs.member_commands`
3. `cogs.config_commands`
4. `cogs.personnel_commands`
5. `cogs.request_commands`
6. `cogs.career_commands`
7. `cogs.discipline_commands`
8. `cogs.training_commands`
9. `cogs.activity_commands`
10. `cogs.ticket_commands`
11. `cogs.hierarchy_system`
12. `cogs.utility_commands`

### Camadas

- `cogs/`: converte interactions/eventos Discord em chamadas de serviço e apresenta embeds.
- `choque/`: concentra a maior parte das regras e SQL transacional.
- `Services` em `choque/services.py`: container injetado no bot; não há service locator externo.
- `Database`: uma conexão compartilhada, write lock global e `BEGIN IMMEDIATE`.

### Estado em memória

- locks descartáveis por `(guild_id, discord_id)` e tasks de grace em `ShiftService`;
- locks de refresh de painel por cog;
- flag/lock de recuperação de ponto no `ShiftCommands`;
- views persistentes registradas na memória do client;
- tasks periódicas do processo.

Estado funcional durável fica no SQLite. Grace tasks são reconstruídas por `recover_shift()` após
restart. Eventos de treinamento ativos restauram views usando `message_id` persistido.

### Tratamento de erros

- `ChoqueBot.on_tree_error` cria correlation ID e responde ephemeral.
- Views/modals possuem handlers locais que tratam `ChoqueError` e exceções Discord.
- Logging usa JSON UTC com correlation ID opcional.
- Há vários `except ...: pass` em restauração/DM best-effort; isso é dívida de observabilidade.

### Reconnect e rate limits

Reconnect e rate limits HTTP ficam a cargo do `discord.py`. Os listeners `on_ready` são em geral
idempotentes e reutilizam mensagens por `panel_type`. Não existe rate limiter de negócio por
usuário; constraints/updates condicionais protegem os fluxos críticos, mas modais não possuem
throttle próprio.

## 7. Interactions do Discord

| Interaction/classe | Tipo | Arquivo | Função | Estado |
|---|---|---|---|---|
| `RegistrationPanelView` + `RegistrationModal` | botão/modal | `cogs/member_commands.py` | envia cadastro pendente | IMPLEMENTADO |
| `PointPanelView` | 4 botões persistentes | `cogs/shift_commands.py` | iniciar, finalizar, horas e histórico | IMPLEMENTADO |
| `ShiftHistoryView` | paginação | `cogs/shift_commands.py` | dez sessões por página | IMPLEMENTADO |
| `ConfigurationMenuView` | 8 botões persistentes | `cogs/config_ui.py` | abre canais, calls, cargos, patentes, regras, painéis, módulos e status | IMPLEMENTADO |
| `ChannelBrowserView` / `RoleBrowserView` | selects/paginação/busca | `cogs/config_ui.py` | navega todos os canais/cargos em páginas de 25 | IMPLEMENTADO |
| `RanksConfigurationView` + modais | botões/modais | `cogs/config_ui.py` | cria, edita, desativa e reconcilia 21 patentes pela posição real dos cargos | IMPLEMENTADO |
| `PanelsConfigurationView` | 13 botões | `cogs/config_ui.py` | publica painéis em canal escolhido | IMPLEMENTADO |
| `ModulesConfigurationView` | 10 botões dinâmicos | `cogs/config_ui.py` | liga/desliga módulos com auditoria | IMPLEMENTADO |
| `PersonnelAdminView` | 5 botões persistentes + submenus | `cogs/personnel_commands.py` | entrada categorizada para Efetivo, Disciplina, Processos, Serviço/Operações e refresh; preserva 12 funções | IMPLEMENTADO E VALIDADO AO VIVO |
| `RequestPanelView` | 7 botões persistentes | `cogs/request_commands.py` | ausência, retorno, reserva, horas, dados, desligamento e histórico | IMPLEMENTADO |
| `AdministrativeRequestsView` e fila | botões/select/modal | `cogs/request_commands.py` | análise humana de solicitações | IMPLEMENTADO |
| `CareerPanelView` | 3 botões persistentes | `cogs/career_commands.py` | perfil, histórico e hierarquia | IMPLEMENTADO |
| `CareerAdminView` e fluxo de confirmação | user/rank selects, modal, botões | `cogs/career_commands.py` | promoção/rebaixamento com alvo explícito | IMPLEMENTADO |
| `DisciplinePanelView` | 2 botões persistentes | `cogs/discipline_commands.py` | resumo e histórico pessoal | IMPLEMENTADO |
| `DisciplineAdminView` | buttons/selects/modals | `cogs/discipline_commands.py` | ocorrência, advertência, suspensão e decisões | IMPLEMENTADO |
| `TrainingPanelView` | 3 botões persistentes | `cogs/training_commands.py` | eventos abertos, inscrições e cursos pessoais | IMPLEMENTADO |
| `TrainingEventView` | 3 botões persistentes por mensagem | `cogs/training_commands.py` | participar, cancelar e ver detalhes | IMPLEMENTADO |
| `TrainingAdminView` e gestão | selects/modals/botões | `cogs/training_commands.py` | criar, fechar, decidir participantes, concluir/cancelar | IMPLEMENTADO |
| `ActivityPanelView` | 3 botões persistentes | `cogs/activity_commands.py` | atividade, quadro e histórico | IMPLEMENTADO |
| `ActivityAdminView` / `ReportsView` | botões/modal/user select | `cogs/activity_commands.py` | regras, fechamento, monitoramento e sete relatórios | IMPLEMENTADO |
| `RecruitmentPanelView` | 3 botões persistentes | `cogs/ticket_commands.py` | candidatura, histórico e requisitos | IMPLEMENTADO |
| `TicketPanelView` | 5 botões persistentes | `cogs/ticket_commands.py` | candidatura, transferência, denúncia, outro assunto e histórico | IMPLEMENTADO |
| `RecruitmentAdminPanelView` | 3 botões persistentes | `cogs/ticket_commands.py` | filas de candidatura/transferência | IMPLEMENTADO |
| `TicketAdminView` | 3 botões ephemeral | `cogs/ticket_commands.py` | denúncias, outros assuntos e fila completa | IMPLEMENTADO |
| `TicketQueueSelect` / `TicketDecisionView` | select/modal/botões | `cogs/ticket_commands.py` | decisão condicional de ticket | IMPLEMENTADO |
| application command groups | slash handlers internos | `cogs/config_commands.py`, `cogs/member_commands.py`, `cogs/shift_commands.py`, `cogs/hierarchy_system.py`, `cogs/utility_commands.py` | compatibilidade/migração; árvore local tem 46 handlers | PARCIAL: não publicados na guild |

Custom IDs persistentes usam prefixo versionado `choque:*:v1`, exceto os botões de período do
ranking (`today/week/month/total`) e os três IDs de evento de treinamento, ligados a `message_id`.
Não altere esses IDs sem estratégia de compatibilidade.

## 8. Eventos do Discord

| Evento | Arquivo | Responsabilidade |
|---|---|---|
| `ChoqueBot.on_ready` | `choque/bot.py` | limpa/sincroniza comandos da guild e registra conexão |
| `on_voice_state_update` | `cogs/shift_commands.py` | persiste evento de voz e transiciona ponto/segmento/grace |
| `on_member_update` | `cogs/shift_commands.py` | hoje apenas encerra ponto ao perder todos os cargos autorizados |
| `on_ready` do ponto | `cogs/shift_commands.py` | recupera shifts por heartbeat/call, outbox e painel de efetivo |
| `on_ready` de configuração | `cogs/config_commands.py` | restaura a Central de Configuração |
| `on_ready` de pessoal | `cogs/personnel_commands.py` | restaura Administração/Ranking e inicia expiração de estados |
| `on_ready` de requests/carreira/disciplina/atividade/tickets/hierarquia | cogs correspondentes | reutiliza ou publica a mensagem persistida configurada |
| `TrainingCommands.cog_load/on_ready` | `cogs/training_commands.py` | restaura views de eventos e mensagens ativas |

Não existe listener de `guild_member_update` para sincronização automática de patente, nem listener
de saída de membro. Não há `interactionCreate` manual: `discord.py` despacha callbacks das views.

## 9. Mensagens Persistentes

`panels` usa chave `(guild_id, panel_type)` e armazena `channel_id`, `message_id`, `updated_at`.
`SettingsService.upsert_panel()` e os métodos `publish_or_refresh()` editam a mesma mensagem quando
possível. O banco local contém também aliases legados, preservados para migração.

| `panel_type` ativo | Finalidade | View/componentes |
|---|---|---|
| `CONFIG` | configuração completa | `ConfigurationMenuView` (8) |
| `MEMBER` | cadastro | `RegistrationPanelView` (1) |
| `MEMBER_CENTRAL` | links aos serviços | botões de link reconstruídos pelo provisionador |
| `POINT` | bate-ponto | `PointPanelView` (4) |
| `SERVICE` | efetivo ativo | embed sem botões; refresh por evento e 5 min |
| `HIERARCHY` | hierarquia | embed gerado de `ranks` |
| `REQUESTS` | solicitações | `RequestPanelView` (7) |
| `CAREER` | carreira | `CareerPanelView` (3) |
| `DISCIPLINE` | disciplina | `DisciplinePanelView` (2) |
| `TRAINING` | treinamentos | `TrainingPanelView` (3) |
| `ACTIVITY` | atividade | `ActivityPanelView` (3) |
| `RANKING` | ranking | `RankingPeriodView` (4) |
| `PERSONNEL_ADMIN` | central administrativa | `PersonnelAdminView` (5 + submenus) |
| `RECRUITMENT` | recrutamento | `RecruitmentPanelView` (3) |
| `TICKET` | atendimento | `TicketPanelView` (5) |
| `RECRUITMENT_ADMIN` | fila de atendimento | `RecruitmentAdminPanelView` (3) |

`TRAINING_LANDING`, `RECRUITMENT_LANDING`, `TICKET_LANDING`, `ABSENCE` e outros aliases no banco são
vestígios de migração; não significam painéis adicionais ativos.

## 10. Sistema de Patrulha

### Estado real: NÃO IMPLEMENTADO

Não existe `PatrolQueueService`, tabela de fila, matcher, patrulha ativa, alocação de call, movimento
automático de usuários ou encerramento de patrulha. A categoria/calls de Patrulhas existem no
Discord e 11 delas estão autorizadas para o ponto, mas isso é infraestrutura visual/voz.

Fluxo real atual:

```text
membro entra manualmente em call autorizada
→ clica Iniciar Serviço
→ ShiftService valida membro/cargo/call
→ cria shifts + shift_segments + audit_logs
→ eventos de voz trocam segmentos ou iniciam grace
→ saída/finalização/restart fecha ou recupera a sessão
```

Fila, quantidade mínima, composição, call vazia, movimento, abandono e concorrência de patrulha são
NÃO IMPLEMENTADOS. A especificação futura está em `docs/INTELLIGENT_OPERATIONS_EXPANSION_SPEC.md`.

## 11. Sistema de Voz

`ShiftCommands.on_voice_state_update` observa voz; ele não move usuários. `ShiftService` trata:

- call autorizada → segmento válido;
- troca entre autorizadas → fecha e abre segmento no mesmo timestamp;
- saída para call inválida → fecha segmento imediatamente e inicia grace configurável;
- retorno no grace → novo segmento, sem contar intervalo externo;
- expiração → fechamento condicional único;
- perda de cargo autorizado → fechamento imediato;
- restart → recuperação por heartbeat e call atual ou `REVIEW_REQUIRED`.

Calls são persistidas em `authorized_voice_channels`. O layout possui calls de ticket, eventos,
recrutamento, cursos, ausência e reunião, mas elas não são autorizadas automaticamente. Não há
criação/limpeza dinâmica de calls, fila de voz ou movimentação de membros.

## 12. Banco de Dados

SQLite é a fonte de verdade. IDs Discord são `INTEGER`; timestamps novos são epoch UTC em
milissegundos; payloads estruturados usam JSON text. O banco legado é copiado para
`data/choque_bgr.db` quando necessário e recebe `*.migration-backup` antes da primeira migration.

### Configuração e runtime

- `schema_migrations`: versão aplicada.
- `guild_settings`: configuração JSON por guild/chave; inclui `discord_layout_registry_v2`.
- `authorized_voice_channels`: calls que contam para o ponto.
- `rbac_bindings`: cargo Discord → perfil RBAC.
- `panels`: identidade das mensagens persistentes.
- `bot_runtime`: heartbeat global e shutdown limpo.
- `audit_logs`: auditoria/outbox com status/tentativas/erro.

### Membros e carreira

- `ranks`: nome, prefixo, nível, cargo Discord, perfil e ativo.
- `members`: identidade, personagem, `rank_id`, unidade, status e atividade.
- `member_applications`: cadastro pendente/aprovado/negado.
- `personnel_actions`: promoções/rebaixamentos append-only.
- `administrative_requests`: solicitações tipadas e decisões.
- `absence_requests`: afastamentos com período e status anterior.
- `punishments`: advertência, suspensão, desligamento e ciclo de decisão.
- `disciplinary_occurrences`: fatos separados de punição.

### Ponto

- `shifts`: sessão e máquina `ACTIVE/GRACE/REVIEW_REQUIRED/CLOSED`.
- `shift_segments`: intervalos válidos por call.
- `shift_adjustments`: minutos positivos/negativos append-only.
- `voice_events`: trilha de transições de voz.

### Formação e atividade

- `training_events`: agenda, responsável, capacidade, estado e mensagem.
- `training_enrollments`: inscrição, presença e resultado.
- `member_qualifications`: cursos/resultados permanentes.
- `course_catalog`: nove cursos históricos, cargo, nota, cooldown, edital e fonte.
- `course_requirements`: cargos obrigatórios ordenados e ativos por curso.
- `course_applications`: solicitações, snapshot de elegibilidade e decisão humana.
- `weekly_activity_snapshots`: fechamento semanal append-only.

### Atendimento

- `service_tickets`: candidatura, transferência, denúncia e outro assunto; payload privado e decisão.

### Legado preservado, não usado pelo runtime novo

- `absences`, `cash_control`, `farm_deliveries`, `farm_tickets`.

Não há RLS, pois SQLite é local e não existe API externa. Foreign keys estão habilitadas; deleções
relevantes usam `RESTRICT` e o código prefere estado/histórico em vez de apagar.

## 13. Migrations

As migrations são strings SQL em `choque/database.py`, aplicadas em ordem dentro de transação e
registradas em `schema_migrations`. Nunca edite uma migration aplicada; adicione a próxima versão.

| Versão | Conteúdo principal |
|---:|---|
| 1 | schema base, configuração, membros, ranks, ponto, auditoria, painéis e runtime |
| 2 | `guild_id` explícito em segmentos/ajustes e índices auxiliares |
| 3 | carreira, punições e afastamentos |
| 4 | solicitações administrativas e restauração de status |
| 5 | ocorrências e ciclo disciplinar ampliado |
| 6 | treinamentos, inscrições e qualificações |
| 7 | snapshots semanais de atividade |
| 8 | `service_tickets` para recrutamento/transferência/denúncia |
| 9 | amplia `service_tickets` com `OTHER`, preservando dados e índices existentes |
| 10 | `RankSyncService`, estado de sync do membro e histórico append-only |
| 11 | salas privadas persistentes de ticket |
| 12 | entrega/arquivo idempotente de cadastros analisados |
| 13 | catálogo, requisitos e solicitações de cursos |
| 14 | mínimo de patrulha, classificação de calls/segmentos, validação e overrides append-only |
| 15 | prontidão operacional, patrulhas e snapshots de estado |
| 16 | outbox de ações originadas no Centro de Comando Web |
| 17 | formulários, blocos e candidaturas versionadas de recrutamento |
| 18 | contexto, execução e achados do Robô Analista |
| 19 | eventos e controles persistentes de segurança |
| 20 | comandante de patrulha e histórico de atribuições |
| 21 | Portaria, gate de cadastro e conformidade de identidade |
| 22 | controles, prioridade e histórico de tickets |
| 23 | perfis RBAC, identidade e reconciliação Discord/Web |
| 24 | conformidade de patente sem cadastro em 72 horas |
| 25 | presença ao vivo nas calls de patrulha |
| 26 | mudanças append-only e sincronização bidirecional de qualificações |

Última versão encontrada e validada localmente e na Discloud: **26**. A próxima migration deve
ser adicionada sem editar as versões aplicadas.

## 14. Modelo de Permissões

`choque/rbac.py` define cinco perfis acumulativos por vínculos de cargo:

- `MEMBRO`: ponto próprio, horas próprias, requests, carreira/disciplina/treinamento/atividade.
- `GRADUADO`: visão ampla de ponto/membros/horas.
- `INSTRUTOR`: gestão de treinamento e revisão de recrutamento.
- `COMANDO`: gestão de membros, pessoal, disciplina, requests, relatórios, tickets e painéis.
- `ADMINISTRADOR`: wildcard `*`.

Owner da guild e humano com `Administrator` recebem bootstrap `*`. Cada callback sensível chama
`PermissionService.has()` ou helper equivalente; esconder o canal não é a única proteção. O ponto
também exige membro ativo e pelo menos um cargo de patente ativo ou o `member_role_id` configurado.

Permissões dos canais são aplicadas pelo remodelador conforme perfil público/membro/privado e
overwrites específicos. O código não precisa de `Administrator`, mas o relatório vivo registrou que
o cargo atual do bot ainda possui essa permissão; remover após validar permissões granulares.

Não existe middleware HTTP, RLS ou autenticação web.

## 15. Autenticação do Painel

NÃO IMPLEMENTADO / NÃO APLICÁVEL. Não há painel web, login, sessão, OAuth, Supabase Auth, callback
ou logout. “Painel” neste projeto significa uma mensagem Discord persistente. A identidade vem do
`discord.Interaction.user`; autorização vem dos cargos da guild e do RBAC persistido.

## 16. Frontend

NÃO IMPLEMENTADO. Não existem diretórios, páginas, layouts, React/Next.js, componentes web ou
dashboard HTTP. Os únicos componentes visuais são embeds e `discord.ui` em `cogs/`.

## 17. Backend / API

Não existe servidor HTTP nem endpoints. A interface externa é a API/Gateway do Discord consumida
por `discord.py`.

| Método | Endpoint | Arquivo | Autorização | Função |
|---|---|---|---|---|
| — | — | — | — | API própria NÃO IMPLEMENTADA |

Os scripts `validate_live_phase*.py` fazem leituras REST da API Discord com o token local para
validar mensagens, componentes e comandos. Eles não expõem uma API do projeto.

## 18. Services / Domain

| Serviço | Arquivo | Regra principal |
|---|---|---|
| `Database` | `choque/database.py` | conexão, migrations, lock de escrita e transações |
| `SettingsService` | `choque/settings.py` | settings, calls, RBAC, painéis e importação legada |
| `AuditService` | `choque/audit.py` | auditoria/outbox e entrega com retry |
| `PermissionService` | `choque/rbac.py` | perfis/cargos → permissões |
| `MemberService` | `choque/members.py` | membros e cadastro/aprovação |
| `ModuleFlagService` | `choque/module_flags.py` | dez módulos ativos/desativados |
| `ShiftService` | `choque/shifts.py` | ponto, segmentos, grace, recovery, totais e ajustes |
| `PersonnelService` | `choque/personnel.py` | carreira, punição, afastamento, ranking e expirações |
| `RequestService` | `choque/requests.py` | requests tipados e aplicação transacional |
| `DisciplineService` | `choque/discipline.py` | ocorrência, advertência e suspensão |
| `TrainingService` | `choque/training.py` | eventos, capacidade, inscrições e qualificações |
| `ActivityService` | `choque/activity.py` | meta/snapshot/inatividade/relatórios |
| `TicketService` | `choque/tickets.py` | candidatura, transferência, denúncia, outro assunto e decisão |

As regras principais estão no domínio, mas ainda há lógica Discord/negócio duplicada nos cogs,
principalmente formatação e sincronização de patente/nickname em `cogs/member_sync.py`,
`cogs/personnel_commands.py` e `cogs/member_commands.py`.

## 19. Realtime / Eventos

Não há Supabase Realtime, WebSocket próprio, Pub/Sub ou broker. O Gateway Discord fornece eventos de
voz/membro/ready. Atualizações de painéis são feitas por edição REST da mensagem.

## 20. Jobs / Workers / Filas

Todos os jobs rodam no processo do bot:

| Frequência | Arquivo | Função |
|---|---|---|
| 60 s | `cogs/shift_commands.py` | heartbeat global |
| 60 s | `cogs/shift_commands.py` | retry da auditoria/outbox |
| 5 min | `cogs/shift_commands.py` | refresh do efetivo em serviço |
| 1 min | `cogs/personnel_commands.py` | ativa/expira suspensão e afastamento, restaura status |
| 30 min | `cogs/activity_commands.py` | fecha semanas concluídas idempotentemente |
| deadline individual | `choque/shifts.py` | task de grace por membro, reconstruída no restart |

Não há Celery, Redis, cron externo ou worker separado. “Fila” de requests/tickets é consulta SQL por
status, não uma message queue. A futura fila de patrulha não existe.

## 21. Auditoria

`AuditService.record()` insere em `audit_logs` dentro da mesma conexão/transação da ação quando
recebe `connection`. Após commit, agenda entrega. O retry busca `PENDING/FAILED`, limita a dez
tentativas e preserva registros quando a guild não está conectada ou o canal ainda não foi
configurado. O embed público de auditoria mostra ação, responsável/alvo, motivo, data e ID.

São auditados: configuração, módulos, cadastro, ponto, ajustes/revisão, status, carreira, disciplina,
requests, treinamento, atividade, tickets, layout/importação e falhas de sincronização relevantes.
Nem todos os `except ...: pass` de refresh/DM geram audit ou log; esses pontos devem ser revisados.
O remodelador visual persiste registry/settings, mas não grava um `CHANNEL_NAME_MIGRATED` por canal.

## 22. Logs e Observabilidade

`choque/logging_config.py` produz uma linha JSON UTC por evento em stderr/stdout, com `timestamp`,
`level`, `logger`, `message`, `correlation_id` opcional e exception. O runtime local redireciona para
`logs/bot.out.log`/`bot.err.log`. Não há métricas, tracing distribuído, Sentry ou dashboard.

Os scripts live imprimem marcadores como `LIVE_PHASE11_OK` e `LIVE_PHASE12_OK`. O banco mantém
heartbeat, shutdown limpo, falhas da outbox e auditoria. A renderização do separador Unicode não é
observável via API e precisa de teste humano nos clientes.

## 23. Variáveis de Ambiente

Todas as variáveis referenciadas por código existem em `.env.example`:

```env
DISCORD_TOKEN=
DATABASE_PATH=data/choque_bgr.db
DEFAULT_GUILD_ID=
LOG_LEVEL=INFO
BRANDING_LOGO_URL=
```

- `DISCORD_TOKEN`: token atual do bot; `TOKEN` existe somente como fallback obsoleto com warning.
- `DATABASE_PATH`: caminho do SQLite.
- `DEFAULT_GUILD_ID`: guild inicial/única.
- `LOG_LEVEL`: nível do logging.
- `BRANDING_LOGO_URL`: logo opcional nos embeds.

`.env` é ignorado pelo Git. Não copie seu conteúdo para documentação. O token já compartilhado no
histórico da conversa deve ser tratado como comprometido e regenerado antes de produção.

## 24. Infraestrutura

- `discloud.config`: `TYPE=bot`, `MAIN=main.py`, nome `CHOQUE-BGR`, RAM declarada 900 MB.
- Scripts PowerShell: operação local em Windows.
- SQLite local: pressupõe armazenamento persistente e uma única instância.
- Backups do layout Discord: `data/server_layout_backups/`, ignorados pelo Git.
- Backup pré-migration: ao lado do banco, também ignorado.

Não existem Dockerfile, compose, Railway, Vercel, Supabase ou pipeline CI. O deploy Discloud ainda é
pendência de rollout, não foi possível determiná-lo como ativo pelo repositório.

## 25. Segurança

### Já implementado

- `.env`, bancos, config real, logs e backups ignorados pelo Git.
- RBAC no backend das interactions sensíveis; bootstrap controlado por owner/admin humano.
- queries parametrizadas; f-strings SQL observadas usam operadores/ordens internos previamente
  validados, não SQL arbitrário do usuário.
- validações de estado e campos no domínio.
- foreign keys, WAL, busy timeout, transações e constraints parciais.
- updates condicionais contra decisões/finalizações concorrentes.
- respostas pessoais ephemeral e denúncia armazenada sem publicação pública do conteúdo.
- auditoria transacional e IDs de correlação em erros.
- canais administrativos/auditoria/arquivo com overwrites privados.

### Problemas encontrados

1. O token foi exposto na conversa anterior. Regeneração é obrigatória antes de produção.
2. O cargo do bot foi observado com `Administrator`, embora o código não dependa disso.
3. A árvore Git está muito modificada e sem commits das Fases 1–12; um reset pode destruir todo o
   trabalho moderno.
4. `data/choque_bgr.db`, `.env`, `config.json` e backups não são versionados. Outro ambiente precisa
   de provisionamento/restauração explícita.
5. `MemberService.review_application()` usa `UPDATE ... WHERE status='PENDING'`, mas não verifica
   `rowcount`; duas análises concorrentes podem continuar após uma perder a corrida.
6. O código limpa/sincroniza comandos da guild, mas não há verificação/limpeza explícita de comandos
   globais antigos. O validador atual consulta comandos da guild.
7. Não há lock distribuído/lease contra uma instância local e uma Discloud usando o mesmo banco/token.
8. Vários erros Discord best-effort são silenciados com `pass`, reduzindo evidência operacional.
9. Não há throttle de negócio por usuário para spam de modais/interactions; constraints protegem
   duplicidades persistentes, não volume de requisições.

### Melhorias recomendadas

- regenerar token e remover `Administrator` após teste de permissões granulares;
- criar commit/branch de checkpoint sem versionar secrets/dados;
- corrigir concorrência da análise de cadastro e testá-la;
- verificar também comandos globais da application;
- garantir singleton no ambiente definitivo;
- substituir catches silenciosos por logs estruturados quando não forem DMs opcionais;
- não abrir API externa sobre este SQLite sem reavaliar ADR 002.

IDOR, XSS, CSRF, mass assignment e RLS web não se aplicam porque não há web/API. Spoof de IDs é
mitigado usando `Interaction.user` e objetos selecionados da guild; fluxos administrativos ainda
devem manter guards antes de qualquer service call.

## 26. Concorrência e Idempotência

### Proteções existentes

- SQLite `BEGIN IMMEDIATE` + um write lock no processo serializam transações.
- ponto: `KeyedLockPool`, índice `ux_active_shift_per_member`, índice de segmento aberto, updates
  condicionais e deadline esperado no grace.
- requests/tickets/afastamentos/suspensões: índices parciais e updates por status/`rowcount`.
- treinamento: unique enrollment, capacidade conferida na transação e updates condicionais.
- carreira: compare-and-set de `rank_id`; direção validada.
- atividade: unique snapshot por membro/período e fechamento idempotente.
- painéis: lock por cog e `panel_type` estável.
- auditoria: `correlation_id` único e outbox após commit.

### Riscos

- as proteções em memória não atravessam processos;
- análise de `member_applications` e solicitações de curso usam update condicional/`rowcount`;
- sincronização Discord acontece após commits em vários fluxos; `RankSyncService` reconcilia
  patente/nickname, mas recusas externas de hierarquia ainda precisam de intervenção humana;
- callbacks Discord podem ser repetidos; fluxos com update condicional resistem melhor que fluxos
  apenas read-then-write;
- a Central de Patrulha usa índices parciais e lock por guild; a garantia singleton ainda depende
  de uma única instância de runtime enquanto o banco for SQLite;
- decisões concorrentes críticas são protegidas no banco; a proteção singleton ainda depende do
  processo/ambiente de deploy.

## 27. Estado das Funcionalidades

| Módulo | Estado | Frontend | Backend | Banco | Discord | Observações |
|---|---|---|---|---|---|---|
| Cadastro/aprovação | IMPLEMENTADO | — | sim | sim | painel/modal/admin | decisão concorrente coberta |
| RBAC/configuração | IMPLEMENTADO | — | sim | sim | central com 8 áreas | bootstrap owner/admin |
| Bate-ponto por voz | IMPLEMENTADO | — | sim | sim | 4 botões + listeners | 11 calls autorizadas/classificadas |
| Tempo mínimo em patrulha | IMPLEMENTADO | — | sim | migration v14 | painel/config/admin | 15 min persistidos; faixa 5–120 |
| Central/Fila de Patrulha Inteligente | IMPLEMENTADO | — | `OperationsService` | migration v15 | 8 botões + listener | FIFO, move e rollback |
| Solicitações administrativas | IMPLEMENTADO | — | sim | sim | 8 botões + fila | inclui troca consensual |
| Carreira/promoção/rebaixamento | IMPLEMENTADO | — | sim | sim | painel e confirmação | ação por painel funciona |
| Sync automático patente/cargo/nick | IMPLEMENTADO | — | `RankSyncService` | histórico v10 | listener/debounce/recovery | warning externo de hierarquia |
| Disciplina | IMPLEMENTADO | — | sim | sim | painéis/modal | fatos não punem automaticamente |
| Afastamento/reserva/suspensão | IMPLEMENTADO | — | sim | sim | requests + cargos | job de expiração 1 min |
| Treinamentos/cursos | IMPLEMENTADO | — | eventos + catálogo | migrations v13/v15 | 2 painéis + admin | requisitos estendidos e avaliação |
| Atividade semanal/relatórios | IMPLEMENTADO | — | sim | sim | painel/admin | sem punição automática |
| Recrutamento/transferência | IMPLEMENTADO | — | sim | sim | painéis/fila | aprovação vira cadastro pendente |
| Denúncia privada/tickets | IMPLEMENTADO | — | sim | sim | modal/fila/sala privada | arquivo preserva histórico |
| Auditoria/outbox | IMPLEMENTADO | — | sim | sim | canal + retry | máximo 10 tentativas |
| Feature flags/manutenção | IMPLEMENTADO | — | sim | settings + v15 | 11 módulos | não apagam dados |
| Layout visual v2 | IMPLEMENTADO | — | formatter/registry/migrador | registry | 19 categorias/97 canais | `U+00B7`, fallback `U+30FB` |
| Eventos operacionais | IMPLEMENTADO | — | `domain_events` | migration v15 | resumo privado | eventos idempotentes |
| Escala/troca de atividade | IMPLEMENTADO | — | consentimento + Comando | migration v15 | Central do Membro/Admin | nunca troca sem aceite |
| Disponibilidade/prontidão | IMPLEMENTADO | — | estados derivados | migration v15 | Central de Patrulha | sem polling por segundo |
| Matriz de qualificação | IMPLEMENTADO | — | cursos existentes | migrations v13/v15 | pessoal/admin | requisitos automáticos |
| Elegibilidade de promoção | IMPLEMENTADO (consultivo) | — | diagnóstico | dados existentes | submenu privado | nunca promove automaticamente |
| Dossiê funcional | IMPLEMENTADO | — | agregador privado | múltiplas tabelas | submenu RBAC | sem duplicar dados |
| Painel web/dashboard | NÃO IMPLEMENTADO | não | não | — | — | nenhum código web |
| API/backend HTTP | NÃO IMPLEMENTADO | — | não | — | — | monólito Discord apenas |
| Integração MTA | NÃO IMPLEMENTADO | — | não | não | não | somente campos de nick/personagem |
| Farm/Caixa/Resgate | NÃO IMPLEMENTADO (ativo) | — | legado desativado | tabelas preservadas | não carregado | não reativar diretamente |

## 28. Funcionalidades Implementadas

- migrations/backup e SQLite transacional;
- branding, logging UTC e erros com correlation ID;
- configuração visual de 21 canais, calls, cinco cargos de estado, RBAC, ranks, regras, 13 tipos de
  painel e dez módulos;
- importação idempotente de configuração/ranks legados;
- cadastro pendente e análise;
- ponto com segmentos, grace, recovery, heartbeat, revisão, ajustes e painel de efetivo;
- solicitações, carreira, disciplina, afastamentos e expirações;
- treinamentos, presença, resultado e qualificações;
- atividade semanal, snapshots, inatividade e relatórios;
- recrutamento, transferências, denúncias, outros assuntos e fila administrativa;
- auditoria/outbox;
- layout por ID com snapshot e registry persistido;
- runtime local com PID e validadores ao vivo.
- Operações Inteligentes com fila/patrulhas, prontidão, flags, integridade, identidade, matriz,
  recrutas, dossiê, inbox, trocas, decisões e manutenção.

## 29. Funcionalidades Parciais

### Sincronização de patente/cargo/nickname

**IMPLEMENTADA na Fase 13.** `RankSyncService` é a única autoridade de sincronização; usa cargos
Discord como verdade operacional, formato `[ABREVIAÇÃO] NOME [ID]`, histórico append-only,
debounce, locks descartáveis, políticas de múltiplos/sem cargo, enforcement e reconciliação de
startup. O rollout real reconciliou 3/3 membros. Há apenas uma configuração externa pendente: mover
o cargo do bot acima de Comandante Geral para que o Discord permita alterar o apelido desse usuário.

### Matriz de qualificação e dossiê

**IMPLEMENTADOS na Fase 15.** A matriz reutiliza `member_qualifications` e o catálogo; o dossiê
agrega dados existentes sem cópia. Patente, horas, tempo, suspensão e pré-requisito são conferidos
server-side, e elegibilidade nunca executa promoção.

### Layout visual

**IMPLEMENTADO E REMEDIADO.** `choque/channel_names.py` usa `U+00B7` entre palavras e `U+30FB`
como fallback. `scripts/migrate_channel_names.py` resolve os 97 canais fixos pelo registry e salas
dinâmicas por `ticket_rooms`, altera somente o nome do mesmo ID, valida a menção e reconcilia os
labels das calls autorizadas. A segunda varredura ao vivo terminou sem divergências.

## 30. Funcionalidades Não Implementadas

- módulo funcional de eventos;
- Centro de Comando Web, autenticação, dashboard, API e realtime externo; especificação completa em
  `docs/COMMAND_CENTER_WEB_SPEC.md`;
- sistema web completo de alistamento/processo seletivo, form builder, avaliação controlada,
  entrevistas e conversão em recruta; o fluxo básico atual do bot permanece implementado e deve ser
  integrado conforme `docs/RECRUITMENT_INTEGRITY_SYSTEM_SPEC.md`;
- Robô Analista de Candidaturas somente leitura: implementado localmente na migration v18, com
  provider desativado por padrão e sem envio de dados reais; rollout externo ainda não autorizado;
- hardening completo da futura arquitetura web/API/Supabase/Railway; o baseline atual do bot está
  descrito na seção 25 e o programa final está em `docs/SECURITY_HARDENING_SPEC.md`;
- integração MTA;
- múltiplas instâncias/PostgreSQL;
- deploy/monitoramento definitivo confirmado na Discloud.

## 31. Bugs Conhecidos Encontrados

### Separador visual incompatível entre clientes

- Estado: RESOLVIDO EM 2026-08-22.
- Impacto anterior: palavras coladas ou quadrados `□` em nomes de canais.
- Arquivos: `choque/channel_names.py`, `scripts/remodel_discord_layout.py`,
  `docs/CHANNEL_NAMING_STANDARD.md`.
- Causa confirmada: `U+17B5` era preservado pela API, mas não tinha glifo uniforme; sete fillers,
  incluindo `U+3164` e `U+2800`, foram removidos pela API atual.
- Correção: `U+00B7` visível, `U+30FB` como fallback, snapshot e edição por ID. Foram migrados 68
  canais fixos e uma sala dinâmica; dez labels de call foram reconciliados e `review=0`.

### Análise concorrente de cadastro

- Estado: RESOLVIDO E VALIDADO.
- `review_application()` usa update condicional/`rowcount`; somente um revisor vence, e publicação
  idempotente no histórico ocorre antes da remoção da mensagem pendente.

### PID do bot apontava apenas para o launcher Python

- Estado: RESOLVIDO EM 2026-08-22.
- Impacto anterior: `stop_bot.ps1` podia encerrar o launcher e deixar o runtime filho conectado.
- Correção: start/status/stop localizam todos os processos pelo caminho absoluto exato do
  `main.py`; o teste real encerrou os dois PIDs, confirmou offline e iniciou uma única instância.

### Divergência de patente/nickname

- Estado: RESOLVIDO NO CÓDIGO E VALIDADO AO VIVO.
- `choque/rank_sync.py` centraliza cargos, banco, nickname, histórico e auditoria; o listener fica em
  `cogs/rank_sync_system.py`.
- Ressalva ambiental conhecida: `NICKNAME_PERMISSION_ERROR` no Comandante Geral enquanto o cargo do
  bot estiver abaixo dele. A falha não reverte o banco nem entra em retry infinito.

### Risco de comandos globais antigos

- Estado: risco a verificar, não reproduzido.
- O startup limpa e sincroniza a árvore da guild; não consulta/limpa explicitamente comandos globais
  da application. Os validadores reportam zero comandos de guild.

## 32. Dívidas Técnicas

- árvore Git principal muito suja e sem checkpoint das Fases 1–12;
- arquivos grandes: `cogs/config_ui.py` (~1780 linhas), `cogs/personnel_commands.py` (~1088),
  `scripts/provision_discord_layout.py` (~1080), `choque/personnel.py` (~889);
- classes `ErrorView/AdminView/ErrorModal` repetidas entre cogs;
- 46 slash handlers legados ainda carregados localmente apesar da operação zero-command;
- `scripts/provision_discord_layout.py` mantém implementação visual intermediária extensa, embora
  seu `main()` delegue ao remodelador v2;
- IDs conhecidos do layout estão hardcodedados para bootstrap no script; depois do bootstrap a
  fonte operacional é `discord_layout_registry_v2`;
- serviços acessam SQL diretamente, sem repositories; aceitável no monólito, mas aumenta tamanho;
- payloads de requests/tickets em JSON reduzem tipagem/migrations de campos;
- catches silenciosos em refresh/DM;
- validadores live possuem números de fase/migration/componentes hardcodedados e precisam ser
  atualizados junto com novas fases;
- não há CI, coverage report, type checker ou testes E2E de UI Discord;
- documentação intermediária contém fatos históricos que podem ficar obsoletos; este handoff deve
  ser atualizado por fase.

## 33. Decisões Arquiteturais Existentes

1. Monólito modular: `docs/adr/001-monolito-modular.md`.
2. SQLite transacional para uma única instância: `docs/adr/002-sqlite-transacional.md`.
3. Ponto por timestamps/segmentos, sem contador por segundo: `docs/adr/003-ponto-por-timestamps.md`.
4. Discord é a interface; não há painel web nesta etapa.
5. Operação publicada é por componentes, sem comandos remotos de guild.
6. Decisões disciplinares, promoção e atividade são humanas; indicadores não punem automaticamente.
7. Históricos e ajustes são append-only; não reescrever segmentos originais.
8. Mensagens persistentes são reutilizadas por ID.
9. Farm/Caixa/Resgate permanecem legados e desativados.
10. IDs e identificadores internos são fonte de integração; nomes visuais são apresentação.
11. PostgreSQL só deve ser reconsiderado com API externa concorrente ou múltiplas instâncias.

## 34. Regras de Negócio Descobertas

- membro precisa existir, estar `ACTIVE`, possuir cargo autorizado e estar em call autorizada para
  iniciar ponto;
- um membro não pode ter dois shifts ativos/grace; um shift não pode ter dois segmentos abertos;
- tempo fora da call nunca conta; grace fecha no instante da saída válida;
- `REVIEW_REQUIRED` não entra nos totais até decisão;
- ajuste de horas é append-only e não altera segmentos;
- perda de cargo, suspensão, reserva, afastamento/desligamento efetivo encerram ponto conforme fluxo;
- patentes têm nível ordenado; promoção sobe e rebaixamento desce;
- promoção/rebaixamento exigem alvo, motivo e confirmação humana;
- ocorrência disciplinar não é punição automática;
- suspensão pode ser futura, é única enquanto agendada/ativa e restaura status efetivo no fim;
- ausência e requests possuem no máximo um pendente do tipo por membro conforme índices;
- inscrição em treinamento exige membro ativo, respeita capacidade e não duplica;
- conclusão de curso exige decisão dos participantes e preserva aprovados/reprovados/ausentes;
- fechamento semanal é idempotente e reserva/afastamento geram isenção;
- atividade/inatividade não cria punição;
- candidato não pode ter duas solicitações abertas do mesmo tipo;
- denúncia não pode ter o próprio autor como alvo;
- aprovação de candidatura cria `member_application` pendente, não aprova membro diretamente;
- desativar módulo bloqueia novas interactions sem apagar dados ou interromper recovery necessário;
- novas calls de layout não contam para ponto sem configuração explícita.

## 35. Arquivos Mais Importantes

### Leia estes arquivos primeiro

1. `PROJECT_HANDOFF.md` — estado e prioridades.
2. `main.py` — entrypoint, check e erros de login/intent.
3. `choque/bot.py` — composição, cogs, intents e remoção de comandos.
4. `choque/database.py` — schema/migrations/transações.
5. `choque/services.py` — mapa dos serviços.
6. `choque/shifts.py` — ponto e concorrência.
7. `cogs/shift_commands.py` — listeners de voz, recovery e jobs.
8. `choque/settings.py` — configuração, calls, painéis e importação.
9. `choque/rbac.py` — autorização.
10. `choque/members.py` — cadastro e bug concorrente conhecido.
11. `choque/personnel.py` — carreira, punições e expirações.
12. `choque/requests.py` — aplicação transacional de requests.
13. `choque/discipline.py` — ciclo disciplinar.
14. `choque/training.py` — treinamento/qualificação.
15. `choque/activity.py` — snapshots e relatórios.
16. `choque/tickets.py` — recrutamento/tickets.
17. `choque/audit.py` — outbox.
18. `cogs/config_ui.py` — Central de Configuração.
19. `choque/rank_sync.py` — autoridade central de patente, cargo, nickname e histórico.
20. `cogs/rank_sync_system.py` — listener com debounce e reconciliação de startup.
21. `cogs/personnel_commands.py` — Central Administrativa.
22. `cogs/member_sync.py` — adaptadores finos para `RankSyncService` e status.
23. `choque/channel_names.py` — formatter central remediado com `U+00B7` e fallback `U+30FB`.
24. `scripts/remodel_discord_layout.py` e `scripts/migrate_channel_names.py` — registry, layout e
    migração segura dos 19 grupos/97 canais e salas dinâmicas.
25. `docs/RANK_SYNC_SPEC.md` — contrato concluído da Fase 13.
26. `docs/MINIMUM_PATROL_TIME_SPEC.md` — contrato concluído da Fase 14.
27. `docs/INTELLIGENT_OPERATIONS_EXPANSION_SPEC.md` — expansão/Patrulha Inteligente.
28. `docs/COMMAND_CENTER_WEB_SPEC.md` — programa web com seis subfases e uso do Lovable.
29. `docs/PHASE_QUEUE.md` — ordem oficial de continuidade.
30. `docs/RECRUITMENT_INTEGRITY_SYSTEM_SPEC.md` — alistamento web integrado, antes do hardening final.
31. `docs/RECRUITMENT_AI_ANALYST_SPEC.md` — análise assistida por IA, sem decisão automática.
32. `docs/SECURITY_HARDENING_SPEC.md` — último item da fila e gate final de produção.

## 36. Fluxos Críticos

### Início e acompanhamento do ponto

```text
PointPanelView
→ ShiftCommands.handle_panel_action
→ ModuleFlagService + PermissionService
→ ShiftService.start_shift
→ transaction: members + shifts + shift_segments + audit_logs
→ after commit: cargo Em Serviço + painel efetivo + outbox
→ on_voice_state_update
→ handle_voice_transition
→ segmentos / grace / close
```

### Recovery após restart

```text
ShiftCommands.on_ready
→ heartbeat anterior + shifts ACTIVE/GRACE
→ call atual do membro
→ ShiftService.recover_shift
→ continuar / reagendar grace / trocar segmento / REVIEW_REQUIRED
→ heartbeat novo + painel + entrega de auditoria
```

### Aprovação de cadastro

```text
RegistrationPanelView → RegistrationModal
→ MemberService.submit_application
→ PersonnelAdminView → ApplicationDecisionModal
→ MemberService.review_application
→ members/rank inicial/audit
→ sync_registered_member (cargo + nickname no Discord)
```

Há risco concorrente no `review_application`; corrigir antes de ampliar o recrutamento.

### Solicitação administrativa

```text
RequestPanelView/modal/confirmação
→ RequestService.submit (unique pending)
→ fila administrativa
→ RequestDecisionModal
→ RequestService.review (update condicional)
→ status/ajuste/dados/desligamento + audit na mesma transaction
→ apply_discord_result + DM best-effort
```

### Movimentação de carreira

```text
CareerAdminView → member/rank selects → motivo → confirmação
→ PersonnelService.change_rank_to (compare-and-set + personnel_actions + audit)
→ cogs.member_sync.sync_rank_to_discord
→ cargo/nickname Discord
```

O segundo passo não é transacional com Discord e será substituído pelo serviço central de sync.

### Disciplina

```text
DisciplineAdminView
→ ocorrência OU advertência/suspensão com confirmação
→ DisciplineService transaction
→ punishment/occurrence + status + fechamento de shift + audit
→ sincronização do cargo de status
```

### Treinamento

```text
TrainingAdminView → responsável/modal
→ TrainingService.create_training
→ mensagem + TrainingEventView persistente
→ enroll/cancel com capacidade transacional
→ decisões de presença/resultado
→ complete_training
→ member_qualifications + mensagem final + audit
```

### Recrutamento/ticket

```text
RecruitmentPanelView/TicketPanelView → modal
→ TicketService.create (unique aberto)
→ RecruitmentAdminPanelView/TicketAdminView
→ decisão condicional
→ candidatura aprovada cria member_application na mesma transaction
→ audit + refresh + DM/canal de resultado best-effort
```

### Remodelação de canais

```text
CHANNEL_SPECS (key/display name/known ID)
→ format_channel_name
→ snapshot do servidor
→ registry/known ID resolve canal
→ edit no mesmo ID, sem sync forçado de permissions
→ persist discord_layout_registry_v2
→ fetch API + validação
```

## 37. Como Executar Localmente

Requer Python 3.12 e Windows para os scripts PowerShell.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Preencha localmente `DISCORD_TOKEN` e `DEFAULT_GUILD_ID`; não versione a `.env`.

```powershell
python main.py --check
python main.py
```

Ou use o guard de processo:

```powershell
.\scripts\start_bot.ps1
.\scripts\status_bot.ps1
.\scripts\stop_bot.ps1
```

Layout, sempre com bot parado para não abrir duas conexões Gateway com o mesmo token:

```powershell
python -m scripts.provision_discord_layout
python -m scripts.provision_discord_layout --apply
```

O entrypoint público delega para `scripts/remodel_discord_layout.py`. Sem `--apply` apenas inventaria
e faz backup; com `--apply` altera a guild. O separador já foi remediado, mas todo novo rollout deve
continuar usando snapshot, dry-run e IDs.

## 38. Como Testar

Instale dependências dev:

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest -q
python -m compileall -q choque cogs scripts tests main.py
python main.py --check
```

Validação real, com token/guild e bot/layout no estado esperado:

```powershell
python -m scripts.validate_live_phase11
python -m scripts.validate_live_phase12
python -m scripts.sync_rank_roles
```

Não há typecheck configurado (mypy/pyright), build web, testes de browser ou E2E automatizado do
cliente Discord.

## 39. Estado dos Testes

Última contagem local validada em 2026-08-22: **141 testes aprovados**. Cobertura funcional inclui:

- migration/backup/import legado/RBAC/timezone;
- dez cenários obrigatórios do ponto, concorrência e recovery;
- outbox e identidade de painéis;
- configuração, paginação de todos os canais/cargos e reconciliação ordenada das 21 patentes;
- carreira, punições, afastamentos e ranking;
- requests e decisões concorrentes;
- disciplina e suspensão;
- treinamento/capacidade concorrente/qualificação;
- atividade/snapshots/inatividade;
- tickets/recrutamento/outros assuntos/privacidade/concorrência;
- os 12 cenários obrigatórios de RankSync, nickname oficial, startup, debounce, histórico e falhas;
- formatter/estrutura estática do layout.
- Fase 14 com limiar, segmentos, invalidação, override e filtros de totais;
- Fase 15 com FIFO 1/2/3/4, reserva/rollback/encerramento, feedback privado, manutenção,
  integridade, requisitos de curso, avaliação, recruta, elegibilidade sem promoção, dossiê, troca
  consensual, flags não punitivas, inbox e views persistentes.

Sem cobertura suficiente:

- edição real do apelido de Comandante Geral até o cargo do bot ser elevado acima dele;
- comandos globais antigos;
- inspeção humana adicional em Discord Mobile após atualização futura do cliente;
- deploy simultâneo local/Discloud (continua proibido e depende de operação externa);
- movimento real de duas contas QA entre calls; o fluxo e rollback estão cobertos localmente, e a
  configuração/painéis/calls foram validados ao vivo.

## 40. Último Estado Validado

Atualizar esta seção ao término de cada fase, somente depois de executar as validações. Estado
registrado em 2026-08-22:

```text
Typecheck: NOT CONFIGURED
Lint (Ruff): PASS - All checks passed
Tests: PASS - 141 passed
Compile/import smoke: PASS
main.py --check: PASS - migration 15, 15 cogs, 46 handlers locais, 21 views persistentes
Live RankSync: PASS - 3/3 membros reconciliados, 21 patentes e painel com contagens reais
Live RankSync warning: apelido do Comandante Geral bloqueado por posição do cargo do bot; auditado
Live Phase 11: PASS - componentes 3/5/3/10, settings 7/7, modulos ativos
Outro assunto: PASS - ticket real OTHER pendente, auditado e foreign_key_check sem erros
Live Ranks: PASS - 21 patentes em níveis 1-21, painel com 21 campos; Alto Comando/Xenon ignorados
Live Phase 12: PASS na API - 19 categorias, 97 canais fixos, 1 sala dinâmica e 12 calls autorizadas
Visitor permissions: PASS - conta real sem cargos enxerga somente as quatro categorias publicas
Ticket room: PASS - sala arquivada privada, solicitante negado, 11/11 cargos de Comando e bot
Application archive: PASS - historico privado por registry, 3 legados, 0 entregas pendentes
Presentation: PASS - 6/6 paineis, 3/3 canais de parcerias e medalhas historicas preservadas
Renderizacao Phase 12: PASS - U+00B7 aplicado; 69 nomes, 10 labels e zero revisoes pendentes
Course catalog: PASS - 9/9 fontes, 9 cursos, 10 requisitos, 9 botoes e zero cargos ausentes
Minimum patrol: PASS - minimo 15, 12 calls classificadas, schema 7/7 e zero comandos
Intelligent operations: PASS - 13/13 tabelas, 1 call espera, 11 ativas, paineis 3/3, botoes 8/3/5
Build web: NOT APPLICABLE
Runtime local: PASS - bot online em Python 3.13.13
```

## 41. Próximas Prioridades

### P0 — Crítico

1. ✅ Visibilidade de visitantes corrigida por registry/ID e validada com conta real sem cargos.
2. ✅ Tickets criam e mencionam sala privada real, com fechamento e arquivamento persistentes.
3. ✅ Cadastro analisado sai da fila após publicação idempotente no histórico; corrida corrigida.
4. Regenerar o token se ainda for o que foi compartilhado e confirmar que nenhum secret entrou no
   Git/log/documentação.
5. Criar branch/commit de checkpoint da árvore atual, revisando as deleções legadas e sem adicionar
   `.env`, DB, `config.json`, logs ou backups.
6. Garantir que nunca existam instância local e Discloud simultâneas no mesmo ambiente operacional.
7. Mover manualmente o cargo do bot acima de Comandante Geral e executar novamente
   `python scripts/validate_live_rank_sync.py` para eliminar o único warning de nickname.

### P1 — Alta

1. ✅ Painéis de cadastro e bate-ponto refeitos nas mesmas mensagens com identidade militar.
2. ✅ Sete medalhas históricas conferidas e publicadas em quadro persistente consultável.
3. ✅ Transferências e Parcerias remodelada nos mesmos três canais, com botões e histórico intacto.
4. ✅ Separador visual corrigido por formatter/IDs com `U+00B7`; fallback `U+30FB` não foi necessário.
5. ✅ Catálogo histórico concluído com 9 cursos, 10 requisitos e análise administrativa.
6. ✅ Mínimo de patrulha implementado e validado na Fase 14.
7. ✅ Operações Inteligentes implementadas e validadas na Fase 15.
8. Executar os fluxos críticos com contas reais MEMBRO/INSTRUTOR/COMANDO e remover `Administrator`
   do bot após confirmar permissões granulares.

### P2 — Média

1. ✅ Expansão de Operações Inteligentes/Central de Patrulha concluída na migration v15.
2. Reduzir duplicação de UI/error handlers e separar os cogs gigantes sem alterar custom IDs.
3. Adicionar verificação de comandos globais e melhorar logs de falhas best-effort.
4. Criar CI com Ruff, pytest, compile e `--check` sobre banco temporário.

### P3 — Baixa

- ✅ Centro de Comando Web concluído localmente conforme `docs/COMMAND_CENTER_WEB_SPEC.md`, com
  skill de frontend design, protótipo Lovable revisado e ADRs 004–007;
- executar `docs/RECRUITMENT_INTEGRITY_SYSTEM_SPEC.md` depois do Centro Web, reutilizando o
  recrutamento básico, RankSync, outbox e core existentes, com Lovable nas interfaces;
- executar `docs/RECRUITMENT_AI_ANALYST_SPEC.md` depois do recrutamento completo, mantendo IA
  somente leitura, decisão humana, provider desacoplado e Lovable restrito à interface;
- executar o programa `docs/SECURITY_HARDENING_SPEC.md` depois do Robô Analista como gate
  final; os controles básicos de segurança continuam obrigatórios durante todas as fases;
- eventos operacionais;
- integração MTA;
- reconsiderar Farm/Caixa/Resgate somente com requisitos e migration próprios.

## 42. Próximo Passo Recomendado

Os Lotes 0 e 1, as Fases 13–15 e o Programa Centro de Comando Web estão concluídos localmente. O
próximo item é o Sistema de Alistamento, Recrutamento e Integridade de
`docs/RECRUITMENT_INTEGRITY_SYSTEM_SPEC.md`. A ordem completa, encerrando com o Security Hardening
depois do recrutamento e Robô Analista, está em `docs/PHASE_QUEUE.md`.

## 43. NÃO QUEBRAR / NÃO REESCREVER SEM ANÁLISE

- Não rode `git reset --hard`, checkout destrutivo ou descarte a árvore suja: o trabalho novo ainda
  não está em commits.
- Não versione nem exponha `.env`, `config.json`, `data/`, bancos, logs ou backups.
- Não edite migrations 1–8; crie a próxima.
- Não remova tabelas/linhas legadas durante migration.
- Não altere custom IDs persistentes `choque:*:v1` sem compatibilidade.
- Não envie novos painéis quando existe `panel_type`/`message_id`; edite a mensagem.
- Não use nome visual para localizar canal; use registry/settings/panel IDs.
- Não recrie canais para renomear: preservar IDs, histórico, posição e overwrites.
- Não reescreva segmentos de ponto; ajustes são append-only.
- Não transforme indicadores de atividade/elegibilidade em punição/promoção automática.
- Não carregue `legacy/` em `COGS`.
- Não execute duas instâncias com o mesmo token/banco.
- Não transforme SQLite em backend multi-instância sem nova decisão arquitetural.
- Não presumir que categoria/call visual significa feature implementada.

## 44. Cuidados ao Continuar

- Atualize este `PROJECT_HANDOFF.md` ao concluir cada fase.
- Pare o bot antes de provisionar/remodelar o Discord.
- Faça snapshot do banco/layout antes de migrations/alterações em massa.
- Use transaction + auditoria no mesmo commit para toda ação funcional.
- Faça efeitos Discord somente após commit e registre divergência/falha.
- Adicione constraint/update condicional e teste concorrente em toda fila/decisão nova.
- Reuse `ModuleFlagService`, `PermissionService`, branding e error handling.
- Mantenha respostas pessoais ephemeral e dados de denúncia privados.
- Valide limits do Discord: cinco componentes por row, 25 options por select, 100 chars de nome,
  32 chars de nickname e 1024 por field.
- Ao mexer no rank sync, evite loops de `on_member_update`, use debounce e locks descartáveis.
- Ao criar Patrulha Inteligente, modele a fila no banco; não dependa só de memória.
- Execute Ruff, pytest, compile, `--check` e validadores live proporcionais à fase.

## 45. Pendências de Configuração Externa

- token regenerado no Discord Developer Portal;
- `Server Members Intent` habilitado;
- permissões granulares do bot e posição do cargo acima dos cargos gerenciados;
- remoção de `Administrator` após teste;
- `.env` com guild/caminho/token no host;
- persistência do arquivo SQLite e restauração segura na Discloud;
- garantir apenas uma instância;
- canais/cargos/ranks configurados no banco local/provisionamento;
- teste Desktop/Web/Mobile dos nomes;
- testes com contas reais de cada perfil;
- implantação Discloud e observação de heartbeat/outbox/recovery;
- screenshots do sistema antigo, se ainda forem relevantes.
- Vercel CLI 59.4.0 instalado; projeto externo ainda não vinculado ou publicado;

O protótipo privado Lovable do Centro Web foi criado sem dados/segredos, teve seu diff revisado e
não foi publicado. API FastAPI, Auth.js/Discord OAuth, configuração Vercel/Railway e refresh
convergente existem localmente. Supabase/PostgreSQL, credenciais OAuth, domínio e deploy reais
continuam pendências externas e exigem projeto exclusivo e autorização de rollout.

## 46. Contexto para o Próximo Codex

O repositório saiu de um bot legado para um monólito modular funcional até a Fase 15 e um Centro de
Comando Web local completo. O bot está operacional por painéis, com migration 16 e layout v2
remediado. A árvore contém todo o trabalho moderno ainda sem commits; preserve-a. RankSync,
contagem real, nomes, catálogo de cursos, validação mínima, Operações Inteligentes e Centro Web
estão concluídos. O próximo trabalho de `docs/PHASE_QUEUE.md` é o Sistema de Alistamento,
Recrutamento e Integridade de `docs/RECRUITMENT_INTEGRITY_SYSTEM_SPEC.md`, integrando o fluxo básico já existente
e usando Lovable apenas com fixtures sintéticas. Em seguida, implemente o Robô Analista de
`docs/RECRUITMENT_AI_ANALYST_SPEC.md`, sem autoridade administrativa e com decisão humana. Depois
execute o Security Hardening Completo de
`docs/SECURITY_HARDENING_SPEC.md` como último item e gate de produção, sem adiar os controles
básicos de segurança das fases anteriores.

O frontend está em `web/` e a API em `command_center/`; publicação externa continua ausente.

## 47. Fila Consolidada e Fontes Recuperadas

Em 2026-08-22 foram revisadas 56 mensagens já materializadas, recuperados 12 follow-ups da fila
visual, inspecionadas 6 capturas e preservados 12 prompts extensos. Os textos originais longos estão
em `docs/source-prompts/`, com hashes em `docs/source-prompts/README.md`. O índice de cobertura é
`docs/REQUEST_LEDGER.md`; a ordem executável é `docs/PHASE_QUEUE.md`.

Os 12 pedidos recuperados, sem omissões, são:

1. ✅ Arquivar/retirar da fila a solicitação de membro já analisada e publicar o resultado em log.
2. ✅ Melhorar visual e conteúdo do painel de cadastro.
3. ✅ Refazer a mensagem de medalhas com estética militar.
4. ✅ Melhorar visual, detalhes e identidade militar do bate-ponto.
5. ✅ Criar disponibilidade por botão no canal `1164363506083172413`.
6. ✅ Criar menu de última patrulha/debrief no canal `1540590792522072155`.
7. ✅ Remodelar Transferências e Parcerias, categoria `1540589594691772477`, com botões.
8. ✅ Reimportar os nove cursos históricos de `1162114694581059584`, requisitos e inscrições.
9. Avaliar Vercel + Supabase + Railway na arquitetura futura, com uma única fonte de dados.
10. ✅ Criar e mencionar canal/thread privado por ticket para solicitante, Alto Comando e bot.
11. ✅ Restringir visitantes a Recepção, Ticket, Recrutamento e Transferências/Parcerias.
12. ✅ Corrigir a contagem de pessoas por cargo no painel de hierarquia.

Esses itens permanecem registrados sem omissões. Estão concluídos 1–8 e 10–12, além de
`Outro assunto`, lista das 21 patentes, RankSync e nomes dos canais. O item 9 será decidido no
Programa Web. Tudo continua na ordem de
`docs/PHASE_QUEUE.md`.

## 49. Hotfix de visitantes concluído em 2026-08-22

- Política central em `choque/visitor_access.py`, coberta para todas as 19 categorias e 97 canais.
- Somente `reception`, `ticket`, `recruitment` e `partnerships` são públicas; `ticket.queue`,
  `recruitment.approved` e `recruitment.rejected` permanecem privados.
- O aplicador usa exclusivamente `discord_layout_registry_v2` e preserva IDs, nomes, posições,
  mensagens, históricos e overwrites de outros cargos/usuários.
- Snapshot de rollback:
  `data/server_layout_backups/visitor_permissions_1146622062895579186_20260822T070707Z.json`.
- Validação real: uma conta sem cargos enxergou exatamente as quatro categorias esperadas e nenhum
  canal interno; uma segunda leitura sem escrita confirmou o estado.
- QA: Ruff aprovado e 105 testes aprovados. O próximo item é o canal privado por ticket.

## 48. Fase 13 — RankSyncService concluída em 2026-08-22

### Implementação

- `choque/rank_sync.py` é a autoridade única para patente, cargo e nickname. O cargo de patente no
  Discord é a verdade operacional; banco e histórico são estruturados e nickname nunca é usado
  como parser.
- O formato único é `[ABREVIAÇÃO] NOME [ID]`, produzido por `format_member_nickname()` e limitado
  de forma determinística aos 32 caracteres do Discord.
- `cogs/rank_sync_system.py` compara somente o conjunto final de cargos de patente, ignora cargos
  alheios, restaura nickname manual quando configurado, agrega rajadas por debounce e usa
  tasks/locks descartáveis sem loop.
- A reconciliação de startup percorre somente `members` já cadastrados. Usuários sem cadastro são
  ignorados e nunca criados automaticamente.
- Múltiplas patentes escolhem o maior `ranks.level`, geram `RANK_ROLE_INCONSISTENCY` e só removem
  patentes inferiores quando `auto_remove_old_rank_roles=true`; o padrão seguro é `false`.
- Sem cargo de patente, `KEEP_LAST` preserva a patente anterior e marca `MISSING_ROLE`; a opção
  `MARK_UNSYNCED` remove apenas o vínculo atual, sem apagar histórico.
- Falhas de cargo e nickname produzem respectivamente `ROLE_HIERARCHY_ERROR` e
  `NICKNAME_PERMISSION_ERROR`, depois do commit, sem rollback do banco ou retry infinito.
- Cadastro, alteração de dados, promoção e rebaixamento chamam o serviço central. Uma patente já
  existente no Discord prevalece no cadastro; sem ela, usa-se a menor patente ativa.
- Mudanças manuais geram `rank_sync_events` append-only e aparecem no histórico de carreira com
  origem distinta de promoção/rebaixamento formal.
- O menu **Patentes → Sincronização** configura enforcement de nickname, remoção automática de
  patentes antigas e política sem cargo, sem depender de slash commands.
- O painel de hierarquia conta `Role.members` reais, exclui bots e usa o banco só como fallback em
  modo offline/check.

### Schema, QA e rollout

- Migration v10: `members.rank_sync_status`, `members.rank_sync_checked_at` e
  `rank_sync_events`, com índices por membro/origem e timestamps UTC epoch.
- Backup consistente anterior à migration:
  `data/choque_bgr.db.pre-rank-sync-v10-20260822-034811`, 331776 bytes, SHA-256
  `1E2C85F2A707A3ACCDD4ED4C146B8DEB0D678BEA507028113ACC94D8C5190FDB`.
- `python -m pytest -q`: 91 aprovados; os 12 casos obrigatórios de `RANK_SYNC_SPEC.md` possuem
  testes explícitos em `tests/test_rank_sync.py`.
- Ruff, compile/import smoke e `python main.py --check` aprovados: migration 10, 13 cogs,
  46 handlers locais e 13 views persistentes.
- `python scripts/validate_live_rank_sync.py`: `RANK_SYNC_LIVE_PASS`, 3 cadastrados reconciliados,
  3 eventos de startup, 21 patentes e contagens do painel idênticas aos cargos reais.
- Resultado real: uPaiva → Comandante Geral, Lopes → Comandante e Ricardo → Coronel.
- Única ressalva externa: o Discord devolveu `50013 Missing Permissions` ao alterar o nickname de
  uPaiva, porque o cargo do bot está abaixo de Comandante Geral. O banco ficou correto e a auditoria
  foi criada. Um administrador humano precisa mover o cargo do bot acima de Comandante Geral e
  executar novamente o validador; o bot não pode elevar o próprio cargo por segurança do Discord.
- Runtime final: bot online localmente, PID `17912`, uma única instância confirmada.

## 50. Fase 14 — Tempo mínimo em patrulha concluída em 2026-08-22

### Contrato funcional

- O padrão `minimum_patrol_minutes=15` está centralizado em `SettingsService`, persistido na guild
  e editável apenas na faixa segura 5–120 pelo painel de regras.
- `authorized_voice_channels.service_allowed` controla se a call mantém o ponto;
  `counts_toward_patrol_minimum` controla se ela avança a validação. Cada segmento salva a
  classificação vigente ao entrar e alterações futuras não reescrevem o histórico.
- Sessão abaixo do mínimo fecha como `CLOSED` + `validation_status=INVALIDATED`, motivo
  `MINIMUM_PATROL_TIME_NOT_REACHED`, aparece no histórico e vale zero em horas, ranking, meta e
  relatórios. Não existe punição automática.
- Encerramento manual curto possui confirmação ephemeral vinculada ao usuário e ao shift exato.
  Grace expirado invalida automaticamente. Recuperação usa os segmentos persistidos.
- Override excepcional do Comando preserva `automatic_validation_status=INVALIDATED`, grava
  `validation_source=ADMIN_OVERRIDE`, responsável, justificativa, auditoria e uma linha append-only
  em `shift_validation_overrides`.

### Arquivos e schema

- Migration v14 em `choque/database.py` adiciona classificação das calls/segmentos, estado de
  validação completo e a tabela de overrides.
- `choque/shift_validation.py` é a autoridade compartilhada para progresso, fechamento e filtro de
  sessões contabilizáveis.
- `choque/shifts.py`, `choque/activity.py`, `choque/personnel.py`, `choque/discipline.py` e
  `choque/requests.py` aplicam a regra nas transações e consultas.
- `cogs/shift_commands.py`, `cogs/config_ui.py`, `cogs/personnel_commands.py` e
  `cogs/activity_commands.py` expõem toda a operação por painéis, botões, selects e modais.

### Evidências

- O arquivo `data/choque_bgr.db.pre-minimum-patrol-v14-20260822-080000` foi posteriormente
  identificado como cópia incompleta do arquivo principal com WAL ativo (migration 13). Ele não é
  backup autoritativo e não deve ser usado para rollback sem reconstrução/verificação.
- `tests/test_minimum_patrol.py` cobre os oito cenários temporais obrigatórios, saída confirmada,
  exclusões, snapshot de call, override e concorrência. Suite completa: 131 aprovados.
- Ruff, compileall e `python main.py --check` aprovados; migration 14, 14 cogs, 46 handlers locais,
  18 views persistentes.
- `MINIMUM_PATROL_LIVE_PASS`: mínimo 15, 11 calls, schema 7/7, painéis atualizados e zero comandos
  publicados. Os cinco validadores vivos de regressão também passaram.
- Runtime final: bot online localmente em uma única instância.

## 51. Fase 15 — Operações Inteligentes concluída em 2026-08-22

### Entrega

- Migration v15 adiciona 13 superfícies de persistência para disponibilidade, registry de calls,
  patrulhas, fila FIFO, feedback, flags, integridade, avaliações, trocas, manutenção e eventos. Os
  índices parciais impedem duas entradas atuais na fila, duas patrulhas por membro e duas formações
  na mesma call.
- `choque/operations.py` é a autoridade de domínio. `cogs/operations_commands.py` contém somente
  integração Discord, UI, listener de voz, movimentação/rollback e refresh global de painéis.
- Formação seleciona os mais antigos em grupos do mínimo configurável, reserva banco/call, move os
  integrantes e ativa apenas após sucesso total. Falha devolve os movidos à espera e restaura a fila.
  Formar patrulha nunca inicia o ponto.
- `PATROL_CENTRAL` edita a mensagem no canal `1164363506083172413`; `PATROL_REPORT` edita a do
  canal `1540590792522072155`; `MEMBER_CENTRAL` preserva seu `panel_type/message_id` e reúne ações
  operacionais e links existentes. Consultas pessoais e administrativas são ephemeral.
- Prontidão, flags e integridade são informativos. Correções ambíguas exigem revisão; elegibilidade
  nunca promove, acompanhamento nunca efetiva e flags nunca punem.
- Cursos conferem patente, horas válidas, tempo de corporação, suspensão e pré-requisito. Avaliação
  pós-treinamento persiste presença, resultado, desempenho e observação. Recrutas, dossiê e matriz
  reutilizam dados existentes.
- Troca de atividade segue `WAITING_MEMBER → WAITING_COMMAND → APPROVED/DENIED`; ninguém é trocado
  sem consentimento. Inbox referencia registros de origem. Manutenção bloqueia novas ações do módulo
  com motivo e preserva estados em andamento.
- Scripts de start/status/stop foram corrigidos para controlar todos os processos pertencentes ao
  caminho absoluto deste `main.py`, evitando runtime filho órfão.

### Backup, QA e rollout

- Backup consistente pré-v15:
  `data/choque_bgr.db.pre-intelligent-operations-v15-20260822-082100-consistent`, 475136 bytes,
  migration 14, `integrity_check=ok`, SHA-256
  `362092E9A39886C5F6327D2D25A3DCAD141ABF20CB769DAE18BA7F0D7380C302`.
- `tests/test_intelligent_operations.py` e regressões: **141 testes aprovados**. Ruff, compileall e
  check offline passaram; migration 15, 15 cogs, 46 handlers locais e 21 views persistentes.
- `INTELLIGENT_OPERATIONS_LIVE_PASS`: 13/13 tabelas, uma call de espera, 11 calls ativas, 3/3
  painéis, custom IDs 8/3/5 e zero comandos publicados.
- Regressões reais: Fase 12, mínimo, catálogo, arquivo de cadastros, tickets e Fase 11 passaram. A
  call de espera continua autorizada sem contar para o mínimo; as 11 calls ativas contam.
- Runtime final: bot online em uma única instância lógica; start/status registram os dois PIDs do
  launcher/runtime e stop encerra ambos com confirmação offline.

## 52. Programa Centro de Comando Web concluído localmente em 2026-08-22

- `web/` entrega Next.js 16.3.2 App Router, TypeScript estrito, Auth.js/Discord OAuth, Server
  Components, shell RBAC responsivo e 22 rotas reais para Operação, Efetivo, Administração,
  Inteligência e Sistema. O design segue centro de operações institucional, sem estética SaaS/gamer.
- `command_center/` entrega FastAPI com autenticação HMAC interna, revalidação de membro/RBAC em
  cada request, CORS restrito, endpoints de consulta/decisão/configuração e health check.
- Migration v16 adiciona `web_action_outbox`, `web_access_events` com IP/UA em HMAC e
  `discord_resource_registry`. Promoção e aprovação de membro persistem sincronização Discord na
  mesma transação; o worker aplica cargo/nickname com retry e mantém 213 recursos atuais por ID.
- Calls, canais, patentes e vínculos RBAC são editados por registry/ID. O frontend nunca recebe
  token Discord, `DATABASE_URL`, chave administrativa Supabase ou regra de autorização.
- ADRs 004–007 fixam topologia, OAuth/RBAC, linguagem visual e atualização. `web/vercel.ts`, os dois
  arquivos Railway e `docs/COMMAND_CENTER_DEPLOYMENT.md` preparam o rollout sem provisioná-lo.
- Lovable foi usado em projeto privado não publicado com fixtures sintéticas; o diff foi inspecionado
  e sua colisão de layout não foi copiada. A implementação local foi revisada por screenshots reais
  em 1440, 1280, 1024, 768 e 390 px, sem overflow global ou erros de console.
- Backup consistente pré-v16:
  `data/choque_bgr.db.pre-command-center-v16-20260822-064402`, 651264 bytes, migration 15,
  `integrity_check=ok`, SHA-256
  `37838C26A54D807DC9C9B296CC2D675134ADA88765A7E865CA34639546151C29`.
- QA: Ruff/compileall aprovados, **146 testes Python**, 6 testes Vitest, `npm audit` sem
  vulnerabilidades, typecheck/lint/build aprovados e Playwright em Chromium desktop/mobile e
  Firefox. `main.py --check`: migration 16, 15 cogs, 46 handlers, 21 views.
- Rollout local: bot reconectado, 3 membros reconciliados sem alteração, outbox sem pendências e
  registry com 213 recursos. Supabase, OAuth/domínio e deploy de produção continuam externos e não
  foram executados por segurança.

## 53. Sistema de Alistamento, Recrutamento e Integridade concluído em 2026-08-22

- Migration atual: **17**. O domínio está centralizado em `choque/recruitment.py`; não existe fluxo
  paralelo ao ticket legado. Candidaturas antigas `CANDIDACY` são importadas uma vez e mantêm a
  origem auditável.
- A versão publicada do formulário guarda snapshot imutável de 45 questões e 12 grupos; cada
  candidato recebe 24 questões balanceadas. O enunciado só aparece após início server-side, com
  token HMAC, timer, autosave, expiração e confirmação irreversível.
- Sinais de foco, copiar/colar, tentativa de contexto e similaridade são evidências colapsadas por
  janela. Nunca decidem, pontuam personalidade ou reprovam automaticamente.
- Portal público: `/recrutamento`, `/recrutamento/avaliacao` e `/minha-candidatura`. Administração:
  `/recruitment`, dossiê, campanha, formulário, preview e bloqueios. A API revalida identidade,
  guild, BOLA, RBAC e rate limit.
- Aprovação humana cria/atualiza membro, vínculo de origem, follow-up e `MEMBER_SYNC` de forma
  atômica. Resultado, entrevista e lembretes usam outbox com retry e auditoria.
- QA aprovado: 169 testes Python, Ruff, compileall, check v17; 16 Vitest, typecheck, ESLint, build;
  6 E2E em Chromium desktop/mobile e Firefox. Banco íntegro, FK=0, bot online.
- Snapshot: `data/choque_bgr.db.post-recruitment-v17-20260822-081052` (692224 bytes).
- A campanha padrão permanece `DRAFT`. Abrir campanha, configurar OAuth/domínio e provisionar
  Vercel/Railway/Supabase são operações externas deliberadamente não executadas.
- A continuidade registrada naquele momento foi concluída nas seções 54 e 55 abaixo.

## 54. Robô Analista de Candidaturas concluído localmente em 2026-08-22

- Migration v18 adiciona contexto de avaliação, rubrica/critérios, jobs, resultados e feedback
  versionados. A análise utiliza input hash, cache, retry limitado e preserva todo histórico.
- `choque/recruitment_analysis.py` isola o provider sem tools. A configuração padrão é `disabled`;
  um endpoint OpenAI-compatible/NVIDIA NIM só pode ser ativado com segredo de ambiente e ação de
  Comando. Nenhuma candidatura real foi transmitida nesta entrega.
- Dados enviados são minimizados e estruturados. O backend valida schema estrito, evidências e IDs
  de questão, sanitiza conteúdo ativo, recalcula a nota ponderada e mantém integridade objetiva
  separada da análise qualitativa. A IA nunca decide ou altera o processo.
- `/recruitment/ai` administra provider, rubrica, contexto, qualidade e preview sintético. No dossiê,
  a análise fica recolhida depois das respostas e só aparece para RBAC autorizado; o portal do
  candidato não recebe esses dados.
- QA aprovado: 183 testes Python, Ruff, compileall e check v18; 16 Vitest, typecheck, ESLint, build
  e 6 E2E. Revisão visual 1440/390 px usou banco e candidatos totalmente sintéticos.
- Snapshot pré-v18: `data/choque_bgr.db.pre-recruitment-ai-v18-20260822-084125`, 1007616 bytes.
  Banco oficial em v18 com `integrity_check=ok`, FK=0, uma rubrica/contexto padrão e zero jobs.
  Bot online e conectado após instalar as dependências fixadas no `.venv`.
- Lovable não gerou diff por falta de créditos. Vercel não possui projeto deste app, Railway exige
  reautenticação e os projetos Supabase encontrados eram alheios; nenhum recurso externo foi tocado.
- O Security Hardening subsequente foi concluído localmente e está registrado na seção 55.

## 55. Security Hardening completo concluído localmente em 2026-08-22

- Migration atual: **19**. Eventos de segurança, revogação de sessão, nonce anti-replay e snapshots
  Discord foram adicionados sem apagar legado.
- Autenticação web usa OAuth Discord + sessão segura + HMAC por request; API revalida guild,
  membro, status, RankSync e RBAC. Lockdown, step-up, revogação e auditoria são server-side.
- CI inclui CodeQL, Dependabot, secret scan, dependency audit, SBOM e todo o QA. Dependências
  corrigidas: discord.py 2.7.1 sem extra de áudio não utilizado, FastAPI 0.141.1, Starlette 1.3.1 e
  python-dotenv 1.2.2.
- Backup pré-v19 e restore drill: `data/security_backups/choque_bgr-20260822T125959Z.db`, SHA-256
  `e94b603cdbc4f7ed054c9f657b5a3eeb452afac2b6b09d9b112bf7a594338e14`, integrity ok, FK=0.
- Banco real migrou para v19; backup automático pós-migration foi criado. Bot online. Auditoria real
  registrou CRITICAL porque o cargo gerenciado do bot possui Administrator, Ban/Kick Members,
  Manage Guild/Channels/Webhooks. Isso requer edição humana do cargo no Discord.
- QA: 192 pytest, 16 Vitest, Ruff, compile, check, typecheck, ESLint, build, 6 E2E, audits sem CVEs,
  secret scan e SBOM. Revisão visual `/security` em 1440/390 sem overflow/console errors.
- Matriz completa: 164 implementados, 27 não aplicáveis, 29 pendentes. Veredito atual:
  **FAIL — não pronto para produção pública**, principalmente por token exposto sem rotação e
  controles externos ainda não comprovados.
- Novos prompts foram preservados em `docs/source-prompts/13-*` e `14-*`. A fila agora continua no
  item 18: correção definitiva de nomes com `U+3164`, depois comandante automático, Portaria
  Digital, expansão de tickets e publicação privada GitHub/Vercel.

## 56. Correção U+3164 executada com bloqueio externo em 2026-08-22

- O formatador central gera o caractere por `chr(0x3164)`; o teste direto confirmou `U+3164` em
  todas as fronteiras de palavras locais. O fallback é `chr(0x2800)` e U+30FB ficou exclusivo do
  separador visível do emoji.
- A API real removeu U+3164 e U+2800. Também removeu U+3164 combinado com VS16, CGJ, WORD JOINER,
  ZWJ e ZWNJ. Nenhum canal temporário reteve o codepoint após fetch.
- Por segurança, a migração não foi aplicada. Dry-run identificou 69 recursos e alterou zero.
  Snapshot completo: `data/server_layout_backups/discord_layout_1146622062895579186_20260822T131041Z.json`.
- O migrador passou a executar rollback automático quando o Discord normaliza primário e fallback.
  Nomes atuais continuam legíveis, sem perda de IDs/mensagens/overwrites. A conclusão visual exigida
  permanece tecnicamente bloqueada pela plataforma; não foi falsamente marcada como validada.
- Próximo item em execução: Fase 16, Comandante Automático da Patrulha.

## 57. Fase 16 — Comandante Automático da Patrulha concluída em 2026-08-22

- Migration atual: **20**. `patrols` guarda comandante, momento, origem e lock manual;
  `patrol_commander_history` preserva cada janela de comando e `patrol_operational_flags` envia a
  falta de elegíveis para a inbox sem inventar um responsável.
- A seleção em `choque/operations.py` é determinística/configurável e reutiliza patente/RankSync,
  tempo na patente, horas válidas, antiguidade, suspensões, afastamentos e `member_qualifications`.
  Somente integrantes ativos e presentes na call participam.
- O comandante atual é preservado enquanto elegível por padrão. Saída/perda de elegibilidade gera
  transferência transacional; override manual exige `patrol.commander.override`, motivo e lock,
  mas não impede substituição se o escolhido deixar de ser elegível.
- O submenu `Patrulhas` da Central Administrativa contém encerramento, override, configuração,
  presets de prioridade e histórico. Discord e web exibem o comandante real, e relatórios/feedback
  consultam o histórico em vez de presumir que o primeiro integrante liderou.
- Startup, voz, alteração de cargos e loop global reconciliam patrulhas ativas de forma idempotente.
  `PATROL_COMMANDER_LIVE_PASS`: v20, 2/2 tabelas, 4/4 colunas, 5/5 controles e zero comandos.
- QA completo: 198 pytest, Ruff, compileall, check, 16 Vitest, typecheck, ESLint, build e 6 E2E.
  Bot online em uma única instância; zero patrulhas reais foram criadas durante a validação.
- Rollback v19 verificado em `data/security_backups/choque_bgr-20260822T130039Z.db` (SHA-256
  `4ce50811763de8a900cc52cb18b69abedd342997721730c5be3c378340479f7c`). Snapshot pós-v20:
  `choque_bgr-20260822T132741Z.db` (SHA-256
  `2417ce26877c2220c958699a25ac328747af67267d04f28bafb440621589e871`).
- Próximo item em execução: Fase 17, Portaria Digital / cadastro obrigatório.

## 58. Fase 17 — Portaria Digital / cadastro obrigatório concluída em 2026-08-22

- Migration atual: **21**. `registration_gate_records`, eventos append-only, classificações,
  snapshots, achados e checklists persistem o ciclo completo sem apagar membros, candidaturas ou
  cargos legados. O índice único impede duas identidades BGR ou duas contas Discord ativas.
- `RegistrationGateService` é a autoridade transacional para cadastro próprio, reaproveitamento de
  candidato/membro, duplicidade, reentrada, revisão, correção, vínculo, rejeição, bypass e estado de
  sincronização. Visitante desconhecido nunca vira membro ativo automaticamente.
- O painel público existente foi preservado e movido por ID para Recepção. Ele oferece Cadastro,
  Situação e Ajuda por botão/modal, pedindo somente nick MTA e ID BGR. A Central Administrativa
  ganhou fila, decisão, vínculo, correção, validação de acesso, reconciliação e configuração por
  RoleSelect/ChannelSelect, sem depender de comandos.
- O gate toca somente os cargos gerenciados de não cadastrado, candidato, membro e patente. Owner,
  bots, Administrator e bypass explícito são protegidos. RankSync continua responsável pelo cargo
  e apelido oficial de membros vinculados; a aprovação do recrutamento atualiza o gate e o checklist
  na mesma transação/outbox.
- O Centro de Comando recebeu `/registration`, endpoints RBAC para consulta, decisão e configuração,
  contadores, achados e bloqueadores de ativação. O inbox agrega solicitações e vazamentos do gate.
- Antes do rollout foi criado e restaurado o backup consistente v20
  `data/security_backups/choque_bgr-20260822T141145Z.db` (SHA-256
  `1c7fa2d5bb301346775d416daa78693d438c8ef69ce448d56527e9b2e3f08ac9`). O snapshot reversível do
  Discord é `data/server_layout_backups/registration_gate_1146622062895579186_20260822T141811Z.json`.
- O rollout criou/configurou os cargos gerenciados, preservou o painel e classificou 121 contas sem
  cadastro. `REGISTRATION_GATE_LIVE_PASS` confirmou 96 recursos protegidos, 21 recursos públicos,
  amostra de dez contas reais, zero vazamentos e zero recursos sem classificação. Um usuário com
  patente mas sem identidade vinculada permanece corretamente na Portaria até cadastro/revisão.
- A primeira reconciliação revelou contenção causada pela tentativa de entregar centenas de logs
  imediatamente. A auditoria continua transacional, mas a entrega passou para a outbox/retry global;
  a reconciliação seguinte sincronizou todos os registros sem perda ou duplicação.
- QA da fase: **210 testes Python**, Ruff, compileall, `main.py --check`, **16 Vitest**, typecheck,
  ESLint e build aprovados. A validação E2E final deve permanecer verde antes da publicação.
- Bot online em uma única instância lógica. O gate de segurança público geral continua **FAIL** até
  o token exposto ser rotacionado e o cargo do bot perder Administrator/permissões excessivas.
- Próximo item em execução: Fase 18 — Operação avançada de tickets.

## 59. Fase 18 — Operação avançada de tickets concluída em 2026-08-22

- Migration atual: **22**. Tickets ganharam prioridade, versão e controle de aviso; salas guardam
  categorias, cargo responsável, menção única, reabertura e versão. Participantes, eventos
  operacionais e metadados/hash de transcrições são append-only; o conteúdo da transcrição não é
  persistido no banco.
- `TicketService` centraliza assumir/liberar com concorrência, prioridade, participantes, cooldown de
  notificação, transcrição minimizada com redação de padrões de segredo, fechamento, arquivamento e
  reabertura da mesma sala. Toda mudança relevante grava evento e auditoria transacional.
- A sala possui oito controles persistentes: assumir/liberar, prioridade, adicionar/remover pessoa,
  avisar solicitante, transcrição, reabrir e encerrar. O encerramento exige motivo e `ENCERRAR`, gera
  transcrição final e retira solicitante/participantes do arquivo; Comando/Administrador preservam
  acesso. Reabrir restaura o mesmo canal, histórico e permissões.
- O cargo responsável configurado recebe acesso e uma única menção na abertura. `@everyone` é
  negado; participante recebe somente overwrite individual; membro comum não recebe acesso. A
  confirmação pública continua mencionando a sala criada e “Outro assunto” foi preservado.
- Central Administrativa e `/tickets` no Centro de Comando configuram categorias, cargo responsável,
  canal privado de transcrição e cooldown por ID/registry. A API valida tipo do recurso, categorias
  distintas e posição do cargo do bot.
- Rollout real: duas categorias exclusivas foram criadas; uma sala histórica arquivada foi movida sem
  trocar ID, mensagem, histórico ou nome. Snapshot reversível:
  `data/server_layout_backups/ticket_operations_1146622062895579186_20260822T145310Z.json`.
  A primeira tentativa falhou por duas premissas incorretas do validador e executou rollback completo;
  a segunda passou.
- Backup pré-v22 restaurado:
  `data/security_backups/choque_bgr-20260822T145053Z.db/choque_bgr-20260822T145053Z.db`, migration 21,
  integrity ok, FK=0, SHA-256
  `32e946888773ddc779868b18f9fbeaf96f6f6a7bb514c88d7e52d233bfbe5691`. Backup pós-v22 restaurado:
  `data/security_backups/ticket-v22-20260822T145322Z/choque_bgr-20260822T145322Z.db`, integrity ok,
  FK=0, SHA-256 `ef0cb2d272b65e2f7142e275f0bc1db206ac11da9347bd1382aa3ce9122956c3`.
- `TICKET_OPERATIONS_LIVE_PASS`: 0 salas ativas, 1 arquivada, dez visitantes amostrados, 1/1 painel
  com 8/8 controles e matriz real de permissões aprovada. `TICKET_ROOM_LIVE_PASS` confirmou
  `@everyone` negado, bot e 11/11 cargos de Comando autorizados e solicitante sem acesso ao arquivo.
- QA: **219 pytest**, Ruff, compileall, check v22, **16 Vitest**, ESLint, build, typecheck e **6 E2E**.
  Bot online em uma única instância lógica. O gate público geral segue FAIL até rotação do token e
  redução humana das permissões do cargo do bot.
- Próximo item em execução: publicação final privada no GitHub e Centro de Comando na Vercel.

## 60. Publicação final — GitHub e status Vercel concluídos, rollout operacional retido em 2026-08-22

- Foi criado `https://github.com/EoPaiva/choque-bgr-gestao` como repositório privado. O primeiro
  push usou um commit-raiz gerado por índice Git isolado, sem incluir o histórico antigo que pode
  conter o token comprometido. O índice/worktree original e todas as alterações locais foram
  preservados.
- O snapshot remoto passou `scripts/security_scan.py` e uma inspeção de paths: 292 arquivos, zero
  `.env` real, banco, log, backup, `data/`, `__pycache__`, `config.json`, `ranking_config.json` ou
  `replace.txt`. `.env.example` permanece apenas como template vazio.
- Alertas de vulnerabilidade e correções automáticas foram ativados. Secret scanning/push
  protection não está disponível para esse repositório privado no plano atual. O CI recebeu
  `next typegen` antes do typecheck e permissão `actions: read` para o CodeQL.
- O alerta Dependabot de `pytest < 9.0.3` foi corrigido e fechado. `pytest==9.0.3` com
  `pytest-asyncio==1.4.0` manteve 223 testes verdes. O Security gate remoto passou; CodeQL executa
  `security-extended` com upload desativado somente para o painel indisponível e preserva os SARIF
  como artefatos usando `actions/upload-artifact@v6`.
- A execução CodeQL final passou; a inspeção baixada registrou `python.sarif=0` e
  `javascript.sarif=0`. A tentativa de proteger `main` com checks `validate`/`analyze` recebeu HTTP
  403 porque branch protection em repositório privado exige GitHub Pro; o repositório permaneceu
  privado e essa limitação externa ficou registrada.
- A topologia Railway foi corrigida: SQLite não usa dois serviços. `deploy/railway.combined.toml` e
  `scripts/run_combined.py` executam migrations e supervisionam bot + FastAPI em um único serviço,
  um volume e uma réplica. Os dois TOMLs antigos ficam somente para o corte PostgreSQL futuro.
- `/status` foi publicado em `https://web-plum-tau-82.vercel.app/status`. A página é pública, não
  recebe secrets e mostra 20/22 fases, o gate retido e o estado da publicação. A validação real
  confirmou HTTP 200, título `Centro de Comando | CHOQUE - BGR`, indicadores `20 / 22`, `235+` e
  `RETIDO`, zero erros de console/overlay e renderização responsiva em desktop e mobile.
- QA consolidado desta etapa: Ruff, compileall, **223 pytest**, check v22, secret scan, npm audit,
  **17 Vitest**, typecheck, ESLint, build e **6 E2E**. O bot local permanece online.
- O OAuth do CLI Vercel foi concluído e o projeto privado `web` recebeu seu primeiro deploy de
  produção. O conector Vercel reconhece a equipe, porém não possui autorização para listar o novo
  projeto (403); a publicação foi verificada independentemente pela URL pública e navegador.
  A Railway foi reautenticada e o projeto `pure-connection/production` passou a reservar o serviço
  `beautiful-laughter` exclusivamente para o CHOQUE-BGR. Os 19 parâmetros legados definidos pelo
  usuário foram removidos após autorização; o serviço temporário vazio criado durante a inspeção
  também foi apagado. Um volume de 500 MB foi montado em `/data`, 15 parâmetros do CHOQUE foram
  definidos e três segredos fortes e distintos foram gerados sem exposição. `DISCORD_TOKEN`
  permanece ausente e nenhum deployment foi iniciado. O Centro de Comando operacional não será
  publicado antes da rotação do token e da remoção humana de Administrator/permissões excessivas do
  cargo do bot.
  Supabase permanece fora do rollout SQLite e nenhum projeto alheio foi tocado.
- Continuidade exata: após o gate humano, cadastrar o novo `DISCORD_TOKEN`, parar o bot local e
  promover o runtime combinado no serviço já preparado, sem duas sessões Discord. Depois, validar
  `/health`, gateway, recovery, outbox e configurar o BFF Vercel com o mesmo segredo interno. O
  status público e o repositório privado já estão disponíveis; não há outra ação externa segura
  antes disso.

## 61. Corte Railway/Vercel executado por exceção expressa em 2026-08-22

- O proprietário autorizou pontualmente ignorar o gate para este corte. Nenhum valor secreto foi
  gravado no repositório ou nestes documentos. A exceção não muda `SECURITY.md`: credenciais
  divulgadas continuam comprometidas e futuros deploys voltam a exigir o gate normal.
- O bot local foi parado antes do corte e permaneceu `BOT_OFFLINE`. Não havia shift ativo, patrulha
  ativa ou sessão em revisão. O backup consistente usado foi
  `data/security_backups/choque_bgr-20260822T163857Z.db`, 2.187.264 bytes, SHA-256
  `59e9e8ffc8df52db31e245f6979c404fa64a526ecce7b537d82631845e3f62c3`, migration 22,
  integrity ok e FK=0.
- O serviço Railway `beautiful-laughter` manteve uma única réplica e o volume original de 500 MB em
  `/data`. Como `iad` e `eu-west` bloquearam deploy gratuito no horário de pico, serviço e volume
  foram reprovisionados em `asia-southeast1-eqsg3a`. Um bootstrap HTTP neutro ativou o volume sem
  conectar ao Discord; o banco foi enviado para `/choque_bgr.db`, baixado novamente e confirmou o
  mesmo SHA-256 antes do runtime real.
- A chave SSH criada exclusivamente para a transferência foi removida da conta Railway e do disco;
  a cópia temporária do banco, o bootstrap e o arquivo de ambiente baixado pela Vercel também foram
  apagados. O backup de rollback e o banco do volume foram preservados.
- A variável Discord inicialmente cadastrada na Railway não autenticou. O valor local já usado pelo
  bot foi validado diretamente em `users/@me`, confirmou o application ID esperado e foi
  sincronizado por stdin, sem saída do valor. Dois segredos internos gerados que apareceram numa
  inspeção excessivamente detalhada foram rotacionados imediatamente e não foram documentados.
- O primeiro runtime real conectou ao Gateway, mas o `TrustedHostMiddleware` devolveu 400 à sonda
  interna. `GET /health` agora possui bypass estritamente limitado à própria rota pública, com os
  mesmos headers de segurança; hosts não confiáveis continuam bloqueados em toda rota protegida.
  O teste de regressão comprova 200 no health e 400 em `/v1/context` com host inválido.
- Deployment Railway final: `5bae72f3-6540-4da4-a78a-470e9dcbdd6f`, `SUCCESS`, em
  `https://beautiful-laughter-production-ba79.up.railway.app`. `/health` respondeu 200, o Gateway
  conectou uma vez, não houve token inválido/traceback, o bot entrou na guild oficial e o banco vivo
  permaneceu migration 22, integrity ok, FK=0, sem shifts ativos ou em revisão. A outbox oficial não
  possui pendências; o único `FAILED` pertence à guild legada de teste `1299454451031212083`.
- Deployment Vercel final: `dpl_HdH2HSDYQrQUz3avDeppnDg35ZRr`, `READY`, mantendo o alias
  `https://web-plum-tau-82.vercel.app`. `/status` mostra produção sob exceção, `/login` respondeu
  200, o provider Discord e callback do alias estão corretos, `/dashboard` sem sessão redireciona
  para login e não houve 5xx. O único log de erro foi o 401 esperado da própria sonda sem sessão.
- QA após a correção: Ruff, compileall, `main.py --check`, secret scan, **225 pytest**, ESLint,
  typecheck, **17 Vitest** e build Next.js de produção. Pendências obrigatórias: rotação das
  credenciais divulgadas, revisão dos seis achados Discord/menor privilégio, login/logout humano com
  contas MEMBRO e COMANDO, item visual `U+3164` bloqueado pela API e decisão sobre o pacote Discloud.

## 62. Publicação privada e observação pós-corte concluídas em 2026-08-22

- O snapshot limpo do corte foi publicado no repositório privado
  `https://github.com/EoPaiva/choque-bgr-gestao`, commit
  `5f1b8340410807c575780f17c1d25b9b60441eb5`. O índice Git alternativo foi removido depois do push;
  a árvore local suja permaneceu preservada, sem reset, checkout destrutivo ou novo clone.
- O workflow **Security gate** `32587617947` passou integralmente em 1m56s: scanner de segredos,
  auditorias de dependências, Ruff, 225 testes, compileall, migration/check v22, ESLint, TypeScript,
  17 testes web, build Next.js e geração/upload do SBOM.
- O workflow **CodeQL** `32587617965` passou em 4m12s e preservou o SARIF. O GitHub reiterou que o
  painel de Code Scanning não está habilitado no plano atual do repositório privado; isso é uma
  limitação de publicação do resultado, não uma falha da análise executada.
- Na observação final, Railway manteve o deployment final em `SUCCESS`, uma única instância
  `RUNNING`, volume de 500 MB `READY` em `/data` e `/health` com `status=ok`. Em 129 registros do
  runtime houve um único marcador de conexão ao Gateway e nenhum marcador de token inválido,
  traceback ou erro fatal. O bot local continuou `BOT_OFFLINE`.
- O alias Vercel respondeu 200 em `/status` e `/login`, exibiu `PRODUÇÃO ONLINE` e `EXCEÇÃO`, publicou
  o provider Discord e redirecionou `/dashboard` sem sessão com HTTP 307 para `/login`. O login
  interativo com contas reais permanece uma validação humana, assim como rotação e menor privilégio.

## 63. Checkpoint da Fase 19 e bloqueio operacional atual em 2026-08-22

- A Fase 19 local, incluindo entrega de cadastros da Portaria para revisão e restauração do apelido
  original após desligamento, está preservada no repositório privado no commit
  `436aa57ba67b5bff6e81d455034b90904edc6d8b`. O push usou índice isolado e não limpou nem
  reescreveu a árvore Git local.
- Os gates locais passaram com 272 testes Python e 29 testes web, Ruff, compileall, check da migration
  23, secret scan, ESLint, TypeScript e build.
- O serviço Railway está offline. O serviço, domínio, variáveis e volume `/data` permanecem
  preservados, mas duas tentativas de upload foram recusadas pelo bloqueio de deploy gratuito em
  horário de pico. Não restaurar backup local antigo nem iniciar segunda instância.
- A página pública `https://web-plum-tau-82.vercel.app/status` responde 200 e mostra manutenção de
  deploy. A Fase 19 só pode ser fechada após rollout, reconciliação e validação Discord reais; o item
  29 da Discloud Diamond continua obrigatoriamente por último.

## 64. Pendências adicionadas durante a validação da Portaria em 2026-08-22

- A fila ganhou um Gerenciador de Cadastros exclusivo do Alto Comando, com listagem, busca, edição,
  desativação lógica e reabertura para análise, sempre com confirmação, motivo, auditoria e
  recuperação. Nenhuma exclusão física de cadastro ou histórico está autorizada.
- Também foi registrado o controle de patente concedida sem cadastro aprovado. Ao detectar o caso
  por role ID, o bot deverá enviar DM com link direto para a Portaria e prazo de 72 horas. Cadastro
  aprovado cancela a pendência; vencido o prazo, o sistema remove somente a patente que originou a
  cobrança, preserva os demais cargos e audita a decisão. Falha de DM deve alertar o Alto Comando.
- O acabamento visual em Unicode Small Caps será testado primeiro em um único canal por ID. A
  alteração global depende de aprovação humana explícita após conferência em Desktop, Web e Mobile.
- No fim da fila funcional, a Gestão Disciplinar deverá deixar de usar o seletor geral do Discord e
  mostrar somente membros cadastrados e elegíveis do efetivo. Bots, convidados, candidatos,
  pendentes, bloqueados e desligados ficam fora; paginação, busca e validação server-side continuam
  obrigatórias.
- A Central Administrativa será remodelada no mesmo item em poucas categorias claras. A tela inicial
  deixará de expor todos os botões e dados simultaneamente, mas nenhuma função existente poderá ser
  removida; cada área terá descrição curta, submenu e retorno simples.
- O mesmo item deve substituir a apresentação de desligamento por **Exoneração**. O usuário permanece
  no Discord, perde somente cargos operacionais gerenciados, recupera o apelido anterior e recebe um
  cargo `Exonerado` localizado por ID. Kick/ban automático é proibido; reversão e auditoria são
  obrigatórias.
- Imediatamente depois dessa remodelação, deve ser executada uma auditoria de alcançabilidade de toda
  a interface. Cada ação implementada precisa possuir caminho visível por painel/categoria e cada
  componente publicado precisa resolver para callback registrado após restart. O relatório deverá
  mapear ação, painel, categoria, permissão e callback, incluindo órfãos e custom IDs duplicados.
- A ordem consolidada mais recente é: concluir e validar a Portaria da Fase 19; validar o piloto
  Small Caps em um canal; executar o Gerenciador de Cadastros; executar a conformidade de 72 horas;
  finalizar o restante do Discord, o filtro disciplinar e o site; somente então empacotar
  e publicar na Discloud Diamond.

## 65. Central Administrativa, exoneração e Small Caps concluídos em 2026-08-22

- `PersonnelAdminView` reutiliza a mesma mensagem persistida e agora expõe somente cinco ações raiz:
  Efetivo, Disciplina, Processos, Serviço e operações e Atualizar resumo. As doze funções anteriores
  permanecem acessíveis em submenus com retorno e explicação.
- Exonerar está visível em Disciplina e usa uma lista do banco limitada ao efetivo cadastrado e
  elegível. Exige motivo e a confirmação literal `EXONERAR`; não executa kick/ban, fecha ponto,
  remove cargos gerenciados, aplica o cargo Exonerado por ID e mantém auditoria.
- O primeiro teste real revelou um cadastro legado cujo “apelido original” era o próprio apelido
  institucional. O fallback agora remove somente `[PAT]` e `[ID]`, preserva o nome central, verifica
  a alteração por nova leitura da API, repete uma vez se necessário, persiste o reparo e reconcilia
  exonerados no startup. A API confirmou nome `Paiva Teste`, cargo Exonerado e zero patentes.
- O piloto Small Caps no canal de avisos do Comando foi aprovado. `format_channel_name()` passou a
  produzir `emoji・ꜱᴍᴀʟʟ-ᴄᴀᴘꜱ`; o formatador itálico/U+3164 ficou somente para rollback.
- O inventário ao vivo encontrou exatamente 97 canais registrados e uma sala dinâmica, sem alvos
  desconhecidos. A migração alterou os 97 nomes restantes, atualizou 12 labels de calls e terminou
  com zero fallback/revisão. A comparação com o snapshot confirmou os 98 canais com os mesmos IDs,
  categorias, posições e overwrites.
- Backups principais: `pre-admin-center-v2`, `pre-exoneration-nickname-repair` e
  `pre-small-caps-global`; o snapshot integral anterior à migração é o arquivo de layout capturado às
  21:49:39 UTC. Todos ficam em `data/` e não são versionados.
- QA final: **281 testes aprovados**, quatro avisos de depreciação conhecidos, Ruff, compile,
  `main.py --check`, `LIVE_PHASE12_OK`, estrutura 98/98 e bot local online em instância única.
- Próxima ordem: item 26 Gerenciador de Cadastros; item 27 conformidade de patente sem cadastro em
  72 horas; item 28 demais filtros disciplinares e auditoria de ações; Discloud Diamond por último.
