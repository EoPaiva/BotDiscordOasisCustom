# VALIDAÇÃO DO PONTO POR TEMPO MÍNIMO EM PATRULHA

Adicionar ao sistema de bate ponto da **CHOQUE - BGR** uma regra obrigatória de tempo mínimo em patrulha.

Por padrão:

```text
TEMPO MÍNIMO DE PATRULHA = 15 MINUTOS
```

Esse valor deverá ser configurável no painel administrativo, porém inicialmente utilizar:

```text
15 minutos
```

A finalidade é impedir que membros:

* iniciem o ponto;
* permaneçam poucos minutos em call;
* encerrem;
* acumulem pequenos períodos sem terem realizado uma patrulha efetiva.

---

# 1. REGRA PRINCIPAL

Um ponto somente será considerado:

```text
VÁLIDO
```

caso o membro acumule pelo menos:

```text
15 minutos de tempo válido em patrulha
```

durante aquela sessão.

Se o ponto for encerrado antes de atingir o mínimo:

```text
PONTO INVALIDADO
```

Exemplo:

```text
Início: 20:00
Fim: 20:11

Tempo em patrulha:
11 minutos

Mínimo necessário:
15 minutos

Resultado:
INVALIDADO
```

Esses 11 minutos NÃO devem ser adicionados:

* às horas totais;
* às horas semanais;
* às horas mensais;
* ao ranking;
* à meta semanal;
* aos relatórios de horas válidas.

---

# 2. NÃO APAGAR O PONTO INVALIDADO

O ponto não deve ser deletado.

Registrar normalmente a sessão no banco com status:

```text
INVALIDATED
```

ou equivalente na arquitetura existente.

Guardar:

* horário de início;
* horário de encerramento;
* duração bruta;
* duração em patrulha;
* motivo da invalidação;
* membro;
* calls utilizadas;
* data;
* identificador da sessão.

Exemplo:

```text
Sessão:
#000182

Membro:
Lucas

Início:
20:00

Fim:
20:11

Tempo bruto:
11m

Tempo válido em patrulha:
11m

Status:
INVALIDADO

Motivo:
Tempo mínimo de patrulha não atingido.
```

Isso é importante para auditoria.

---

# 3. ESTADOS DO PONTO

Utilizar estados claros.

Exemplo:

```text
ACTIVE
VALID
INVALIDATED
CANCELLED
```

Ou adaptar aos estados existentes.

Durante os primeiros 15 minutos:

```text
ACTIVE
```

mas ainda:

```text
minimumRequirementMet = false
```

Após atingir o mínimo:

```text
minimumRequirementMet = true
```

Ao finalizar:

se verdadeiro:

```text
VALID
```

caso contrário:

```text
INVALIDATED
```

---

# 4. NÃO PRECISA ESPERAR 15 MINUTOS PARA ABRIR O PONTO

O membro consegue iniciar normalmente.

Exemplo:

```text
20:00
[ INICIAR SERVIÇO ]
```

O sistema começa a acompanhar o tempo imediatamente.

Durante esse período, no painel pessoal mostrar algo semelhante a:

```text
SERVIÇO EM ANDAMENTO

Tempo em patrulha
08m 32s

Tempo mínimo
15m

Validação
⏳ Ainda não validado
```

Quando atingir:

```text
15m
```

alterar para:

```text
Validação
✅ Ponto validado
```

---

# 5. AVISO AO INICIAR

Quando o membro clicar em:

```text
INICIAR SERVIÇO
```

responder ephemeral:

```text
Serviço iniciado com sucesso.

Para que este ponto seja considerado válido, você precisa acumular pelo menos 15 minutos em patrulha.

Caso encerre antes disso, a sessão será registrada como invalidada e não contará em suas horas.
```

---

# 6. TENTATIVA DE FINALIZAR ANTES DOS 15 MINUTOS

Se o membro clicar em:

```text
FINALIZAR SERVIÇO
```

antes de atingir o mínimo:

NÃO finalizar imediatamente sem aviso.

Mostrar confirmação:

```text
ATENÇÃO

Você possui apenas:

11m 42s

de patrulha válida.

O mínimo necessário para validar este ponto é:

15m

Se finalizar agora, esta sessão será INVALIDADA e não contará em suas horas.

[ FINALIZAR MESMO ASSIM ]

[ CONTINUAR EM SERVIÇO ]
```

Isso evita invalidações acidentais.

---

# 7. FINALIZAÇÃO CONFIRMADA ANTES DO MÍNIMO

Se clicar:

```text
FINALIZAR MESMO ASSIM
```

encerrar sessão.

Resultado:

```text
PONTO INVALIDADO

Tempo em patrulha:
11m 42s

Tempo mínimo:
15m

Esta sessão foi mantida no histórico, mas não será contabilizada nas suas horas.
```

---

# 8. AO ATINGIR 15 MINUTOS

Quando o membro atingir exatamente o mínimo configurado:

```text
15:00
```

a sessão passa a ser elegível para validação.

Não é necessário enviar mensagem pública.

Opcionalmente enviar ephemeral somente quando houver interação posterior.

Internamente:

```text
minimumRequirementMet = true
minimumRequirementMetAt = timestamp
```

---

# 9. TROCA ENTRE CALLS DE PATRULHA

O membro NÃO precisa permanecer os 15 minutos na mesma call.

Se todas forem configuradas como calls válidas de patrulha, o tempo é acumulativo.

Exemplo:

```text
Patrulhamento 01
8 minutos

↓

Patrulhamento 02
7 minutos
```

Total:

```text
15 minutos
```

Resultado:

```text
PONTO VÁLIDO
```

A troca entre calls autorizadas não reinicia o contador.

---

# 10. CALL AUTORIZADA NÃO SIGNIFICA NECESSARIAMENTE PATRULHA

Separar dois conceitos:

```text
CALL AUTORIZADA PARA SERVIÇO
```

e:

```text
CALL QUE CONTA COMO PATRULHA
```

Isso permite possuir, por exemplo:

```text
Patrulhamento 01 → conta como patrulha
Patrulhamento 02 → conta como patrulha
Operação → configurável
Treinamento → não conta
Comando → não conta
Aguardando Guarnição → não conta
```

Cada call deverá possuir configuração semelhante a:

```text
serviceAllowed = true
countsTowardPatrolMinimum = true
```

---

# 11. EXEMPLO

Membro abre ponto.

```text
20:00 → 20:05
Aguardando Guarnição
```

Essa call permite manter o serviço aberto, porém:

```text
Tempo de patrulha = 0
```

Depois:

```text
20:05 → 20:18
Patrulhamento 01
```

Tempo de patrulha:

```text
13 minutos
```

Depois encerra.

Apesar do ponto bruto possuir:

```text
18 minutos
```

o tempo de patrulha é somente:

```text
13 minutos
```

Resultado:

```text
INVALIDADO
```

O requisito é baseado no tempo que efetivamente conta como patrulha.

---

# 12. TEMPO FORA DA CALL NÃO CONTA

Durante o grace period:

```text
60 segundos
```

o ponto pode continuar aberto para evitar encerramento por queda rápida.

Porém o período em que o membro está desconectado NÃO conta para os 15 minutos.

Exemplo:

```text
14m30s em patrulha
↓
queda por 40s
↓
retorna
```

Ao retornar continua com:

```text
14m30s
```

e não:

```text
15m10s
```

---

# 13. TROCA PARA CALL QUE NÃO CONTA COMO PATRULHA

Exemplo:

```text
Patrulhamento 01
10 minutos
```

depois:

```text
Treinamento
20 minutos
```

Total do serviço:

```text
30 minutos
```

Tempo em patrulha:

```text
10 minutos
```

Se encerrar:

```text
PONTO INVALIDADO
```

mesmo tendo permanecido 30 minutos com o ponto aberto.

---

# 14. CÁLCULO DO TEMPO

Não utilizar contador executando a cada segundo.

Continuar utilizando:

```text
timestamps + segmentos
```

Cada segmento deve indicar:

```text
startedAt
endedAt
channelId
countsTowardPatrolMinimum
```

No encerramento:

```text
patrolDuration =
soma dos segmentos onde
countsTowardPatrolMinimum = true
```

Depois:

```text
if patrolDuration >= minimumPatrolDuration
    VALID
else
    INVALIDATED
```

---

# 15. VALOR CONFIGURÁVEL

No painel:

```text
CONFIGURAÇÕES
↓
CONTROLE DE SERVIÇO
↓
TEMPO MÍNIMO
```

Mostrar:

```text
TEMPO MÍNIMO PARA VALIDAR PONTO

Atual:
15 minutos

[ ALTERAR ]
```

Permitir valores seguros.

Por exemplo:

```text
5 – 120 minutos
```

Não espalhar `15` hardcoded pelo projeto.

Configuração:

```text
minimumPatrolMinutes = 15
```

---

# 16. CONFIGURAÇÃO DAS CALLS

No painel das calls:

```text
PATRULHAMENTO 01

Permite serviço:
✅

Conta para validação mínima:
✅
```

Exemplo:

```text
TREINAMENTO

Permite serviço:
✅

Conta para validação mínima:
❌
```

Assim a administração controla facilmente quais canais efetivamente representam patrulha.

---

# 17. HISTÓRICO DO MEMBRO

Pontos inválidos devem aparecer no histórico.

Exemplo:

```text
22/08 — 20:00

Tempo:
11m

Status:
❌ Invalidado

Motivo:
Tempo mínimo não atingido
```

Não somar ao total.

---

# 18. RELATÓRIOS

Relatórios administrativos podem separar:

```text
Pontos válidos:
23

Pontos invalidados:
4
```

E permitir visualizar os invalidados.

Isso ajuda a identificar membros que constantemente iniciam serviços curtos.

---

# 19. NÃO PUNIR AUTOMATICAMENTE

O bot NÃO deve:

* advertir automaticamente;
* suspender;
* retirar cargo;
* marcar negativamente o membro.

Ele apenas invalida aquela sessão.

O histórico administrativo permite que o comando decida se existe abuso.

---

# 20. MÚLTIPLOS PONTOS INVÁLIDOS

Registrar todos.

Exemplo:

```text
Lucas

Últimos 30 dias

Pontos válidos:
18

Pontos invalidados:
5
```

Isso pode aparecer somente para o comando.

Não aplicar punição automática.

---

# 21. FINALIZAÇÃO AUTOMÁTICA ANTES DE 15 MINUTOS

Se o membro sair da call e não retornar após o grace period:

o bot encerra automaticamente.

Se possuía:

```text
12 minutos
```

resultado:

```text
INVALIDATED
```

Motivo:

```text
Tempo mínimo de patrulha não atingido.
```

Origem do encerramento:

```text
VOICE_DISCONNECT_TIMEOUT
```

---

# 22. BOT REINICIA ANTES DOS 15 MINUTOS

Exemplo:

```text
Ponto aberto:
10 minutos

Bot reinicia.
```

Após voltar:

não perder esses 10 minutos já registrados.

Recuperar os segmentos persistidos.

Se o membro continuar em call válida:

continuar contabilizando.

Ao alcançar:

```text
15 minutos
```

sessão poderá ser validada normalmente.

---

# 23. NÃO VALIDAR PELO TEMPO BRUTO

Essa regra é obrigatória.

Errado:

```text
shift duration >= 15 min
```

Correto:

```text
validPatrolDuration >= 15 min
```

Porque alguém pode deixar o ponto aberto por 1 hora sem realmente estar em patrulha.

---

# 24. CORREÇÃO ADMINISTRATIVA

Se por algum motivo um ponto válido tiver sido invalidado erroneamente, o comando poderá utilizar o painel administrativo para revisar.

Mostrar:

```text
REVISAR PONTO

Membro:
Lucas

Tempo bruto:
21m

Tempo de patrulha:
13m

Status:
INVALIDADO

[ AJUSTAR TEMPO ]

[ VALIDAR MANUALMENTE ]
```

Qualquer override deve exigir:

* motivo;
* confirmação;
* responsável.

E gerar audit log.

---

# 25. VALIDAÇÃO MANUAL EXCEPCIONAL

Se administrador validar manualmente:

registrar:

```text
validationSource = ADMIN_OVERRIDE
```

e não fingir que a regra automática foi cumprida.

Exemplo de auditoria:

```text
PONTO VALIDADO MANUALMENTE

Sessão:
#182

Tempo de patrulha:
13m

Mínimo:
15m

Responsável:
Ten. João

Motivo:
Queda geral do Discord
```

---

# 26. INDICADOR VISUAL

No painel pessoal, durante o serviço:

Antes dos 15 minutos:

```text
Validação:
⏳ 11m / 15m
```

Depois:

```text
Validação:
✅ Requisito mínimo atingido
```

Isso deixa a regra transparente.

---

# 27. PROGRESSO

Pode apresentar:

```text
Tempo mínimo de patrulha

████████░░ 12m / 15m
```

Mas não precisa atualizar a mensagem a cada segundo.

O valor é calculado quando:

* membro consulta;
* muda de call;
* encerra;
* ocorre evento relevante.

Evitar atualizações desnecessárias na API do Discord.

---

# 28. STATUS NO BANCO

Salvar dados suficientes para saber por que uma sessão foi invalidada.

Exemplo:

```text
status = INVALIDATED

invalidReason =
MINIMUM_PATROL_TIME_NOT_REACHED

requiredPatrolSeconds = 900

actualPatrolSeconds = 702
```

Não salvar apenas:

```text
invalid = true
```

---

# 29. TESTES OBRIGATÓRIOS

### 14 minutos e 59 segundos

Resultado:

```text
INVALIDADO
```

### 15 minutos exatos

Resultado:

```text
VÁLIDO
```

### 20 minutos em call válida

Resultado:

```text
VÁLIDO
```

### 10 min Patrulha 01 + 5 min Patrulha 02

Resultado:

```text
VÁLIDO
```

### 10 min Patrulha + 20 min Treinamento

Resultado:

```text
INVALIDADO
```

### 14m30 + queda de 40 segundos + retorno + 30 segundos

Resultado:

```text
15 minutos válidos
VÁLIDO
```

Os 40 segundos desconectados não contam.

### Ponto encerrado automaticamente com 8 minutos

Resultado:

```text
INVALIDADO
```

### Bot reinicia aos 10 minutos e membro continua em call

Resultado após completar mais 5 minutos válidos:

```text
VÁLIDO
```

---

# 30. REGRA FINAL

A abertura do ponto NÃO significa que as horas já serão contabilizadas como válidas.

O fluxo correto é:

```text
MEMBRO INICIA SERVIÇO
↓
PONTO FICA ATIVO
↓
BOT MONITORA TEMPO REAL DE PATRULHA
↓
ATINGIU 15 MINUTOS?
```

Se:

```text
SIM
```

↓

```text
SESSÃO ELEGÍVEL PARA VALIDAÇÃO
```

Se encerrar antes:

```text
NÃO
```

↓

```text
SESSÃO INVALIDADA
↓
ZERO HORAS ADICIONADAS
↓
HISTÓRICO PRESERVADO
```

O tempo mínimo deverá ser configurável, usando **15 minutos como padrão inicial da CHOQUE - BGR**.
