# CONTEXTO

Este prompt é **COMPLEMENTAR aos prompts anteriores do projeto CHOQUE - BGR**.

Você já possui acesso ao repositório e já recebeu anteriormente as regras gerais de:

* arquitetura;
* QA;
* banco de dados;
* sistema de membros;
* sistema de ponto;
* calls autorizadas;
* tempo mínimo de patrulha;
* cadastro;
* patentes;
* sincronização automática de cargos;
* nickname `[PATENTE] NICK [ID]`;
* ausências;
* solicitações;
* treinamentos;
* disciplina;
* relatórios;
* auditoria;
* painéis fixos;
* mensagens ephemeral;
* permissões;
* configurações;
* recuperação após restart.

NÃO substitua nem remova essas funcionalidades.

Este prompt adiciona novos módulos ao sistema existente.

# REGRA ABSOLUTA DE UX

Continuam valendo todas as regras anteriores:

# NÃO UTILIZAR COMANDOS.

Não criar:

* slash commands;
* prefix commands;
* comandos por mensagem;
* fluxos dependentes de texto digitado em chat.

Todas as novas funcionalidades deverão funcionar através de:

**MENSAGENS FIXAS → BOTÕES → SELECT MENUS → MODAIS → AUTOMAÇÕES**

Sempre que possível, utilizar respostas ephemeral para não poluir canais.

---

# 1. OBJETIVO DESTA EXPANSÃO

Adicionar os seguintes módulos:

1. Central de Patrulha Inteligente;
2. Fila Automática de Formação de Patrulha;
3. Validação Inteligente de Ponto;
4. Painel de Prontidão do Efetivo;
5. Sistema de Disponibilidade;
6. Troca de Escala/Atividade entre Membros;
7. Matriz de Qualificação;
8. Requisitos Automáticos para Cursos;
9. Painel de Elegibilidade de Promoção;
10. Dossiê Funcional Resumido;
11. Sistema de Acompanhamento de Recrutas;
12. Avaliação Pós-Treinamento;
13. Feedback Privado Pós-Patrulha;
14. Caixa de Entrada Administrativa;
15. Histórico de Decisões;
16. Detecção de Membros Esquecidos/Inconsistentes;
17. Central de Identidade Automática;
18. Histórico de Patrulhas do Membro;
19. Modo de Manutenção da Corporação;
20. Painel "O que mudou?".

Todos devem se integrar aos sistemas já existentes sem duplicar regras de negócio.

---

# 2. CENTRAL DE PATRULHA INTELIGENTE

Criar um painel fixo chamado:

# CENTRAL DE PATRULHA

Exemplo visual:

```text
CHOQUE - BGR
CENTRAL DE PATRULHA

Gerencie sua disponibilidade e acompanhe as patrulhas em andamento.

[ ENTRAR NA FILA ]

[ SAIR DA FILA ]

[ MINHA PATRULHA ]

[ PATRULHAS ATIVAS ]
```

O painel deve ser simples.

O membro não cria uma patrulha manualmente.

O sistema forma automaticamente uma patrulha quando os requisitos forem atingidos.

---

# 3. FILA DE FORMAÇÃO DE PATRULHA

Criar uma call específica:

```text
Aguardando Patrulha
```

Essa call deverá ser configurável.

O membro entra nessa call e pode também marcar disponibilidade pelo painel.

O sistema deverá monitorar a call.

## REGRA PRINCIPAL

Quando existirem pelo menos:

```text
2 membros
```

válidos dentro da call de espera:

o sistema poderá formar automaticamente uma patrulha.

---

# 4. VALIDAÇÕES ANTES DE FORMAR PATRULHA

Antes de utilizar os membros da fila, verificar:

* membro cadastrado;
* status ATIVO;
* não está AUSENTE;
* não está SUSPENSO;
* não está RESERVA quando reserva impedir serviço;
* possui patente válida;
* possui nickname sincronizado;
* possui cargo de membro;
* não está em outra patrulha ativa;
* não está em treinamento;
* não está em outro processo incompatível;
* está realmente conectado à call de espera.

Membro inválido não deve ser utilizado na formação.

---

# 5. QUANTIDADE MÍNIMA

Por padrão:

```text
MIN_PATROL_MEMBERS = 2
```

Deixar configurável.

Inicialmente usar:

```text
2 membros
```

Não hardcodar esse valor dentro do listener de voz.

---

# 6. LOCALIZAR CALL DE PATRULHA LIVRE

Quando houver membros suficientes:

buscar uma call configurada como:

```text
PATRULHA_ATIVA
```

Exemplos:

```text
Patrulha 1
Patrulha 2
Patrulha 3
Patrulha 4
Patrulha 5
Patrulha 6
```

Considerar uma call disponível quando:

* estiver vazia;
* estiver habilitada;
* não estiver reservada;
* não possuir patrulha ativa associada.

Selecionar a primeira call disponível de acordo com ordem configurada.

---

# 7. MOVIMENTAÇÃO AUTOMÁTICA

Exemplo:

```text
Aguardando Patrulha

João
Pedro
```

O bot detecta 2 membros válidos.

Encontra:

```text
Patrulha 1
```

vazia.

Resultado:

```text
João → Patrulha 1
Pedro → Patrulha 1
```

Criar automaticamente:

```text
Patrulha #00091
```

Registrar:

* participantes;
* call;
* início;
* origem automática;
* horário;
* responsável pelo sistema;
* status.

---

# 8. NÃO FORMAR DUAS PATRULHAS COM OS MESMOS MEMBROS

A formação precisa ser transacional/idempotente.

Proteger contra:

* dois eventos de voiceStateUpdate simultâneos;
* dois workers;
* entrada simultânea de vários membros;
* duas rotinas selecionando a mesma call;
* clique + evento de voz ao mesmo tempo.

Uma pessoa nunca pode participar de duas patrulhas ativas.

Uma call nunca pode possuir duas patrulhas ativas.

---

# 9. FILA COM MAIS DE DUAS PESSOAS

Exemplo:

```text
Aguardando Patrulha

João
Pedro
Lucas
Marcos
Carlos
```

Com mínimo de 2:

o sistema poderá formar:

```text
Patrulha 1
João + Pedro
```

e:

```text
Patrulha 2
Lucas + Marcos
```

Carlos permanece aguardando.

Não formar patrulha individual com Carlos.

---

# 10. ORDEM DA FILA

Utilizar ordem de entrada.

Registrar:

```text
queueEnteredAt
```

Membros que chegaram primeiro devem ter preferência.

Não reorganizar arbitrariamente.

---

# 11. SAÍDA DA FILA

Se membro sair da call de espera antes da formação:

remover automaticamente da fila.

Não manter membro fantasma.

---

# 12. FALHA AO MOVER MEMBRO

Se o bot não possuir permissão para mover:

* não criar patrulha parcialmente;
* registrar erro;
* manter membros na fila quando possível;
* informar no painel administrativo;
* evitar loop infinito.

---

# 13. PAINEL DE PATRULHAS ATIVAS

Criar mensagem fixa atualizada automaticamente:

```text
PATRULHAS ATIVAS

Patrulha 1
2 membros
42min

Patrulha 2
3 membros
18min

Patrulha 3
Disponível

Patrulha 4
Disponível
```

Não atualizar a cada segundo.

Atualizar em eventos relevantes.

---

# 14. INTEGRAÇÃO COM O BATE PONTO

Formar uma patrulha NÃO deve automaticamente fabricar horas.

O sistema de ponto existente continua sendo a fonte das horas.

Caso a política definida no projeto determine que o ponto inicia manualmente pelo botão:

continue assim.

A patrulha apenas representa agrupamento operacional em call.

---

# 15. TEMPO MÍNIMO DE 15 MINUTOS

Integrar com a regra existente:

```text
tempo mínimo de patrulha = 15 minutos
```

Tempo dentro de calls marcadas como `PATRULHA_ATIVA` conta para esse requisito.

Call:

```text
Aguardando Patrulha
```

NÃO conta.

---

# 16. ENCERRAMENTO DA PATRULHA

A patrulha deverá ser encerrada quando:

* todos os membros saírem da call;
* superior encerrar via painel;
* call deixar de ser válida;
* manutenção obrigar encerramento.

Não encerrar apenas porque um dos dois membros saiu, se ainda houver integrante.

Caso reste apenas uma pessoa, criar uma política configurável:

```text
continueUntilEmpty = true
```

ou:

```text
closeWhenBelowMinimum = true
```

Por padrão, prefira manter a patrulha até a call ficar vazia para evitar encerramentos acidentais.

---

# 17. SISTEMA DE DISPONIBILIDADE

Adicionar status operacional temporário.

Estados:

```text
DISPONÍVEL PARA PATRULHA
INDISPONÍVEL
EM PATRULHA
EM TREINAMENTO
AUSENTE
```

Não confundir isso com status administrativo do membro.

Exemplo:

```text
status administrativo = ATIVO
status operacional = DISPONÍVEL
```

---

# 18. PAINEL DE DISPONIBILIDADE

Na Central do Membro:

```text
MINHA DISPONIBILIDADE

[ DISPONÍVEL PARA PATRULHA ]

[ INDISPONÍVEL ]
```

Se estiver em treinamento ou suspenso:

o sistema sobrescreve logicamente a disponibilidade quando necessário.

---

# 19. PAINEL DE PRONTIDÃO DO EFETIVO

Criar painel fixo resumido:

```text
PRONTIDÃO DO EFETIVO

Em Patrulha
14

Aguardando Patrulha
5

Disponíveis
8

Em Treinamento
3

Ausentes
6

Suspensos
1
```

Não expor dados administrativos sensíveis publicamente.

Permitir versão pública resumida e versão administrativa detalhada.

---

# 20. VALIDAÇÃO INTELIGENTE DE PONTO

Expandir o sistema já existente de validação.

Não aplicar punições automaticamente.

Criar um mecanismo para identificar padrões suspeitos ou inconsistentes.

Exemplos:

* muitos pontos invalidados;
* sessões repetidamente abaixo de 15 minutos;
* entradas e saídas excessivas;
* múltiplos pontos muito curtos;
* sessão com comportamento incomum;
* alterações administrativas frequentes;
* grande divergência entre tempo bruto e tempo válido.

---

# 21. SCORE NÃO PUNITIVO DE ATENÇÃO

Não criar "score criminal" ou punição oculta.

Criar apenas flags administrativas.

Exemplo:

```text
PONTO #0192

Status:
Válido

Observação automática:
⚠ Padrão incomum detectado

Motivo:
4 sessões invalidadas nos últimos 7 dias.
```

Essas flags servem apenas para revisão humana.

---

# 22. FLAGS POSSÍVEIS

Exemplos:

```text
MANY_INVALID_SHIFTS
SHORT_SHIFT_PATTERN
FREQUENT_VOICE_DISCONNECTS
MANUAL_ADJUSTMENT_FREQUENCY
UNUSUAL_SESSION_PATTERN
```

O sistema deve informar exatamente por que criou a flag.

---

# 23. TROCA DE ESCALA / ATIVIDADE ENTRE MEMBROS

Adicionar na Central de Solicitações:

```text
TROCA DE ATIVIDADE
```

Fluxo:

```text
Membro A
↓
Seleciona atividade/escala
↓
Seleciona Membro B
↓
Informa motivo
↓
Membro B recebe solicitação
↓
Aceita / Recusa
↓
Se aceitar, comando analisa quando necessário
```

---

# 24. NUNCA TROCAR SEM CONSENTIMENTO

Membro B precisa aceitar.

Depois, dependendo do tipo de atividade:

pode exigir aprovação do comando.

Estados:

```text
AGUARDANDO_MEMBRO
AGUARDANDO_COMANDO
APROVADA
NEGADA
CANCELADA
```

---

# 25. MATRIZ DE QUALIFICAÇÃO

Criar visão organizada das qualificações do membro.

Exemplo:

```text
MATRIZ DE QUALIFICAÇÃO — JOÃO

Formação
✅

Patrulhamento
✅

Choque
✅

Instrutor
❌

Recrutador
✅

Operações Aéreas
❌
```

A lista deve vir dos cursos/qualificações configurados no sistema.

---

# 26. MATRIZ ADMINISTRATIVA

Permitir ao comando visualizar vários membros.

Exemplo:

```text
                Formação  Choque  Instrutor
João               ✅       ✅       ❌
Pedro              ✅       ✅       ✅
Lucas              ✅       ❌       ❌
```

Caso não caiba bem no Discord, utilizar páginas individuais ou filtros.

Não criar embeds ilegíveis.

---

# 27. REQUISITOS AUTOMÁTICOS PARA CURSOS

Cada curso poderá possuir requisitos configuráveis.

Exemplos:

* patente mínima;
* horas mínimas;
* curso anterior;
* status ATIVO;
* tempo mínimo na corporação;
* ausência de suspensão;
* qualificação específica.

---

# 28. VALIDAÇÃO AO SE INSCREVER

Quando membro clicar:

```text
PARTICIPAR DO TREINAMENTO
```

o sistema verifica requisitos automaticamente.

Exemplo aprovado:

```text
REQUISITOS

Patente mínima
✅

10 horas de serviço
✅

Formação concluída
✅

Status ativo
✅

Você está apto a participar.
```

---

# 29. REQUISITO NÃO CUMPRIDO

Exemplo:

```text
Você ainda não atende todos os requisitos.

Patente mínima
✅

10 horas de serviço
❌ 7h31

Formação
✅
```

Não permitir inscrição.

Explicar o que falta.

---

# 30. PAINEL DE ELEGIBILIDADE DE PROMOÇÃO

Criar painel administrativo:

```text
ANÁLISE DE PROMOÇÃO
```

Superior seleciona membro.

O sistema apresenta:

```text
João

Patente atual
Soldado

Tempo na patente
31 dias ✅

Horas mínimas
42h / 30h ✅

Cursos obrigatórios
3 / 3 ✅

Meta recente
✅

Advertências bloqueantes
0 ✅

Situação
ELEGÍVEL
```

---

# 31. NÃO PROMOVER AUTOMATICAMENTE

A análise serve apenas como suporte.

Resultado possível:

```text
ELEGÍVEL
```

ou:

```text
REQUISITOS PENDENTES
```

Nunca transformar isso em promoção automática.

---

# 32. DOSSIÊ FUNCIONAL RESUMIDO

Criar uma das funções principais do painel administrativo.

Botão:

```text
DOSSIÊ DO MEMBRO
```

Após selecionar membro, mostrar resumo em uma ou mais páginas ephemeral.

---

# 33. CONTEÚDO DO DOSSIÊ

Incluir de forma organizada:

```text
IDENTIFICAÇÃO

Nome
Discord
ID
Patente
Status
Data de ingresso
```

```text
ATIVIDADE

Horas semanais
Horas mensais
Horas totais
Última patrulha
Número de patrulhas
Pontos invalidados
```

```text
CARREIRA

Patente atual
Tempo na patente
Promoções anteriores
Rebaixamentos
```

```text
QUALIFICAÇÕES

Cursos concluídos
Cursos pendentes
```

```text
DISCIPLINA

Advertências ativas
Advertências históricas
Suspensões
```

```text
ADMINISTRATIVO

Ausências recentes
Solicitações pendentes
Última alteração importante
```

Não mostrar informações às quais o usuário não tem permissão.

---

# 34. SISTEMA DE ACOMPANHAMENTO DE RECRUTAS

Membros com patente/status configurado como recruta devem possuir acompanhamento próprio.

Painel:

```text
ACOMPANHAMENTO DE RECRUTAS

Recrutas ativos
12

[ VER RECRUTAS ]

[ PENDÊNCIAS ]

[ AVALIAÇÕES ]
```

---

# 35. PERFIL DO RECRUTA

Exemplo:

```text
RECRUTA JOÃO

Ingresso
18/08

Tempo como recruta
4 dias

Horas
7h21

Patrulhas
6

Formação
✅

Treinamento obrigatório
2 / 3

Avaliações
1 / 2

Advertências
0
```

---

# 36. REQUISITOS DE EFETIVAÇÃO

Configurar requisitos simples.

Exemplo:

* X dias;
* X horas;
* cursos obrigatórios;
* X avaliações;
* nenhuma pendência crítica.

O sistema apenas mostra:

```text
APTO PARA ANÁLISE
```

Não efetivar automaticamente.

---

# 37. AVALIAÇÃO PÓS-TREINAMENTO

Quando treinamento for finalizado:

o responsável deverá receber opção:

```text
FINALIZAR E AVALIAR
```

Selecionar participante.

Depois registrar:

```text
Presença
Aprovado / Reprovado
Desempenho
Observação
```

---

# 38. AVALIAÇÃO SIMPLES

Não criar formulários gigantes.

Sugestão:

```text
Resultado:
Aprovado / Reprovado

Desempenho:
Ótimo
Bom
Regular
Insuficiente

Observação:
opcional
```

---

# 39. ATUALIZAÇÃO AUTOMÁTICA DE QUALIFICAÇÃO

Caso aprovado:

* adicionar curso/qualificação;
* atualizar matriz;
* atualizar histórico;
* registrar instrutor;
* registrar data.

---

# 40. FEEDBACK PRIVADO PÓS-PATRULHA

Ao encerrar uma patrulha, permitir que o responsável pela patrulha registre um feedback interno.

Isso NÃO é advertência.

Não mostrar publicamente.

---

# 41. FLUXO DO FEEDBACK

Após encerramento:

```text
PATRULHA ENCERRADA

Deseja registrar feedback da equipe?

[ REGISTRAR FEEDBACK ]

[ IGNORAR ]
```

---

# 42. FEEDBACK INDIVIDUAL

Selecionar membro.

Campos simples:

```text
Avaliação:
Positiva
Neutra
Necessita atenção

Observação:
opcional
```

Evitar notas excessivamente detalhadas.

---

# 43. PRIVACIDADE DO FEEDBACK

Feedback pós-patrulha deverá ser visível apenas para cargos administrativos autorizados.

Não mostrar diretamente ao membro salvo se houver regra específica.

Não transformar automaticamente em punição.

---

# 44. HISTÓRICO DE FEEDBACK

Dossiê administrativo pode mostrar:

```text
Últimos feedbacks

21/08
Positivo
"Boa comunicação durante patrulha."

19/08
Necessita atenção
"Precisa melhorar organização."
```

Sempre mostrar autor e data para administradores autorizados.

---

# 45. CAIXA DE ENTRADA ADMINISTRATIVA

Criar um painel central que reúna tudo que necessita de decisão humana.

Esse módulo é prioritário.

Mensagem fixa:

```text
CHOQUE - BGR
CAIXA DE ENTRADA ADMINISTRATIVA

Ausências pendentes
5

Correções de ponto
2

Trocas de atividade
3

Cadastros pendentes
1

Revisões disciplinares
2

Avaliações pendentes
4

[ ABRIR CAIXA DE ENTRADA ]
```

---

# 46. FILTROS DA CAIXA DE ENTRADA

Ao abrir:

```text
[ TODAS ]

[ SOLICITAÇÕES ]

[ PONTO ]

[ MEMBROS ]

[ DISCIPLINA ]

[ TREINAMENTOS ]
```

Mostrar itens paginados.

---

# 47. ITEM DA CAIXA DE ENTRADA

Exemplo:

```text
#REQ-00291

Tipo
Ausência

Membro
João

Criado
há 2 horas

Prioridade
Normal

[ ANALISAR ]

[ VER MEMBRO ]
```

---

# 48. NÃO DUPLICAR SOLICITAÇÕES

A caixa de entrada não cria novos dados.

Ela é apenas uma visão unificada dos módulos existentes.

Exemplo:

```text
AbsenceRequest
```

continua pertencendo ao sistema de ausência.

A inbox apenas referencia.

---

# 49. HISTÓRICO DE DECISÕES

Criar painel administrativo:

```text
HISTÓRICO DE DECISÕES
```

Permitir consultar:

* aprovações;
* negações;
* promoções;
* rebaixamentos;
* alterações de ponto;
* suspensões;
* desligamentos;
* revisões;
* alterações administrativas.

---

# 50. DADOS DA DECISÃO

Cada decisão deve mostrar:

```text
Ação
Responsável
Membro afetado
Data
Motivo
Estado anterior
Estado posterior
ID de auditoria
```

Não apagar decisões antigas.

---

# 51. DETECÇÃO DE MEMBROS ESQUECIDOS / INCONSISTENTES

Criar um serviço de integridade.

Ele deverá identificar casos como:

* membro cadastrado sem cargo de patente;
* membro com duas patentes;
* nickname fora do padrão;
* membro desligado ainda com cargos;
* ausência encerrada ainda marcada como ativa;
* suspensão vencida;
* membro ativo sem cargo de membro;
* patente no banco diferente do cargo;
* membro sem ID;
* ponto ativo inconsistente;
* solicitação pendente há tempo excessivo.

---

# 52. NÃO CORRIGIR TUDO ÀS CEGAS

Classificar inconsistências:

```text
AUTO_FIX_SAFE
REQUIRES_REVIEW
```

Exemplo:

Nickname incorreto:

```text
AUTO_FIX_SAFE
```

Duas patentes:

```text
REQUIRES_REVIEW
```

dependendo da configuração.

---

# 53. PAINEL DE INTEGRIDADE

```text
INTEGRIDADE DO EFETIVO

Problemas encontrados
8

Corrigíveis automaticamente
5

Necessitam revisão
3

[ VER PROBLEMAS ]

[ CORRIGIR SEGUROS ]
```

---

# 54. CENTRAL DE IDENTIDADE AUTOMÁTICA

Expandir o sistema de nickname e cargo já definido anteriormente.

Criar painel:

```text
CENTRAL DE IDENTIDADE

Nicknames incorretos
4

Patentes divergentes
2

Membros sem ID
1

Cargos inconsistentes
3

[ ANALISAR ]

[ SINCRONIZAR ]
```

---

# 55. NÃO DUPLICAR A REGRA DE NICKNAME

Continuar utilizando obrigatoriamente o formatador existente:

```text
[ABREVIAÇÃO] NICK [ID]
```

Exemplo:

```text
[RCT] João [152]
```

A Central de Identidade apenas gerencia e audita essa sincronização.

---

# 56. SINCRONIZAÇÃO EM LOTE

Permitir:

```text
SINCRONIZAR IDENTIDADES
```

Antes de executar, apresentar:

```text
4 nicknames serão corrigidos
2 patentes serão sincronizadas
1 membro continuará pendente

[ CONFIRMAR ]
```

Somente corrigir operações consideradas seguras.

---

# 57. HISTÓRICO DE PATRULHAS DO MEMBRO

Expandir o histórico atual de pontos.

Mostrar também estatísticas específicas de patrulha.

Exemplo:

```text
HISTÓRICO DE PATRULHAS — JOÃO

Patrulhas totais
48

Tempo total em patrulha
72h31

Duração média
1h30

Maior patrulha
3h42

Pontos válidos
46

Pontos invalidados
2

Última patrulha
21/08
```

---

# 58. LISTA DE PATRULHAS

Permitir paginação:

```text
#00481
21/08
1h42
Patrulha 2
Válida

#00472
20/08
58min
Patrulha 1
Válida

#00463
20/08
11min
Patrulha 3
Invalidada
```

---

# 59. DETALHES DA PATRULHA

Ao selecionar:

mostrar:

* início;
* fim;
* duração;
* call;
* integrantes;
* segmentos;
* ponto associado;
* status;
* feedback existente, se tiver permissão.

---

# 60. MODO DE MANUTENÇÃO DA CORPORAÇÃO

Criar painel administrativo:

```text
MODO DE MANUTENÇÃO
```

Permitir desabilitar temporariamente módulos específicos.

Exemplo:

```text
Bate Ponto
ATIVO

Cadastro
ATIVO

Patrulhas
ATIVO

Treinamentos
MANUTENÇÃO
```

---

# 61. MANUTENÇÃO POR MÓDULO

Não precisa desligar o bot inteiro.

Exemplo:

```text
Treinamentos
MANUTENÇÃO
Motivo:
Ajustes internos

Previsão:
Não informada
```

Quando membro clicar:

```text
O módulo de Treinamentos está temporariamente em manutenção.

Motivo:
Ajustes internos.
```

---

# 62. NÃO AFETAR AÇÕES JÁ EM ANDAMENTO SEM NECESSIDADE

Se colocar:

```text
PATRULHAS = manutenção
```

definir política clara.

Por padrão:

* impedir novas patrulhas;
* não encerrar patrulhas existentes automaticamente.

Para ações destrutivas, exigir confirmação adicional.

---

# 63. PAINEL "O QUE MUDOU?"

Criar resumo administrativo de alterações importantes em determinado período.

Painel:

```text
O QUE MUDOU?

Período:
Últimos 7 dias

Novos membros
8

Promoções
5

Rebaixamentos
1

Ausências
4

Retornos
3

Advertências
2

Suspensões
1

Cursos concluídos
19

Horas de patrulha
217h

Pontos invalidados
6
```

---

# 64. FILTRO DE PERÍODO

Permitir:

```text
HOJE
7 DIAS
30 DIAS
PERÍODO PERSONALIZADO
```

Período personalizado via modal.

---

# 65. DETALHES DO "O QUE MUDOU?"

Botões:

```text
[ MEMBROS ]

[ CARREIRA ]

[ DISCIPLINA ]

[ ATIVIDADE ]

[ TREINAMENTOS ]
```

Cada botão abre detalhes ephemeral.

---

# 66. SISTEMA DE EVENTOS INTERNOS

Os novos módulos devem reutilizar serviços/eventos existentes.

Exemplo:

```text
PATROL_CREATED
PATROL_FINISHED
MEMBER_AVAILABILITY_CHANGED
TRAINING_EVALUATED
IDENTITY_RECONCILED
ADMIN_DECISION_CREATED
```

Não criar listeners desorganizados espalhados.

---

# 67. AUDITORIA

Gerar audit log para ações relevantes.

Exemplos:

```text
PATROL_AUTO_CREATED
PATROL_AUTO_FINISHED
PATROL_MEMBER_MOVED
AVAILABILITY_CHANGED
SHIFT_FLAGGED
ACTIVITY_SWAP_APPROVED
TRAINING_EVALUATED
IDENTITY_BULK_SYNC
MAINTENANCE_ENABLED
MAINTENANCE_DISABLED
```

---

# 68. NÃO POLUIR LOG

Eventos triviais de interface não precisam virar log administrativo.

Exemplo:

não registrar:

```text
João abriu a página 2.
```

Registrar apenas ações relevantes.

---

# 69. PERMISSÕES

Adicionar permissões específicas quando necessário.

Exemplo:

```text
patrol.view
patrol.manage

readiness.view
readiness.view.admin

qualification.view
qualification.manage

promotion.evaluate

member.dossier.view

recruit.followup

training.evaluate

patrol.feedback.create
patrol.feedback.view

admin.inbox.view
admin.inbox.manage

decision.history.view

integrity.view
integrity.fix

identity.manage

maintenance.manage

changes.view
```

---

# 70. PRIVACIDADE

Informações como:

* disciplina;
* feedback privado;
* histórico administrativo;
* dossiê completo;

não podem ficar disponíveis para qualquer membro.

Aplicar RBAC no backend.

Não confiar apenas no fato de o painel estar em canal privado.

---

# 71. PERFORMANCE DA FILA DE PATRULHA

Não utilizar polling a cada segundo para verificar a call.

Preferir:

```text
voiceStateUpdate
```

ou evento equivalente da biblioteca atual.

Ao entrar/sair:

recalcular estado da fila.

---

# 72. DEBOUNCE DA FILA

Entradas simultâneas podem gerar múltiplos eventos.

Criar pequena proteção para evitar:

```text
Evento 1 → forma patrulha
Evento 2 → tenta formar novamente
```

O processo precisa ser seguro.

---

# 73. LOCK DE FORMAÇÃO

Durante a seleção de membros e call:

utilizar mecanismo que evite concorrência.

Conceitualmente:

```text
PatrolFormationLock
```

Adapte à stack atual.

---

# 74. NÃO PRENDER MEMBROS EM CALL

Caso mover um membro falhe:

não ficar tentando a cada segundo.

Registrar falha e aguardar novo evento ou ação administrativa.

---

# 75. CALL DE PATRULHA INDISPONÍVEL

Se houver 4 membros aguardando, mas nenhuma call disponível:

manter fila.

Painel pode mostrar:

```text
4 membros aguardando patrulha.

Nenhuma call disponível no momento.
```

Quando uma call ficar vazia:

tentar formar automaticamente.

---

# 76. FEEDBACK DA FORMAÇÃO AUTOMÁTICA

Ao mover os membros:

enviar resposta/notificação discreta quando tecnicamente adequado.

Não criar spam público.

Exemplo por DM ou painel:

```text
Sua patrulha foi formada automaticamente.

Call:
Patrulha 2

Integrantes:
João
Pedro
```

DM deve ser opcional/configurável.

---

# 77. TESTES — FILA DE PATRULHA

Testar:

### 1 pessoa na fila

Esperado:

```text
Nenhuma patrulha formada.
```

### 2 pessoas

Esperado:

```text
Patrulha formada.
```

### 3 pessoas

Esperado:

```text
2 movidos
1 permanece
```

### 4 pessoas

Esperado:

```text
2 patrulhas, caso existam 2 calls livres.
```

### Nenhuma call livre

Esperado:

```text
todos aguardam
```

### Um membro inválido + um válido

Esperado:

```text
não formar patrulha
```

### Bot sem Move Members

Esperado:

```text
falha controlada
```

---

# 78. TESTES — VALIDAÇÃO INTELIGENTE

Testar:

* 1 ponto inválido;
* vários pontos inválidos;
* sessão normal;
* desconexões;
* alteração manual;
* ausência de padrão suspeito.

Não flaggar usuários normais sem motivo.

---

# 79. TESTES — QUALIFICAÇÃO

Testar:

* curso sem requisito;
* patente insuficiente;
* horas insuficientes;
* curso prévio faltando;
* todos os requisitos cumpridos.

---

# 80. TESTES — PROMOÇÃO

Verificar que:

```text
Elegível
```

não executa promoção.

É apenas informação administrativa.

---

# 81. TESTES — DOSSIÊ

Validar permissão.

Membro comum nunca deve conseguir acessar dossiê administrativo de outro membro.

---

# 82. TESTES — FEEDBACK PRIVADO

Validar que feedback não aparece:

* em perfil público;
* para cargo sem autorização;
* em canais públicos.

---

# 83. TESTES — CAIXA DE ENTRADA

Validar:

* item aparece;
* item processado desaparece de pendentes;
* dado original permanece no módulo correto;
* dois admins não processam a mesma solicitação simultaneamente.

---

# 84. TESTES — IDENTIDADE

Reutilizar testes definidos no prompt anterior de sincronização:

* cargo manual;
* promoção;
* rebaixamento;
* nickname errado;
* duas patentes;
* restart.

A Central de Identidade não substitui o sincronizador já existente.

---

# 85. TESTES — MANUTENÇÃO

Testar:

* módulo ativo;
* ativar manutenção;
* membro tentar usar;
* retirar manutenção;
* ações existentes não serem destruídas.

---

# 86. INTEGRAÇÃO COM PAINÉIS EXISTENTES

Não criar um novo canal para cada função.

Agrupar.

Exemplo:

## Central do Membro

Adicionar:

```text
[ DISPONIBILIDADE ]
[ MINHAS PATRULHAS ]
```

## Central do Comando

Adicionar:

```text
[ CAIXA DE ENTRADA ]
[ PRONTIDÃO ]
[ DOSSIÊ ]
[ INTEGRIDADE ]
[ O QUE MUDOU? ]
```

## Treinamentos

Adicionar:

```text
[ MATRIZ DE QUALIFICAÇÃO ]
```

## Carreira

Adicionar:

```text
[ ANALISAR PROMOÇÃO ]
```

---

# 87. EVITAR EXCESSO DE BOTÕES

Discord possui limites de componentes.

Não colocar 20 botões em uma única mensagem.

Utilizar hierarquia:

```text
Painel principal
↓
Categoria
↓
Submenu ephemeral
```

---

# 88. NÃO CRIAR CANAIS DESNECESSÁRIOS

Estas funcionalidades são principalmente sistemas internos do bot.

Não criar:

```text
#dossies
#feedbacks
#qualificacoes
#trocas
#integridade
```

sem necessidade.

Preferir painéis e menus.

---

# 89. NÃO DUPLICAR DADOS

Exemplo:

qualificação do membro deve vir do sistema de cursos existente.

Não criar:

```text
memberQualifications
```

se o próprio relacionamento de cursos já responde isso adequadamente.

Faça agregação quando possível.

---

# 90. DEFINITION OF DONE

Cada módulo deste prompt somente está pronto quando possuir:

* UI por painel;
* botões/selects/modais;
* permissões;
* regras;
* persistência;
* auditoria;
* integração com sistemas existentes;
* proteção contra duplicação;
* tratamento de falhas;
* restart quando aplicável;
* testes.

---

# 91. PRIORIZAÇÃO DESTA EXPANSÃO

Implemente nesta ordem:

## FASE A — PATRULHA

1. Sistema de disponibilidade;
2. Fila de espera;
3. Formação automática com mínimo de 2;
4. Movimentação para call livre;
5. Central de Patrulha;
6. Histórico de patrulhas;
7. Feedback pós-patrulha.

## FASE B — VISÃO OPERACIONAL

8. Painel de prontidão;
9. Validação inteligente de ponto;
10. Detecção de inconsistências;
11. Central de identidade.

## FASE C — DESENVOLVIMENTO DO MEMBRO

12. Matriz de qualificação;
13. Requisitos de cursos;
14. Avaliação pós-treinamento;
15. Acompanhamento de recrutas;
16. Elegibilidade de promoção;
17. Dossiê.

## FASE D — ADMINISTRAÇÃO

18. Caixa de entrada;
19. Troca de atividade;
20. Histórico de decisões;
21. Painel O que mudou?;
22. Modo de manutenção.

---

# 92. NÃO ALTERAR REGRAS ANTERIORES

Este prompt não autoriza remover ou modificar sem necessidade:

* ponto por call;
* mínimo de 15 minutos;
* nickname automático;
* sincronização por cargos;
* sistema de ausência;
* auditoria;
* painéis fixos;
* zero comandos;
* permissões existentes.

Integre.

Não substitua.

---

# 93. REGRA FINAL DE FILA DE PATRULHA

A funcionalidade mais importante adicionada neste prompt deverá obedecer exatamente:

```text
MEMBRO ENTRA EM "AGUARDANDO PATRULHA"
↓
SISTEMA VALIDA O MEMBRO
↓
ENTRA NA FILA
↓
EXISTEM PELO MENOS 2 MEMBROS VÁLIDOS?
```

Se NÃO:

```text
CONTINUA AGUARDANDO
```

Se SIM:

```text
LOCALIZAR CALL DE PATRULHA VAZIA
↓
RESERVAR CALL
↓
SELECIONAR OS 2 PRIMEIROS DA FILA
↓
CRIAR REGISTRO DA PATRULHA
↓
MOVER OS DOIS PARA A CALL
↓
REMOVER DA FILA
↓
ATUALIZAR PAINÉIS
```

Se nenhuma call estiver vazia:

```text
MANTER NA FILA
```

Assim que uma call ficar disponível:

```text
TENTAR FORMAÇÃO NOVAMENTE
```

Tudo deve funcionar automaticamente através dos eventos do Discord.

---

# 94. FILOSOFIA FINAL

Esses novos módulos devem tornar o bot mais inteligente sem transformá-lo em um sistema que toma decisões disciplinares sozinho.

O bot deve:

**detectar → organizar → informar → automatizar tarefas previsíveis → registrar**

O comando deve:

**avaliar → decidir**

O membro deve:

**interagir por painéis simples**

O resultado deve continuar parecendo uma aplicação administrativa própria da **CHOQUE - BGR**, construída dentro do Discord e totalmente integrada às funcionalidades já implementadas pelos prompts anteriores.
