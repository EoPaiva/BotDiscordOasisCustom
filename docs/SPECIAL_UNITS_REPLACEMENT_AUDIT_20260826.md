# Auditoria prévia — substituição de Cursos e candidaturas por Unidades Especiais

Data da evidência: **2026-08-26**

Branch auditada: **`codex/phase-b-transfers`**

Commit auditado: **`ba06093`**

Produção observada: **migração 54**, serviço `choque-bgr-api` saudável, um Gateway ativo e aplicação legada offline.

## Veredito executivo

A substituição é viável, mas **não é seguro remover o sistema antigo primeiro**. Já existem dados,
painéis persistentes, cargos reais e dependências cruzadas que precisam de migração aditiva.

Bloqueios antes do corte:

1. Existem **8 candidaturas de Unidades pendentes** e não há respostas, protocolo público nem snapshot
   de requisitos nelas. Devem entrar como legado para revisão humana; não podem ser aprovadas,
   rejeitadas ou invalidadas automaticamente.
2. Existe **1 solicitação de curso pendente**. Ela deve ser resolvida ou encerrada formalmente antes de
   desativar a fila antiga.
3. O banco possui **0 memberships de Unidade**, mas os cargos já existem no Discord. É obrigatório
   reconciliar os detentores reais desses cargos antes de considerar o banco como fonte definitiva.
4. No DC 2, os cargos `COMANDO • ROCAM`, `COMANDO • TÁTICO` e `COMANDO • ELITE` possuem a permissão
   global `Administrator`. Isso viola o escopo por Unidade e também faz o provisionamento atual falhar.
5. Cursos/Qualificações são usados por promoção, recrutamento, prontidão, dossiê e comando de patrulha.
   A interface de Cursos pode ser aposentada; o histórico de qualificação não pode ser apagado.
6. O serviço de tickets existe e deve ser estendido. Porém, no DC 2 só há `ticket_bot_role_id`;
   categorias ativa/arquivo, responsável e transcrição ainda não estão configuradas.

Nenhuma alteração de código, banco ou Discord foi aplicada durante esta auditoria.

## 1. Estrutura atual de Cursos

- Catálogo histórico com **9 cursos por servidor**, totalizando **18 registros ativos** em
  `course_catalog`.
- Em cada servidor, **7 inscrições estão abertas** e **2 fechadas**.
- No DC 2, o formato correto já é **uma mensagem por curso no mesmo canal**, com botão próprio de
  candidatura. Há 9 mensagens persistidas em `course_panel_messages`.
- Cursos: Membro Águia, Atirador de Elite, Modulação, Membro ROCAM, P1 Tático, P1 Oficial,
  ROCAM Elite, Abordagem Básica e Abordagem Avançada.
- O catálogo guarda cargo, requisitos, nota, cooldown, patente mínima, horas válidas, tempo de casa,
  ausência de suspensão/ADV, pré-requisito, canal e mensagem.
- `TrainingService` cuida de elegibilidade, candidatura, decisão, turma, presença, resultado e
  concessão de qualificação.
- Estado produtivo: **1 candidatura de curso pendente**, **0 turmas**, **0 inscrições em turmas**,
  **0 resultados em `member_qualifications`** e **43 mudanças de qualificação** no ledger
  `qualification_changes` (39 concessões e 4 revogações).

Conclusão: retirar o catálogo/candidatura pública é possível; apagar tabelas, cargos ou ledger não é.

## 2. Estrutura atual de candidaturas

O módulo atual de Unidades usa quatro códigos: `ROCAM`, `TATICO`, `ELITE` e `CORREGEDORIA`.

Fluxo atual:

1. Um único painel apresenta um select com as quatro Unidades.
2. A seleção cria imediatamente uma linha `PENDING`.
3. Um responsável pode assumir a linha.
4. O Comando aprova ou rejeita diretamente, sem treinamento.
5. A aprovação cria membership, promove até o piso global configurado e enfileira sincronização dos
   cargos nos dois servidores.

Estado produtivo:

| Unidade | Pendentes | Memberships ativos |
|---|---:|---:|
| ROCAM | 4 | 0 |
| TÁTICO | 2 | 0 |
| ELITE | 2 | 0 |
| CORREGEDORIA | 0 | 0 |

Limitações atuais: sem requisitos por Unidade, sem abertura/fechamento, sem modal, sem respostas,
sem protocolo `UNI-*`, sem snapshot, sem ticket, sem agendamento e sem estados de treinamento.

Há ainda um acoplamento perigoso: a aprovação de uma **entrada por indicação** pode criar, assumir e
aprovar automaticamente uma candidatura de Unidade. Esse atalho deve ser removido do novo fluxo,
pois contorna requisitos e treinamento.

## 3. Canais envolvidos

| Servidor | Finalidade | Canal atual |
|---|---|---|
| CHOQUE principal | Cursos | `1162114694581059584` |
| CHOQUE principal | Treinamentos | `1540546969649291376` |
| CHOQUE principal | Central ROCAM | `1542020023634239549` |
| CHOQUE principal | Central TÁTICO | `1542020028772384798` |
| CHOQUE principal | Central ELITE | `1542020037433491528` |
| CHOQUE principal | Central CORREGEDORIA | `1542020041720074311` |
| DC 2 | Cursos | `1541938761204629557` |
| DC 2 | Treinamentos | `1541938762748010506` |
| DC 2 | Candidaturas de Unidades | `1542020054919413862` (`candidaturas-unidades`) |
| DC 2 | Mesa administrativa | `1542020056517713921` (`mesa-unidades`) |

Não foram encontrados, na topologia relevante auditada, canais ativos separados para aprovados em
curso, reprovados em curso ou instrutores. Esses conceitos estão hoje em banco, painéis e cargos.

## 4. Categorias envolvidas

| Servidor | Categoria | ID |
|---|---|---:|
| CHOQUE principal | Cursos | `1162114516318949529` |
| CHOQUE principal | ROCAM | `1542020022548041728` |
| CHOQUE principal | TÁTICO | `1542020026687823982` |
| CHOQUE principal | ELITE | `1542020034942206052` |
| CHOQUE principal | CORREGEDORIA | `1542020040549728346` |
| DC 2 | Cursos | `1541938753822527498` |
| DC 2 | Unidades Especiais | `1542020054072168479` |
| DC 2 | ADM Unidades | `1542020055741505597` |

As quatro categorias privadas do servidor principal contêm uma central por Unidade. Como o banco não
possui memberships, elas devem ser arquivadas somente depois de reconciliar cargos e confirmar que
não há conteúdo operacional único.

## 5. Cargos das Unidades

Os cargos existentes devem ser reutilizados, nunca recriados.

| Unidade | Principal — membro/auxiliar | DC 2 — membro/auxiliar |
|---|---|---|
| ROCAM | `1542020009637716108` / `1542020010011140117` | `1542020043825750067` / `1542020044429590569` |
| TÁTICO | `1542020012028465302` / `1542020012632703036` | `1542020046170361857` / `1542020047000567858` |
| ELITE | `1542020014096388096` / `1542020014540849293` | `1542020048149807214` / `1542020048967704646` |
| CORREGEDORIA | `1542020015954329661` / `1542020016789127218` | `1542020050511204422` / `1542020050792489092` |

O cadastro canônico ainda possui o campo simples `members.unit`; os valores atuais são principalmente
`BGR`, nulo ou `Choque`, e não representam memberships confiáveis das quatro Unidades. A fonte nova
deve ser `special_unit_memberships`, mantendo `members.unit` apenas como projeção compatível.

## 6. Cargos de Comando

| Unidade | Principal | DC 2 |
|---|---:|---:|
| ROCAM | `1542020011273490532` | `1542020045289554030` |
| TÁTICO | `1542020012942819340` | `1542020047306891295` |
| ELITE | `1542020015463604266` | `1542020049970266243` |
| CORREGEDORIA | `1542020017699164160` | `1542020051752722443` |

Os cargos de Comando do principal e o de Corregedoria no DC 2 têm permissões globais zero. Os três
demais cargos de Comando no DC 2 têm `Administrator`. A correção exige alteração humana/autorizada
dos cargos e smoke test de permissões granulares antes do novo módulo.

## 7. Permissões atuais

- Principal: `@everyone` não vê as centrais; membro/auxiliar/Comando da Unidade veem e escrevem;
  Comando também gerencia mensagens.
- DC 2 público: `@everyone` não vê; o cargo de membro CHOQUE vê sem escrever; auxiliares, Comandos,
  recrutamento e instrutor veem e escrevem.
- DC 2 administrativo: o cargo de membro CHOQUE é explicitamente impedido de ver.
- Backend atual: Discord Administrator, qualquer usuário com `recruitment.approve`, ou cargos
  auxiliar/Comando da Unidade passam por `require_unit_staff`. Para ações de comando, auxiliar é
  excluído.
- Problema: `recruitment.approve` concede acesso global às Unidades e não diferencia configuração,
  treinamento e decisão. O novo módulo precisa de permissões próprias.
- Ocultar botões não é autorização. Todo callback, endpoint e worker deve resolver novamente o ator,
  o guild canônico, a Unidade e a permissão no servidor.

## 8. Models/tabelas envolvidos

### Unidades atuais

- `special_units`: catálogo básico.
- `special_unit_guild_resources`: canais, categoria e cargos por servidor.
- `special_unit_applications`: candidatura simples e lock/versionamento.
- `special_unit_memberships`: vínculo e nível membro/auxiliar/Comando.
- `special_unit_events`: trilha append-only com `correlation_id` único.

### Cursos e treinamentos atuais

- `course_catalog`, `course_requirements`, `course_applications`, `course_panel_messages`.
- `training_events`, `training_enrollments`, `training_evaluations`.
- `member_qualifications`, `qualification_changes`.

### Infraestrutura reutilizável

- `service_tickets`, `ticket_rooms`, `ticket_participants`, `ticket_operation_events`,
  `ticket_transcripts`.
- `panels` para mensagens persistentes.
- `web_action_outbox` para sincronização recuperável de cargos.
- `audit_logs` para auditoria institucional; produção contém 19.805 registros.
- `members`, `ranks`, `discord_role_mappings`, perfis RBAC, posições, pontos/turnos, ADV e ausências.

O projeto usa serviços e SQL explícito, não ORM. Qualquer mudança de `CHECK` em SQLite deve reconstruir
a tabela em migração transacional e validar `foreign_key_check`/`quick_check`.

## 9. Dependências encontradas

1. Qualificações alimentam promoção (`promotion_required_courses`).
2. Qualificações alimentam recrutamento (`recruit_required_courses`).
3. A regra do comandante de patrulha pode exigir uma qualificação específica.
4. Dossiê, perfil, readiness, Central Administrativa e site exibem cursos/qualificações.
5. `/v1/trainings`, `/v1/qualifications` e `/v1/qualifications/manage` dependem do catálogo.
6. As páginas web `/trainings`, `/qualifications` e `/members/[id]` exibem esses dados.
7. O outbox sincroniza cargos de qualificação e de Unidade separadamente.
8. Ausência usa `special_unit_memberships` e recua para `members.unit`.
9. Aprovação de Unidade atual pode promover patente e gerar notificação de carreira.
10. Entrada por indicação pode aprovar Unidade automaticamente.
11. `service_tickets.ticket_type` não contém `UNIT_TRAINING`.
12. A unicidade atual de candidatura/membership implementa **uma Unidade ativa por militar**.

## 10. Dados que precisam ser preservados

- 18 catálogos, 20 requisitos, 18 IDs de mensagens e hashes dos editais.
- 1 candidatura de curso pendente e qualquer decisão posterior.
- 43 eventos do ledger de qualificações e os cargos de curso válidos existentes.
- 8 candidaturas de Unidade pendentes e seus 8 eventos de criação.
- IDs reais dos 16 cargos de membro/auxiliar e 8 cargos de Comando nos dois servidores.
- IDs de categorias, canais e painéis para rollback e arquivamento.
- Histórico de tickets: 11 tickets, 11 salas, 56 eventos e 10 transcrições.
- Auditoria, correlações, timestamps, atores e razões.
- Cadastro, patente, tempo de corporação, turnos, ADV, ausências e status do militar.
- Conteúdo histórico dos canais antes de qualquer arquivamento.

As oito candidaturas antigas devem receber protocolo novo e marca `LEGACY`, mas respostas e snapshots
desconhecidos devem permanecer explicitamente nulos/desconhecidos.

## 11. Componentes reutilizáveis

- `SpecialUnitService`, catálogo de Unidades, memberships, eventos e role sync.
- `TicketService`: sala privada, claim/release, participantes, prioridade, notificação, transcrição,
  fechamento, arquivamento, reabertura, versão e histórico.
- `PermissionService` e RBAC compartilhado entre Discord/API/site.
- `SettingsService`, `panels` e registro de views persistentes.
- `AuditService` e `special_unit_events`.
- `web_action_outbox` e retry de sincronização.
- Cadastro canônico, hierarquia real de `ranks`, tenure, turnos e disciplina.
- Padrões do `TrainingService` para avaliação humana e histórico, sem reutilizar o domínio de turma
  como se fosse o novo caso individual.
- Design System e shell do site.

## 12. Componentes obsoletos

Devem ser desativados apenas no corte final:

- select único que envia candidatura imediatamente;
- aprovação direta de Unidade sem treinamento;
- piso global `special_unit_minimum_rank_level` aplicado após aprovação;
- painel administrativo que mostra apenas quantidade e um select de até 25 itens;
- quatro centrais separadas no principal, após confirmação de ausência de conteúdo único;
- publicadores ativos de curso e treinamento antigos;
- páginas/links “Cursos e treinamentos” quando o substituto estiver aceito;
- atalho de indicação que aprova Unidade automaticamente;
- concessão global de Unidade por `recruitment.approve` sem escopo explícito.

As tabelas históricas e o ledger de qualificação **não são obsoletos para exclusão**.

## 13. Nova arquitetura proposta

Adicionar sem duplicar serviços:

- `special_unit_configs`: configuração por guild canônico e Unidade, com descrição, patente mínima
  real, dias mínimos, inscrições abertas, versão, ator e timestamps.
- ampliar/reconstruir `special_unit_applications`: protocolo `UNI-*`, respostas JSON, origem, patente e
  tenure capturados, snapshot dos requisitos, estados, lock com expiração e versão.
- `special_unit_trainings`: caso individual um-para-um com candidatura, ticket, responsável, agenda,
  estados simples e versão.
- `special_unit_training_schedules`: cada agendamento/reagendamento, preservando histórico.
- ampliar eventos existentes com os tipos `UNIT_*` exigidos.
- ampliar `service_tickets` com tipo explícito `UNIT_TRAINING`; não criar outro ticket service.
- novas permissões RBAC: `unit.view`, `unit.apply`, `unit.application.review`, `unit.training.manage`,
  `unit.configuration.manage`, `unit.history.view` e `unit.manage.all`.

`special_unit_guild_resources` continua sendo o mapa de IDs por servidor. Não duplicar IDs em
`special_units`.

## 14. Estrutura final dos canais

No **DC 2**:

- reutilizar `1542020054072168479` como categoria **UNIDADES ESPECIAIS**;
- reutilizar/renomear `1542020054919413862` para **`unidades-especiais`**;
- publicar **quatro mensagens independentes**, uma por Unidade, no mesmo canal;
- reutilizar `1542020055741505597` como categoria **ADMINISTRAÇÃO**;
- reutilizar/renomear `1542020056517713921` para **`adm-unidades`**;
- criar/reutilizar categorias de tickets ativo/arquivo no DC 2 e gerar canais privados
  dinamicamente;
- reutilizar a infraestrutura de logs/transcrições; não criar canal de log por Unidade.

Após aceite: arquivar os painéis de Cursos/Treinamentos e as quatro centrais do principal. Só excluir
canais em fase posterior, mediante backup e autorização separada.

## 15. Fluxo completo do candidato

1. Abre `unidades-especiais` e escolhe uma das quatro mensagens.
2. Vê descrição, cargo, patente mínima, dias mínimos e estado aberto/fechado.
3. Clica `CANDIDATAR-SE`.
4. Backend valida cadastro, presença, consistência, Unidade aberta, patente, tenure e duplicidades.
5. Bot mostra exatamente o que atende/falta.
6. Se apto, abre modal curto: motivação, experiência e disponibilidade.
7. Transação cria `UNI-000142`, respostas e snapshot dos requisitos.
8. Confirmação efêmera mostra protocolo/status e botão `AGENDAR TREINAMENTO`.
9. Clique cria uma única sala privada e a relaciona à candidatura.
10. Responsável define data; candidato confirma ou solicita novo horário.
11. Treinamento passa por aguardando, agendado, confirmado e em treinamento.
12. Aprovação/reprovação/cancelamento preserva histórico, notifica e arquiva o ticket.

## 16. Fluxo completo do Comando

1. Abre `adm-unidades`.
2. O backend mostra somente Unidades e ações autorizadas.
3. `MINHA UNIDADE` exibe métricas, requisitos e inscrições.
4. Configuração altera patente mínima, dias ou estado com confirmação, versão e auditoria.
5. Fila mostra uma candidatura por vez, mais antiga primeiro, com anterior/próxima.
6. `ASSUMIR ANÁLISE` usa compare-and-set e lock expirável.
7. Fila de treinamentos separa sem horário, hoje, próximos, andamento e finalizados.
8. Responsável assume, agenda, reagenda, inicia e decide.
9. Aprovação dispara transação de domínio e outbox; falha de Discord permanece pendente para retry.
10. `PRÓXIMO` leva ao item seguinte sem voltar ao menu.

## 17. Modelo de permissões

- Membro ativo: ver painéis, consultar elegibilidade, candidatar-se e operar sua confirmação.
- Auxiliar da Unidade X: ver X e auxiliar treinamento X, conforme grants explícitos.
- Comando da Unidade X: configurar, analisar e decidir somente X.
- Comando Y: sem acesso automático a X.
- Alto Comando/Admin: acesso global apenas via `unit.manage.all` ou bootstrap técnico existente.
- Todo endpoint/callback recebe `unit_code`, resolve recursos reais e valida escopo no backend.
- Workers não confiam no ator do payload; revalidam estado, versão e destino.
- Cargos Discord ficam sem permissões globais administrativas; acesso ocorre por overwrites e RBAC.

## 18. Modelo de candidatura

Campos mínimos:

- `id`, `protocol`, `recruitment_guild_id`, `canonical_guild_id`, `member_id`, `discord_id`;
- `unit_code`, `status`, `origin`, `answers_json`;
- `rank_id_at_application`, `rank_level_at_application`, `rank_name_at_application`;
- `corporation_days_at_application`;
- `minimum_rank_id_at_application`, `minimum_rank_level_at_application`,
  `minimum_days_at_application`, `requirements_version`;
- `assigned_to`, `assigned_at`, `assignment_expires_at`;
- `reviewed_by`, `reviewed_at`, `decision_reason`;
- `version`, `submitted_at`, `updated_at`.

Estados recomendados: `PENDING`, `IN_REVIEW`, `AWAITING_TRAINING`, `APPROVED`, `REJECTED`,
`CANCELLED` e `LEGACY_REVIEW`. O estado detalhado do treinamento fica na tabela própria.

Manter a regra atual de uma Unidade ativa por militar como padrão de compatibilidade. Alterá-la exige
decisão de produto e mudanças em `members.unit`, índices, ausência, cargo e UI.

## 19. Modelo de treinamento

`special_unit_trainings`:

- vínculo único com candidatura e ticket;
- `status`: `AWAITING_SCHEDULE`, `SCHEDULED`, `CONFIRMED`, `IN_TRAINING`, `APPROVED`, `REJECTED`,
  `CANCELLED`;
- responsável, agenda vigente, confirmação, início real, conclusão, resultado e motivo;
- `version`, correlação e timestamps.

`special_unit_training_schedules` registra cada proposta, confirmação, pedido de novo horário e
substituição. Datas devem ser persistidas em UTC; apresentação usa `America/Sao_Paulo`.

## 20. Estratégia dos tickets

- Estender `TicketService` e o `CHECK` de `service_tickets.ticket_type` para `UNIT_TRAINING`.
- Guardar `application_id`, `unit_code` e `training_id` no payload e também por FK no domínio.
- Unicidade real: um treinamento/ticket ativo por candidatura, protegida por índice e transação.
- Criar a sala no DC 2 com candidato, Comando da Unidade, responsáveis e bot.
- Reutilizar claim/release, participantes, prioridade, transcrição, fechamento, arquivo e reabertura.
- Configurar no DC 2 categorias ativa/arquivo, papel responsável e destino de transcrição antes de
  liberar o botão.
- Se criação do canal falhar, manter registro `ROOM_PENDING`/outbox e permitir retry idempotente.

## 21. Estratégia de auditoria

- Eventos de domínio em `special_unit_events` com `correlation_id` único e metadata minimizada.
- Decisões institucionais também passam por `AuditService`/`audit_logs`.
- Alteração de requisito registra campo, antes, depois, ator, Discord ID, Unidade e horário.
- Agendamentos e reagendamentos ficam em histórico imutável.
- Tickets continuam usando `ticket_operation_events` e transcrições com hash.
- Não gravar respostas sensíveis completas em logs operacionais; mantê-las no registro autorizado.

## 22. Integração com cadastro/cargos

- Usar `members` e `ranks` do guild canônico para patente e tenure.
- Aprovação cria/ativa `special_unit_memberships` e projeta `members.unit` por compatibilidade.
- Aplicar apenas cargos mapeados em `special_unit_guild_resources`.
- Preservar cargos não gerenciados.
- Reutilizar `SPECIAL_UNIT_ROLE_SYNC` nos dois servidores.
- Banco confirma a decisão antes do Discord; falha externa vira retry pendente, nunca rollback falso.
- Não promover patente automaticamente como efeito colateral da Unidade sem regra explícita aprovada.
- Antes do corte, reconciliar detentores dos cargos reais com memberships, produzindo relatório de
  adicionar/manter/remover sem mutação automática.

## 23. Integração com Analytics

Não existe uma tabela genérica `analytics_events`. O sistema global atual usa consultas sobre dados
operacionais e endpoints de dashboard/relatórios. Portanto:

- `special_unit_events`, candidaturas e treinamentos serão a fonte do mesmo ecossistema;
- ampliar `/v1/dashboard`/relatórios ou criar endpoints do mesmo Command Center, não outro serviço;
- métricas: volume por Unidade/período, demanda, pendentes, aprovação, reprovação, no-show, tempo até
  treinamento/decisão e produtividade de responsáveis;
- o site ganha área **Unidades Especiais** e histórico no dossiê;
- retirar visualizações antigas de Cursos somente após preservar/realocar Qualificações necessárias.

## 24. Plano de migração

1. **Auditoria e backups:** banco, layout Discord, painéis, cargos, overwrites e mensagens.
2. **Correção de segurança autorizada:** remover `Administrator` dos três cargos de Comando no DC 2
   e validar acesso granular.
3. **Migração aditiva:** criar configuração, ampliar candidatura, criar treinamento/agendas e tipo de
   ticket; feature flag permanece desligada.
4. **Seed:** mapear quatro Unidades e todos os IDs reais; não criar cargos paralelos.
5. **Legado:** migrar 8 candidaturas para `LEGACY_REVIEW`; gerar protocolo; não inventar respostas ou
   snapshots. Resolver formalmente a candidatura de curso pendente.
6. **Reconciliação:** comparar memberships, `members.unit` e detentores reais dos cargos; aplicar só
   um plano aprovado.
7. **Serviços:** implementar configuração, elegibilidade, candidatura, fila, agenda, decisão e retry.
8. **Painéis:** publicar quatro mensagens independentes e a nova central administrativa no DC 2.
9. **Tickets:** configurar infraestrutura do DC 2 e liberar treinamento individual.
10. **Site/Analytics:** adaptar rotas, navegação, dossiê e métricas no sistema existente.
11. **Shadow/aceite:** testes locais, restore test, restart, smoke humano com membro/Comando/Admin.
12. **Corte:** fechar publicadores antigos, ativar o novo fluxo e observar filas/outbox.
13. **Limpeza reversível:** arquivar painéis/canais antigos. Exclusão física fica fora do primeiro
    corte e exige autorização posterior.

Rollback: desligar feature flag, restaurar painéis antigos e manter tabelas aditivas. Nenhuma fase
deve depender de apagar histórico para voltar.

## 25. Plano de testes

### Domínio e banco

- abaixo/acima da patente e tenure; inscrições fechadas; cadastro/presença inconsistentes;
- candidatura e ticket duplicados; protocolo único; snapshot imutável após mudar requisito;
- candidatura legada sem dados inventados;
- uma Unidade ativa por militar; migração e `foreign_key_check`/`quick_check`;
- clique duplo, dois avaliadores, lock expirado, compare-and-set e retry parcial.

### Permissões

- Comando X configura/processa X; não acessa Y;
- auxiliar com ações limitadas; Admin global explícito; membro sem acesso administrativo;
- validação server-side no Discord, API e site;
- cargos de Comando sem `Administrator` e matriz de overwrites validada com contas reais.

### Treinamento/ticket

- criação, claim, data, confirmação, reagendamento, início, aprovação, reprovação e cancelamento;
- não comparecimento; transcrição; fechamento/arquivo/reabertura;
- falha de criação de canal e falha de aplicação de cargo com retry sem duplicação.

### Integração

- cargo correto nos dois servidores, cargos válidos preservados, cadastro e histórico atualizados;
- eventos/audit/Analytics emitidos uma vez;
- promoção, recrutamento, prontidão, patrulha e dossiê continuam corretos durante a transição;
- atalho de indicação não contorna o treinamento.

### UX e operação

- quatro mensagens independentes, mobile, fila anterior/próxima, poucos cliques e sem comandos;
- restart com views/painéis persistentes;
- deploy, migração, healthcheck, um único Gateway e serviço legado offline;
- smoke humano separado para candidato, Comando de cada Unidade e Alto Comando;
- rollback ensaiado com backup restaurável.

## Decisões recomendadas antes da implementação

1. **Manter uma única Unidade ativa por militar** nesta entrega, preservando a regra atual.
2. **Executar tickets no DC 2**, onde ocorre a candidatura, configurando ali a infraestrutura faltante.
3. **Aposentar o fluxo ativo de Cursos**, mas preservar ledger, histórico e cargos de qualificação até
   que promoção/recrutamento/prontidão/patrulha tenham migração aprovada.
4. **Não promover patente automaticamente** ao aprovar uma Unidade; patente mínima é requisito de
   entrada, não recompensa implícita.
5. **Migrar candidaturas antigas para revisão humana**, sem aprovação automática.

Com essas decisões aprovadas, a próxima etapa segura é a migração aditiva e feature-flagged, sem
publicar painéis nem alterar cargos durante a primeira entrega técnica.
