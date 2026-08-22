# Expansão de Operações Inteligentes — CHOQUE - BGR

Status: **CONCLUÍDO E VALIDADO EM 2026-08-22**.

Implementação autoritativa: migration v15 em `choque/database.py`, domínio em
`choque/operations.py`, UI/listeners em `cogs/operations_commands.py` e cobertura em
`tests/test_intelligent_operations.py`. O rollout real confirmou 13/13 tabelas, uma call de espera,
11 calls ativas, painéis `PATROL_CENTRAL`, `PATROL_REPORT` e `MEMBER_CENTRAL` editados no lugar e
zero comandos publicados. Indicadores continuam não punitivos e promoções/efetivações permanecem
decisões humanas.

Este documento é complementar a todas as fases e especificações anteriores. Ele não remove nem
substitui ponto por call, mínimo de patrulha, cadastro, carreira, sincronização de patente/cargo,
nickname, solicitações, ausências, disciplina, treinamentos, relatórios, auditoria, recuperação após
restart ou permissões existentes.

## Regra absoluta de interface

Não publicar slash commands, prefix commands, comandos por mensagem ou fluxos dependentes de texto
digitado no chat. Toda operação deverá seguir:

```text
MENSAGEM FIXA → BOTÃO → SELECT MENU → MODAL → AUTOMAÇÃO
```

Consultas pessoais e administrativas devem ser ephemeral sempre que possível. Os novos recursos
devem ser agrupados nas centrais existentes; não criar um canal separado para cada função.

## Princípios de integração

- O ponto continua sendo a única fonte de horas; formar patrulha não cria horas.
- O mínimo configurável de patrulha permanece inicialmente em 15 minutos.
- A call de espera não conta como patrulha; calls `PATRULHA_ATIVA` contam.
- Qualificações vêm do módulo de cursos existente.
- A Central de Identidade reutiliza o sincronizador e o formatador obrigatório
  `[ABREVIAÇÃO] NICK [ID]`.
- A caixa de entrada referencia solicitações existentes e não duplica seus dados.
- Flags, prontidão, elegibilidade, avaliações e integridade apoiam decisões humanas; nunca aplicam
  promoção, punição, suspensão, efetivação ou desligamento automaticamente.
- RBAC deve ser aplicado no backend, mesmo quando o painel estiver em canal privado.
- Listeners e jobs devem chamar serviços centrais; não espalhar regras de negócio por componentes.
- Persistência, auditoria e eventos devem ser idempotentes e sobreviver a restart quando aplicável.

## Fase A — Patrulha

### 1. Disponibilidade operacional

Persistir um estado operacional temporário independente do status administrativo:

- `AVAILABLE_FOR_PATROL`;
- `UNAVAILABLE`;
- `ON_PATROL`;
- `IN_TRAINING`;
- `AWAY`.

A Central do Membro terá um submenu **Disponibilidade** para marcar disponível ou indisponível.
Treinamento, ausência, reserva impeditiva e suspensão prevalecem logicamente sobre a escolha manual.

### 2. Central de Patrulha e fila FIFO

Criar um painel fixo **Central de Patrulha** com:

- **Entrar na fila**;
- **Sair da fila**;
- **Minha patrulha**;
- **Patrulhas ativas**.

A entrada na call configurável **Aguardando Patrulha** também deve inserir o membro na fila. A
saída remove imediatamente a entrada para impedir membros fantasmas. Persistir `queue_entered_at` e
respeitar rigorosamente a ordem de entrada.

O mínimo deve ser `MIN_PATROL_MEMBERS=2` por padrão, configurável e centralizado. Não hardcodar o
valor no listener de voz. Recalcular a fila em eventos de voz e ações do painel, sem polling por
segundo.

Antes de entrar na formação, validar que o membro:

- está cadastrado e `ACTIVE`;
- não está ausente, suspenso ou em reserva impeditiva;
- possui patente válida, nickname sincronizado e cargo de membro;
- não participa de outra patrulha ativa;
- não está em treinamento ou processo incompatível;
- está realmente conectado à call de espera.

Membros inválidos permanecem fora da formação e devem receber uma explicação adequada.

### 3. Formação automática

Calls de destino serão configuradas como `PATRULHA_ATIVA`, com habilitação e ordem explícitas. Uma
call está livre quando estiver vazia, habilitada, não reservada e sem patrulha ativa associada.

Fluxo obrigatório:

```text
MEMBRO ENTRA EM AGUARDANDO PATRULHA
→ VALIDAR MEMBRO
→ INSERIR NA FILA
→ HÁ PELO MENOS 2 VÁLIDOS?
→ RESERVAR A PRIMEIRA CALL LIVRE
→ SELECIONAR OS 2 PRIMEIROS
→ CRIAR RESERVA/REGISTRO DA PATRULHA
→ MOVER OS DOIS
→ REMOVER DA FILA
→ ATUALIZAR PAINÉIS
```

Com cinco membros e mínimo dois, formar dois pares quando existirem duas calls livres; o quinto
permanece na fila. Nunca formar patrulha individual. Se não houver call livre, manter todos na fila
e tentar novamente quando uma call ficar disponível.

A formação deverá possuir lock/debounce, reserva transacional e garantias únicas para que:

- um membro não participe de duas patrulhas ativas;
- uma call não possua duas patrulhas ativas;
- eventos simultâneos, clique e evento de voz, ou mais de um worker não dupliquem a formação.

Se faltar `Move Members` ou qualquer movimentação falhar, não ativar uma patrulha parcial. Registrar
a falha, reverter a reserva, preservar/recompor a fila quando possível e aguardar novo evento ou
ação administrativa, sem retry a cada segundo. DM de formação será opcional e configurável.

### 4. Ciclo e painel de patrulhas

Cada patrulha deve registrar identificador sequencial, participantes, call, início/fim, origem
automática ou administrativa, status e timestamps. Um painel fixo **Patrulhas Ativas** exibirá calls
ocupadas, quantidade de membros, duração aproximada e calls disponíveis. Atualizar somente em
eventos relevantes.

Encerrar quando a call ficar vazia, um superior confirmar pelo painel, a call deixar de ser válida
ou a manutenção exigir. Por padrão, uma patrulha continua com um integrante até ficar vazia
(`continue_until_empty=true`). A política alternativa `close_when_below_minimum` será configurável e
ações destrutivas exigirão confirmação.

Formar patrulha não inicia o ponto automaticamente. Tempo na call de espera não conta para o mínimo;
segmentos em calls `PATRULHA_ATIVA` integram a validação já especificada em
`MINIMUM_PATROL_TIME_SPEC.md`.

### 5. Histórico e feedback pós-patrulha

Adicionar **Minhas Patrulhas** à Central do Membro, com total, tempo, média, maior duração, pontos
válidos/invalidados, última patrulha e lista paginada. O detalhe mostra período, duração, call,
integrantes, segmentos, ponto associado e status.

Ao encerrar, o responsável poderá **Registrar feedback** ou **Ignorar**. O feedback individual terá
avaliação positiva, neutra ou necessita atenção e observação opcional. É privado, mostra autor/data
no dossiê administrativo e nunca vira punição automaticamente.

## Fase B — Visão operacional

### 6. Prontidão do efetivo

Criar painel resumido com membros em patrulha, aguardando, disponíveis, em treinamento, ausentes e
suspensos. Haverá visão pública agregada sem dados sensíveis e visão administrativa detalhada.

### 7. Validação inteligente de ponto

Detectar padrões explicáveis e não punitivos:

- muitos pontos invalidados;
- sessões repetidamente abaixo do mínimo;
- entradas/saídas ou desconexões excessivas;
- múltiplos pontos muito curtos;
- ajustes manuais frequentes;
- comportamento incomum ou divergência relevante entre tempo bruto e válido.

Flags sugeridas: `MANY_INVALID_SHIFTS`, `SHORT_SHIFT_PATTERN`,
`FREQUENT_VOICE_DISCONNECTS`, `MANUAL_ADJUSTMENT_FREQUENCY` e
`UNUSUAL_SESSION_PATTERN`. Cada flag deve registrar evidência e motivo exato, permanecer disponível
para revisão humana e nunca aplicar sanção.

### 8. Integridade do efetivo

Detectar membro sem patente/cargo/ID, duas patentes, nickname inválido, banco divergente do Discord,
desligado ainda com cargos, ausência encerrada ainda ativa, suspensão vencida, ponto inconsistente
e solicitação pendente por tempo excessivo.

Classificar cada achado como `AUTO_FIX_SAFE` ou `REQUIRES_REVIEW`. O painel mostrará totais,
problemas e **Corrigir seguros**. Nunca corrigir ambiguidades em lote sem confirmação.

### 9. Central de Identidade

Mostrar nicknames incorretos, patentes divergentes, membros sem ID e cargos inconsistentes. A
sincronização em lote apresentará prévia com quantidade de correções, divergências e pendências,
seguida de confirmação. Reutilizar `RankSyncService`/`format_member_nickname()` definidos em
`RANK_SYNC_SPEC.md`; não criar outra regra de identidade.

## Fase C — Desenvolvimento do membro

### 10. Matriz de qualificação

Construir a matriz a partir de cursos e qualificações existentes. O membro consulta sua visão; o
Comando consulta vários membros por filtros ou páginas legíveis. Não duplicar
`member_qualifications` nem criar embeds tabulares ilegíveis.

### 11. Requisitos automáticos para cursos

Permitir por curso: patente mínima, horas mínimas, pré-requisito, status ativo, tempo de corporação,
ausência de suspensão e qualificação específica. Ao clicar **Participar**, mostrar checklist
ephemeral com valores atuais. Bloquear inscrição explicando exatamente o que falta.

### 12. Avaliação pós-treinamento

Adicionar **Finalizar e avaliar**. Para cada participante, registrar presença, resultado
aprovado/reprovado, desempenho ótimo/bom/regular/insuficiente e observação opcional. Aprovação
atualiza qualificação, matriz e histórico com instrutor/data; não duplicar a lógica de conclusão já
existente.

### 13. Acompanhamento de recrutas

Identificar recrutas por patente/status configurável. O painel mostrará ativos, pendências e
avaliações. O perfil reúne ingresso, tempo como recruta, horas, patrulhas, formação, treinamentos,
avaliações e advertências.

Requisitos configuráveis de análise: dias, horas, cursos, quantidade de avaliações e ausência de
pendência crítica. O sistema informa **Apto para análise**, sem efetivar automaticamente.

### 14. Elegibilidade de promoção

O Comando seleciona um membro e vê patente atual, tempo na patente, horas, cursos obrigatórios, meta
recente, advertências bloqueantes e checklist. Resultado: `ELIGIBLE` ou
`REQUIREMENTS_PENDING`. Nunca executar promoção a partir da análise.

### 15. Dossiê funcional resumido

Função administrativa ephemeral e protegida por RBAC, com páginas para:

- identificação: Discord, ID, patente, status e ingresso;
- atividade: horas, última patrulha, quantidade e pontos invalidados;
- carreira: tempo na patente, promoções e rebaixamentos;
- qualificações: cursos concluídos e pendentes;
- disciplina: advertências e suspensões;
- administrativo: ausências, solicitações e última alteração importante;
- feedbacks privados recentes, com autor e data.

O conteúdo deve respeitar a permissão do operador; membro comum nunca consulta dossiê de terceiros.

## Fase D — Administração

### 16. Caixa de entrada administrativa

Módulo prioritário que unifica referências a ausências, correções de ponto, trocas, cadastros,
revisões disciplinares e avaliações pendentes. A mensagem fixa mostra contagens e abre filtros:
**Todas**, **Solicitações**, **Ponto**, **Membros**, **Disciplina** e **Treinamentos**.

Itens paginados exibem ID, tipo, membro, idade e prioridade, com **Analisar** e **Ver membro**. O dado
continua pertencendo ao módulo de origem. Updates condicionais impedem dois administradores de
decidir o mesmo item; processados deixam a lista de pendentes sem serem apagados.

### 17. Troca de atividade

Adicionar **Troca de atividade** à Central de Solicitações. O solicitante escolhe atividade/escala,
membro de destino e motivo. O destinatário precisa aceitar ou recusar; conforme o tipo, o Comando
aprova depois. Estados: `WAITING_MEMBER`, `WAITING_COMMAND`, `APPROVED`, `DENIED` e `CANCELLED`.
Nunca trocar sem consentimento.

### 18. Histórico de decisões

Painel imutável e paginado para aprovações, negações, promoções, rebaixamentos, ajustes de ponto,
suspensões, desligamentos, revisões e alterações administrativas. Mostrar ação, responsável,
membro, data, motivo, antes/depois e ID da auditoria.

### 19. Painel “O que mudou?”

Resumir hoje, 7 dias, 30 dias ou período personalizado: novos membros, promoções, rebaixamentos,
ausências, retornos, advertências, suspensões, cursos, horas de patrulha e pontos invalidados.
Submenus de Membros, Carreira, Disciplina, Atividade e Treinamentos mostram detalhes ephemeral.

### 20. Modo de manutenção

Permitir manutenção por módulo, com motivo e previsão opcional, sem desligar o bot. Interações devem
explicar o estado ao membro. Por padrão, manutenção de patrulhas impede novas formações e preserva
as existentes. Encerramentos ou outras ações destrutivas exigem confirmação adicional.

## Eventos, auditoria e permissões

Reutilizar um serviço/event bus central para eventos como `PATROL_CREATED`, `PATROL_FINISHED`,
`MEMBER_AVAILABILITY_CHANGED`, `TRAINING_EVALUATED`, `IDENTITY_RECONCILED` e
`ADMIN_DECISION_CREATED`.

Auditar ações relevantes, incluindo `PATROL_AUTO_CREATED`, `PATROL_AUTO_FINISHED`,
`PATROL_MEMBER_MOVED`, `AVAILABILITY_CHANGED`, `SHIFT_FLAGGED`, `ACTIVITY_SWAP_APPROVED`,
`TRAINING_EVALUATED`, `IDENTITY_BULK_SYNC`, `MAINTENANCE_ENABLED` e `MAINTENANCE_DISABLED`.
Navegação trivial, como abrir uma página, não gera log administrativo.

Permissões previstas:

```text
patrol.view                 patrol.manage
readiness.view              readiness.view.admin
qualification.view          qualification.manage
promotion.evaluate          member.dossier.view
recruit.followup            training.evaluate
patrol.feedback.create      patrol.feedback.view
admin.inbox.view            admin.inbox.manage
decision.history.view       integrity.view
integrity.fix               identity.manage
maintenance.manage          changes.view
```

Disciplina, feedback privado, histórico administrativo e dossiê completo nunca ficam disponíveis
para membros sem autorização.

## Organização dos painéis

- Central do Membro: **Disponibilidade** e **Minhas Patrulhas**.
- Central de Patrulha: fila, patrulha atual e patrulhas ativas.
- Central do Comando: **Caixa de Entrada**, **Prontidão**, **Dossiê**, **Integridade** e
  **O que mudou?**.
- Treinamentos: **Matriz de Qualificação**.
- Carreira: **Analisar Promoção**.

Respeitar limites de componentes usando painel principal → categoria → submenu ephemeral. Não criar
canais isolados para dossiês, feedbacks, qualificações, trocas ou integridade sem necessidade.

## Cobertura obrigatória

- Fila: 1, 2, 3 e 4 pessoas; nenhuma call livre; membro inválido; falha de `Move Members`;
  concorrência, FIFO, saída da fila e call liberada.
- Ponto inteligente: sessão normal/inválida, múltiplas invalidações, desconexões, ajustes e ausência
  de falso positivo.
- Cursos: sem requisito, patente/horas/pré-requisito insuficientes e todos cumpridos.
- Promoção: elegibilidade nunca promove.
- Dossiê/feedback: RBAC e ausência de exposição pública.
- Inbox: aparecimento, remoção após decisão sem apagar origem e concorrência entre administradores.
- Identidade: cargo manual, promoção, rebaixamento, nickname, duas patentes e restart.
- Manutenção: ativar, bloquear nova ação, retirar e preservar ações em andamento.

## Ordem obrigatória desta expansão

1. **Fase A — Patrulha**: disponibilidade, fila, formação automática, movimento, Central de
   Patrulha, histórico e feedback.
2. **Fase B — Visão Operacional**: prontidão, validação inteligente do ponto, integridade e
   identidade.
3. **Fase C — Desenvolvimento do Membro**: matriz, requisitos, avaliação, recrutas, elegibilidade e
   dossiê.
4. **Fase D — Administração**: inbox, troca, decisões, O que mudou e manutenção.

Cada módulo só estará pronto com UI, RBAC, persistência, auditoria, integração, idempotência,
tratamento de falhas, recuperação após restart quando aplicável e testes.

Filosofia: o bot deve **detectar, organizar, informar, automatizar tarefas previsíveis e registrar**;
o Comando deve **avaliar e decidir**.
