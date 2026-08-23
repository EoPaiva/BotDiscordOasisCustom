# Registro consolidado de pedidos — CHOQUE BGR

Atualizado em 2026-08-23.

## Auditoria complementar da conversa — 2026-08-23

A releitura dos pedidos, incluindo a conversa de voz recente, recuperou itens que haviam sido
somente mencionados ou resumidos genericamente. A fila detalhada está nos itens 32–42.

| Pedido | Estado verificado | Destino |
|---|---|---|
| Patrulha ocupada aparecer no site | CONCLUÍDO com Patrulha Alfa real | item 32 |
| Link sem `/recrutamento/recrutamento` | CONCLUÍDO e validado pelo usuário | hotfix web |
| Gestão site ↔ Discord de qualificações | CONCLUÍDO e publicado | item 34 |
| Recrutas e Gestão de Carreira sem conteúdo útil | CONCLUÍDO e publicado | item 35 |
| Redesign autoral do recrutamento | CONCLUÍDO e validado responsivamente | item 36 |
| Robô Analista | IMPLEMENTADO, DESATIVADO sem provider | item 37 |
| Domínio/subdomínio sem marca Vercel | NÃO EXECUTADO; depende de escolha | item 38 |
| Medalhas apagadas intencionalmente | CONCLUÍDO; módulo e recriação estrutural desabilitados | item 39 |
| Compactação detalhada do servidor | ADIADA; plano preservado | item 40 |
| Rotação de segredos/menor privilégio | PENDÊNCIA externa obrigatória | item 41 |
| Paridade fonte local ↔ Discloud | URGÊNCIA descoberta no hotfix | item 33 |
| Requisito real de 15 anos | CONCLUÍDO em produção com migration 27 e auditoria 16 → 15 | item 43 |
| Remover CNH B e porte de arma dos requisitos | CONCLUÍDO; ausentes do fluxo ativo | item 43 |
| Página pública de andamento coerente | CONCLUÍDO; Discloud online/Gateway/v27 | item 43 |
| Escopo de gestão das qualificações | CONFIRMADO para todo o Alto Comando | item 44 |
| Checkpoint atual no GitHub privado | CONCLUÍDO e sanitizado no commit `1fa51db` | item 45 |

Itens dependentes de resposta humana recuam temporariamente; nenhum pedido é descartado ou marcado
como concluído apenas porque foi anotado ou implementado localmente.

## Pedidos concluídos nesta continuidade

- **Medalhas intencionalmente removidas:** o canal não é exigido pelo runtime, validadores ou
  scripts estruturais. O módulo histórico permanece somente para rollback e não é carregado.
- **Idade do alistamento:** mensagem e regra real agora exigem 15 anos fora do personagem; a
  migration 27 registrou o valor anterior e o banco remoto confirmou a alteração.
- **Acompanhamento público:** `/status` reflete Discloud Diamond online, Gateway ativo e banco v27,
  sem a antiga mensagem de Railway pausada.
- **Checkpoint privado:** o estado consolidado foi publicado apenas em `EoPaiva/CHOQUE-BGR`, após
  scanner de segredos e revisão do conjunto; o remoto público permaneceu intocado.
- **Escopo das qualificações:** o proprietário confirmou todo o Alto Comando; o RBAC vigente já
  corresponde à decisão e não exigiu mudança de acesso.

- **Portaria sem atalho de ingresso:** o botão público agora identifica vínculo. Visitante sem
  candidatura ou role reconhecida não pode ser aprovado como membro por esse caminho.
- **Timeout na aprovação:** decisões confirmam a interação antes do trabalho transacional e
  respondem por follow-up; a ordem recebeu teste dedicado.
- **Recrutamento visível e organizado:** cinco canais de leitura pública, Mesa privada, posto
  `Setar tag`, menção do aprovado, DM e fallback administrativo foram aplicados e validados.
- **Protocolo anterior:** `AL-00005` foi atualizado no quadro e no resultado sem duplicar mensagens.
- **Patrulha no site:** ocupação real das calls passou a alimentar API e frontend, mesmo sem uma
  patrulha formal aberta; a Patrulha Alfa foi retornada com um ocupante no endpoint real.
- **Acesso ao site:** Centro de Comando restrito a Comando/Alto Comando; jornada pública de
  candidatura não depende desse perfil.
- **Qualificações bidirecionais:** matriz web, RBAC exclusivo, histórico append-only, outbox e
  listener de cargos foram publicados. Site e Discord reconciliam por IDs sem loop de eventos.
- **Recrutas e Carreira:** patentes Small Caps são normalizadas pelo identificador canônico; a API
  e as páginas mostram efetivo, prontidão, cursos e movimentações reais com estados vazios úteis.
  O banco remoto confirmou 4 recrutas entre 12 membros ativos e 14 mudanças de patente.
- **Recrutamento autoral:** a composição editorial grafite/vermelho foi validada em desktop e
  mobile, sem overflow ou controles visíveis sem nome. O E2E passou em Chromium e Firefox.
- **Pendência preservada:** a compactação estrutural do servidor continua como trabalho futuro,
  sem alterações destrutivas nesta rodada.

Este arquivo é o índice de cobertura dos pedidos. Ele não substitui as especificações e não declara
como concluído aquilo que apenas entrou na fila. A ordem operacional oficial está em
`docs/PHASE_QUEUE.md`.

## Auditoria da conversa

- 56 mensagens de usuário já materializadas na tarefa foram revisadas.
- 12 follow-ups que ainda estavam na fila visual do Codex foram recuperados pelo texto integral.
- 15 prompts longos foram arquivados integralmente em `docs/source-prompts/`: os 12 primeiros foram
  preservados byte a byte e os três mais recentes normalizados para UTF-8/LF sem alteração textual.
- 6 capturas ligadas aos follow-ups foram inspecionadas; elas servem apenas como evidência visual e
  não foram copiadas para o repositório por conterem interface e identificação do servidor.
- Pedidos como “prossiga”, “qual a próxima fase” e testes de conectores foram classificados como
  navegação da conversa, não como funcionalidades separadas.
- O token compartilhado na conversa não foi copiado para documentação ou código.
- HumanReply AI não pertence ao escopo; este registro trata somente do BotDiscord CHOQUE BGR.

## Doze pedidos recuperados da fila, na ordem de envio

Os itens abaixo preservam a ordem original. Os itens 1–8 e 10–12 foram concluídos; o item 9 segue
para a decisão arquitetural do Programa Web.

1. **CONCLUÍDO EM 2026-08-22.** Após decisão, o resultado é publicado de forma idempotente no
   histórico privado configurado por ID e somente então a mensagem original é removida da caixa de
   entrada. IDs de origem/destino ficam persistidos, decisões concorrentes são bloqueadas e o
   startup recupera entregas incompletas sem repostar registros legados.
2. **CONCLUÍDO EM 2026-08-22.** O painel público de cadastro foi ampliado com ordem de ingresso,
   dados necessários, validações e privacidade, mantendo `MEMBER`, a mensagem e o custom ID.
3. **CONCLUÍDO EM 2026-08-22.** O quadro militar de medalhas preserva Bravura, Pacificador, Guerra,
   Sargento, Honra, Sheriff e Distinção, com os sete cargos históricos conferidos e consulta por
   select. A mensagem original foi preservada como fonte.
4. **CONCLUÍDO EM 2026-08-22.** O painel de bate-ponto explica entrada, call, segmentos, tolerância,
   estados e auditoria em identidade militar, mantendo a máquina transacional e quatro custom IDs.
5. **CONCLUÍDO EM 2026-08-22.** O painel persistente no canal `1164363506083172413` registra
   disponibilidade, fila FIFO e situação operacional, forma patrulhas nas 11 calls registradas e
   envia notificação privada quando configurado, sem iniciar ponto automaticamente.
6. **CONCLUÍDO EM 2026-08-22.** O painel persistente no canal `1540590792522072155` recupera a
   última patrulha real, duração/validação do ponto e feedback individual privado com observação;
   autor e avaliado precisam pertencer à mesma patrulha encerrada.
7. **CONCLUÍDO EM 2026-08-22.** A categoria `1540589594691772477` recebeu painéis de transferência,
   relações institucionais e termos, com botões funcionais e atendimento privado. Os canais
   `1166861438728548432`, `1540590814839967784` e `1540590816383336520`, históricos, IDs e
   overwrites foram preservados.
8. **CONCLUÍDO EM 2026-08-22.** As nove mensagens históricas continuam intactas. Foram importados
   9 cursos, 10 requisitos, notas mínimas, editais e cooldown; `COURSE_CATALOG` possui nove botões
   persistentes e a solicitação é aceita somente após validação server-side de membro, cargos,
   qualificação anterior, duplicidade e intervalo.
9. **CONCLUÍDO EM 2026-08-22.** ADRs 004–007 definem Vercel/Next.js, Railway/FastAPI+bot e corte
   único futuro para Supabase PostgreSQL, proibindo dual-write. Configurações tipadas e runbook
   foram entregues; nenhum projeto externo foi provisionado ou publicado automaticamente.
10. **CONCLUÍDO EM 2026-08-22.** Cada atendimento cria uma sala privada real por ID, visível somente
    ao solicitante, perfis COMANDO/ADMINISTRADOR e bot. A confirmação menciona a sala, o botão
    persistente permite encerramento autorizado e decisões/encerramentos arquivam o mesmo canal sem
    expor denúncias ou dados privados. O startup recupera tickets que ficaram sem sala.
11. **CONCLUÍDO EM 2026-08-22.** Os overwrites de visitantes/novos membros foram centralizados e
    aplicados por registry/ID: antes da aprovação, uma conta real sem cargos enxerga apenas
    Recepção, Ticket, Recrutamento e Transferências e Parcerias. Central do Membro, Registro,
    Informações, Membros CHOQUE e todas as demais áreas internas ficaram ocultas; filas e resultados
    administrativos dentro de categorias públicas também permanecem privados.
12. **CONCLUÍDO EM 2026-08-22.** Corrigir o painel de hierarquia para mostrar a quantidade real de usuários em cada cargo do
    Discord. A contagem atual usa apenas membros `ACTIVE` vinculados por `members.rank_id`, por isso
    pode mostrar zero mesmo quando o cargo Comandante Geral está atribuído; o painel deve reconciliar
    cargo real, cadastro e RankSync sem contar bots ou membros inelegíveis por engano.

## Pedidos anteriores e destino durável

| Pedido | Estado | Fonte principal |
|---|---|---|
| Fundação, QA, SQLite transacional e ponto por voz | IMPLEMENTADO nas Fases 1–3 | `source-prompts/01-*`, `docs/IMPLEMENTATION_REPORT.md` |
| Remodelação completa sem comandos e por painéis | IMPLEMENTADO progressivamente nas Fases 4–12 | `source-prompts/02-*`, `PROJECT_HANDOFF.md` |
| Mapeamento e remodelação do Discord | IMPLEMENTADO, incluindo migração final dos nomes por ID | `docs/DISCORD_LAYOUT_MAP.md`, `docs/DISCORD_LAYOUT_REDESIGN_SPEC.md` |
| Padrão obrigatório de nomes | IMPLEMENTADO; Small Caps com hífen aprovado e aplicado aos 98 canais; `U+30FB` permanece somente entre emoji e nome | `docs/CHANNEL_NAMING_STANDARD.md`, `source-prompts/08-*` |
| RankSync de cargo/patente/nickname | IMPLEMENTADO; rollout real com uma ressalva de hierarquia externa | `docs/RANK_SYNC_SPEC.md`, `source-prompts/03-*` |
| Sincronização Discord, identidade funcional e RBAC convergente | EM EXECUÇÃO na Fase 19; complementa RankSync e PermissionService sem duplicá-los | `docs/DISCORD_IDENTITY_RBAC_SYNC_SPEC.md`, `source-prompts/15-*` |
| Tempo mínimo em patrulha | IMPLEMENTADO e validado local/ao vivo na Fase 14 | `docs/MINIMUM_PATROL_TIME_SPEC.md`, `source-prompts/04-*` |
| Operações Inteligentes/Central de Patrulha | IMPLEMENTADO e validado na Fase 15 | `docs/INTELLIGENT_OPERATIONS_EXPANSION_SPEC.md`, `source-prompts/06-*` |
| Layout de referência externo adaptado às funções CHOQUE | REFERÊNCIA, não cópia literal | `source-prompts/05-*`, `docs/DISCORD_LAYOUT_REDESIGN_SPEC.md` |
| Handoff vivo atualizado a cada fase | ATIVO | `PROJECT_HANDOFF.md`, `source-prompts/07-*` |
| Centro de Comando Web com Lovable | IMPLEMENTADO localmente; rollout externo não provisionado | `docs/COMMAND_CENTER_WEB_SPEC.md`, `source-prompts/09-*` |
| Recrutamento, alistamento e integridade | IMPLEMENTADO localmente e validado na migration v17; campanha permanece DRAFT | `docs/RECRUITMENT_INTEGRITY_SYSTEM_SPEC.md`, `source-prompts/11-*` |
| Robô Analista de candidaturas | IMPLEMENTADO localmente na migration v18; provider desativado e sem envio de dados reais | `docs/RECRUITMENT_AI_ANALYST_SPEC.md`, `source-prompts/12-*`, `choque/recruitment_analysis.py` |
| Security Hardening completo | IMPLEMENTADO localmente; gate público FAIL por pendências externas registradas | `SECURITY.md`, `docs/SECURITY_CONTROL_MATRIX.md`, `source-prompts/10-*` |
| Separador `U+3164` em nomes de canais | SUPERADO pela decisão visual posterior: API remove U+3164/U+2800; formatador legado preservado só para rollback e Small Caps usa hífen | `docs/CHANNEL_NAMING_STANDARD.md`, `scripts/probe_channel_separators.py` |
| Comandante automático de patrulha | IMPLEMENTADO e validado na migration v20/Fase 16 | `docs/PATROL_COMMANDER_SPEC.md`, `source-prompts/13-*` |
| Portaria Digital / cadastro obrigatório | IMPLEMENTADO e validado na migration v21/Fase 17 | `docs/REGISTRATION_GATE_SPEC.md`, `source-prompts/14-*` |
| Ticket em categoria exclusiva, equipe responsável e controles avançados | IMPLEMENTADO e validado na migration v22/Fase 18 | `docs/TICKET_OPERATIONS_EXPANSION_SPEC.md` |
| Repositório GitHub privado e publicação web Vercel | GitHub privado e `/status` publicados; Security gate/CodeQL verdes, SARIF 0/0 e alerta Dependabot corrigido; alvo Railway `pure-connection/beautiful-laughter` limpo e preparado com volume/configuração, mas sem token/deployment até o gate externo | `docs/PHASE_QUEUE.md`, `docs/COMMAND_CENTER_DEPLOYMENT.md` |
| Ticket “Outro assunto” | IMPLEMENTADO e validado ao vivo | `PROJECT_HANDOFF.md`, `docs/IMPLEMENTATION_REPORT.md` |
| Hierarquia com 21 patentes, sem Alto Comando/Xenon | IMPLEMENTADO e validado ao vivo | `PROJECT_HANDOFF.md`, `scripts/sync_rank_roles.py` |
| Contagem real por cargo na hierarquia | IMPLEMENTADO e validado ao vivo | `cogs/hierarchy_system.py`, `scripts/validate_live_rank_sync.py` |
| Permissões de visitantes por registry | IMPLEMENTADO e validado com conta real sem cargos | `choque/visitor_access.py`, `scripts/enforce_visitor_permissions.py` |
| Sala privada por ticket e arquivo | IMPLEMENTADO e validado pela API Discord | `choque/tickets.py`, `cogs/ticket_commands.py`, `scripts/validate_live_ticket_rooms.py` |
| Arquivo de cadastros analisados | IMPLEMENTADO e validado no registry/DB/API | `choque/members.py`, `cogs/member_commands.py`, `scripts/validate_live_application_archive.py` |
| Encaminhamento da Portaria para recrutador/Comando | IMPLEMENTADO localmente na migration v23; rollout real pendente | `choque/registration_gate.py`, `cogs/registration_gate_system.py`, `cogs/member_commands.py` |
| Restaurar apelido anterior no desligamento | IMPLEMENTADO localmente na migration v23; rollout real pendente | `choque/rank_sync.py`, `cogs/member_sync.py`, `cogs/personnel_commands.py` |
| Lote visual cadastro/ponto/medalhas/parcerias | IMPLEMENTADO e validado pela API | `cogs/member_commands.py`, `cogs/shift_commands.py`, `cogs/medals_system.py`, `cogs/ticket_commands.py` |
| Piloto Small Caps e migração visual global | IMPLEMENTADO e validado ao vivo; item 25 concluído | `docs/CHANNEL_NAMING_STANDARD.md`, `docs/PHASE_QUEUE.md` |
| Gerenciador completo de cadastros para o Alto Comando | CONCLUÍDO; item 26 da fila | `docs/PHASE_QUEUE.md` |
| Patente/Companheiro sem cadastro: DM, prazo de 72h e retirada do cargo de origem | CONCLUÍDO e ativo; item 27 da fila | `docs/PHASE_QUEUE.md` |
| Disciplina deve listar somente o efetivo cadastrado e elegível | CONCLUÍDO; item 28 | `docs/PHASE_QUEUE.md`, `cogs/discipline_commands.py` |
| Exoneração mantém usuário no Discord e aplica cargo Exonerado | IMPLEMENTADO e validado ao vivo; cargo, patentes e apelido conferidos pela API | `docs/PHASE_QUEUE.md`, `cogs/member_sync.py` |
| Simplificar Central Administrativa por categorias e explicar cada área | IMPLEMENTADO e validado ao vivo; cinco ações raiz e doze funções preservadas | `docs/PHASE_QUEUE.md`, `cogs/personnel_commands.py` |
| Auditar botões e ações implementadas sem caminho visível | CONCLUÍDO; item 28 | `docs/INTERACTION_ROUTE_AUDIT.md` |
| Empacotamento e publicação Discloud Diamond | CONCLUÍDO operacionalmente; ZIP sanitizado validado e runtime ativo. Rotação de credenciais continua dívida do gate de segurança | `docs/PHASE_QUEUE.md` |
| Entrada de visitantes sem dúvida ou procura de canais | CONCLUÍDO; candidatura em um clique na Recepção e no Recrutamento, Portaria separada, DM orientativa e validação ao vivo | `cogs/member_commands.py`, `cogs/ticket_commands.py`, `cogs/registration_gate_system.py`, `scripts/validate_live_phase11.py` |

## Recrutamento público ativado — 2026-08-23

- O portal público sem OAuth foi publicado na Vercel e a campanha inicial foi aberta no backend.
- Os painéis persistentes usam `Candidatar-me`, `Minha candidatura` e `Requisitos`, localizados por
  IDs e atualizados no lugar, sem duplicar mensagens.
- Um teste sintético completou 24 questões, submeteu a candidatura, gerou dossiê e confirmou a
  entrega no canal administrativo pelo outbox. O registro de QA foi retirado depois da entrega.
- O teste encontrou o uso do atributo legado `branding.footer_text`; o hotfix usa a propriedade
  central `branding.footer`, possui teste de regressão e já está ativo na Discloud.
- O Robô Analista permanece bloqueado somente pela ausência de provider/credencial no runtime. A
  decisão humana e todo o recrutamento básico continuam operacionais sem classificação fabricada.

## Entrada pública simplificada — 2026-08-23

- Pedido: quem entra no Discord sem ser membro deve localizar imediatamente `Candidatar-me`, abrir o
  processo e enviar a candidatura sem navegar por vários canais.
- Entrega: a mensagem `MEMBER` da Recepção ganhou link direto para o portal e explica que a Portaria
  é somente para aprovados/vínculos existentes; `RECRUITMENT` ganhou candidatura e acompanhamento
  diretos, requisitos e sequência de quatro passos; a DM de entrada repete os dois caminhos.
- Preservação: mensagens, canais, IDs, históricos, posições e overwrites não foram substituídos. Os
  custom IDs anteriores continuam registrados para compatibilidade; apenas os CTAs públicos ativos
  passaram a links de um clique.
- Rollout: o incidente de WAL causado pelo empacotamento de `data/*.db*` foi contido sem prosseguir
  com escritas, restaurado a partir do backup pré-deploy e eliminado da política de pacote. O banco
  remoto terminou íntegro e o validador REST confirmou as superfícies reais.

## Regras transversais da fila

- Operação do servidor deve permanecer por painéis, botões, selects e modais; comandos não podem ser
  requisito de uso.
- Reutilizar mensagens persistidas; não duplicar painéis quando um `panel_type` já possui mensagem.
- Localizar canais/cargos por ID, registry ou identificador interno, nunca pelo nome estilizado.
- Preservar IDs, mensagens, histórico, posição e overwrites antes de qualquer remodelação.
- Fazer snapshot antes de alterações em massa e oferecer rollback verificável.
- Toda decisão administrativa e mudança de estado deve ser transacional e auditada.
- Dados pessoais, denúncias, avaliações e candidaturas devem respeitar RBAC e respostas privadas.
- Nenhuma IA decide aprovação, punição, promoção ou desligamento automaticamente.
- Lovable é ferramenta de planejamento/interface nas fases web; nunca recebe secrets ou dados reais.
- O handoff, o relatório vivo e esta fila devem ser atualizados após cada lote concluído.

## Portaria Digital / cadastro obrigatório — concluída em 2026-08-22

- O pedido complementar de cadastro obrigatório foi implementado como migration v21 e fluxo visual
  persistente. Cadastro próprio solicita nick MTA e ID BGR; duplicidade, ex-membro, vínculo existente
  e divergência de identidade vão para revisão humana, nunca para liberação automática.
- O usuário observado com patente e nome não sincronizado foi coberto pela reconciliação: patente sem
  identidade não equivale a cadastro. Cargos protegidos, owner, bots, Administrator e bypass não são
  removidos pelo gate.
- Acesso pré-aprovação foi aplicado por ID/registry, com snapshot reversível. O painel persistido foi
  movido para Recepção sem trocar canal, mensagem, histórico ou overwrites próprios. 121 contas foram
  sincronizadas; dez contas reais sem cadastro foram amostradas sem acesso fora das quatro áreas
  públicas autorizadas.
- Discord, core, recrutamento, RankSync, onboarding, inbox e Centro de Comando Web compartilham o
  mesmo estado persistido. A próxima solicitação ativa no registro é a expansão operacional de tickets.

## Operação avançada de tickets — concluída em 2026-08-22

- O pedido para separar tickets em categoria própria, mencionar o cargo responsável e ampliar os
  controles foi concluído sobre o fluxo existente. “Outro assunto”, IDs, sala histórica, mensagem e
  histórico foram preservados.
- Tickets ativos e arquivados usam categorias distintas por ID. A sala privada permite assumir,
  liberar, priorizar, incluir/remover participante, avisar, transcrever, encerrar com confirmação e
  reabrir a mesma sala. Concorrência, antispam, transcript hash e auditoria são server-side.
- A privacidade foi verificada com uma matriz Discord temporária e removida: somente solicitante,
  cargo responsável, Comando/Administrador, participantes explícitos e bot acessam uma sala ativa;
  visitante e membro comum não acessam. O arquivo retira acessos operacionais desnecessários.
- Configuração visual existe no Discord e no Centro de Comando Web. Snapshot e dois backups com
  restore drill permitem rollback. O próximo pedido ativo é a publicação privada GitHub/Vercel.

## Publicação operacional por exceção — executada em 2026-08-22

- O pedido de usar o serviço Railway `beautiful-laughter`, cadastrar as credenciais fornecidas e
  ignorar o gate somente naquele momento foi executado como exceção pontual, sem valores em arquivos
  versionados. `SECURITY.md` permanece `FAIL` e a rotação continua obrigatória.
- O banco v22 foi transferido para o volume `/data` depois de backup consistente e comparação
  SHA-256 de ida e volta. O runtime combinado Railway está `SUCCESS`, `/health` 200, Gateway
  conectado, banco vivo íntegro e bot local desligado.
- O site de acompanhamento foi republicado em `https://web-plum-tau-82.vercel.app/status` e agora
  informa produção online sob exceção. Login, provider/callback Discord e proteção de rota passaram;
  OAuth humano com contas reais continua pendente.
- QA final desta entrega: **225 pytest**, Ruff, compile/check, scanner de segredos, **17 Vitest**,
  ESLint, TypeScript e build. A fila preserva o bloqueio visual `U+3164`, as ações humanas de
  segurança e o empacotamento Discloud ainda não decidido/concluído.
- O snapshot final foi enviado ao repositório privado no commit `5f1b8340410807c575780f17c1d25b9b60441eb5`.
  Security gate `32587617947` e CodeQL `32587617965` passaram. A observação pós-corte confirmou uma
  única instância remota, nenhum erro fatal, health Railway ok, Vercel 200 e bot local offline.

## Continuidade da Fase 19, Portaria e desligamento — parcial em 2026-08-22

- Pedidos de cadastro agora são publicados no canal de aprovação e reconciliados por retry; decisões
  arquivam o resultado de forma idempotente. O desligamento usa o sincronizador central e restaura o
  apelido anterior ao primeiro nome oficial.
- O corte local passou 272 testes Python e 29 testes web, além dos demais gates. O checkpoint privado
  foi publicado no commit `436aa57ba67b5bff6e81d455034b90904edc6d8b`.
- O rollout real permanece pendente: a Railway recusou novamente o upload por indisponibilidade do
  plano gratuito durante horário de pico. Serviço, volume e banco persistente continuam preservados;
  nenhuma publicação desatualizada ou alternativa paga foi iniciada.

## Central Administrativa, exoneração e Small Caps — concluídos em 2026-08-22

- A Central Administrativa reutiliza a mensagem persistida, apresenta cinco áreas claras e preserva
  as doze funções anteriores nos submenus. `Exonerar membro` tornou-se uma ação visível e restrita
  ao efetivo cadastrado/elegível.
- A exoneração real não expulsou nem baniu: removeu cargos operacionais/patente, aplicou Exonerado e
  encerrou o estado funcional. O apelido legado foi reparado preservando somente o nome central;
  releitura da API confirmou o resultado. O fallback, a segunda tentativa e a reconciliação de
  startup passaram a proteger os próximos casos.
- O piloto Small Caps foi aprovado e expandido para os 97 canais do registry e uma sala dinâmica.
  IDs, categorias, posições e overwrites permaneceram idênticos ao snapshot; 12 labels de calls
  foram atualizadas e o formatador central passou a criar novos canais no mesmo padrão.
- Evidência final do lote: 281 testes, Ruff, compile, `main.py --check`, validação REST do layout e
  bot local online em instância única. O próximo item é o Gerenciador de Cadastros do Alto Comando.
