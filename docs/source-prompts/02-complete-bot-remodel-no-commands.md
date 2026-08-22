Você já possui acesso ao repositório completo do bot existente.

Sua tarefa é realizar um **QA completo no projeto, corrigir problemas, otimizar o código existente e transformar o bot atual em um sistema completo de gerenciamento da corporação CHOQUE - BGR dentro do Discord**.

O objetivo não é criar um bot exageradamente complexo.

Quero um sistema prático, organizado, confiável e fácil de utilizar diariamente.

# REGRA ABSOLUTA

NÃO utilizar comandos.

Não criar:

* slash commands;
* prefix commands;
* comandos por mensagem;
* comandos administrativos escondidos;
* ações dependentes de mensagens digitadas no chat.

Toda interação deverá acontecer através de:

* mensagens fixas;
* botões;
* select menus;
* user selects;
* role selects;
* channel selects;
* modais;
* mensagens ephemeral;
* atualização automática de mensagens existentes.

A filosofia é:

```text
PAINEL FIXO
↓
BOTÃO
↓
SELECT / MODAL
↓
VALIDAÇÃO
↓
AÇÃO
↓
BANCO
↓
AUDITORIA
↓
ATUALIZAÇÃO DO PAINEL
```

---

# 1. OBJETIVO DO PROJETO

Transformar o bot existente em uma central administrativa da:

# CHOQUE - BGR

O bot deverá ajudar a organizar:

* membros;
* hierarquia;
* bate ponto;
* horas;
* ausências;
* afastamentos;
* solicitações;
* promoções;
* rebaixamentos;
* advertências;
* suspensões;
* cursos;
* treinamentos;
* presença;
* atividade semanal;
* relatórios;
* histórico dos membros.

Tudo dentro do Discord.

---

# 2. PRIMEIRO PASSO — QA DO REPOSITÓRIO

Antes de implementar novas funções:

analise todo o projeto existente.

Identifique:

* linguagem;
* framework;
* versão da biblioteca Discord;
* banco de dados;
* ORM;
* estrutura de pastas;
* handlers;
* eventos;
* botões;
* modais;
* selects;
* comandos existentes;
* configuração;
* logs;
* permissões;
* dependências;
* testes.

Procure:

* código duplicado;
* funções não utilizadas;
* listeners duplicados;
* erros async/await;
* promises não tratadas;
* race conditions;
* memory leaks;
* IDs hardcoded;
* token ou secrets no código;
* consultas excessivas;
* timers desnecessários;
* tratamento ruim de erros;
* interações sem validação;
* componentes que deixam de funcionar após restart;
* permissões excessivas;
* dependências desnecessárias.

Não reescreva tudo sem necessidade.

Reaproveite a estrutura existente sempre que ela estiver adequada.

---

# 3. EXECUÇÃO E TESTES DO ESTADO ATUAL

Antes das alterações:

* execute o bot;
* valide conexão com banco;
* valide eventos;
* valide botões;
* valide modais;
* valide selects;
* valide persistência;
* valide restart;
* valide tratamento de erros.

Crie uma lista dos problemas encontrados.

Corrija primeiro os problemas estruturais.

---

# 4. REMOVER SISTEMA DE COMANDOS

Analise os comandos existentes.

Para cada funcionalidade útil atualmente acessada por comando:

converta para botão, select ou modal.

Exemplo antigo:

```text
/ponto iniciar
```

Novo:

```text
[ INICIAR SERVIÇO ]
```

Exemplo antigo:

```text
/promover @usuario
```

Novo:

```text
PAINEL DO COMANDO
↓
GERENCIAR MEMBRO
↓
Selecionar membro
↓
PROMOVER
```

Depois que todas as funcionalidades úteis forem convertidas, remover a necessidade dos comandos antigos.

---

# 5. IDENTIDADE CHOQUE - BGR

Converter toda identidade visual para:

# CHOQUE - BGR

Centralizar:

* nome;
* cor;
* logo;
* footer;
* imagens;
* textos padrão.

Evitar informações visuais espalhadas pelo código.

O visual deve ser:

* escuro;
* limpo;
* institucional;
* moderno;
* sério;
* fácil de ler;
* sem excesso de emojis.

---

# 6. ARQUITETURA

Separar interface Discord das regras do sistema.

Estrutura esperada:

```text
Painel Discord
↓
Interaction Handler
↓
Service
↓
Repository
↓
Database
```

Exemplo:

```text
Botão "Iniciar Serviço"
↓
ShiftInteraction
↓
ShiftService.start()
↓
ShiftRepository
↓
Database
```

Não colocar toda regra dentro do handler de botão.

---

# 7. PAINÉIS FIXOS

Criar painéis principais permanentes.

Sugestão:

```text
#・central-membro
#・controle-servico
#・solicitacoes
#・treinamentos
#・painel-comando
#・logs
```

Cada canal possui uma mensagem principal controlada pelo bot.

Evitar várias mensagens desnecessárias.

Sempre que possível:

```text
Mensagem fixa
↓
Botão
↓
Resposta ephemeral
```

---

# 8. PERSISTÊNCIA DOS PAINÉIS

Salvar:

* guild ID;
* channel ID;
* message ID;
* tipo do painel;
* versão;
* status.

Ao reiniciar:

* recuperar painéis;
* validar se mensagens continuam existentes;
* restaurar componentes;
* atualizar painel se necessário.

Não depender somente de memória.

---

# 9. CENTRAL DO MEMBRO

Mensagem fixa:

```text
CHOQUE - BGR
CENTRAL DO MEMBRO

Utilize as opções abaixo para acessar suas informações
e realizar solicitações.

[ MEU PERFIL ]
[ MINHAS HORAS ]

[ SOLICITAÇÕES ]
[ TREINAMENTOS ]

[ MEU HISTÓRICO ]
[ MINHA SITUAÇÃO ]
```

Tudo deverá responder de forma ephemeral.

---

# 10. PAINEL DE CONTROLE DE SERVIÇO

Criar:

```text
CHOQUE - BGR
CONTROLE DE SERVIÇO

Para iniciar seu serviço você precisa estar conectado
em uma das calls autorizadas.

[ 🟢 INICIAR SERVIÇO ]

[ 🔴 FINALIZAR SERVIÇO ]

[ ⏱ MINHAS HORAS ]

[ 📋 HISTÓRICO ]
```

---

# 11. BATE PONTO POR CALL

Ao clicar:

`INICIAR SERVIÇO`

verificar:

1. membro está cadastrado;
2. possui status permitido;
3. possui cargo autorizado;
4. está em canal de voz;
5. canal está na lista permitida;
6. não possui serviço ativo.

Se tudo estiver válido:

criar sessão.

Registrar:

* membro;
* data;
* horário;
* call;
* início;
* status.

---

# 12. CONTAGEM DE TEMPO

Não utilizar contador a cada segundo.

Utilizar timestamps.

Estrutura:

```text
SHIFT

started_at
ended_at
status
```

E segmentos:

```text
SHIFT_SEGMENT

shift_id
voice_channel_id
started_at
ended_at
```

---

# 13. TROCA DE CALL

Se o membro trocar:

```text
CALL AUTORIZADA
→
OUTRA CALL AUTORIZADA
```

o serviço continua.

Fechar segmento anterior.

Criar novo segmento.

---

# 14. SAÍDA DA CALL

Se sair da call autorizada:

iniciar uma pequena tolerância configurável.

Exemplo:

```text
60 segundos
```

Se voltar dentro do período:

continuar serviço.

Caso contrário:

finalizar automaticamente.

---

# 15. RESTART DO BOT

O serviço ativo precisa sobreviver a restart.

Ao inicializar:

* buscar serviços ativos;
* verificar membro;
* verificar call atual;
* recuperar sessões válidas;
* finalizar sessões inconsistentes quando necessário;
* evitar duplicação de tempo.

---

# 16. PROTEÇÕES DO PONTO

Impedir:

* abrir dois serviços;
* iniciar fora da call;
* acumular horas fora das calls permitidas;
* clicar várias vezes e criar sessões duplicadas;
* finalizar duas vezes;
* membro editar próprias horas;
* alteração administrativa sem justificativa.

---

# 17. STATUS DO SERVIÇO

Ao membro clicar em:

`MINHA SITUAÇÃO`

mostrar:

```text
SERVIÇO ATUAL

Status
🟢 Em serviço

Início
21:32

Tempo válido
01h24

Call
Patrulhamento 01
```

---

# 18. EFETIVO EM SERVIÇO

Criar painel público atualizado automaticamente.

Exemplo:

```text
CHOQUE - BGR
EFETIVO EM SERVIÇO

Sgt. João
Patrulhamento 01
01h32

Cb. Pedro
Patrulhamento 02
52min

Sd. Lucas
Operação
31min

Total em serviço
3
```

Editar a mensagem existente.

Não criar uma mensagem nova a cada alteração.

---

# 19. SISTEMA DE MEMBROS

Criar cadastro estruturado.

Campos:

* Discord ID;
* nome;
* nome utilizado na corporação;
* patente;
* status;
* data de ingresso;
* horas totais;
* observações administrativas;
* última atividade.

Status:

```text
ATIVO
AUSENTE
RESERVA
SUSPENSO
EM_FORMAÇÃO
DESLIGADO
```

---

# 20. STATUS CENTRALIZADO

Criar serviço central responsável por determinar:

* pode bater ponto;
* entra na meta;
* aparece no efetivo;
* pode participar de treinamento;
* pode receber determinadas ações;
* quais cargos Discord precisa possuir.

Não espalhar essas verificações pelo projeto.

---

# 21. SINCRONIZAÇÃO DE CARGOS

Quando status ou patente mudar:

sincronizar automaticamente os cargos.

Exemplo:

```text
Status = AUSENTE
↓
Adicionar cargo Ausente
↓
Remover cargos incompatíveis
```

Caso o bot reinicie:

reconciliar banco e Discord.

---

# 22. PERFIL DO MEMBRO

Botão:

`MEU PERFIL`

Mostrar:

```text
FICHA FUNCIONAL

Nome
João

Patente
Cabo

Status
Ativo

Ingresso
10/05/2026

Horas semanais
7h21

Horas mensais
31h42

Horas totais
127h11

Treinamentos concluídos
4

Advertências ativas
0
```

---

# 23. HISTÓRICO FUNCIONAL

Criar timeline.

Exemplo:

```text
10/05
Ingressou na corporação

18/05
Concluiu formação

28/05
Promovido para Soldado

17/06
Advertência registrada

04/07
Promovido para Cabo

12/08
Ausência aprovada

17/08
Retornou ao efetivo
```

Utilizar paginação.

---

# 24. CENTRAL DE SOLICITAÇÕES

Mensagem fixa:

```text
CHOQUE - BGR
CENTRAL DE SOLICITAÇÕES

Selecione o que deseja solicitar.

[ 📅 AUSÊNCIA ]

[ 🔄 RETORNO ]

[ 🪖 RESERVA ]

[ ⏱ CORREÇÃO DE HORAS ]

[ 🪪 ALTERAÇÃO DE DADOS ]

[ 🚪 DESLIGAMENTO ]
```

---

# 25. AUSÊNCIA

Ao clicar:

`AUSÊNCIA`

abrir modal.

Campos:

* data inicial;
* data final;
* motivo;
* observação.

Depois:

salvar solicitação como:

`PENDENTE`.

---

# 26. PAINEL DE SOLICITAÇÕES DO COMANDO

Mensagem fixa:

```text
CHOQUE - BGR
SOLICITAÇÕES ADMINISTRATIVAS

Pendentes
7

[ VER PENDENTES ]

[ HISTÓRICO ]
```

Ao clicar:

mostrar lista.

Administrador seleciona solicitação.

---

# 27. ANÁLISE DA AUSÊNCIA

Exemplo:

```text
SOLICITAÇÃO DE AUSÊNCIA

Membro
João

Início
25/08

Fim
30/08

Motivo
Viagem

[ ✅ APROVAR ]

[ ❌ NEGAR ]

[ 👤 VER PERFIL ]
```

---

# 28. APROVAÇÃO DE AUSÊNCIA

Ao clicar em aprovar:

automaticamente:

* alterar status para AUSENTE;
* adicionar cargo;
* bloquear novo serviço;
* retirar da cobrança de meta;
* registrar aprovação;
* salvar aprovador;
* registrar histórico;
* agendar retorno;
* notificar membro.

Nada disso deve depender de ajustes manuais posteriores.

---

# 29. RETORNO AUTOMÁTICO

Ao chegar a data final:

* encerrar ausência;
* status → ATIVO;
* sincronizar cargos;
* restaurar elegibilidade;
* atualizar histórico;
* notificar membro.

O processo deve sobreviver a restart.

---

# 30. RETORNO ANTECIPADO

Membro pode clicar:

`RETORNO`

Se tiver ausência ativa:

mostrar:

```text
Você possui uma ausência ativa até 30/08.

[ SOLICITAR RETORNO ANTECIPADO ]
```

Comando aprova pelo painel administrativo.

---

# 31. RESERVA

Membro pode solicitar entrada na reserva.

Após aprovação:

* status → RESERVA;
* retirar de meta;
* bloquear serviço caso definido;
* atualizar cargo;
* manter histórico e patente.

---

# 32. CORREÇÃO DE HORAS

Membro seleciona:

`CORREÇÃO DE HORAS`

Modal:

* data/sessão;
* problema;
* horário correto;
* motivo.

Comando analisa.

Ao aprovar:

registrar:

* tempo anterior;
* novo tempo;
* responsável;
* motivo.

Nunca alterar horas sem audit log.

---

# 33. ALTERAÇÃO DE DADOS

Permitir solicitar alteração de:

* nome utilizado;
* identificação interna;
* outros dados administrativos relevantes.

Após aprovação:

atualizar cadastro.

---

# 34. DESLIGAMENTO

Membro pode solicitar desligamento.

Comando recebe no painel.

Se aprovado:

* finalizar serviço ativo;
* status → DESLIGADO;
* remover cargos relacionados;
* registrar data;
* registrar motivo;
* preservar histórico.

Nunca deletar ficha.

---

# 35. PAINEL DO COMANDO

Mensagem fixa:

```text
CHOQUE - BGR
CENTRAL DO COMANDO

[ 👥 EFETIVO ]

[ 📥 SOLICITAÇÕES ]

[ 📈 CARREIRA ]

[ ⚠ DISCIPLINA ]

[ 🎓 TREINAMENTOS ]

[ ⏱ ATIVIDADE ]

[ 📊 RELATÓRIOS ]

[ ⚙ CONFIGURAÇÕES ]
```

---

# 36. GESTÃO DO EFETIVO

Botão:

`EFETIVO`

Abrir:

```text
GESTÃO DO EFETIVO

[ LOCALIZAR MEMBRO ]

[ ATIVOS ]

[ AUSENTES ]

[ RESERVA ]

[ SUSPENSOS ]

[ DESLIGADOS ]
```

---

# 37. LOCALIZAR MEMBRO

Usar User Select.

Após selecionar:

mostrar:

```text
JOÃO

Patente
Cabo

Status
Ativo

Ingresso
10/05/2026

Horas totais
127h

[ PERFIL ]

[ CARREIRA ]

[ DISCIPLINA ]

[ TREINAMENTOS ]

[ GERENCIAR ]
```

---

# 38. HIERARQUIA

Criar sistema de patentes configurável.

Estrutura:

```text
rank.id
rank.name
rank.level
rank.role_id
```

Não deixar patentes hardcoded dentro dos handlers.

---

# 39. PAINEL DE CARREIRA

```text
GESTÃO DE CARREIRA

[ ⬆ PROMOVER ]

[ ⬇ REBAIXAR ]

[ 📋 HISTÓRICO ]
```

---

# 40. PROMOÇÃO

Fluxo:

```text
Selecionar membro
↓
Selecionar nova patente
↓
Inserir motivo
↓
Confirmar
```

Ao confirmar:

* atualizar patente;
* atualizar cargo;
* registrar patente anterior;
* registrar nova patente;
* registrar responsável;
* registrar motivo;
* atualizar histórico.

---

# 41. REBAIXAMENTO

Mesmo fluxo.

Sempre exigir confirmação.

Exemplo:

```text
CONFIRMAR ALTERAÇÃO

Membro
João

Patente atual
Cabo

Nova patente
Soldado

Motivo
Conduta administrativa

[ CONFIRMAR ]

[ CANCELAR ]
```

---

# 42. NÃO PROMOVER AUTOMATICAMENTE

O sistema pode mostrar informações como:

```text
Tempo na patente
35 dias

Horas no mês
28h

Advertências ativas
0
```

Mas a decisão da promoção continua humana.

---

# 43. SISTEMA DE DISCIPLINA

Painel:

```text
DISCIPLINA

[ REGISTRAR OCORRÊNCIA ]

[ APLICAR ADVERTÊNCIA ]

[ SUSPENDER MEMBRO ]

[ CONSULTAR HISTÓRICO ]
```

---

# 44. OCORRÊNCIAS

Registrar ocorrência sem necessariamente punir.

Campos:

* membro;
* descrição;
* evidência/link opcional;
* observação.

Status:

```text
ABERTA
ARQUIVADA
CONVERTIDA EM ADVERTÊNCIA
```

---

# 45. ADVERTÊNCIA

Fluxo:

```text
Selecionar membro
↓
Selecionar tipo
↓
Informar motivo
↓
Confirmar
```

Registrar:

* tipo;
* motivo;
* responsável;
* data;
* evidência opcional;
* status.

---

# 46. STATUS DE ADVERTÊNCIA

Possíveis estados:

```text
ATIVA
CUMPRIDA
REVOGADA
```

Nunca apagar advertência do histórico.

---

# 47. SUSPENSÃO

Comando seleciona:

`SUSPENDER MEMBRO`

Define:

* membro;
* motivo;
* início;
* duração;
* observação.

Ao aplicar:

* status → SUSPENSO;
* finalizar ponto se estiver ativo;
* bloquear novo ponto;
* sincronizar cargo;
* registrar histórico;
* agendar fim.

---

# 48. FIM AUTOMÁTICO DA SUSPENSÃO

Quando período terminar:

* restaurar status adequado;
* sincronizar cargo;
* registrar fim;
* notificar membro.

Também deve funcionar após restart.

---

# 49. TREINAMENTOS

Canal fixo:

```text
CHOQUE - BGR
TREINAMENTOS

[ TREINAMENTOS ABERTOS ]

[ MEUS TREINAMENTOS ]

[ MEUS CURSOS ]
```

---

# 50. PAINEL ADMINISTRATIVO DE TREINAMENTO

```text
GESTÃO DE TREINAMENTOS

[ CRIAR TREINAMENTO ]

[ TREINAMENTOS ATIVOS ]

[ HISTÓRICO ]
```

---

# 51. CRIAÇÃO DE TREINAMENTO

Usar:

* modal;
* selects;
* channel select quando necessário.

Campos:

* nome;
* data;
* horário;
* responsável;
* número de vagas;
* descrição.

---

# 52. PAINEL DE TREINAMENTO

Exemplo:

```text
TREINAMENTO DE CHOQUE

Responsável
Sgt. João

Data
25/08

Horário
21:00

Vagas
12 / 20

[ ✅ PARTICIPAR ]

[ ❌ CANCELAR PARTICIPAÇÃO ]

[ ℹ DETALHES ]
```

Atualizar a mesma mensagem conforme inscrições.

---

# 53. FINALIZAÇÃO DO TREINAMENTO

Responsável abre:

`GERENCIAR TREINAMENTO`

Seleciona participantes.

Marca:

* presente;
* ausente;
* aprovado;
* reprovado.

Salvar no histórico do membro.

---

# 54. CURSOS / QUALIFICAÇÕES

Manter lista simples de qualificações do membro.

Exemplo:

```text
CURSOS

✅ Formação
✅ Patrulhamento
✅ Choque
❌ Instrutor
```

Não criar sistema exageradamente complexo.

Curso precisa ter:

* nome;
* data;
* responsável;
* resultado.

---

# 55. ATIVIDADE SEMANAL

Criar painel.

Exemplo:

```text
ATIVIDADE SEMANAL

Meta
5h

João
8h21 ✅

Pedro
5h10 ✅

Lucas
3h42 ⚠

Carlos
1h05 ❌
```

---

# 56. META SEMANAL

Configuração simples.

Exemplo:

```text
5 horas
```

Status:

* cumprida;
* próxima;
* não cumprida;
* isento.

Ausência e reserva podem gerar isenção.

---

# 57. FECHAMENTO SEMANAL

No final da semana:

salvar snapshot.

Não apagar os dados antigos.

Registrar:

* horas;
* meta;
* situação;
* isenção.

---

# 58. INATIVIDADE

Identificar membros que estão há muitos dias sem atividade.

Painel administrativo:

```text
MONITORAMENTO DE ATIVIDADE

[ ATIVIDADE NORMAL ]

[ BAIXA ATIVIDADE ]

[ SEM ATIVIDADE ]
```

Não punir ninguém automaticamente.

---

# 59. RELATÓRIOS

Painel:

```text
RELATÓRIOS

[ DIÁRIO ]

[ SEMANAL ]

[ MENSAL ]

[ MEMBRO ]

[ PONTOS ]

[ AUSÊNCIAS ]

[ TREINAMENTOS ]
```

---

# 60. RELATÓRIO DIÁRIO

Exemplo:

```text
RELATÓRIO DIÁRIO

Membros que trabalharam
18

Horas realizadas
62h31

Pontos abertos
3

Ausências ativas
4

Treinamentos
1
```

---

# 61. RELATÓRIO SEMANAL

Exibir:

* horas totais;
* média;
* meta;
* membros que cumpriram;
* membros abaixo;
* ausentes;
* novos membros;
* promoções;
* advertências;
* treinamentos.

---

# 62. RELATÓRIO POR MEMBRO

Selecionar membro.

Mostrar:

```text
RELATÓRIO — JOÃO

Horas semana
8h22

Horas mês
32h18

Horas total
127h51

Serviços realizados
41

Último serviço
21/08

Advertências ativas
0

Treinamentos concluídos
4
```

---

# 63. LOGS DE AUDITORIA

Toda ação administrativa relevante deve gerar log.

Registrar:

* ação;
* responsável;
* membro;
* valor anterior;
* valor novo;
* motivo;
* data;
* ID.

Exemplo:

```text
ALTERAÇÃO DE PATENTE

Membro
João

Anterior
Soldado

Nova
Cabo

Responsável
Ten. Pedro

Motivo
Promoção

ID
AUD-00129
```

---

# 64. AÇÕES QUE PRECISAM DE AUDITORIA

No mínimo:

* promoção;
* rebaixamento;
* correção de horas;
* ausência aprovada;
* ausência negada;
* suspensão;
* fim de suspensão;
* advertência;
* desligamento;
* alteração de status;
* alteração de configuração.

---

# 65. PERMISSÕES

Criar RBAC central.

Exemplos:

```text
shift.start
shift.finish.self
shift.manage

member.view
member.manage
member.promote
member.demote

absence.request
absence.review

discipline.create
discipline.manage

training.create
training.manage

report.view

settings.manage
```

Não espalhar checagem de cargos dentro de todos os botões.

---

# 66. SEGURANÇA DOS BOTÕES

Mesmo que um botão administrativo apareça somente em canal privado:

verificar permissão novamente no backend.

Nunca confiar apenas na interface.

---

# 67. CONFIGURAÇÕES

Criar painel:

```text
CONFIGURAÇÕES

[ CALLS DE SERVIÇO ]

[ CARGOS ]

[ CANAIS ]

[ META SEMANAL ]

[ PATENTES ]

[ MÓDULOS ]
```

---

# 68. CONFIGURAÇÃO DE CALLS

Usar Channel Select.

Exemplo:

```text
CALLS AUTORIZADAS

Patrulhamento 01
Patrulhamento 02
Operação

[ ADICIONAR ]

[ REMOVER ]
```

---

# 69. CONFIGURAÇÃO DE CARGOS

Usar Role Select.

Configurar:

* membro;
* comando;
* ausência;
* suspensão;
* reserva;
* patentes.

---

# 70. FEATURE FLAGS

Permitir desativar módulos.

Exemplo:

```text
Ponto
Ativo

Ausências
Ativo

Treinamentos
Ativo

Disciplina
Ativo
```

Não precisa criar sistema exageradamente sofisticado.

Apenas permita ativar/desativar módulos principais.

---

# 71. BANCO DE DADOS

Avalie o banco existente.

Estrutura conceitual suficiente:

```text
guild_settings
panels

members
member_status_history

ranks
rank_history

shifts
shift_segments
shift_adjustments

requests
absences

occurrences
punishments
suspensions

trainings
training_attendance
courses

weekly_activity

audit_logs
scheduled_jobs
```

Não crie tabelas sem necessidade real.

---

# 72. TRANSAÇÕES

Usar transaction em ações críticas.

Exemplo:

promoção:

```text
BEGIN

alterar patente
criar histórico
criar auditoria

COMMIT
```

---

# 73. CONCORRÊNCIA

Proteger contra:

* botão clicado duas vezes;
* dois admins aprovando mesma solicitação;
* duas finalizações de ponto;
* job e administrador alterando mesma ausência;
* duas promoções simultâneas.

---

# 74. SCHEDULER

Criar mecanismo persistente para:

* fim de ausência;
* fim de suspensão;
* fechamento semanal.

Não depender somente de `setTimeout`.

---

# 75. JOBS IDEMPOTENTES

Se o mesmo job executar duas vezes:

não duplicar efeitos.

Exemplo:

se ausência já terminou:

ignorar segunda execução com segurança.

---

# 76. PAGINAÇÃO

Usar botões:

```text
[ ← ]

Página 2 / 5

[ → ]
```

Para:

* históricos;
* membros;
* solicitações;
* logs;
* treinamentos.

---

# 77. MODAIS

Usar modal apenas para texto necessário.

Exemplos:

* motivo;
* observação;
* datas;
* descrição.

Não usar modal quando select resolve.

---

# 78. EPHEMERAL

Usar para:

* perfil;
* histórico pessoal;
* erros;
* ações administrativas;
* confirmação;
* formulários;
* detalhes de solicitações.

---

# 79. CONFIRMAÇÃO DE AÇÕES CRÍTICAS

Sempre confirmar:

* promoção;
* rebaixamento;
* suspensão;
* desligamento;
* alteração de horas.

Exemplo:

```text
CONFIRMAR SUSPENSÃO

Membro
João

Duração
3 dias

Motivo
Conduta

[ CONFIRMAR ]

[ CANCELAR ]
```

---

# 80. UX

Nunca responder:

```text
Erro.
```

Responder:

```text
Não foi possível iniciar seu serviço porque você não está conectado em uma call autorizada.
```

---

# 81. NÃO POLUIR CANAIS

Evitar mensagens públicas para:

* entrada em ponto;
* troca de call;
* consultas pessoais;
* erros;
* ações administrativas.

Essas informações devem ficar:

* no banco;
* nos logs;
* em ephemeral.

---

# 82. TESTES DO PONTO

Testar:

1. iniciar fora da call;
2. iniciar em call válida;
3. clicar duas vezes;
4. trocar de call;
5. sair da call;
6. voltar durante tolerância;
7. não voltar;
8. restart;
9. finalizar manualmente;
10. membro ausente;
11. membro suspenso.

---

# 83. TESTES DE AUSÊNCIA

Testar:

1. solicitação;
2. aprovação;
3. negação;
4. início;
5. fim automático;
6. retorno antecipado;
7. restart;
8. clique duplo;
9. dois administradores aprovando juntos.

---

# 84. TESTES DE CARREIRA

Testar:

* promoção;
* rebaixamento;
* cargo inexistente;
* membro inexistente;
* histórico;
* botão duplicado;
* falta de permissão.

---

# 85. TESTES DE DISCIPLINA

Testar:

* advertência;
* suspensão;
* fim automático;
* restart;
* bloqueio de ponto;
* histórico.

---

# 86. TESTES DE PAINÉIS

Testar:

* painel após restart;
* mensagem apagada;
* botão antigo;
* interação inválida;
* ausência de permissão;
* modal cancelado.

---

# 87. NÃO IMPLEMENTAR

Não implementar:

* integração direta com MTA;
* API MTA;
* dashboard web;
* controle de armas;
* inventário;
* controle de equipamentos;
* controle complexo de viaturas;
* geolocalização;
* economia;
* sistema financeiro;
* inteligência artificial;
* reconhecimento de voz;
* punições automáticas;
* promoções automáticas;
* desligamentos automáticos;
* sistemas externos desnecessários.

O bot deve permanecer focado no Discord.

---

# 88. PRIORIZAÇÃO

## FASE 1 — QA

* analisar repositório;
* corrigir erros;
* remover código morto;
* melhorar segurança.

## FASE 2 — PAINÉIS

* sistema de componentes;
* persistência;
* central do membro;
* painel do comando.

## FASE 3 — MEMBROS

* cadastro;
* perfil;
* status;
* cargos;
* histórico.

## FASE 4 — PONTO

* call;
* sessões;
* segmentos;
* horas;
* restart;
* painel.

## FASE 5 — SOLICITAÇÕES

* ausência;
* retorno;
* reserva;
* correção de horas;
* desligamento.

## FASE 6 — CARREIRA

* patentes;
* promoção;
* rebaixamento;
* histórico.

## FASE 7 — DISCIPLINA

* ocorrências;
* advertências;
* suspensão.

## FASE 8 — TREINAMENTOS

* criação;
* inscrição;
* presença;
* cursos.

## FASE 9 — ATIVIDADE

* meta semanal;
* inatividade;
* relatórios.

## FASE 10 — CONFIGURAÇÕES

* calls;
* cargos;
* canais;
* patentes;
* módulos.

---

# 89. DEFINITION OF DONE

Um módulo só está pronto quando possuir:

* painel;
* botões/selects;
* modal quando necessário;
* validação;
* permissão;
* persistência;
* tratamento de erros;
* auditoria;
* proteção contra duplicação;
* recuperação após restart quando aplicável;
* testes.

---

# 90. REGRA DE AUTOMAÇÃO

Automatizar tarefas administrativas previsíveis.

Exemplo:

```text
AUSÊNCIA APROVADA
↓
status alterado
↓
cargo atualizado
↓
meta suspensa
↓
retorno agendado
↓
histórico criado
```

Mas não automatizar decisões humanas.

---

# 91. DECISÕES QUE DEVEM CONTINUAR HUMANAS

O bot NÃO deve decidir sozinho:

* promoção;
* rebaixamento;
* punição;
* desligamento;
* aprovação de ausência;
* aprovação de correção de horas.

Ele pode apresentar informações.

A decisão final é do responsável.

---

# 92. FLUXO IDEAL

A lógica principal do sistema deve seguir:

```text
MEMBRO CLICA
↓
BOT VALIDA
↓
MEMBRO PREENCHE
↓
SISTEMA REGISTRA
↓
COMANDO ANALISA QUANDO NECESSÁRIO
↓
COMANDO CLICA APROVAR / NEGAR
↓
BOT EXECUTA AS CONSEQUÊNCIAS
↓
AUDITORIA É CRIADA
↓
PAINEL É ATUALIZADO
```

---

# 93. PROIBIÇÃO FINAL DE COMANDOS

Durante todo o projeto:

# NÃO CRIAR SLASH COMMANDS.

# NÃO CRIAR PREFIX COMMANDS.

# NÃO CRIAR COMANDOS DE TEXTO.

Inclusive para administração.

Toda função precisa ser acessível através de:

**PAINEL FIXO → BOTÃO → SELECT → MODAL.**

---

# 94. ENTREGA FINAL

Ao finalizar cada fase, informe:

### O que foi implementado

### O que foi corrigido

### Arquivos alterados

### Alterações no banco

### Testes executados

### Problemas encontrados

### Pendências

Não diga que uma função está pronta se ela não foi realmente implementada e testada.

---

# REGRA FINAL

Você já possui acesso ao repositório.

Não peça novamente o projeto.

Não produza apenas documentação.

Analise o código existente e trabalhe diretamente nele.

O resultado final deverá ser um bot da **CHOQUE - BGR** focado exclusivamente em gestão dentro do Discord, com:

* bate ponto por call;
* controle de horas;
* cadastro de membros;
* status;
* ausências;
* retornos automáticos;
* solicitações;
* promoções;
* rebaixamentos;
* advertências;
* suspensões;
* treinamentos;
* cursos;
* atividade semanal;
* relatórios;
* auditoria;
* configurações;

tudo operado através de **mensagens fixas, botões, selects e modais**, sem necessidade de utilizar qualquer comando.
