# Fase 19 — Sincronização Discord, identidade funcional e RBAC

Status: **EM EXECUÇÃO**.

Fonte integral: `docs/source-prompts/15-discord-role-access-sync-original.md`.

Esta especificação consolida o complemento obrigatório recebido para eliminar divergências como
`Discord = Comandante Geral`, `site = Membro`, `bot = Superior` e `banco = Membro`. Ela amplia o
`RankSyncService`, o `PermissionService`, a Portaria Digital e o Centro de Comando existentes; não
autoriza uma segunda implementação paralela de patente, identidade ou autorização.

## Objetivo e fluxo oficial

Para cargos funcionais e níveis de acesso, o Discord é a fonte operacional de verdade. O estado
persistido é a projeção estruturada e auditável consumida por bot, API e site:

```text
DISCORD
  -> RECONCILIAÇÃO DE IDENTIDADE
  -> PATENTE + CARGO PRINCIPAL + FUNÇÕES + PERFIL
  -> PERMISSION SERVICE
  -> BOT + API + SITE
```

Uma alteração manual de cargo relevante no Discord deve convergir automaticamente para o mesmo
estado funcional em todos os consumidores. Alterações cosméticas não podem modificar autorização.

## Princípios obrigatórios

- Discord roles são referenciadas por `role_id`; nomes visuais nunca identificam regras.
- Patente, cargo funcional, qualificação, acesso, sistema e cosmético são conceitos separados.
- Um membro possui no máximo um cargo funcional principal, escolhido por prioridade configurada, e
  pode possuir várias funções secundárias simultâneas.
- Funções secundárias não são descartadas quando existe cargo principal de maior prioridade.
- Acesso não depende apenas do cargo principal ou de um nível numérico.
- Permissão ausente é negada por padrão.
- Frontend esconde superfícies apenas por UX; toda ação é autorizada novamente no backend.
- Remoção de privilégio tem prioridade sobre concessão e deve produzir downgrade imediato ou em
  poucos segundos.
- Mudanças são transacionais, idempotentes, auditadas e invalidam caches relacionados.
- O bot não altera cargos cosméticos, não infere acesso por nomes e não cria loops ao observar uma
  alteração originada pelo próprio sistema.
- Sincronização de roles não sobrescreve horas, disciplina, candidaturas, avaliações, cursos ou
  outros dados não relacionados.

## Integração com a arquitetura existente

### RankSync

O fluxo de patente existente continua sendo a única implementação autorizada para:

```text
Discord rank role -> rank_id -> format_member_nickname() -> histórico/auditoria
```

A Fase 19 deve evoluir a reconciliação atual para uma única pipeline de identidade, equivalente a
`reconcile_member_identity_from_discord()`, coordenando patente, nickname, cargos funcionais,
funções, perfil de acesso e versão de autorização. Não criar outro listener ou resolvedor de
patentes.

### PermissionService

O `PermissionService` existente será a única porta de autorização para bot, API, site e workers. A
função central equivalente a `resolve_effective_permissions(member)` deve compor:

```text
perfil base
+ permissões da patente
+ permissões das funções Discord mapeadas
+ concessões específicas do membro
- negações explícitas
```

Negações explícitas prevalecem. Perfis elevados não significam acesso automático a secrets,
Railway, API keys ou infraestrutura. Cargo RP e administrador técnico permanecem separados.

### Portaria Digital e recrutamento

- Ao concluir cadastro, os roles Discord atuais são reconciliados antes de definir a identidade
  efetiva; um usuário com função válida não permanece artificialmente como `MEMBER`.
- Uma aprovação inicial pode projetar `RECRUIT`, mas futuras alterações no Discord atualizam a
  identidade sem edição manual do cadastro.
- Membro sem cadastro continua sujeito ao access gate; possuir role funcional não equivale a
  identidade automaticamente aprovada.

### Persistência e topologia

A implementação deve usar a fonte de dados operacional única do ambiente. Enquanto o runtime
oficial permanecer em SQLite/Railway, a migration e os serviços usam essa base. Uma migração futura
para PostgreSQL/Supabase deverá preservar o mesmo modelo e pipeline, sem dual-write.

## Modelo de dados

A migration versionada deve adaptar o schema real com relações equivalentes às seguintes, sem
apagar tabelas ou histórico existente.

### Membro

`members` passa a manter, diretamente ou por projeção normalizada:

- `rank_id` — patente atual, preservando a FK existente;
- `primary_position_id` — cargo funcional principal resolvido;
- `access_profile_id` ou referência equivalente ao perfil efetivo;
- `discord_synced_at` — UTC epoch do último estado Discord aplicado;
- `authorization_version` — inteiro monotônico incrementado quando a autorização muda;
- estado, datas e campos de identidade já existentes.

### Entidades novas ou equivalentes

- `positions`: identificador interno estável, nome de apresentação, prioridade, flag de candidato a
  cargo principal e estado ativo.
- `member_positions`: associação de todas as funções efetivas do membro, com indicação de principal,
  origem e timestamps; unicidade por guild/membro/cargo.
- `discord_role_mappings`: `guild_id`, `discord_role_id`, tipo, identificador interno, prioridade,
  perfil concedido, candidato a principal e `enabled`.
- `access_profiles`: perfis configuráveis e ordenação apenas informativa.
- tabelas/relações de permissões por perfil, patente, posição, concessão individual e negação
  individual, reutilizando o RBAC existente sempre que possível.
- histórico de identidade/sincronização com estado anterior, estado posterior, origem, ator quando
  conhecido, correlação e timestamp.
- estado agregado de execução para métricas, falhas, divergências e fila pendente.

### Tipos de role mapping

```text
RANK
POSITION
QUALIFICATION
SYSTEM
COSMETIC
ACCESS
```

Somente mappings habilitados e explicitamente funcionais participam de autorização. Deve existir
unicidade por `guild_id + discord_role_id`, FKs válidas e constraints que impeçam duas posições
principais simultâneas para o mesmo membro.

### Perfis iniciais

Os nomes podem ser adaptados aos perfis já usados pelo projeto, preservando equivalência:

```text
CANDIDATE
RECRUIT
MEMBER
SUPERVISOR
COMMAND
HIGH_COMMAND
SYSTEM_ADMIN
```

O nível/ordem auxilia apresentação e resolução, mas não substitui permissões explícitas.

## Serviço central de reconciliação

Um serviço central, integrado ao `RankSyncService`, deve executar deterministicamente:

1. ler o conjunto final de roles do membro pela API/cache fresco do Discord;
2. filtrar apenas `discord_role_mappings` habilitados por ID;
3. delegar a resolução de patente ao fluxo RankSync existente;
4. resolver todas as posições/funções funcionais;
5. selecionar a posição principal pela maior prioridade configurada, com desempate estável;
6. preservar as demais como funções secundárias;
7. resolver o perfil e as permissões efetivas;
8. comparar estado desejado e persistido;
9. atualizar identidade, versão de autorização, histórico e auditoria na mesma transação;
10. invalidar caches e publicar evento/outbox para os consumidores;
11. reconciliar nickname somente pela função central já existente.

O serviço deve aceitar origens explícitas:

- `DISCORD_ROLE_CHANGE`;
- `SYSTEM_RECONCILIATION`;
- `PANEL_ACTION`;
- `REGISTRATION`;
- `MANUAL_DATA_UPDATE`.

Quando o ator real não puder ser comprovado, registrar `UNKNOWN_DISCORD_ACTOR`; nunca inventar o
responsável. Consulta ao audit log é opcional e deve lidar com atraso/ambiguidade sem atribuição
falsa.

## Eventos, idempotência e concorrência

- O listener `on_member_update`/`guildMemberUpdate` compara os IDs de roles anteriores e atuais.
- Alterações sem role mapeada são ignoradas sem escrita de identidade/autorização.
- Eventos próximos para o mesmo membro são coalescidos pelo debounce/lock já utilizado no
  RankSync.
- O resolvedor sempre avalia o conjunto final, não apenas o role adicionado ou removido.
- Updates condicionais e comparação before/after evitam history duplicado.
- Eventos gerados por alterações do próprio bot convergem sem repetir a alteração.
- Locks por membro são descartados depois do uso.

O histórico diferencia `RANK_CHANGED`, `POSITION_CHANGED`, `FUNCTION_ASSIGNED` e
`FUNCTION_REMOVED`. Adicionar Instrutor ou Recrutador não é promoção formal.

## Revalidação e recuperação

### Startup

No startup, reconciliar membros cadastrados/relevantes contra os roles atuais e corrigir eventos
perdidos durante downtime, sem criar membros implicitamente e sem duplicar histórico.

### Periódica

Executar job configurável de segurança em intervalo de horas, com lotes, métricas e proteção contra
rate limit. Não consultar toda a guild a cada minuto.

### Sob demanda

Permitir reconciliação individual e em lote para administrador autorizado. O lote possui preview
com contagens de sem alteração, posições divergentes, patentes divergentes, falhas e casos que
exigem revisão antes de aplicar.

Ações extremamente sensíveis — por exemplo segurança, bypass, lockdown ou gestão de Alto Comando —
podem exigir revalidação fresca contra Discord antes da autorização final.

## Sessões e revogação de privilégio

- O login Discord OAuth identifica o Discord User ID, confirma vínculo à guild, localiza o membro,
  obtém o estado relevante atual e resolve permissões server-side.
- A sessão carrega a `authorization_version` observada, não roles/perfis fornecidos pelo browser.
- Toda requisição protegida compara a versão da sessão com a versão atual ou resolve autorização
  atual por mecanismo equivalente.
- Quando role, patente, posição, perfil, grant ou deny muda, a versão é incrementada e caches são
  invalidados.
- Sessão com versão antiga deve revalidar/atualizar; se perdeu permissão, a ação retorna `403` mesmo
  com a interface antiga aberta.
- O downgrade deve ser propagado imediatamente ou em poucos segundos por evento/outbox/realtime.

Se o usuário perde acesso à página atual, o frontend atualiza o contexto e redireciona ao dashboard
ou apresenta `403 — Você não possui mais acesso a esta área`.

## Bot, API e Centro de Comando

### Bot

Botões, selects, modais e painéis usam `PermissionService.can(actor_member_id, permission)`. Nenhum
módulo mantém uma segunda regra por nome de cargo. Operações elevadas consultam estado sincronizado
ou revalidam o Discord quando o risco exigir.

### API

O contexto autenticado (`GET /v1/context`, `/me` ou equivalente) deve retornar, sem expor detalhes
sensíveis desnecessários:

```json
{
  "member": {
    "rank": "Coronel",
    "primaryPosition": "Comandante Geral",
    "functions": ["Instrutor"],
    "discordSyncedAt": 1787418840
  },
  "access": {
    "profile": "HIGH_COMMAND",
    "permissions": [],
    "authorizationVersion": 12
  }
}
```

Toda rota administrativa aplica a mesma autorização no backend. Campos de perfil, cargo ou
permissões enviados pelo cliente são ignorados.

### Site

- Sidebar e ações visíveis derivam da lista real de permissões retornada pela API, nunca de
  `if commanderGeneral`.
- A ficha do membro exibe patente, cargo principal, funções, perfil e último sync com Discord.
- O próprio membro pode consultar sua identidade funcional, sem necessariamente ver a matriz RBAC
  interna.
- A página `Sistema -> Discord -> Mapeamento de cargos` permite administrar role ID, tipo,
  identificador interno, prioridade, perfil e estado.
- A página `Sistema -> Discord -> Sincronização` mostra último sync, membros sincronizados,
  divergências, falhas e fila pendente, além de reparar um membro e reconciliar todos com preview.
- Realtime, SSE, WebSocket, polling invalidante ou mecanismo existente deve refletir alteração sem
  novo login ou F5 e revogar a navegação que perdeu acesso.

## Configuração e segurança

- Mapping e permissões são configuráveis por guild e administráveis somente com permissões
  técnicas específicas.
- `Comandante Geral`/`HIGH_COMMAND` não recebe secrets ou infraestrutura por inferência.
- Owner/bootstrap técnico segue o fluxo controlado existente e continua auditável.
- Nenhum nome de role, ordem visual do Discord, localStorage ou campo do frontend é fonte de
  autorização.
- Role cosmético, cor, apoiador, loja, ping e evento não alteram perfil ou permissões sem mapping
  funcional explícito.
- Ações de mapeamento, grants, denies, preview, aplicação e reparo produzem auditoria com correlação.

## Observabilidade

Registrar e expor de forma autorizada:

- momento e origem do último sync por membro;
- quantidade processada, alterada, sem mudança e falha;
- mismatches de patente, posição, perfil e versão;
- duração e resultado das reconciliações;
- fila/retry pendente;
- invalidação de sessão/cache;
- erros de API Discord e rate limit sem vazar token ou dados pessoais.

## Testes obrigatórios do prompt

1. **Membro base:** role Discord mapeada como Membro resulta em perfil `MEMBER`.
2. **Concessão de Comandante Geral:** adicionar o role por ID atualiza automaticamente
   `primaryPosition = COMMANDER_GENERAL` e `accessProfile = HIGH_COMMAND`.
3. **Upgrade durante sessão:** usuário já logado recebe Comandante Geral e o site atualiza sem novo
   login.
4. **Downgrade durante sessão:** remover Comandante Geral revoga imediatamente o acesso elevado e
   incrementa/invalida a versão de autorização.
5. **Funções múltiplas:** Comandante Geral + Instrutor resulta em principal
   `COMMANDER_GENERAL` e função secundária `INSTRUCTOR`.
6. **Patente integrada:** mudança de patente reutiliza RankSync, atualiza `rank_id` e recalcula o
   nickname pela função única.
7. **Cargo cosmético:** adicionar/remover role não funcional não altera perfil, permissões ou versão
   de autorização.
8. **Evento perdido:** role alterada com o bot offline é corrigida pela reconciliação de startup.
9. **Backend após downgrade:** endpoint administrativo chamado por interface antiga retorna `403`
   depois da perda de cargo.

## Cobertura adicional mínima

- prioridade determinística e desempate de cargo principal;
- preservação de duas ou mais funções secundárias;
- grants combinados e deny explícito prevalecendo;
- idempotência, debounce, evento do próprio bot e concorrência;
- transação sem estado intermediário entre identidade, versão, histórico e auditoria;
- ator desconhecido sem atribuição inventada;
- cache invalidado e contexto do site convergente;
- reconciliação individual, preview em lote, aplicação e retry parcial;
- mapeamento desabilitado e role renomeada sem quebra por uso de ID;
- cadastro/recrutamento integrados sem liberação de pessoa não aprovada;
- nenhuma alteração em horas, disciplina, candidatura, avaliações e cursos.

## Definition of Done

A Fase 19 só pode ser concluída quando houver evidência de que:

- o mapping de roles Discord por ID existe e é configurável;
- patente e cargo/função são persistidos separadamente;
- todas as funções do membro são preservadas e uma principal é resolvida por prioridade;
- `on_member_update` usa a pipeline central e cargos cosméticos são ignorados;
- cadastro, bot, API, site e RBAC convergem automaticamente;
- sessões antigas perdem privilégio após downgrade e o backend retorna `403`;
- startup, reconciliação periódica e reparo sob demanda existem;
- caches e contexto web são invalidados/atualizados;
- histórico e auditoria distinguem patente, posição e função sem duplicidade;
- os nove testes obrigatórios e a cobertura adicional passam;
- Ruff, pytest, compile/import smoke, `python main.py --check` e testes web passam;
- validação real proporcional ao risco comprova concessão e remoção por role ID sem expor secrets;
- `PROJECT_HANDOFF.md`, fila, ledger e relatório vivo foram atualizados com evidências reais.

