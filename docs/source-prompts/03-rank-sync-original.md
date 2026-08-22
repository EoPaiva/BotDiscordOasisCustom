# OBJETIVO

Implemente no bot da **CHOQUE - BGR** um sistema automático de sincronização entre:

* cargo de patente no Discord;
* patente registrada no banco;
* abreviação da patente;
* nickname do membro.

O sistema deve funcionar mesmo quando a patente do membro for alterada **manualmente por um administrador diretamente nos cargos do Discord**, sem utilizar painel, botão ou qualquer fluxo interno do bot.

A regra principal é:

```text
CARGO ALTERADO
↓
BOT DETECTA
↓
IDENTIFICA A PATENTE
↓
ATUALIZA O BANCO
↓
ATUALIZA O NICKNAME
↓
REGISTRA O HISTÓRICO
```

---

# 1. PADRÃO DE NICKNAME

Todo membro cadastrado na corporação deve utilizar:

```text
[ABREVIAÇÃO] NICK [ID]
```

Exemplo:

```text
[RCT] Lucas [152]
```

Onde:

* `RCT` = abreviação da patente;
* `Lucas` = nome cadastrado do membro;
* `152` = ID cadastrado.

A abreviação nunca deve ser escrita manualmente no perfil do membro.

Ela deve vir da configuração da patente.

---

# 2. PATENTES CONFIGURÁVEIS

Cada patente deve possuir pelo menos:

```text
name
abbreviation
level
discordRoleId
```

Exemplo:

```text
Nome: Recruta
Abreviação: RCT
Level: 1
Cargo Discord: @Recruta
```

Outro:

```text
Nome: Soldado
Abreviação: SD
Level: 2
Cargo Discord: @Soldado
```

Os nomes e abreviações NÃO devem ficar hardcoded dentro da função de nickname.

---

# 3. EXEMPLO DE HIERARQUIA

Use apenas como exemplo inicial e mantenha tudo configurável:

```text
Recruta     → RCT
Soldado     → SD
Cabo        → CB
Sargento    → SGT
Subtenente  → ST
Aspirante   → ASP
Tenente     → TEN
Capitão     → CAP
Major       → MAJ
Coronel     → CEL
```

As abreviações reais poderão ser alteradas posteriormente.

---

# 4. CADASTRO INICIAL

Durante o cadastro do membro, solicitar através do painel/modal:

* nome;
* ID.

A patente inicial pode ser determinada pelo cargo que o membro já possui ou pela regra de cadastro existente.

Exemplo:

```text
Nome:
Lucas

ID:
152

Cargo:
@Recruta
```

Resultado:

```text
[RCT] Lucas [152]
```

Salvar separadamente no banco:

```text
name = Lucas
internalId = 152
rankId = RECRUIT
```

Nunca armazenar apenas o nickname completo como fonte de verdade.

---

# 5. MONITORAR ALTERAÇÕES DE CARGO

Implementar monitoramento do evento de atualização de membro do Discord.

Quando os cargos de um membro forem alterados:

1. comparar cargos anteriores;
2. comparar cargos atuais;
3. identificar se algum cargo configurado como patente foi adicionado ou removido;
4. resolver qual é a patente atual;
5. atualizar banco;
6. atualizar nickname;
7. registrar histórico;
8. registrar auditoria.

Essa lógica deve funcionar independentemente da origem da alteração.

---

# 6. ALTERAÇÃO MANUAL DE CARGO

Este cenário é obrigatório.

Estado inicial:

```text
Cargo:
@Recruta

Nickname:
[RCT] Lucas [152]
```

Um administrador altera manualmente:

```text
Remove @Recruta
Adiciona @Soldado
```

O bot deve detectar automaticamente.

Resultado:

```text
Cargo:
@Soldado

Patente no banco:
Soldado

Nickname:
[SD] Lucas [152]
```

Nenhum painel precisa ser utilizado.

---

# 7. PROMOÇÃO MANUAL

Exemplo:

```text
ANTES

@Soldado
[SD] Lucas [152]
```

Administrador adiciona:

```text
@Cabo
```

e remove:

```text
@Soldado
```

Resultado automático:

```text
@Cabo
[CB] Lucas [152]
```

Banco:

```text
Patente anterior:
Soldado

Patente atual:
Cabo
```

---

# 8. REBAIXAMENTO MANUAL

Também precisa funcionar no sentido contrário.

Antes:

```text
@Sargento
[SGT] Lucas [152]
```

Administrador altera manualmente para:

```text
@Cabo
```

Resultado:

```text
[CB] Lucas [152]
```

Registrar:

```text
Sargento → Cabo
```

---

# 9. FUNÇÃO CENTRAL DE NICKNAME

Criar uma única função responsável pela montagem.

Exemplo conceitual:

```text
formatMemberNickname()
```

Entrada:

```text
rank.abbreviation = CB
member.name = Lucas
member.internalId = 152
```

Saída:

```text
[CB] Lucas [152]
```

Não duplicar essa lógica em:

* cadastro;
* promoção;
* rebaixamento;
* sincronização;
* alteração de ID;
* alteração de nome.

Todos devem reutilizar a mesma função.

---

# 10. NÃO INTERPRETAR O NICKNAME

O sistema NÃO deve descobrir os dados do membro lendo:

```text
[CB] Lucas [152]
```

O nickname é apenas apresentação.

A fonte de verdade deverá ser:

```text
MEMBER
name
internalId
rankId
```

*

```text
RANK
name
abbreviation
discordRoleId
level
```

Então:

```text
BANCO
↓
FORMATADOR
↓
NICKNAME DO DISCORD
```

Nunca o contrário.

---

# 11. ALTERAÇÃO DE NOME

Caso o nome cadastrado seja alterado:

Antes:

```text
[CB] Lucas [152]
```

Novo nome:

```text
Lucas Paiva
```

Resultado:

```text
[CB] Lucas Paiva [152]
```

A patente permanece igual.

---

# 12. ALTERAÇÃO DE ID

Caso o ID seja alterado:

Antes:

```text
[CB] Lucas [152]
```

Novo ID:

```text
281
```

Resultado:

```text
[CB] Lucas [281]
```

---

# 13. ALTERAÇÃO DE PATENTE PELO BOT

Se uma promoção/rebaixamento for realizada através de um painel do bot:

```text
PAINEL
↓
ALTERA PATENTE
↓
SINCRONIZA CARGO
↓
ATUALIZA BANCO
↓
ATUALIZA NICKNAME
```

O resultado deve ser exatamente o mesmo de uma alteração manual do cargo.

Não implementar duas regras de negócio diferentes.

---

# 14. SINCRONIZAÇÃO BIDIRECIONAL

O comportamento esperado é:

```text
ALTERAÇÃO PELO PAINEL
→ cargo + banco + nickname
```

```text
ALTERAÇÃO MANUAL DE CARGO
→ banco + nickname
```

```text
ALTERAÇÃO DE NOME
→ banco + nickname
```

```text
ALTERAÇÃO DE ID
→ banco + nickname
```

```text
RESTART DO BOT
→ validar cargo + banco + nickname
```

---

# 15. MEMBRO COM MAIS DE UMA PATENTE

O sistema deve lidar com inconsistências.

Exemplo:

```text
@Recruta
@Soldado
@Cabo
```

Nunca escolher uma patente aleatoriamente.

Cada patente possui:

```text
level
```

Exemplo:

```text
Recruta = 1
Soldado = 2
Cabo = 3
```

Se o membro possuir várias patentes configuradas simultaneamente:

por padrão, considerar a patente com maior `level`.

Exemplo:

```text
@Soldado
@Cabo
```

Resultado considerado:

```text
Cabo
```

Nickname:

```text
[CB] Lucas [152]
```

---

# 16. INCONSISTÊNCIA DE CARGOS

Além de resolver a maior patente, registrar a inconsistência.

Exemplo:

```text
WARN

Membro:
Lucas

Problema:
Possui múltiplos cargos de patente.

Cargos:
Soldado
Cabo

Patente considerada:
Cabo
```

Não remover cargos automaticamente sem existir uma configuração explícita autorizando isso.

---

# 17. OPÇÃO DE AUTO-CORREÇÃO DE CARGOS

Criar configuração:

```text
AUTO_REMOVE_OLD_RANK_ROLES
```

Se:

```text
false
```

o bot:

* detecta;
* escolhe maior patente;
* atualiza nickname;
* registra inconsistência.

Se:

```text
true
```

o bot também poderá remover cargos de patente inferiores.

Exemplo:

```text
@Soldado
@Cabo
```

Resultado:

```text
@Cabo
```

Mas essa função deve ser configurável.

---

# 18. MEMBRO SEM CARGO DE PATENTE

Caso um membro cadastrado perca todos os cargos de patente:

não inventar patente.

Registrar estado inconsistente.

Exemplo:

```text
MEMBER_WITHOUT_RANK_ROLE
```

O comportamento deve ser configurável.

Possibilidades:

```text
manter última patente no banco
```

ou:

```text
marcar patente como não sincronizada
```

Não apagar histórico automaticamente.

---

# 19. AUDITORIA

Toda alteração automática de patente deve gerar audit log.

Exemplo:

```text
SINCRONIZAÇÃO DE PATENTE

Membro:
Lucas

Anterior:
Recruta

Atual:
Soldado

Origem:
Alteração manual de cargo no Discord

Nickname anterior:
[RCT] Lucas [152]

Nickname atual:
[SD] Lucas [152]

Data:
22/08/2026

ID:
AUD-00192
```

---

# 20. IDENTIFICAR ORIGEM DA ALTERAÇÃO

Quando possível, diferenciar:

```text
PANEL_ACTION
```

```text
DISCORD_ROLE_CHANGE
```

```text
SYSTEM_RECONCILIATION
```

```text
REGISTRATION
```

```text
MANUAL_DATA_UPDATE
```

Isso melhora a auditoria.

---

# 21. EVITAR LOOP DE EVENTOS

Cuidado com este cenário:

```text
bot altera cargo
↓
evento member update dispara
↓
bot detecta alteração
↓
tenta alterar novamente
↓
loop
```

A implementação deve ser idempotente.

Antes de escrever:

verifique se o estado desejado já existe.

Exemplo:

```text
currentRank === expectedRank
```

Se sim:

não atualizar novamente.

---

# 22. EVITAR ALTERAÇÕES DUPLICADAS

Uma alteração de cargo pode disparar múltiplos eventos próximos.

Não gerar:

* três atualizações de nickname;
* três históricos;
* três auditorias.

Implementar proteção contra processamento duplicado.

---

# 23. ALTERAÇÃO RÁPIDA DE CARGOS

Considere que um administrador pode:

1. adicionar cargo novo;
2. alguns milissegundos depois remover cargo antigo.

Não registrar necessariamente dois eventos funcionais diferentes se ambos fazem parte da mesma mudança.

Implementar pequena estratégia de debounce/coalescência quando necessário.

Depois resolver o estado final dos cargos.

---

# 24. PATENTE DEVE SER DERIVADA DO ESTADO FINAL

Não interpretar apenas:

```text
cargo adicionado
```

Avaliar o conjunto final de cargos.

Exemplo:

```text
ANTES
@Soldado
```

Evento intermediário:

```text
@Soldado
@Cabo
```

Estado final:

```text
@Cabo
```

Patente final:

```text
Cabo
```

---

# 25. RECONCILIAÇÃO APÓS RESTART

Quando o bot iniciar:

para os membros cadastrados, validar:

```text
cargo atual
patente no banco
nickname atual
```

Calcular:

```text
expectedRank
expectedNickname
```

Se houver divergência:

corrigir de forma segura.

Exemplo:

Banco:

```text
Soldado
```

Discord:

```text
@Cabo
```

Nickname:

```text
[SD] Lucas [152]
```

Resultado após reconciliação:

```text
Banco:
Cabo

Nickname:
[CB] Lucas [152]
```

Registrar:

```text
SYSTEM_RECONCILIATION
```

---

# 26. NICKNAME ALTERADO MANUALMENTE

Caso alguém altere manualmente:

```text
[CB] Lucas [152]
```

para:

```text
Lucas
```

o bot deve possuir opção configurável:

```text
ENFORCE_MEMBER_NICKNAME = true
```

Quando habilitada:

restaurar:

```text
[CB] Lucas [152]
```

---

# 27. NÃO CRIAR LOOP DE NICKNAME

Da mesma forma:

```text
bot altera nickname
↓
evento member update
```

não pode gerar nova alteração inútil.

Comparar:

```text
currentNickname
expectedNickname
```

Só editar se forem diferentes.

---

# 28. HIERARQUIA DO DISCORD

Antes de alterar nickname ou cargos:

verificar se o bot possui permissão.

Também verificar se o cargo mais alto do bot está acima do membro.

Caso contrário:

não quebrar o fluxo inteiro.

Registrar:

```text
ROLE_HIERARCHY_ERROR
```

ou:

```text
NICKNAME_PERMISSION_ERROR
```

E informar claramente no painel administrativo/log.

---

# 29. NÃO ALTERAR DONO DO SERVIDOR

Tratar corretamente limitações do Discord.

Se o usuário não puder ter nickname alterado devido às regras do Discord:

não gerar loops tentando novamente indefinidamente.

---

# 30. CARGOS QUE NÃO SÃO PATENTE

Ignorar completamente alterações em cargos comuns.

Exemplo:

```text
@Membro
@Treinamento
@Ausente
@Notificações
```

Essas alterações NÃO devem recalcular patente, a menos que outra regra realmente precise atualizar o nickname.

Somente cargos registrados como:

```text
rank.discordRoleId
```

entram na resolução de patente.

---

# 31. PRESERVAR NOME E ID

Quando somente cargo mudar:

não alterar:

```text
member.name
member.internalId
```

Exemplo:

Antes:

```text
[RCT] Lucas [152]
```

Depois:

```text
[SD] Lucas [152]
```

Somente:

```text
RCT → SD
```

mudou.

---

# 32. CADASTRO PRECISA FUNCIONAR COM CARGO EXISTENTE

Se o membro já estiver com:

```text
@Soldado
```

quando realizar o cadastro:

o sistema deverá reconhecer:

```text
Patente = Soldado
Abreviação = SD
```

E gerar:

```text
[SD] Lucas [152]
```

Não forçar Recruta se o cargo real indica outra patente.

---

# 33. HISTÓRICO DE CARREIRA

Alterações manuais de cargo também precisam aparecer no histórico.

Exemplo:

```text
22/08/2026
Promovido de Recruta para Soldado

Origem:
Alteração direta de cargo
```

Se não for possível identificar quem alterou o cargo diretamente através do evento disponível, NÃO inventar responsável.

Registrar:

```text
Responsável:
Não identificado pelo evento
```

ou consultar audit log do Discord somente se a arquitetura atual justificar e isso puder ser feito com segurança.

---

# 34. NÃO CONFUNDIR SINCRONIZAÇÃO COM PROMOÇÃO FORMAL

Uma alteração de cargo detectada pelo Discord atualiza a patente funcional.

Mas o sistema pode diferenciar:

```text
RANK_SYNC
```

de:

```text
FORMAL_PROMOTION
```

Assim uma alteração manual não precisa automaticamente gerar uma publicação de promoção pública.

Ela deve:

* atualizar patente;
* atualizar nickname;
* atualizar banco;
* registrar histórico/auditoria.

A publicação pública deve seguir configuração própria.

---

# 35. TESTES OBRIGATÓRIOS

Testar no mínimo:

### Caso 1

```text
[RCT] Lucas [152]
@Recruta
```

Admin troca para:

```text
@Soldado
```

Esperado:

```text
[SD] Lucas [152]
```

---

### Caso 2

Soldado → Cabo.

Esperado:

```text
[CB] Lucas [152]
```

Banco atualizado.

---

### Caso 3

Cabo → Soldado.

Esperado:

```text
[SD] Lucas [152]
```

---

### Caso 4

Usuário recebe cargo não relacionado.

Esperado:

nickname não muda.

---

### Caso 5

Usuário possui:

```text
@Soldado
@Cabo
```

Esperado:

resolver Cabo pelo maior `level`.

---

### Caso 6

Usuário perde todos os cargos de patente.

Esperado:

aplicar política definida e registrar inconsistência.

---

### Caso 7

Nickname alterado manualmente.

Com enforcement ativo:

restaurar padrão.

---

### Caso 8

Bot reinicia com nickname incorreto.

Esperado:

reconciliar.

---

### Caso 9

Cargo é atualizado pelo próprio bot.

Esperado:

não gerar loop.

---

### Caso 10

Administrador troca cargos rapidamente.

Esperado:

uma única patente final e uma única atualização funcional.

---

### Caso 11

Bot não possui permissão de nickname.

Esperado:

registrar erro sem quebrar banco.

---

### Caso 12

Membro ainda não está cadastrado.

Esperado:

não criar cadastro automaticamente apenas porque recebeu cargo, salvo se isso estiver explicitamente configurado.

---

# 36. FLUXO FINAL

O comportamento esperado deverá ser:

```text
ADMIN ALTERA CARGO MANUALMENTE
          ↓
MEMBER UPDATE
          ↓
RankSyncService
          ↓
IDENTIFICAR PATENTE ATUAL
          ↓
COMPARAR COM BANCO
          ↓
ATUALIZAR BANCO
          ↓
formatMemberNickname()
          ↓
ATUALIZAR NICKNAME
          ↓
HISTÓRICO
          ↓
AUDITORIA
```

---

# 37. REGRA PRINCIPAL

O usuário não deve depender de um painel de promoção para manter os dados sincronizados.

Se a patente for modificada diretamente através dos cargos do Discord, o bot deverá perceber e se adaptar.

Portanto:

```text
CARGO DO DISCORD = REFERÊNCIA OPERACIONAL DA PATENTE ATUAL
```

e:

```text
BANCO = REGISTRO ESTRUTURADO/HISTÓRICO
```

e:

```text
NICKNAME = REPRESENTAÇÃO VISUAL
```

Os três devem permanecer sincronizados.

---

# 38. RESULTADO ESPERADO

Exemplo completo:

Estado inicial:

```text
@Recruta

[RCT] Matheus [231]
```

Administrador promove manualmente:

```text
Remove @Recruta
Adiciona @Soldado
```

O bot automaticamente transforma em:

```text
@Soldado

[SD] Matheus [231]
```

Posteriormente:

```text
@Soldado → @Cabo
```

Resultado:

```text
[CB] Matheus [231]
```

Posteriormente:

```text
@Cabo → @Sargento
```

Resultado:

```text
[SGT] Matheus [231]
```

Tudo sem precisar clicar em nenhum botão para atualizar nickname.

# REGRA FINAL

Toda alteração de cargo de patente, independentemente de ser realizada:

* pelo bot;
* pelo painel;
* manualmente por administrador;

deve resultar automaticamente na sincronização:

**CARGO → PATENTE → BANCO → ABREVIAÇÃO → NICKNAME → HISTÓRICO → AUDITORIA.**

Implemente isso como um serviço central reutilizável e não como lógica isolada dentro de handlers.
