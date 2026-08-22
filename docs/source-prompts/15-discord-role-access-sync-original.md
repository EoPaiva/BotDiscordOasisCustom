# COMPLEMENTO OBRIGATÓRIO

# SINCRONIZAÇÃO DE CARGOS DO DISCORD, FUNÇÃO DO MEMBRO E NÍVEL DE ACESSO DO SITE

Este prompt é COMPLEMENTAR a toda a arquitetura já existente do projeto CHOQUE - BGR.

Existe atualmente uma inconsistência importante:

Um usuário pode possuir no Discord um cargo elevado, por exemplo:

```text
@Comandante Geral
```

mas no cadastro do membro/site ainda aparecer como:

```text
Membro
```

Isso está ERRADO.

A partir desta implementação, os cargos relevantes exercidos no Discord deverão ser automaticamente refletidos:

1. no cadastro do membro;
2. no Bot;
3. no Centro de Comando Web;
4. no RBAC;
5. nos registros funcionais;
6. na auditoria;
7. nas sessões/permissões do usuário.

---

# 1. PRINCÍPIO CENTRAL

Para CARGOS FUNCIONAIS e NÍVEIS DE ACESSO:

# O DISCORD É A FONTE OPERACIONAL DE VERDADE.

Exemplo:

```text
Discord:
@Comandante Geral
```

O sistema deverá refletir:

```text
Cargo atual:
Comandante Geral

Nível de acesso:
ALTO COMANDO
```

e NÃO:

```text
Cargo atual:
Membro
```

---

# 2. NÃO CONFUNDIR PATENTE COM CARGO/FUNÇÃO

O projeto deve distinguir claramente:

```text
PATENTE
```

de:

```text
CARGO FUNCIONAL
```

Exemplo:

```text
Patente:
Coronel

Cargo/Função:
Comandante Geral
```

Outro exemplo:

```text
Patente:
Capitão

Cargo/Função:
Instrutor
```

Outro:

```text
Patente:
Sargento

Funções:
Recrutador
Instrutor
Supervisor de Patrulha
```

Não armazenar tudo em uma única string `role`.

---

# 3. MODELO CONCEITUAL DO MEMBRO

Adaptar o schema real para suportar algo equivalente a:

```ts
Member {
  id
  discordUserId

  rankId

  primaryPositionId

  status

  accessProfileId

  discordSyncedAt

  createdAt
  updatedAt
}
```

Além disso, um membro pode possuir múltiplas funções:

```text
member_positions
```

ou estrutura equivalente.

Exemplo:

```text
Lucas

Patente:
Coronel

Cargo principal:
Comandante Geral

Funções adicionais:
Instrutor
Recrutador
```

---

# 4. MAPEAMENTO DOS CARGOS DO DISCORD

Criar configuração central dos cargos relevantes.

Exemplo conceitual:

```ts
DiscordRoleMapping {
  discordRoleId
  type
  internalId
  priority
  grantsAccessProfile
  isPrimaryPositionCandidate
  enabled
}
```

Tipos possíveis:

```text
RANK
POSITION
QUALIFICATION
SYSTEM
COSMETIC
ACCESS
```

---

# 5. NUNCA UTILIZAR NOME DO CARGO COMO IDENTIFICADOR

ERRADO:

```ts
if (role.name === "Comandante Geral")
```

CORRETO:

```text
discordRoleId
```

Os IDs dos cargos devem ser configurados no sistema.

O nome pode mudar sem quebrar o vínculo.

---

# 6. EXEMPLO DE MAPEAMENTO

Conceitualmente:

```text
Discord Role ID:
123456789

Nome atual:
Comandante Geral

Tipo:
POSITION

Position:
COMMANDER_GENERAL

Prioridade:
1000

Perfil de acesso:
HIGH_COMMAND
```

Outro:

```text
Discord Role:
Recrutador

Tipo:
POSITION

Perfil:
RECRUITMENT_STAFF
```

---

# 7. PERFIS DE ACESSO

Criar perfis de acesso configuráveis.

Exemplo inicial:

```text
CANDIDATE
RECRUIT
MEMBER
SUPERVISOR
COMMAND
HIGH_COMMAND
SYSTEM_ADMIN
```

Os nomes podem ser adaptados ao projeto.

---

# 8. EXEMPLO DE HIERARQUIA

Conceitualmente:

```text
CANDIDATE        10
RECRUIT          20
MEMBER           30
SUPERVISOR       50
COMMAND          70
HIGH_COMMAND     90
SYSTEM_ADMIN    100
```

Mas NÃO utilizar somente um número para autorização.

O sistema continua utilizando permissões explícitas.

---

# 9. CARGO → PERFIL DE ACESSO

Exemplo:

```text
@Recruta
→ RECRUIT

@Membro CHOQUE
→ MEMBER

@Superior
→ SUPERVISOR

@Comando
→ COMMAND

@Comandante Geral
→ HIGH_COMMAND
```

Tudo configurável.

---

# 10. COMANDANTE GERAL

Se um membro possuir o cargo Discord configurado como:

```text
COMANDANTE_GERAL
```

o cadastro deve imediatamente refletir:

```text
Cargo:
Comandante Geral

Access Profile:
HIGH_COMMAND
```

O site deve então liberar as funcionalidades correspondentes.

---

# 11. EVENTO PRINCIPAL

Monitorar:

```text
guildMemberUpdate
```

ou evento equivalente da biblioteca Discord utilizada.

Comparar:

```text
oldMember.roles
newMember.roles
```

Se cargos relevantes mudaram:

executar:

```ts
syncMemberDiscordRoles(member)
```

---

# 12. SERVIÇO CENTRAL

Criar um serviço único.

Exemplo:

```ts
DiscordMemberRoleSyncService
```

Responsabilidades:

```text
ler cargos atuais do Discord
↓
classificar cargos relevantes
↓
resolver patente
↓
resolver funções
↓
resolver cargo principal
↓
resolver perfil de acesso
↓
atualizar banco
↓
registrar histórico
↓
notificar realtime
```

Não espalhar essa lógica em vários listeners.

---

# 13. RESOLUÇÃO DO CARGO PRINCIPAL

Um membro pode possuir:

```text
Comandante Geral
Instrutor
Recrutador
```

Seu cargo principal deverá ser:

```text
Comandante Geral
```

baseado em:

```text
position.priority
```

Não na ordem visual retornada aleatoriamente.

---

# 14. FUNÇÕES SECUNDÁRIAS

Mesmo que o cargo principal seja:

```text
Comandante Geral
```

não perder:

```text
Instrutor
Recrutador
```

Essas funções continuam disponíveis para RBAC.

---

# 15. ACESSO NÃO DEVE DEPENDER APENAS DO CARGO PRINCIPAL

Exemplo:

```text
Cargo principal:
Capitão
```

e funções:

```text
Recrutador
Instrutor
```

Pode possuir permissões:

```text
training.manage
recruitment.review
```

mesmo que essas permissões não venham da patente.

---

# 16. PERMISSÕES EFETIVAS

Criar função central:

```ts
resolveEffectivePermissions(member)
```

Ela deverá considerar:

```text
perfil base
+
patente
+
funções Discord mapeadas
+
permissões específicas
-
negações explícitas
```

---

# 17. DENY BY DEFAULT

Se uma permissão não for explicitamente concedida:

```text
NEGAR
```

---

# 18. FRONTEND NÃO DECIDE PERMISSÃO

O site poderá esconder componentes baseado nas permissões retornadas pela API.

Mas isso é apenas UX.

O backend deve validar novamente TODA ação.

Nunca:

```ts
if (frontendSaysUserIsCommander)
```

---

# 19. LOGIN NO SITE

Ao realizar Discord OAuth:

backend deve:

1. identificar Discord User ID;
2. localizar membro;
3. consultar/revalidar associação à guild;
4. obter estado atual relevante;
5. resolver permissões;
6. criar sessão.

---

# 20. REVALIDAÇÃO DE CARGOS

Não confiar eternamente no cargo armazenado durante o login.

Se os cargos mudarem no Discord:

o sistema deve atualizar automaticamente.

---

# 21. REMOÇÃO DE CARGO É CRÍTICA

Exemplo:

Usuário possui:

```text
@Comandante Geral
```

e está logado no site.

Admin remove esse cargo no Discord.

O sistema deve:

```text
guildMemberUpdate
↓
RoleSync
↓
HIGH_COMMAND removido
↓
banco atualizado
↓
permissões recalculadas
↓
sessão/realtime atualizado
```

O usuário NÃO pode continuar administrando o site até o próximo login.

---

# 22. REBAIXAMENTO IMEDIATO

Priorizar revogação de privilégio.

Exemplo:

```text
HIGH_COMMAND
↓
MEMBER
```

O acesso elevado deve desaparecer imediatamente ou em poucos segundos.

---

# 23. SESSÃO

Adicionar algo equivalente a:

```text
permissionVersion
```

ou:

```text
authorizationVersion
```

no membro/sessão.

Quando permissões mudarem:

incrementar versão.

Requests com versão antiga deverão atualizar/revalidar sessão.

---

# 24. REALTIME

Se já estiver utilizando Supabase Realtime/WebSocket/SSE:

quando cargo mudar:

site deve refletir sem precisar F5.

Exemplo:

```text
CARGO ATUALIZADO

Comandante Geral
```

---

# 25. SE PERDER ACESSO À PÁGINA ATUAL

Exemplo:

usuário está em:

```text
/settings/security
```

e perde cargo administrativo.

Frontend deve receber atualização e redirecionar:

```text
/dashboard
```

ou:

```text
403 — Você não possui mais acesso a esta área.
```

---

# 26. CADASTRO DO MEMBRO

Na ficha do membro exibir:

```text
IDENTIDADE FUNCIONAL

Patente
Coronel

Cargo principal
Comandante Geral

Funções
• Instrutor
• Recrutador

Perfil de acesso
Alto Comando

Sincronizado com Discord
22/08/2026 14:14
```

---

# 27. PERFIL DO PRÓPRIO MEMBRO

O membro também poderá visualizar seus cargos/funções.

Não necessariamente mostrar detalhes internos de RBAC.

---

# 28. BOT

Quando outro módulo consultar o membro:

não deve trabalhar com cargo antigo em cache.

Utilizar os dados sincronizados ou resolver estado atual quando a ação exigir segurança elevada.

---

# 29. ALTERAÇÃO MANUAL NO DISCORD

Exemplo:

Administrador adiciona manualmente:

```text
@Comandante Geral
```

para Lucas.

Não precisa utilizar painel do bot.

O listener deverá detectar e atualizar:

```text
Lucas
Cargo: Comandante Geral
Access: HIGH_COMMAND
```

automaticamente.

---

# 30. REMOÇÃO MANUAL NO DISCORD

Da mesma forma:

```text
@Comandante Geral REMOVIDO
```

deve atualizar automaticamente o banco e site.

---

# 31. PATENTE

A lógica de sincronização de patente já definida anteriormente deve ser reutilizada.

Não criar outra.

Fluxo:

```text
Discord Role Change
↓
resolver Rank Role
↓
rankId
↓
formatMemberNickname()
```

---

# 32. CARGO FUNCIONAL

Adicionar à mesma reconciliação:

```text
resolver Position Roles
↓
primaryPosition
↓
secondaryPositions
↓
Access Profile
```

---

# 33. UMA ÚNICA PIPELINE DE IDENTIDADE

Idealmente:

```ts
reconcileMemberIdentityFromDiscord()
```

deverá coordenar:

```text
PATENTE
CARGO
FUNÇÕES
STATUS RELACIONADO
ACESSO
NICKNAME
```

sem duplicar regras.

---

# 34. NÃO ALTERAR CARGOS COSMÉTICOS

Discord possui cargos que podem ser:

* cor;
* apoiador;
* decoração;
* loja;
* ping;
* evento.

Esses cargos devem ser ignorados para acesso administrativo.

Mapear explicitamente quais cargos possuem significado funcional.

---

# 35. MULTIPLOS CARGOS FUNCIONAIS

Exemplo:

```text
@Superior
@Recrutador
@Instrutor
```

Não escolher apenas um e descartar os outros.

Armazenar todos.

---

# 36. PRIORIDADE

Exemplo:

```text
Comandante Geral       1000
Subcomandante Geral     950
Alto Comando            900
Comando                  800
Supervisor               600
Instrutor                 400
Recrutador                400
Membro                    100
```

Somente exemplo.

Tudo configurável pelo painel.

---

# 37. PAINEL DE MAPEAMENTO

No site:

```text
SISTEMA
→ DISCORD
→ MAPEAMENTO DE CARGOS
```

Tabela:

```text
CARGO DISCORD        TIPO       INTERNO            ACESSO

Comandante Geral     Função     COMMANDER_GENERAL  HIGH_COMMAND
Recrutador           Função     RECRUITER          MEMBER
Instrutor            Função     INSTRUCTOR         MEMBER
Coronel               Patente   COLONEL            -
```

---

# 38. CONFIGURAR PERMISSÕES POR FUNÇÃO

Exemplo:

```text
COMMANDER_GENERAL

dashboard.full
members.manage
members.dismiss
career.promote
career.demote
discipline.manage
recruitment.manage
training.manage
settings.manage
audit.read
security.manage
```

Tudo centralizado no RBAC já definido.

---

# 39. SEM ACESSO POR NOME VISUAL

Nunca inferir:

```text
"esse cargo tem Comandante no nome, então é admin"
```

Somente mapping configurado.

---

# 40. RECONCILIAÇÃO NO STARTUP

Quando bot iniciar:

executar reconciliação dos membros relevantes.

Objetivo:

corrigir estado caso eventos Discord tenham sido perdidos durante downtime.

---

# 41. EXEMPLO

Banco antes:

```text
Lucas
Cargo = MEMBER
```

Discord:

```text
@Comandante Geral
```

Startup reconciliation:

```text
MEMBER_ROLE_MISMATCH
↓
Cargo atualizado:
COMMANDER_GENERAL
↓
Access:
HIGH_COMMAND
```

---

# 42. RECONCILIAÇÃO PERIÓDICA

Além de eventos realtime, considerar job periódico de segurança.

Não precisa consultar tudo a cada minuto.

Exemplo:

```text
a cada algumas horas
```

ou configuração adequada.

Objetivo é corrigir eventual evento perdido.

---

# 43. RECONCILIAÇÃO SOB DEMANDA

Antes de uma ação extremamente sensível, pode haver revalidação atual contra Discord.

Exemplos:

```text
alterar configurações de segurança
gerenciar bypass
promover Alto Comando
lockdown
```

---

# 44. ORIGEM DA ALTERAÇÃO

Histórico deve indicar:

```text
DISCORD_ROLE_CHANGE
SYSTEM_RECONCILIATION
PANEL_ACTION
```

---

# 45. HISTÓRICO FUNCIONAL

Se mudar cargo funcional:

```text
Membro
→ Comandante Geral
```

registrar:

```text
POSITION_CHANGED
```

com:

```text
before
after
timestamp
origin
```

---

# 46. NÃO TRATAR TODA FUNÇÃO COMO PROMOÇÃO

Adicionar:

```text
@Instrutor
```

não significa promoção.

Histórico deve distinguir:

```text
RANK_CHANGED
POSITION_CHANGED
FUNCTION_ASSIGNED
FUNCTION_REMOVED
```

---

# 47. RESPONSÁVEL

Quando possível, consultar Discord Audit Log para descobrir quem alterou cargo.

Mas:

NUNCA inventar responsável.

Se não for possível identificar:

```text
actor = UNKNOWN_DISCORD_ACTOR
```

ou equivalente.

---

# 48. EVENT LOOP

O bot pode alterar cargos.

Depois Discord envia `guildMemberUpdate`.

Não gerar loop:

```text
bot altera
↓
listener reage
↓
bot altera novamente
↓
listener...
```

Reconciliação deve ser idempotente.

---

# 49. TRANSAÇÃO

Atualizar conjuntamente quando possível:

```text
rank
position
functions
accessProfile
authorizationVersion
history
audit
```

evitando estado intermediário inconsistente.

---

# 50. CACHE

Se houver cache de membro/permissão:

invalidar quando ocorrer:

```text
ROLE_CHANGED
RANK_CHANGED
POSITION_CHANGED
ACCESS_PROFILE_CHANGED
```

---

# 51. API

Criar endpoint conceitual:

```text
GET /me
```

retornando:

```json
{
  "member": {
    "rank": "Coronel",
    "primaryPosition": "Comandante Geral",
    "functions": [
      "Instrutor"
    ]
  },
  "access": {
    "profile": "HIGH_COMMAND",
    "permissions": []
  }
}
```

Permissões podem ser entregues em forma apropriada.

---

# 52. FRONTEND

A sidebar deverá ser baseada nas permissões reais.

Exemplo:

MEMBER vê:

```text
Dashboard
Meu Perfil
Patrulhas
Ponto
Cursos
Solicitações
```

COMANDO vê também:

```text
Efetivo
Carreira
Treinamentos
Recrutamento
Relatórios
```

COMANDANTE GERAL vê também:

```text
Administração
Auditoria
Configurações
Segurança
Manutenção
Discord
```

---

# 53. NÃO HARDCODAR O EXEMPLO

Não implementar:

```ts
if commanderGeneral show everything
```

Utilizar RBAC.

`Comandante Geral` recebe um perfil/permissões configuradas.

---

# 54. ACESSO MAIS ALTO NÃO SIGNIFICA NECESSARIAMENTE TODAS AS PERMISSÕES

Manter capacidade de negar permissões específicas.

Exemplo:

```text
HIGH_COMMAND
```

pode ter quase tudo, enquanto:

```text
SYSTEM_ADMIN
```

possui configurações técnicas.

Não misturar cargo RP com acesso de infraestrutura sem intenção explícita.

---

# 55. OWNER / ADMIN TÉCNICO

Separar:

```text
Comandante Geral
```

de:

```text
Administrador Técnico
```

caso seja necessário.

O cargo hierárquico não precisa automaticamente receber acesso a:

* secrets;
* infraestrutura Railway;
* API keys;
* configuração sensível de segurança.

---

# 56. PORTARIA DIGITAL

Integrar com o cadastro obrigatório.

Quando pessoa concluir cadastro:

```text
Discord roles
↓
sync
↓
determina função real
```

Se já possuir cargo funcional válido no Discord, não deixá-la como:

```text
MEMBER
```

por padrão.

---

# 57. RECRUTAMENTO

Quando aprovado:

inicialmente poderá receber:

```text
@Recruta
```

Então:

```text
primaryPosition = RECRUIT
accessProfile = RECRUIT
```

Se posteriormente ganhar outro cargo:

sincronização atualiza.

---

# 58. BOTÕES E PAINÉIS DISCORD

O mesmo RBAC deve determinar quais botões o usuário pode executar no bot.

Exemplo:

```text
Promover membro
```

backend verifica:

```text
career.promote
```

Não duplicar regra:

```text
siteRoleCheck
discordRoleCheck
```

Criar um único PermissionService.

---

# 59. UM ÚNICO PERMISSION SERVICE

Ideal:

```ts
PermissionService.can(
  actorMemberId,
  "career.promote"
)
```

Utilizado por:

```text
Bot Discord
API
Site
Worker
```

Assim o site e o bot nunca divergem.

---

# 60. EXEMPLO CRÍTICO DO PROBLEMA ATUAL

Cenário:

```text
Discord:
Mateus
@Comandante Geral
```

Cadastro antigo:

```text
role = MEMBER
```

Resultado atual:

```text
Site trata como membro
```

Resultado correto:

```text
Discord Role Sync detecta:
@Comandante Geral

↓

Member:
primaryPosition = COMMANDER_GENERAL

↓

Access:
HIGH_COMMAND

↓

Site:
Centro de Comando completo liberado

↓

Bot:
permissões de Comandante Geral reconhecidas
```

SEM edição manual do cadastro.

---

# 61. TESTES OBRIGATÓRIOS

### Teste 1

Discord:

```text
@Membro
```

Resultado:

```text
MEMBER
```

---

### Teste 2

Adicionar:

```text
@Comandante Geral
```

Resultado automático:

```text
primaryPosition = COMMANDER_GENERAL
accessProfile = HIGH_COMMAND
```

---

### Teste 3

Usuário está logado no site.

Adicionar Comandante Geral no Discord.

Resultado:

site atualiza sem novo login.

---

### Teste 4

Remover Comandante Geral.

Resultado:

acesso elevado revogado imediatamente.

---

### Teste 5

Comandante Geral + Instrutor.

Resultado:

```text
primaryPosition:
COMMANDER_GENERAL

functions:
INSTRUCTOR
```

---

### Teste 6

Mudar patente.

Resultado:

rank atualizado e nickname recalculado.

---

### Teste 7

Adicionar cargo cosmético.

Resultado:

nenhuma alteração de permissão.

---

### Teste 8

Bot estava offline quando cargo mudou.

Ao reiniciar:

```text
startup reconciliation
```

corrige banco.

---

### Teste 9

Frontend tenta chamar endpoint administrativo depois de perder cargo.

Resultado:

```text
403
```

mesmo que a interface antiga ainda esteja aberta.

---

# 62. SEGURANÇA

A autorização final acontece no backend.

Nunca confiar:

* localStorage;
* frontend;
* cargo enviado pelo browser;
* accessProfile enviado pelo cliente;
* campos manipuláveis.

---

# 63. DATABASE CONSTRAINTS

Garantir integridade das relações entre:

```text
members
ranks
positions
discord_role_mappings
access_profiles
permissions
```

---

# 64. OBSERVABILIDADE

Adicionar página:

```text
SISTEMA
→ DISCORD
→ SINCRONIZAÇÃO
```

Mostrar:

```text
Último sync
Membros sincronizados
Divergências
Falhas
Fila pendente
```

---

# 65. REPARAR IDENTIDADE

Admin autorizado poderá:

```text
RECONCILIAR COM DISCORD
```

em um membro.

Sistema lê os cargos atuais e corrige o cadastro.

---

# 66. RECONCILIAÇÃO EM LOTE

Na Central de Identidade:

```text
RECONCILIAR TODOS
```

com preview:

```text
143 sem alterações
4 cargos divergentes
2 patentes divergentes
1 requer revisão
```

Antes de aplicar.

---

# 67. NÃO SOBRESCREVER INFORMAÇÕES NÃO RELACIONADAS

A sincronização de roles não deve alterar:

* horas;
* histórico;
* disciplina;
* candidatura;
* avaliações;
* cursos;

exceto quando uma regra explícita exigir.

---

# 68. DEFINITION OF DONE

Esta tarefa só estará concluída quando:

* Discord Role Mapping existir;
* cargos funcionais forem separados de patentes;
* `guildMemberUpdate` estiver integrado;
* cadastro atualizar automaticamente;
* site atualizar automaticamente;
* bot utilizar o mesmo estado;
* RBAC recalcular automaticamente;
* downgrade revogar acesso;
* startup reconciliation existir;
* caches forem invalidados;
* histórico/auditoria existirem;
* testes de promoção/rebaixamento funcional passarem.

---

# 69. REGRA FINAL

A arquitetura deve ser:

```text
DISCORD
   │
   │ cargos
   ▼
ROLE SYNC SERVICE
   │
   ├── PATENTE
   ├── CARGO PRINCIPAL
   ├── FUNÇÕES
   └── PERFIL DE ACESSO
   │
   ▼
SUPABASE
   │
   ├─────────────┐
   ▼             ▼
BOT             API
                 │
                 ▼
                SITE
```

Não pode existir:

```text
Discord = Comandante Geral
Site = Membro
Bot = Superior
Banco = Membro
```

Todos os componentes devem convergir para o mesmo estado funcional.

# DISCORD → IDENTIDADE → RBAC → BOT + SITE

Esse deve ser o fluxo oficial da CHOQUE - BGR.
