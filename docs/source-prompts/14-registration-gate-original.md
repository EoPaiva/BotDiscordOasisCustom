# MÓDULO COMPLEMENTAR — CADASTRO OBRIGATÓRIO / ACCESS GATE

Este prompt é COMPLEMENTAR a todos os prompts anteriores do projeto CHOQUE - BGR.

Adicionar ao bot o módulo:

# PORTARIA DIGITAL / CADASTRO OBRIGATÓRIO

O objetivo é impedir que usuários sem cadastro concluído tenham acesso normal ao Discord da corporação.

O usuário recém-chegado deverá enxergar SOMENTE os canais necessários para realizar seu cadastro.

Após concluir e validar o cadastro, o bot libera automaticamente o acesso correspondente.

---

# 1. PRINCÍPIO

Fluxo:

```text
USUÁRIO ENTRA NO DISCORD
↓
BOT DETECTA
↓
STATUS = NÃO CADASTRADO
↓
ACESSO RESTRITO
↓
USUÁRIO VISUALIZA SOMENTE RECEPÇÃO/CADASTRO
↓
REALIZA CADASTRO
↓
BACKEND VALIDA
↓
BANCO REGISTRA
↓
BOT SINCRONIZA CARGOS
↓
ACESSO NORMAL É LIBERADO
```

---

# 2. NÃO UTILIZAR COMANDOS

Continuam valendo as regras anteriores.

Nenhum:

* `/cadastro`;
* `!cadastro`;
* comando digitado;
* mensagem manual obrigatória.

Utilizar somente:

* mensagem fixa;
* botão;
* modal;
* User Select quando necessário;
* respostas ephemeral.

---

# 3. CARGO DE NÃO CADASTRADO

Criar configuração:

```text
unregisteredRoleId
```

Exemplo visual:

```text
@Não Cadastrado
```

ou:

```text
@Aguardando Cadastro
```

O nome deve ser configurável.

Ao membro entrar:

```text
guildMemberAdd
↓
aplicar @Não Cadastrado
```

---

# 4. ESTRUTURA DE ACESSO

Enquanto possuir:

```text
@Não Cadastrado
```

o usuário poderá visualizar somente uma categoria semelhante a:

```text
RECEPÇÃO

# boas-vindas
# cadastro
# suporte
```

Opcionalmente:

```text
# regras
```

Todo o restante da corporação deverá permanecer oculto.

---

# 5. NÃO CONFIGURAR PERMISSÃO CANAL POR CANAL MANUALMENTE NO CÓDIGO

Criar conceito central:

```text
ONBOARDING_VISIBLE
MEMBER_ONLY
STAFF_ONLY
PUBLIC
```

ou utilizar configuração equivalente.

O setup do servidor deverá saber quais canais pertencem à área de onboarding.

---

# 6. PAINEL FIXO DE CADASTRO

No canal:

```text
# cadastro
```

criar mensagem persistente:

```text
CHOQUE - BGR

PORTARIA DIGITAL

Para acessar as áreas internas da corporação,
é necessário concluir seu cadastro.

[ REALIZAR CADASTRO ]

[ CONSULTAR SITUAÇÃO ]

[ PRECISO DE AJUDA ]
```

---

# 7. REALIZAR CADASTRO

Ao clicar:

```text
REALIZAR CADASTRO
```

validar primeiro:

* usuário ainda não está cadastrado;
* não possui cadastro em andamento incompatível;
* não está bloqueado;
* não existe conflito de identidade;
* Discord ID ainda não está associado a outro membro.

---

# 8. CAMPOS DO CADASTRO

Reutilizar os dados já definidos no sistema de membros.

Exemplo:

```text
Nick utilizado no BGR
ID no BGR
```

Outros campos somente se realmente necessários.

Não pedir ao usuário informações que o sistema já conhece.

Não perguntar novamente:

```text
Discord username
Discord ID
```

pois vêm automaticamente do Discord.

---

# 9. CADASTRO NÃO É CANDIDATURA

Distinguir claramente:

```text
CADASTRO
= identificação/vinculação no sistema

CANDIDATURA
= processo seletivo para ingressar na CHOQUE
```

Não misturar os dois.

---

# 10. MODOS DE CADASTRO

Preparar para dois cenários.

## MEMBRO JÁ APROVADO

Pessoa já foi aceita no processo seletivo.

O sistema encontra vínculo pendente e finaliza identidade.

## MEMBRO INSERIDO MANUALMENTE

Alto Comando cadastrou previamente o membro.

Usuário apenas confirma/vincula o Discord.

---

# 11. NÃO LIBERAR QUALQUER PESSOA AUTOMATICAMENTE

IMPORTANTE.

Concluir um formulário de cadastro NÃO significa automaticamente que qualquer visitante passa a ser membro da CHOQUE.

Precisamos distinguir:

```text
REGISTERED_VISITOR
CANDIDATE
RECRUIT
MEMBER
```

ou estrutura equivalente já existente.

---

# 12. ACESSO CONFORME STATUS

Exemplo:

### NÃO CADASTRADO

Enxerga:

```text
Recepção
Cadastro
Suporte
```

### CANDIDATO

Enxerga:

```text
Recepção
Recrutamento
Área de candidato
Calls de entrevista
```

### RECRUTA

Enxerga:

```text
áreas de membro
treinamentos de recruta
patrulhamento permitido
```

### MEMBRO

Enxerga áreas normais conforme cargos.

---

# 13. FONTE DE VERDADE

Discord Role NÃO deverá ser a única fonte de verdade.

Banco deve possuir algo equivalente a:

```text
registrationStatus
```

Possíveis estados:

```text
UNREGISTERED
PENDING
REGISTERED
REQUIRES_REVIEW
BLOCKED
```

---

# 14. FLUXO DE CADASTRO

```text
REALIZAR CADASTRO
↓
MODAL
↓
NICK
ID BGR
↓
BACKEND VALIDA
↓
VERIFICA DUPLICIDADE
↓
SALVA
↓
SINCRONIZA IDENTIDADE
↓
REMOVE @Não Cadastrado
↓
APLICA CARGOS CORRETOS
↓
ATUALIZA NICKNAME
↓
LIBERA ACESSO
```

---

# 15. NICKNAME

Reutilizar obrigatoriamente a função central existente:

```text
formatMemberNickname()
```

Exemplo:

```text
[RCT] Lucas [152]
```

Não duplicar a lógica de nickname dentro deste módulo.

---

# 16. DUPLICIDADE DE ID

Se alguém tentar cadastrar:

```text
ID BGR = 152
```

mas esse ID já pertence a outro Discord:

NÃO sobrescrever.

Resultado:

```text
CADASTRO REQUER REVISÃO

Este ID já possui um vínculo no sistema.

Um responsável deverá analisar a situação.
```

Status:

```text
REQUIRES_REVIEW
```

---

# 17. DUPLICIDADE DE DISCORD

Um mesmo `discordUserId` não pode gerar múltiplos membros.

Garantir isso também no banco com constraint quando adequado.

---

# 18. CONFLITO DE IDENTIDADE

Casos como:

```text
Discord já vinculado
ID BGR duplicado
perfil antigo encontrado
ex-membro encontrado
```

devem ir para revisão.

Não criar membro duplicado automaticamente.

---

# 19. CAIXA ADMINISTRATIVA

Integrar com a Caixa de Entrada Administrativa já existente.

Adicionar:

```text
CADASTROS PARA REVISÃO
3
```

Exemplo:

```text
CAD-0192

Discord
@Lucas

ID informado
152

Problema
ID já vinculado

[ ANALISAR ]
```

---

# 20. APROVAÇÃO MANUAL QUANDO NECESSÁRIO

Superior autorizado poderá:

```text
VINCULAR AO PERFIL EXISTENTE
```

ou:

```text
CORRIGIR ID
```

ou:

```text
NEGAR CADASTRO
```

Todas as ações auditadas.

---

# 21. USUÁRIO JÁ CADASTRADO QUE SAI E VOLTA

Esse cenário é importante.

Quando:

```text
guildMemberAdd
```

ocorrer:

consultar o banco ANTES de tratar como novo usuário.

Se:

```text
discordUserId
```

já estiver vinculado a membro ativo:

não obrigar novo cadastro.

Executar:

```text
RECONCILIAR
↓
cargos
↓
patente
↓
nickname
↓
status
```

---

# 22. REENTRADA NÃO SIGNIFICA REATIVAÇÃO

Se o perfil estiver:

```text
DESLIGADO
EXONERADO
BLOCKED
```

não restaurar acesso automaticamente.

Mostrar apenas área de recepção/suporte conforme política.

---

# 23. RECONCILIAÇÃO NO STARTUP

Quando o bot iniciar:

verificar usuários relevantes.

Detectar:

```text
não cadastrado sem cargo restritivo
cadastrado ainda com @Não Cadastrado
membro ativo sem cargos esperados
usuário desligado com acesso interno
```

Corrigir somente os casos seguros.

---

# 24. CENTRAL DE IDENTIDADE

Integrar completamente com a Central de Identidade Automática já existente.

Ela deve poder mostrar:

```text
USUÁRIOS SEM CADASTRO       18
CADASTROS PENDENTES          3
IDENTIDADES DIVERGENTES      2
MEMBROS SEM ID               1
```

---

# 25. NÃO REMOVER CARGOS DE ADMINISTRADORES ÀS CEGAS

CRÍTICO.

Nunca executar limpeza de cargos baseada apenas em:

```text
"usuário não está cadastrado"
```

sem considerar:

* proprietário do servidor;
* contas administrativas autorizadas;
* bots;
* integrações;
* cargos protegidos;
* allowlist administrativa.

---

# 26. GUILD OWNER

O proprietário do servidor jamais deve ser bloqueado pela rotina automática.

---

# 27. BOTS

Outros bots não devem passar pelo cadastro.

Ignorar:

```text
member.user.bot === true
```

ou equivalente.

---

# 28. CONTAS DE SISTEMA

Permitir configuração:

```text
registrationBypassRoleIds
registrationBypassUserIds
```

Uso extremamente restrito.

Auditar alterações nessa configuração.

---

# 29. NÃO USAR @EVERYONE DE FORMA DESTRUTIVA

Planejar permissões cuidadosamente.

Preferir uma estrutura previsível de roles e permission overwrites.

Antes de alterar permissões em lote:

gerar preview.

---

# 30. MODELO RECOMENDADO DE PERMISSÕES

Conceitualmente:

```text
@everyone
→ acesso mínimo

@Não Cadastrado
→ recepção/cadastro

@Candidato
→ recrutamento

@Membro
→ áreas internas básicas

cargos superiores
→ áreas adicionais
```

---

# 31. IMPORTANTE SOBRE PERMISSÕES DO DISCORD

Respeitar precedência real de:

* permission overwrites;
* roles;
* member overwrites;
* Administrator.

Não assumir que adicionar/remover um cargo necessariamente oculta tudo.

O setup deve verificar as permissões efetivas.

---

# 32. VERIFICAÇÃO PÓS-CONFIGURAÇÃO

Criar validador:

```text
RegistrationAccessValidator
```

Ele deve detectar canais internos que usuários não cadastrados ainda conseguem visualizar.

Exemplo:

```text
SECURITY WARNING

@Não Cadastrado consegue visualizar:

# chat-choque
# patrulhas
# membros
```

---

# 33. TESTE DE ACESSO EFETIVO

Ao instalar/configurar o módulo:

analisar todos os canais configurados.

Resultado:

```text
PORTARIA DIGITAL

47 canais internos protegidos
3 canais de onboarding disponíveis
0 exposições detectadas
```

---

# 34. SE UM CANAL NOVO FOR CRIADO

Não confiar que alguém lembrará de configurar manualmente.

A Central de Integridade poderá detectar:

```text
Novo canal sem classificação de acesso
```

e enviar para revisão.

---

# 35. DEFAULT SECURE

Um canal administrado pelo sistema sem classificação deve assumir:

```text
MEMBER_ONLY
```

ou outro default restritivo definido pelo projeto.

Nunca liberar por padrão.

---

# 36. EXPERIÊNCIA DO NOVO USUÁRIO

Quando entrar:

pode receber mensagem no canal/painel:

```text
BEM-VINDO À CHOQUE - BGR

Seu acesso está temporariamente limitado.

Para continuar, conclua seu cadastro na Portaria Digital.

[ REALIZAR CADASTRO ]
```

Não depender exclusivamente de DM.

---

# 37. DM OPCIONAL

Bot poderá enviar DM:

```text
Seu cadastro ainda está pendente.
Acesse a Portaria Digital no servidor.
```

Mas DM não é requisito, pois pode estar bloqueada.

---

# 38. CONSULTAR SITUAÇÃO

Botão:

```text
CONSULTAR SITUAÇÃO
```

Resposta ephemeral:

```text
STATUS DO CADASTRO

Situação
PENDENTE

Discord
@Lucas

Próxima etapa
Finalize sua identificação.
```

---

# 39. CADASTRO CONCLUÍDO

Exemplo:

```text
CADASTRO CONCLUÍDO

Identidade vinculada com sucesso.

Nick:
[RCT] Lucas [152]

Seu acesso foi atualizado.
```

---

# 40. NÃO ENVIAR DADOS PESSOAIS PUBLICAMENTE

O resultado deve ser ephemeral quando contiver dados específicos.

---

# 41. AUDITORIA

Eventos:

```text
REGISTRATION_STARTED
REGISTRATION_COMPLETED
REGISTRATION_REVIEW_REQUIRED
REGISTRATION_APPROVED
REGISTRATION_REJECTED
REGISTRATION_IDENTITY_LINKED
REGISTRATION_ACCESS_GRANTED
REGISTRATION_ACCESS_REVOKED
REGISTRATION_RECONCILED
```

---

# 42. ORIGEM

Registrar:

```text
SELF_REGISTRATION
ADMIN_APPROVAL
SYSTEM_RECONCILIATION
REJOIN
```

---

# 43. PERMISSÕES ADMINISTRATIVAS

Adicionar:

```text
registration.view
registration.review
registration.manage
registration.settings
registration.bypass.manage
```

Deny by default.

---

# 44. SEGURANÇA

Aplicar integralmente o hardening definido anteriormente.

Especialmente:

* validação server-side;
* rate limiting;
* idempotência;
* auditoria;
* least privilege;
* proteção contra mass assignment;
* transações;
* constraints.

---

# 45. RATE LIMIT

Limitar tentativas repetidas de cadastro.

Exemplo:

```text
botão clicado 100 vezes
```

não pode gerar 100 registros.

---

# 46. IDEMPOTÊNCIA

Se clicar duas vezes:

```text
FINALIZAR CADASTRO
```

resultado deve continuar sendo apenas:

```text
1 membro
1 cadastro
1 vínculo
```

---

# 47. TRANSAÇÃO

Conceitualmente:

```text
BEGIN

lock registration
validate identity
create/link member
mark registration completed
create audit
create Discord sync event

COMMIT
```

---

# 48. DISCORD SYNC

Preferir integração assíncrona segura quando necessário.

Se cargos não puderem ser atualizados:

```text
registrationStatus = REGISTERED
discordSyncStatus = PENDING
```

Não perder os dados.

---

# 49. NÃO LIBERAR ACESSO ANTES DO SYNC NECESSÁRIO

Se acesso interno depende do cargo:

não informar:

```text
"Tudo liberado"
```

até confirmar a alteração no Discord.

Pode mostrar:

```text
CADASTRO CONCLUÍDO

Sincronizando seu acesso com o Discord...
```

---

# 50. BOT SEM MANAGE ROLES

Se bot perder permissão:

registrar erro claro:

```text
Não foi possível concluir a liberação de acesso porque o bot não possui permissão para gerenciar o cargo configurado.
```

Gerar alerta administrativo.

---

# 51. HIERARQUIA DE CARGOS

Verificar se o cargo do bot está acima somente dos cargos que precisa administrar.

Não exigir `Administrator` para esse módulo.

---

# 52. MODO DE MANUTENÇÃO

Integrar com o sistema existente.

Configuração:

```text
REGISTRATION = MAINTENANCE
```

Nesse estado:

usuários novos continuam vendo recepção.

Painel mostra:

```text
CADASTRO TEMPORARIAMENTE INDISPONÍVEL

Aguarde a normalização do sistema.
```

Não liberar acesso por fallback.

---

# 53. MODO DE EMERGÊNCIA

Em Security Lockdown:

bloquear novos vínculos sensíveis conforme configuração.

Não apagar cadastros existentes.

---

# 54. SITE

O mesmo status deverá aparecer no Centro de Comando Web.

Página administrativa:

```text
PORTARIA DIGITAL

Não cadastrados        21
Pendentes               4
Revisão necessária      2
Concluídos hoje        13
```

---

# 55. CONFIGURAÇÕES PELO SITE

Permitir configurar:

```text
Cargo não cadastrado
Cargo de candidato
Cargo base de membro

Categoria de recepção
Canal de cadastro
Canal de suporte

Canais disponíveis antes do cadastro

Bypass roles

Cadastro obrigatório
ATIVO
```

---

# 56. ALTERAÇÕES DE SEGURANÇA

Modificar:

```text
bypass
cargo de acesso
categoria protegida
```

deve exigir permissão alta e auditoria.

---

# 57. PREVIEW ANTES DE ATIVAR

Antes de ligar o módulo pela primeira vez:

mostrar:

```text
ATIVAR CADASTRO OBRIGATÓRIO

Usuários afetados
186

Já cadastrados
143

Sem cadastro
38

Requerem revisão
5

Canais que serão protegidos
47

[ CANCELAR ]

[ ATIVAR ]
```

---

# 58. NÃO BLOQUEAR SERVIDOR INTEIRO ACIDENTALMENTE

Antes de aplicar alterações de permissions:

validar:

* bot possui acesso;
* owner permanece com acesso;
* cargos administrativos permitidos continuam funcionais;
* canal de cadastro permanece visível;
* bot consegue escrever no canal;
* painel de suporte permanece disponível.

Fail closed, mas não criar lockout administrativo por erro de configuração.

---

# 59. ROLLBACK DE CONFIGURAÇÃO

Preservar snapshot das permission overwrites alteradas pelo setup.

Se instalação falhar no meio:

reverter alterações aplicadas pela própria operação quando seguro.

---

# 60. NÃO RESTAURAR PERMISSÕES ANTIGAS CEGAMENTE

Se humanos alteraram permissões depois:

não sobrescrever mudanças atuais sem comparação/versionamento.

---

# 61. TESTES OBRIGATÓRIOS

### Usuário novo

Esperado:

```text
entra
↓
recebe Não Cadastrado
↓
só vê recepção
```

### Finaliza cadastro

```text
cargo restritivo removido
↓
cargos corretos adicionados
↓
nickname sincronizado
↓
áreas liberadas
```

### Usuário cadastrado sai e volta

```text
não repete cadastro
↓
identidade reconciliada
```

### Ex-membro volta

```text
não recebe acesso automaticamente
```

### Bot entra

```text
ignorado
```

### Owner

```text
não bloqueado
```

### ID duplicado

```text
REQUIRES_REVIEW
```

### Bot sem Manage Roles

```text
cadastro persiste
sync pendente
admin alertado
```

### Duplo clique

```text
sem duplicidade
```

---

# 62. INTEGRAÇÃO COM RECRUTAMENTO

Após candidato ser aprovado pelo sistema de recrutamento:

o módulo poderá automaticamente reconhecer:

```text
discordUserId aprovado
```

e liberar o fluxo de ingresso sem obrigá-lo a repetir informações já fornecidas.

Reutilizar dados válidos da candidatura quando apropriado.

---

# 63. NÃO PEDIR OS MESMOS DADOS DUAS VEZES

Se candidatura já contém:

```text
Nick BGR
ID BGR
Discord
```

e foi aprovada:

não criar formulário redundante.

Pode simplesmente exigir:

```text
CONFIRMAR CADASTRO
```

ou finalizar automaticamente conforme política configurada.

---

# 64. INTEGRAÇÃO COM ONBOARDING DE RECRUTA

Após cadastro/ingresso:

```text
CADASTRO ✅
NICKNAME ✅
CARGO ✅
PATENTE ✅
REGULAMENTO ⏳
TREINAMENTO ⏳
```

Atualizar automaticamente o checklist do recruta.

---

# 65. NOME FUNCIONAL

Na interface administrativa utilizar:

# PORTARIA DIGITAL

ou:

# CONTROLE DE ACESSO

Internamente:

```text
RegistrationGate
MembershipAccessGate
```

Evitar nomes como:

```text
Anti Intruso
Sistema Anti Pessoa
```

---

# 66. FILOSOFIA FINAL

O Discord deverá possuir uma verdadeira porta de entrada:

```text
ENTROU
↓
IDENTIDADE AINDA NÃO VALIDADA
↓
ACESSO MÍNIMO
↓
CADASTRO
↓
VALIDAÇÃO
↓
IDENTIDADE SINCRONIZADA
↓
ACESSO CONFORME FUNÇÃO
```

O objetivo não é apenas adicionar um cargo.

O objetivo é garantir que:

```text
ACESSO AO SERVIDOR
```

seja consequência de:

```text
IDENTIDADE
+
STATUS
+
CARGO
+
PERMISSÃO
```

e que nenhum usuário não cadastrado consiga navegar pelas áreas internas da CHOQUE - BGR.

