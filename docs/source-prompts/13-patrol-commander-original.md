Este prompt é COMPLEMENTAR aos prompts anteriores do projeto CHOQUE - BGR.

Adicionar ao sistema de Central de Patrulha Inteligente o módulo:

# COMANDANTE AUTOMÁTICO DA PATRULHA

O objetivo é definir automaticamente um responsável por cada patrulha ativa, utilizando critérios objetivos e configuráveis.

NÃO utilizar IA para escolher comandante.

Utilizar regras determinísticas.

---

# 1. MOMENTO DA ESCOLHA

Quando uma patrulha for criada:

```text
PATROL_CREATED
```

executar:

```text
selectPatrolCommander(patrolId)
```

A função deverá analisar somente membros efetivamente integrantes da patrulha.

---

# 2. CRITÉRIOS PADRÃO

Prioridade inicial:

```text
1. possui qualificação exigida para comando
2. maior rank.level
3. maior tempo na patente atual
4. maior tempo total de serviço
5. maior tempo de corporação
6. entrou primeiro na patrulha
```

Adaptar às estruturas reais existentes.

---

# 3. CONFIGURAÇÃO

Não hardcodar regras.

Criar configurações como:

```text
patrolCommander.enabled = true

patrolCommander.requireQualification = false

patrolCommander.requiredQualificationId = null

patrolCommander.minimumRankLevel = 0

patrolCommander.selectionPriority = [
  "QUALIFICATION",
  "RANK_LEVEL",
  "TIME_IN_RANK",
  "TOTAL_SERVICE_TIME",
  "MEMBERSHIP_TIME",
  "PATROL_JOIN_ORDER"
]
```

---

# 4. ELEGIBILIDADE

Antes de escolher, validar:

* membro ativo;
* não suspenso;
* não ausente;
* está na patrulha;
* está na call válida;
* possui patente sincronizada;
* atende patente mínima;
* atende qualificação obrigatória, se configurada.

---

# 5. RESULTADO

Persistir no registro da patrulha:

```text
commanderMemberId
commanderAssignedAt
commanderAssignmentSource
```

Valores de source:

```text
AUTOMATIC
MANUAL_OVERRIDE
REASSIGNMENT
```

---

# 6. PAINEL

Exibir no painel da patrulha:

```text
PTR-03

COMANDANTE
[SGT] Lucas [81]

INTEGRANTES
[CB] Pedro [102]
[SD] João [152]
[RCT] Marcos [208]

TEMPO
01h12
```

---

# 7. SAÍDA DO COMANDANTE

Se o comandante:

* sair da call;
* sair da patrulha;
* encerrar serviço;
* ficar suspenso;
* ficar ausente;
* perder elegibilidade;

executar reavaliação automática.

```text
selectPatrolCommander()
```

novamente.

---

# 8. NÃO TROCAR SEM NECESSIDADE

Se o comandante atual continuar elegível:

não recalcular apenas porque entrou um membro de patente maior depois.

Criar configuração:

```text
reassignWhenHigherRankJoins = false
```

Padrão:

```text
false
```

Isso evita troca de comando toda hora.

---

# 9. TRANSFERÊNCIA AUTOMÁTICA

Exemplo:

```text
Anterior:
[SGT] Lucas [81]

Novo:
[CB] Pedro [102]

Motivo:
COMMANDER_LEFT_PATROL
```

Registrar histórico.

---

# 10. HISTÓRICO DE COMANDO

Criar histórico por patrulha:

```text
patrol_commander_history
```

ou estrutura equivalente.

Campos conceituais:

```text
patrolId
memberId
startedAt
endedAt
source
reason
assignedBy
```

---

# 11. ALTERAÇÃO MANUAL

Superior autorizado poderá:

```text
PATRULHA
↓
GERENCIAR
↓
ALTERAR COMANDANTE
```

User Select apenas com membros daquela patrulha.

Depois:

```text
Motivo
```

e confirmação.

---

# 12. PERMISSÃO

Adicionar:

```text
patrol.commander.override
```

Backend deve validar.

---

# 13. MANUAL OVERRIDE

Se um superior escolher manualmente:

```text
manualCommanderLock = true
```

Por padrão, o bot não deve substituir esse comandante só porque alguém com rank maior entrou.

Ainda deverá substituir se o comandante deixar de estar elegível.

---

# 14. SEM MEMBRO ELEGÍVEL

Se ninguém atender às regras:

```text
commanderMemberId = null
```

Painel:

```text
COMANDANTE
Não definido
```

Criar flag administrativa:

```text
PATROL_WITHOUT_ELIGIBLE_COMMANDER
```

Não inventar comandante.

---

# 15. FORMAÇÃO AUTOMÁTICA

Integrar à fila automática existente.

Fluxo:

```text
2 membros válidos
↓
Patrulha formada
↓
membros movidos
↓
registro criado
↓
comandante selecionado
↓
painel atualizado
```

---

# 16. QUALIFICAÇÃO

Integrar com Matriz de Qualificação existente.

Exemplo:

```text
PATROL_COMMAND
```

ou qualificação configurada.

Não criar segundo sistema de cursos.

---

# 17. TIE BREAK

Se dois membros possuírem exatamente a mesma prioridade:

usar ordem determinística.

Exemplo:

```text
patrolJoinedAt ASC
```

Nunca escolha aleatória.

---

# 18. AUDITORIA

Eventos:

```text
PATROL_COMMANDER_ASSIGNED
PATROL_COMMANDER_REASSIGNED
PATROL_COMMANDER_OVERRIDDEN
PATROL_COMMANDER_CLEARED
```

Registrar:

```text
patrolId
before
after
source
reason
actor
timestamp
```

---

# 19. EVENTOS

A seleção deverá reagir aos eventos centrais já existentes.

Exemplo:

```text
PATROL_CREATED
PATROL_MEMBER_LEFT
MEMBER_STATUS_CHANGED
MEMBER_RANK_CHANGED
QUALIFICATION_CHANGED
```

Mas apenas recalcular quando realmente necessário.

---

# 20. NÃO GERAR LOOP

Mudança automática de comandante não deve disparar um evento que volte a selecionar infinitamente.

Garantir idempotência.

---

# 21. RESTART

Após reinício do bot:

reconciliar patrulhas ativas.

Se:

```text
commanderMemberId
```

não estiver mais presente ou elegível:

selecionar substituto.

---

# 22. RELATÓRIO DE PATRULHA

Histórico da patrulha deverá mostrar:

```text
COMANDANTES

21:02–21:47
[SGT] Lucas [81]

21:47–22:31
[CB] Pedro [102]
```

---

# 23. FEEDBACK PÓS-PATRULHA

O sistema de feedback privado já definido deve identificar corretamente quem estava no comando no momento relevante.

No encerramento, o comandante final poderá receber opção de registrar feedback, conforme regras existentes.

---

# 24. TESTES

Testar:

### Soldado + Cabo

Resultado:

```text
Cabo comandante
```

### Cabo sem qualificação + Soldado com qualificação obrigatória

Se qualificação for obrigatória:

```text
Soldado comandante
```

### Dois Cabos

Usar próximo critério.

### Comandante sai

Novo comandante automaticamente.

### Membro de patente maior entra depois

Com:

```text
reassignWhenHigherRankJoins = false
```

não trocar.

### Manual override

Não substituir automaticamente enquanto o escolhido permanecer elegível.

### Ninguém elegível

Não definir comandante.

---

# 25. PRINCÍPIO FINAL

O sistema deverá sempre responder:

```text
QUAL É O MEMBRO MAIS ELEGÍVEL DESTA PATRULHA AGORA?
```

utilizando regras transparentes e configuráveis.

Nunca:

* escolher aleatoriamente;
* utilizar IA;
* alterar comandante a todo momento;
* ignorar override humano;
* inventar cargo;
* promover alguém por estar comandando.

O comandante de patrulha é apenas uma FUNÇÃO OPERACIONAL TEMPORÁRIA.

Não altera a patente do membro.

