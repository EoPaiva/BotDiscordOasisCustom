# Plano de evolução — bate-ponto, patrulhas e viaturas

Atualizado em 2026-08-24. Fonte integral: `C:\Users\mpaii\.codex\attachments\1315e6e1-7ed5-4e34-9345-0e3a373045da\pasted-text.txt`.

## Limite de publicação

O limite de publicação foi cumprido: nenhum componente isolado foi liberado. O conjunto completo foi
publicado somente depois dos testes unitários, integração, concorrência, restart, backup e autorização
explícita já registrada do proprietário.

## Inventário confirmado

| Necessidade | Base existente preservada | Lacuna real |
|---|---|---|
| Sessão de serviço | `shifts`, `shift_segments`, `shift_adjustments`, `voice_events`; índice parcial de uma sessão `ACTIVE`/`GRACE` por membro; locks por membro | O início é manual e não há vínculo persistido com a viatura atual. |
| Troca e saída de call | `ShiftService.handle_voice_transition()` cria segmentos, mantém a sessão entre calls autorizadas e usa grace | A regra patrol→patrol automática precisa sincronizar composição de viatura. |
| Reinício | `recover_shift()`, heartbeat e `bot_runtime` | Não abre sessão para presença nova nem reconstrói viaturas automáticas. |
| Calls de patrulha | `patrol_channels` por ID, tipo `WAITING`/`ACTIVE`, rótulo e ordem; `authorized_voice_channels` | Faltam capacidade, chave lógica e regras específicas por cargo. |
| Presença ao vivo | `patrol_voice_presence`, atualizada em voz, ready e loop de um minuto | É só projeção de dashboard, sem histórico de composição. |
| Patrulhas/comando | `patrols`, `patrol_members`, `patrol_commander_history`, índices de uma patrulha/call/membro e eleição por hierarquia | PTR formal de fila não representa toda call como viatura automática. |
| Painéis | `SERVICE`, `PATROL_CENTRAL`, `PATROL_REPORT` e mensagens persistentes | Efetivo ainda é individual; falta grupo por viatura e "sem viatura". |
| Relatórios | Histórico PTR, feedback/debrief e `disciplinary_occurrences` | Não existe PTR persistente com ocorrências, artigos e evidências. |
| Segurança | RBAC, auditoria, SQLite transacional e registry por ID | Ações manuais novas precisam de permissões e trilha antes/depois. |

## Decisão de reaproveitamento

Não haverá segundo sistema. `patrols` evoluirá como a entidade durável de viatura/PTR: já guarda
call, status, sequência, integrantes e comandante. `shifts` continua a fonte única das horas e
`shift_segments` a fonte única do tempo por call. `patrol_voice_presence` fica apenas como leitura
rápida, nunca como histórico oficial.

Uma única orquestração de domínio deverá coordenar presença, sessão, composição, comandante e painel.
Os listeners atuais de `ShiftCommands` e `OperationsCommands` não podem continuar decidindo a mesma
transição em paralelo.

## Modelo aditivo proposto

1. Estender `patrols` com número visual não reutilizado e fonte de criação (`VOICE_AUTO`,
   `QUEUE_AUTO`, `ADMIN`), preservando todos os PTRs atuais.
2. Estender `patrol_members` e acrescentar uma timeline append-only de eventos de composição:
   criada, entrou, saiu, comandante, troca de call e encerrada.
3. Estender `patrol_channels` ou criar regra filha por ID para chave lógica, capacidade e cargos
   permitidos; nomes visuais nunca serão chave interna.
4. Adicionar `patrol_reports`, ocorrências, evidências, categorias configuráveis e artigos/
   enquadramentos. Evidências terão URL/attachment persistente, autor e data.
5. Criar índices parciais para uma viatura ativa por call, integrante ativo por membro e comandante
   ativo por viatura, aproveitando as proteções existentes.
6. Todas as migrations serão aditivas, com defaults compatíveis; nenhum ponto, membro, PTR ou
   auditoria será apagado.

## Regras de domínio planejadas

- Entrada em call `ACTIVE`: validar membro/RBAC, garantir sessão única, criar/localizar viatura,
  associar integrante e recalcular comandante pela hierarquia configurada.
- Alfa → Bravo: manter sessão, fechar somente o segmento anterior, abrir outro e atualizar as duas
  composições sem duplicar horas.
- Patrol → call não classificada ou desconexão: encerrar pela regra final compatível com o grace
  period; o tempo não poderá ser fabricado.
- Call vazia: encerrar viatura e preservar seu histórico. Sessão válida fora de viatura aparece em
  "Efetivo sem viatura", nunca desaparece.
- Restart: Discord é a presença atual e SQLite é o histórico. Recuperação é idempotente ou envia
  ambiguidade para revisão, sem criar tempo fictício.
- Ajuste administrativo: RBAC, motivo, valores antes/depois, correlation ID e auditoria.

## Relatórios PTR

O sistema atual será evoluído, não substituído. Ao encerrar uma patrulha, a prévia poderá congelar
viatura, call, comandante, integrantes, início/fim e duração. Ocorrências, perdas, artigos e
evidências serão normalizados e protegidos por RBAC. Indicadores futuros consultarão esses registros
e `shifts`, nunca mensagens Discord.

## Riscos e contenções

| Risco | Contenção |
|---|---|
| Dois listeners para a mesma voz | Orquestrador único, locks/constraints e testes concorrentes. |
| Duplicata/reconexão/duas instâncias | Idempotência, índices parciais, recovery e Gateway único. |
| Tempo duplicado em troca | `shift_segments` canônico e E2E patrol→patrol/patrol→não-patrol. |
| Fila PTR x viatura automática | Fontes de criação explícitas, sem entidades paralelas. |
| Flood/rate limit de painéis | Editar mensagem persistente e coalescer atualizações. |
| Evidência sensível exposta | RBAC server-side, URLs persistentes e auditoria. |
| Migration interrompida | Backup, cópia do banco, nenhum deploy parcial e restore testado. |

## Fases e aceite

1. Fechar regras abertas: grace, calls de serviço não-patrulha, capacidade e cargos.
2. Implementar localmente migrations aditivas, core e orquestração, sem listener novo em produção.
3. Implementar viatura, comandante, timeline e painel agrupado.
4. Implementar PTR, ocorrências, artigos, evidências e correções administrativas auditadas.
5. Executar unitários, integração SQLite, concorrência, restart, os dez cenários obrigatórios,
   permissões e Discord de homologação.
6. Somente com todos os gates verdes: backup, snapshot, uma instância, autorização explícita e
   validação de patrulha real isolada.

## Estado atual

Concluído e publicado em 2026-08-24. A migration 37 evolui as tabelas existentes e adiciona timeline
de composição, relatórios PTR, integrantes congelados, ocorrências, artigos, evidências e correções
administrativas auditadas. `DutyPatrolService` é a única orquestração de voz: inicia e encerra ponto,
mantém uma sessão ao trocar de call, cria/encerra viatura, elege ou transfere comandante e reconcilia
presença após restart sem fabricar tempo.

Os painéis persistentes agora agrupam o efetivo por viatura e exibem explicitamente quem está sem
viatura. A administração configura calls por ID, capacidade, cargos e ponto automático; corrige
integrantes, comandante e ponto com motivo/antes/depois; e gerencia categorias, artigos e relatórios.
O relatório PTR congela a composição, aceita ocorrência/evidência e fornece ao membro somente sua
visão segura.

Gates finais: 419 testes Python, 41 testes web, Ruff, compileall, `main.py --check`, lint, typecheck e
build. Produção: health 200, migration 37, aplicação combinada como único Gateway e backup remoto com
`quick_check=ok` e zero violações de FK. A recuperação ao vivo encontrou duas sessões ligadas a uma
viatura ativa; sem sessão duplicada, call duplicada, comandante aberto duplicado, vínculo inválido ou
ação pendente na outbox.
