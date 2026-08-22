# Sistema de Alistamento, Recrutamento e Integridade — CHOQUE BGR

Status: **IMPLEMENTADO LOCALMENTE E VALIDADO EM 2026-08-22**.

Evidência principal: migration v17, `choque/recruitment.py`, endpoints candidatos e administrativos
em `command_center/app.py`, portal Next.js em `web/src/app/recrutamento`, outbox Discord,
RLS default-deny para o futuro Supabase, 169 testes Python, 16 testes Vitest e 6 cenários E2E.
O processo permanece em `DRAFT` por segurança até abertura humana; nenhum candidato real foi
enviado ao Lovable ou a provedores externos.

Posição: depois do Programa Centro de Comando Web e antes do Security Hardening final.

Fonte: especificação complementar recebida em 2026-08-22 e preservada integralmente abaixo.

## Regras de entrada e integração

- O bot atual já possui um fluxo básico de candidatura, transferência e análise administrativa em
  `choque/tickets.py` e `cogs/ticket_commands.py`. Reutilizar/migrar esse domínio; não criar um
  segundo recrutamento paralelo.
- O estado atual não possui site, API, OAuth, Supabase/PostgreSQL ou Railway. As referências a essas
  camadas abaixo são arquitetura-alvo dependente do Centro de Comando Web.
- Executar as oito subfases da especificação: Domínio, Candidato, Avaliação, Integração, Admin,
  Processo Seletivo, Ingresso e Hardening específico.
- Usar integralmente a skill de frontend design antes de implementar qualquer tela.
- Usar Lovable em modo de planejamento, prototipação e refinamento das telas públicas e
  administrativas; revisar diffs antes de integrar ao repositório principal.
- Nunca enviar ao Lovable questões sigilosas de produção, respostas reais, dados pessoais, tokens,
  cookies, dumps ou secrets. Fixtures devem ser sintéticas e identificadas.
- A proteção anti-copy/paste e telemetria de foco são sinais de integridade, não prova de fraude nem
  base para reprovação automática. A decisão permanece humana.
- Preservar idempotência, optimistic locking, snapshots/versionamento de formulário, timer
  server-side, outbox Discord, RBAC, RLS e auditoria.
- O Security Hardening completo permanece depois desta fase para auditar todo o fluxo novo.
- Atualizar `PROJECT_HANDOFF.md` e `docs/PHASE_QUEUE.md` ao concluir cada subfase.

## Especificação recebida

# PROMPT COMPLEMENTAR CONSOLIDADO

# SISTEMA DE ALISTAMENTO, RECRUTAMENTO E INTEGRIDADE — CHOQUE BGR

Este prompt é **COMPLEMENTAR a todos os prompts anteriores do projeto CHOQUE - BGR**.

Você já possui acesso ao repositório completo e conhece toda a arquitetura definida anteriormente.

NÃO recomece o projeto.

NÃO substitua módulos existentes.

NÃO crie versões paralelas de funcionalidades que já existem.

Integre este módulo ao ecossistema atual.

---

# 1. CONTEXTO ATUAL

O projeto já possui ou está desenvolvendo:

* Bot Discord CHOQUE - BGR;
* Centro de Comando Web;
* Supabase/PostgreSQL;
* Railway;
* Discord OAuth2;
* sistema de membros;
* cargos;
* patentes;
* sincronização automática de identidade;
* nickname `[SIGLA] NICK [ID]`;
* bate-ponto;
* patrulhamento;
* mínimo de 15 minutos;
* cursos;
* treinamentos;
* matriz de qualificações;
* disciplina;
* advertências;
* ausências;
* solicitações;
* acompanhamento de recrutas;
* auditoria;
* RBAC;
* segurança Zero Trust;
* hardening;
* Frontend Design System;
* Caixa de Entrada Administrativa.

Agora deverá ser construído o sistema completo de:

# ALISTAMENTO E PROCESSO SELETIVO DA CHOQUE - BGR

O site será a principal interface para candidatura.

O Discord será utilizado para:

* autenticação;
* notificações;
* entrevistas;
* calls;
* cargos temporários;
* sincronização após aprovação.

---

# 2. OBJETIVO

Criar o seguinte fluxo:

```text
VISITANTE
↓
SITE CHOQUE
↓
ENTRAR COM DISCORD
↓
VALIDAÇÃO DE ELEGIBILIDADE
↓
INICIAR CANDIDATURA
↓
FORMULÁRIO
↓
AVALIAÇÃO CONTROLADA
↓
ENVIO
↓
SUPABASE
↓
NOTIFICAÇÃO DISCORD
↓
ANÁLISE ADMINISTRATIVA
↓
ENTREVISTA
↓
AVALIAÇÃO
↓
DECISÃO
```

Se aprovado:

```text
APROVADO
↓
CRIAR/VINCULAR MEMBRO
↓
PATENTE INICIAL
↓
CARGO DE RECRUTA
↓
NICKNAME
↓
DISCORD SYNC
↓
ACOMPANHAMENTO DE RECRUTA
```

Se reprovado:

```text
REPROVADO
↓
HISTÓRICO
↓
COOLDOWN
↓
POSSIBILIDADE DE NOVA CANDIDATURA FUTURA
```

---

# 3. PRINCÍPIO DE ARQUITETURA

Nunca:

```text
Frontend → Discord Bot Token
```

Nunca:

```text
Frontend → PostgreSQL administrativo
```

Utilizar:

```text
Browser
↓ HTTPS
Frontend
↓
Backend/API
↓
Core de negócio
↓
Supabase PostgreSQL
↓
Outbox/Eventos
↓
Bot Railway
↓
Discord
```

O banco será a fonte de verdade.

Discord será uma interface integrada.

---

# 4. LOGIN COM DISCORD

O candidato deverá obrigatoriamente utilizar:

# ENTRAR COM DISCORD

Utilizar Discord OAuth2 seguro.

Backend deve identificar:

```text
discordUserId
username
globalName
avatar
guildMembership
roles
```

Quando aplicável.

Não confiar em informações enviadas pelo navegador.

---

# 5. VALIDAÇÃO ANTES DO ALISTAMENTO

Antes de liberar candidatura:

```text
Discord autenticado                     ✅
Está no servidor exigido                ✅
Recrutamento aberto                     ✅
Não possui candidatura ativa            ✅
Não está em cooldown                     ✅
Não possui vínculo ativo com CHOQUE     ✅
Não possui bloqueio administrativo      ✅
```

Caso alguma regra impeça a candidatura:

bloquear server-side.

---

# 6. CANDIDATURA ÚNICA

Um `discordUserId` não poderá possuir mais de uma candidatura ativa.

Também verificar:

```text
ID BGR
```

para detectar possíveis duplicidades.

Criar proteção contra:

* duas abas;
* duplo clique;
* dois requests simultâneos;
* replay.

---

# 7. PROTOCOLO

Toda candidatura deve possuir protocolo amigável.

Exemplo:

```text
AL-00281
```

Internamente:

usar UUID ou identificador seguro.

Nunca utilizar protocolo sequencial como mecanismo de autorização.

---

# 8. CAMPANHA DE RECRUTAMENTO

Criar conceito:

```text
PROCESSO SELETIVO
```

Exemplo:

```text
Alistamento CHOQUE — Agosto/2026
```

Campos:

```text
id
name
status
opensAt
closesAt
formVersionId
cooldownDays
minimumAge
maximumApplications
createdAt
createdBy
```

---

# 9. STATUS DO PROCESSO

```text
DRAFT
SCHEDULED
OPEN
PAUSED
CLOSED
ARCHIVED
```

Abrir e fechar automaticamente quando houver datas configuradas.

---

# 10. PÁGINA PÚBLICA

Criar:

```text
/recrutamento
```

Visual conforme identidade militar contemporânea já definida.

Exemplo:

```text
CHOQUE - BGR

ALISTAMENTO

PROCESSO ATUAL
Agosto / 2026

STATUS
INSCRIÇÕES ABERTAS

ENCERRAMENTO
30 AGO 2026

[ INICIAR CANDIDATURA ]
```

Não criar landing page SaaS.

---

# 11. FORMULÁRIO DINÂMICO

As perguntas NÃO deverão ficar presas ao código.

Criar gerenciador administrativo de formulário.

Tipos:

```text
Texto curto
Texto longo
Número
Data
Sim/Não
Seleção única
Seleção múltipla
```

---

# 12. CONFIGURAÇÃO DE CADA PERGUNTA

Cada questão deverá possuir:

```text
id
section
title
description
type

required
position
enabled

minLength
maxLength

expectedMinLength
expectedMaxLength

securityLevel

timerEnabled
timerMode

allowBack
shufflePosition

createdAt
updatedAt
```

---

# 13. NÍVEIS DE SEGURANÇA

Disponibilizar:

```text
NORMAL
CONTROLADA
RIGOROSA
```

## NORMAL

Utilizado para:

* nome;
* nick;
* ID;
* disponibilidade.

Pode permitir copy/paste.

## CONTROLADA

Utilizado para:

* experiência;
* motivação;
* perguntas simples de conhecimento.

Possui:

* anti-paste;
* timer;
* monitoramento básico.

## RIGOROSA

Utilizado principalmente para:

* cenários;
* regras;
* ética;
* tomada de decisão;
* questões situacionais.

Possui:

* uma questão por vez;
* timer server-side;
* anti-copy;
* anti-paste;
* anti-cut;
* anti-drop;
* monitoramento de mudança de aba;
* randomização;
* confirmação antes de avançar.

---

# 14. BANCO PADRÃO DE PERGUNTAS

O sistema deverá vir inicialmente com um:

# BANCO DE QUESTÕES PADRÃO PARA RECRUTAMENTO DE CORPORAÇÃO POLICIAL EM MTA

IMPORTANTE:

Estas perguntas são defaults.

Todas devem poder ser:

* editadas;
* removidas;
* desativadas;
* reorganizadas;
* substituídas;
* duplicadas.

Não hardcodar textos dentro da regra de negócio.

---

# 15. SEÇÃO 01 — IDENTIFICAÇÃO

## Q01 — Nick no servidor

```text
Qual é o seu nick utilizado no servidor BGR?
```

Tipo:

```text
Texto curto
```

Segurança:

```text
NORMAL
```

---

## Q02 — ID no servidor

```text
Qual é o seu ID no servidor BGR?
```

Tipo:

```text
Número
```

---

## Q03 — Idade

```text
Qual é a sua idade?
```

Tipo:

```text
Número
```

Aplicar requisito mínimo configurável.

---

## Q04 — Discord

Discord deverá vir automaticamente do OAuth.

Não perguntar algo que o sistema já conhece.

Mostrar:

```text
Discord vinculado
@usuario
```

---

# 16. SEÇÃO 02 — DISPONIBILIDADE

## Q05

```text
Em quais períodos você costuma estar disponível para atuar no servidor?
```

Opções configuráveis:

```text
Manhã
Tarde
Noite
Madrugada
Variável
```

---

## Q06

```text
Em média, quantas horas por dia você consegue dedicar à corporação?
```

---

## Q07

```text
Você possui disponibilidade para participar de treinamentos, reuniões e operações previamente marcadas?
```

```text
SIM
NÃO
DEPENDE DO HORÁRIO
```

---

# 17. SEÇÃO 03 — EXPERIÊNCIA

## Q08

```text
Você já participou de alguma corporação policial em servidores de MTA ou outros servidores de roleplay?
```

```text
SIM
NÃO
```

---

## Q09

Condicional se Q08 = SIM:

```text
Quais corporações você já integrou e quais funções exercia?
```

Esperado:

```text
100–500 caracteres
```

Segurança:

```text
CONTROLADA
```

---

## Q10

```text
Você já exerceu cargo de liderança, instrução ou supervisão dentro de alguma organização?
```

---

## Q11

Se SIM:

```text
Descreva brevemente sua experiência exercendo essa função.
```

---

# 18. SEÇÃO 04 — MOTIVAÇÃO

## Q12

```text
Por que você deseja ingressar na CHOQUE?
```

Esperado:

```text
300–800 caracteres
```

Segurança:

```text
RIGOROSA
```

Timer automático.

---

## Q13

```text
O que você acredita que pode agregar à corporação?
```

Esperado:

```text
250–700 caracteres
```

---

## Q14

```text
O que você espera encontrar na CHOQUE caso seja aprovado?
```

Esperado:

```text
200–600 caracteres
```

---

# 19. SEÇÃO 05 — CONDUTA

## Q15

```text
Para você, o que significa disciplina dentro de uma corporação?
```

Esperado:

```text
250–700 caracteres
```

---

## Q16

```text
Como você reagiria caso recebesse uma ordem de um superior com a qual não concorda?
```

Esperado:

```text
300–800 caracteres
```

Segurança:

```text
RIGOROSA
```

---

## Q17

```text
Caso um colega da corporação esteja desrespeitando regras internas, como você agiria?
```

Esperado:

```text
300–800 caracteres
```

---

## Q18

```text
Como você deve agir caso perceba que cometeu um erro durante uma patrulha?
```

---

## Q19

```text
Qual deve ser sua postura ao representar a CHOQUE fora de uma operação oficial?
```

---

# 20. SEÇÃO 06 — ROLEPLAY

## Q20

```text
Explique com suas palavras o que significa Roleplay.
```

Esperado:

```text
200–600 caracteres
```

---

## Q21

```text
Por que preservar o Roleplay é importante durante uma abordagem ou operação policial?
```

---

## Q22

```text
Explique a diferença entre agir de acordo com o personagem e utilizar informações obtidas fora do Roleplay.
```

Não exigir necessariamente que o candidato saiba nomenclatura técnica.

Avaliar entendimento.

---

## Q23

```text
Você presencia um jogador utilizando informações que seu personagem não poderia conhecer. Como deve agir?
```

---

# 21. SEÇÃO 07 — COMUNICAÇÃO

## Q24

```text
Por que uma comunicação clara e objetiva é importante durante uma patrulha?
```

---

## Q25

```text
Você está em uma patrulha e vários membros começam a falar ao mesmo tempo durante uma ocorrência. Como você agiria?
```

---

## Q26

```text
Durante uma operação, você não entendeu uma orientação dada pelo comandante. O que deve fazer?
```

---

# 22. SEÇÃO 08 — TRABALHO EM EQUIPE

## Q27

```text
Como você lida com críticas ou correções feitas por um superior?
```

---

## Q28

```text
Um colega de patrulha está tendo dificuldades durante uma atividade. Como você agiria?
```

---

## Q29

```text
Você prefere atuar individualmente ou em equipe? Explique sua resposta.
```

---

# 23. SEÇÃO 09 — CENÁRIOS SITUACIONAIS

Essas questões devem preferencialmente utilizar:

```text
RIGOROSA
```

e banco randomizado.

---

## Q30

```text
Durante uma patrulha, um integrante da sua equipe começa a discutir com outro jogador e abandona a postura esperada da corporação. Como você reagiria?
```

Esperado:

```text
400–1000 caracteres
```

---

## Q31

```text
Você percebe que outro membro da corporação está abusando da autoridade que recebeu dentro do Roleplay. Como você deve proceder?
```

---

## Q32

```text
Durante uma ocorrência, o responsável pela patrulha toma uma decisão diferente daquela que você tomaria. Como você deve se comportar?
```

---

## Q33

```text
Um jogador começa a provocar você repetidamente durante uma abordagem. Como você deve manter sua postura?
```

---

## Q34

```text
Você identifica que um procedimento foi realizado de maneira incorreta por um colega. Como deve lidar com a situação sem comprometer a operação?
```

---

## Q35

```text
Durante uma patrulha, um superior comete um erro. Como você deve agir naquele momento e após o encerramento da situação?
```

---

## Q36

```text
Você está patrulhando com um membro mais antigo que solicita que você faça algo contrário às regras internas da corporação. Como você reagiria?
```

---

# 24. SEÇÃO 10 — RESPONSABILIDADE

## Q37

```text
Caso você saiba que não conseguirá cumprir uma atividade previamente marcada, qual deve ser sua atitude?
```

---

## Q38

```text
Por que registrar corretamente entrada e saída de serviço é importante?
```

---

## Q39

```text
Você iniciou o serviço, mas percebeu que não poderá continuar patrulhando. O que deve fazer?
```

---

# 25. SEÇÃO 11 — CONHECIMENTO DA CHOQUE

Após o candidato ter acesso às regras institucionais:

## Q40

```text
Qual é a principal função da CHOQUE dentro do servidor?
```

A resposta deverá ser configurável conforme as regras reais da organização.

---

## Q41

```text
Cite regras da corporação que você considera fundamentais e explique por quê.
```

---

## Q42

```text
Quais responsabilidades você assume ao ingressar na CHOQUE?
```

---

# 26. SEÇÃO 12 — AUTOAVALIAÇÃO

## Q43

```text
Qual característica sua acredita ser mais útil para atuar na corporação?
```

---

## Q44

```text
Qual aspecto você acredita que ainda precisa desenvolver?
```

---

## Q45

```text
Por que deveríamos considerar sua candidatura?
```

Esperado:

```text
300–800 caracteres
```

---

# 27. BANCO DE QUESTÕES

Não utilizar necessariamente as 45 perguntas em toda candidatura.

Criar sistema de:

# GRUPOS DE QUESTÕES

Exemplo:

```text
IDENTIFICAÇÃO
4 cadastradas
4 utilizadas

DISPONIBILIDADE
3 cadastradas
2 utilizadas

EXPERIÊNCIA
4 cadastradas
3 utilizadas

MOTIVAÇÃO
3 cadastradas
2 utilizadas

CONDUTA
5 cadastradas
3 utilizadas

ROLEPLAY
4 cadastradas
2 utilizadas

COMUNICAÇÃO
3 cadastradas
2 utilizadas

TRABALHO EM EQUIPE
3 cadastradas
2 utilizadas

SITUAÇÕES
7 cadastradas
3 utilizadas

RESPONSABILIDADE
3 cadastradas
2 utilizadas

CHOQUE
3 cadastradas
2 utilizadas

AUTOAVALIAÇÃO
3 cadastradas
1 utilizada
```

Assim duas pessoas podem receber provas diferentes mantendo dificuldade equivalente.

---

# 28. DISTRIBUIÇÃO PADRÃO

Exemplo inicial:

```text
Identificação            4
Disponibilidade          2
Experiência              2
Motivação                2
Conduta                   3
Roleplay                  2
Comunicação              1
Trabalho em equipe       1
Situações                3
Responsabilidade         1
Conhecimento CHOQUE      2
Autoavaliação            1
```

Total aproximado:

```text
24 perguntas
```

O administrador pode alterar.

---

# 29. RANDOMIZAÇÃO

Questões elegíveis podem possuir:

```text
shuffle = true
```

Cada candidatura recebe um snapshot.

Exemplo:

```text
Candidato A
Q30
Q33
Q36

Candidato B
Q31
Q34
Q35
```

---

# 30. DIFICULDADE

Questões poderão possuir:

```text
EASY
MEDIUM
HARD
```

ou:

```text
BÁSICA
INTERMEDIÁRIA
SITUACIONAL
```

Randomização precisa respeitar equivalência.

Não deixar um candidato receber prova muito mais complexa que outro.

---

# 31. ANTI-COLA

Adicionar proteção em questões CONTROLADAS e RIGOROSAS.

Bloquear quando configurado:

```text
Ctrl + V
Cmd + V

Ctrl + C
Cmd + C

Ctrl + X
Cmd + X

Paste
Cut
Copy
Drag and Drop
```

Considerar:

```text
paste
copy
cut
drop
beforeinput
```

Não depender somente de `keydown`.

---

# 32. MOBILE

Também bloquear paste por:

* long press;
* menu nativo;
* mecanismos equivalentes suportados pelo navegador.

Dentro das limitações reais da web.

---

# 33. MENSAGEM DE BLOQUEIO

Exemplo:

```text
COLAGEM NÃO PERMITIDA

Esta questão deve ser respondida diretamente por você.
```

Não apagar resposta já existente.

---

# 34. NÃO LER CLIPBOARD

NUNCA capturar o conteúdo que o candidato tentou colar.

Registrar apenas:

```text
PASTE_BLOCKED
```

---

# 35. COPY DO ENUNCIADO

Questões RIGOROSAS podem impedir seleção/cópia.

Utilizar:

```text
user-select: none
```

como camada de UX.

Mas não tratar isso como segurança absoluta.

---

# 36. NÃO TENTAR BLOQUEAR DEVTOOLS

Não implementar:

```text
bloquear F12
detectar DevTools
```

como medida principal.

É facilmente contornável.

A segurança real está no backend.

---

# 37. UMA QUESTÃO POR VEZ

Nas questões rigorosas:

```text
QUESTÃO 04 DE 24
```

O candidato vê somente a questão atual.

---

# 38. NÃO MOSTRAR A QUESTÃO ANTES DO INÍCIO

Fluxo:

```text
QUESTÃO PRONTA

Tempo disponível:
05:00

O cronômetro começará quando você iniciar.

[ INICIAR QUESTÃO ]
```

Após clique:

backend registra:

```text
startedAt
expiresAt
```

e só então entrega/libera o enunciado.

---

# 39. START IDEMPOTENTE

Clicar duas vezes:

não reinicia.

Atualizar página:

não reinicia.

Fechar e abrir:

não reinicia.

---

# 40. TIMER SERVER-SIDE

O navegador apenas exibe o tempo.

Servidor determina:

```text
questionStartedAt
questionExpiresAt
```

Alterar relógio local não modifica nada.

---

# 41. CÁLCULO DO TEMPORIZADOR

Criar função central:

```text
calculateQuestionTime(question)
```

Considerar principalmente:

```text
expectedMinLength
expectedMaxLength
complexity
baseTimeSeconds
timePerCharacter
minimumTime
maximumTime
```

---

# 42. PERFIS DE RESPOSTA

Criar presets administrativos.

## MUITO CURTA

```text
0–100 caracteres
30–60 segundos
```

## CURTA

```text
100–300 caracteres
1–3 minutos
```

## MÉDIA

```text
300–700 caracteres
3–5 minutos
```

## LONGA

```text
700–1500 caracteres
5–10 minutos
```

Valores iniciais.

Devem ser configuráveis.

---

# 43. EXEMPLO DE CÁLCULO

Pergunta:

```text
Por que você deseja entrar na CHOQUE?
```

Esperado:

```text
300–800 caracteres
```

Sistema pode calcular:

```text
Tempo:
04:30
```

Outra questão:

```text
Descreva como você agiria nesta situação...
```

Esperado:

```text
500–1200 caracteres
```

Resultado:

```text
07:00
```

---

# 44. TEMPO NÃO AUMENTA COM DIGITAÇÃO

Nunca:

```text
escreveu mais
→ ganhou mais tempo
```

O tempo é definido antes de iniciar.

---

# 45. CONTADOR

Exibir:

```text
TEMPO RESTANTE

04:12
```

Avisos:

```text
01:00
```

atenção discreta.

```text
00:30
```

alerta visual maior.

Nada exagerado.

---

# 46. TEMPO ESGOTADO

Ao expirar:

* bloquear edição;
* preservar autosave;
* marcar:

```text
TIME_EXPIRED
```

* prosseguir conforme configuração.

Nunca apagar o que foi escrito.

---

# 47. AUTOSAVE

Salvar resposta com debounce.

Exemplo:

```text
2–5 segundos
```

Não salvar a cada tecla.

Autosave:

não renova cronômetro.

---

# 48. QUEDA DE INTERNET

Mostrar:

```text
CONEXÃO INSTÁVEL

Tentaremos preservar sua resposta assim que a conexão retornar.
```

Timer server-side continua.

Aplicar pequena tolerância técnica de rede apenas no backend.

---

# 49. TROCA DE ABA

Quando configurado:

monitorar:

```text
visibilitychange
window blur
window focus
```

Registrar:

```text
TAB_HIDDEN
TAB_VISIBLE
WINDOW_BLURRED
WINDOW_FOCUSED
```

---

# 50. NÃO REPROVAR POR TROCA DE ABA

Pode ocorrer acidentalmente.

Apenas criar sinal de integridade.

---

# 51. INTEGRITY EVENTS

Criar:

```text
QUESTION_STARTED
QUESTION_SUBMITTED
QUESTION_TIMEOUT

COPY_BLOCKED
PASTE_BLOCKED
CUT_BLOCKED
DROP_BLOCKED

TAB_HIDDEN
TAB_VISIBLE

WINDOW_BLURRED
WINDOW_FOCUSED

UNUSUAL_INPUT_PATTERN
```

---

# 52. ANÁLISE DE DIGITAÇÃO

Detectar somente padrões grosseiramente incompatíveis.

Exemplo:

```text
1000 caracteres apareceram instantaneamente
```

Gerar:

```text
UNUSUAL_INPUT_PATTERN
```

Não acusar automaticamente.

---

# 53. NÃO CRIAR BIOMETRIA

Não construir fingerprint baseado em:

* ritmo individual de teclas;
* padrões biométricos;
* hardware;
* comportamento pessoal.

---

# 54. MARCA D'ÁGUA

Para questões rigorosas:

adicionar watermark discreto.

Exemplo:

```text
AL-00281
```

repetido sutilmente no fundo da área da avaliação.

Pode dificultar compartilhamento casual por screenshot.

---

# 55. NÃO TENTAR IMPEDIR SCREENSHOT

Isso não é confiável em navegador.

Não vender proteção falsa.

---

# 56. RESPOSTAS SEMELHANTES

Criar opcionalmente detector de respostas muito semelhantes entre candidatos.

Resultado:

```text
POSSIBLE_SIMILAR_RESPONSE
```

Somente para análise humana.

Nunca reprovar automaticamente.

---

# 57. CLASSIFICAÇÃO DE INTEGRIDADE

Estados:

```text
NORMAL
ATENÇÃO
REVISÃO
```

Nunca:

```text
COLADOR
FRAUDADOR
CHEATER
```

---

# 58. EXEMPLO DE RELATÓRIO

```text
INTEGRIDADE DA AVALIAÇÃO

Tempo total
37m42s

Questões respondidas
24 / 24

Questões expiradas
1

Tentativas de colagem
2

Tentativas de cópia
0

Trocas de aba
3

Tempo fora da página
41s

Padrões incomuns
0

CLASSIFICAÇÃO
ATENÇÃO
```

Nenhuma decisão automática.

---

# 59. PAINEL DO CANDIDATO

Criar:

```text
/minha-candidatura
```

Exemplo:

```text
MINHA CANDIDATURA

AL-00281

INSCRIÇÃO
● CONCLUÍDA

ANÁLISE
● EM ANDAMENTO

ENTREVISTA
○ PENDENTE

RESULTADO
○ PENDENTE
```

---

# 60. NÃO MOSTRAR EVENTOS ANTI-COLA AO CANDIDATO

Não exibir:

```text
Você possui 5 pontos de suspeita.
```

Ele recebe somente avisos imediatos de regras.

---

# 61. TIMELINE PÚBLICA

Exemplo:

```text
22/08 02:17
Candidatura recebida

22/08 10:42
Análise iniciada

23/08 19:20
Encaminhado para entrevista
```

---

# 62. STATUS INTERNOS

Estados internos:

```text
DRAFT
SUBMITTED
UNDER_REVIEW
INTERVIEW_PENDING
INTERVIEW_SCHEDULED
INTERVIEW_COMPLETED
FINAL_REVIEW
APPROVED
REJECTED
WITHDRAWN
EXPIRED
```

Podem ser simplificados no frontend do candidato.

---

# 63. NOTIFICAÇÃO NO DISCORD

Ao enviar candidatura:

criar:

```text
RECRUITMENT_APPLICATION_SUBMITTED
```

Outbox/evento persistido.

Bot processa.

---

# 64. MENSAGEM NO DISCORD

Exemplo:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━
NOVA CANDIDATURA

PROTOCOLO
AL-00281

CANDIDATO
@Lucas

ID BGR
1842

PROCESSO
Alistamento Agosto/2026

ENVIADO
22/08/2026 • 02:17

STATUS
AGUARDANDO ANÁLISE

[ ANALISAR NO PAINEL ]
━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

# 65. NÃO ENVIAR AS RESPOSTAS NO DISCORD

Regra obrigatória.

O canal recebe somente resumo.

O conteúdo completo permanece no site.

---

# 66. BOTÃO DISCORD

```text
ANALISAR NO PAINEL
```

leva para candidatura.

Conhecer a URL não concede acesso.

Backend continua exigindo permissão.

---

# 67. DASHBOARD DE RECRUTAMENTO

Criar dentro do Centro de Comando:

# RECRUTAMENTO

Exemplo:

```text
PROCESSO ATUAL
AGOSTO 2026

RECEBIDAS             247
AGUARDANDO ANÁLISE     31
EM ANÁLISE             18
ENTREVISTAS             12
APROVADAS               21
REPROVADAS             165
```

---

# 68. LISTAGEM

Tabela:

```text
PROTOCOLO
CANDIDATO
ID BGR
ENVIO
ETAPA
INTEGRIDADE
RESPONSÁVEL
STATUS
```

---

# 69. FILTROS

```text
Processo
Status
Etapa
Responsável
Integridade
Data
```

Busca:

```text
Nick
Discord
ID BGR
Protocolo
```

---

# 70. PÁGINA DE ANÁLISE

Layout administrativo:

```text
LISTA                         CANDIDATURA
────────────────────────────────────────────

AL-0281 Lucas                 AL-0281
AL-0280 Gabriel               Lucas Ferreira
AL-0279 Pedro
                              IDENTIFICAÇÃO
                              RESPOSTAS
                              INTEGRIDADE
                              ENTREVISTA
                              HISTÓRICO
                              NOTAS INTERNAS

                              [ PRÓXIMA ETAPA ]
                              [ REPROVAR ]
```

---

# 71. DOSSIÊ DE CANDIDATURA

Organização:

```text
01 IDENTIFICAÇÃO
02 DISPONIBILIDADE
03 EXPERIÊNCIA
04 RESPOSTAS
05 INTEGRIDADE
06 PROCESSO SELETIVO
07 ENTREVISTA
08 AVALIAÇÕES
09 HISTÓRICO
10 OBSERVAÇÕES INTERNAS
```

---

# 72. INTEGRIDADE POR QUESTÃO

Mostrar:

```text
Q12 — Por que deseja ingressar?

Tempo permitido
04m30s

Tempo utilizado
03m48s

Paste bloqueado
0

Trocas de aba
1

Status
NORMAL
```

---

# 73. ASSUMIR ANÁLISE

Botão:

```text
ASSUMIR ANÁLISE
```

Registrar responsável.

Evitar dois recrutadores tomando decisões conflitantes.

---

# 74. OPTIMISTIC LOCKING

Toda candidatura deverá possuir:

```text
version
```

Se outro recrutador alterou:

```text
Esta candidatura foi atualizada por outro usuário.
Atualize antes de continuar.
```

---

# 75. CAIXA DE ENTRADA ADMINISTRATIVA

Integrar:

```text
RECRUTAMENTO
31 pendentes
```

Também:

```text
INTEGRIDADE PARA REVISÃO
4
```

---

# 76. CANDIDATURA ESQUECIDA

Detectar:

```text
24h sem análise
48h sem análise
```

conforme configuração.

Apenas alertar.

Nunca reprovar automaticamente.

---

# 77. ENTREVISTA

Após análise:

```text
ENCAMINHAR PARA ENTREVISTA
```

Status:

```text
INTERVIEW_PENDING
```

---

# 78. CARGO TEMPORÁRIO

Opcional:

```text
@Candidato
```

Somente na etapa apropriada.

Configuração:

```text
CandidateDiscordRoleId
```

---

# 79. CALL

Configurar:

```text
Aguardando Recrutamento
```

para entrevistas.

---

# 80. AGENDAMENTO

Campos:

```text
Data
Horário
Entrevistador
Observação
```

---

# 81. AVALIAÇÃO DA ENTREVISTA

Modelo simples:

```text
COMUNICAÇÃO
Ótimo / Bom / Regular / Insuficiente

POSTURA
Ótimo / Bom / Regular / Insuficiente

CONHECIMENTO
Ótimo / Bom / Regular / Insuficiente

DISCIPLINA
Ótimo / Bom / Regular / Insuficiente

RESULTADO
APTO / NÃO APTO / REAVALIAR

OBSERVAÇÃO
```

---

# 82. AVALIAÇÃO NÃO ANÔNIMA

Guardar:

```text
evaluatorId
evaluatedAt
```

---

# 83. APROVAÇÃO

Somente usuários com:

```text
recruitment.approve
```

podem aprovar.

---

# 84. CONFIRMAÇÃO

```text
APROVAR CANDIDATO

Lucas Ferreira
ID 1842

Esta ação irá:

• concluir a candidatura;
• criar ou vincular o membro;
• definir patente inicial;
• sincronizar cargos;
• atualizar nickname;
• iniciar acompanhamento de recruta;
• registrar auditoria.

[ CANCELAR ]

[ CONFIRMAR APROVAÇÃO ]
```

---

# 85. INGRESSO

Utilizar services existentes.

```text
APPROVED
↓
MemberService
↓
RankService
↓
DiscordIdentityService
↓
RecruitFollowupService
```

Não duplicar lógica.

---

# 86. PATENTE INICIAL

Configuração:

```text
initialRecruitRankId
```

Não hardcodar.

---

# 87. NICKNAME

Utilizar obrigatoriamente:

```text
formatMemberNickname()
```

Resultado conceitual:

```text
[RCT] Lucas [1842]
```

---

# 88. DISCORD SYNC

Após aprovação:

* remover cargo `Candidato`;
* adicionar cargo base da CHOQUE;
* adicionar patente inicial;
* atualizar nickname.

Se falhar:

```text
DISCORD_SYNC_PENDING
```

Não perder aprovação.

---

# 89. ACOMPANHAMENTO DE RECRUTA

Criar/vincular automaticamente ao módulo existente.

Candidatura original deverá ficar ligada ao perfil:

```text
originApplicationId
```

---

# 90. REPROVAÇÃO

Fluxo:

```text
REPROVAR
↓
MOTIVO
↓
MENSAGEM PÚBLICA
↓
COOLDOWN
↓
CONFIRMAÇÃO
```

---

# 91. MOTIVOS

Defaults:

```text
Requisitos não atendidos
Respostas insuficientes
Conhecimento insuficiente
Entrevista
Conduta
Incompatibilidade com o perfil esperado
Informações inconsistentes
Outro
```

Todos configuráveis.

---

# 92. MOTIVO INTERNO E PÚBLICO

Separar:

```text
internalReason
candidateMessage
```

Nunca expor automaticamente toda anotação administrativa.

---

# 93. COOLDOWN

Configuração:

```text
reapplicationCooldownDays
```

Exemplo:

```text
30 dias
```

Mostrar ao candidato:

```text
Você poderá realizar uma nova candidatura a partir de 21/09/2026.
```

---

# 94. FORM BUILDER

Criar área administrativa:

```text
RECRUTAMENTO
→ FORMULÁRIO
```

Exemplo:

```text
12. Por que deseja ingressar na CHOQUE?

Tipo
Texto longo

Grupo
Motivação

Segurança
RIGOROSA

Resposta esperada
300–800 caracteres

Temporizador
AUTOMÁTICO

Tempo calculado
04m30s

Bloquear paste
SIM

Bloquear copy
SIM

Detectar troca de aba
SIM
```

---

# 95. PREVIEW

```text
VISUALIZAR COMO CANDIDATO
```

Preview não deve gerar eventos reais.

---

# 96. VERSIONAMENTO DO FORMULÁRIO

Quando formulário publicado:

```text
Formulário v4
```

Candidaturas iniciadas permanecem associadas à versão correspondente.

---

# 97. SNAPSHOT DA AVALIAÇÃO

Ao iniciar candidatura, persistir:

```text
questions
questionOrder
optionOrder
timers
securityRules
formVersion
```

Alterar formulário administrativo não afeta avaliação já iniciada.

---

# 98. NÃO PERMITIR RETORNO EM QUESTÕES RIGOROSAS

Configuração:

```text
allowPreviousQuestionEdit = false
```

Após:

```text
CONFIRMAR RESPOSTA
```

não alterar.

---

# 99. CONFIRMAÇÃO DA RESPOSTA

```text
CONFIRMAR RESPOSTA?

Após continuar, esta resposta não poderá mais ser alterada.

[ CONTINUAR EDITANDO ]

[ CONFIRMAR ]
```

---

# 100. ADAPTAÇÃO DE ACESSIBILIDADE

Criar opção administrativa auditada:

```text
ADAPTAÇÃO DE AVALIAÇÃO
```

Possibilidades:

```text
tempo adicional
restrição de clipboard adaptada
formato alternativo
```

Não prejudicar candidatos que necessitem tecnologia assistiva.

---

# 101. TEMPO EXTRA

```text
extraTimePercent
```

Exemplo:

```text
+25%
```

Exigir:

```text
responsável
motivo
data
```

---

# 102. SEGURANÇA

Aplicar integralmente o prompt de cybersecurity anterior:

* HTTPS;
* TLS moderno;
* Discord OAuth;
* CSRF;
* CSP;
* CORS;
* HttpOnly cookies;
* SameSite;
* rate limiting;
* RLS;
* backend authorization;
* validation;
* XSS protection;
* SQL injection protection;
* idempotência;
* logs seguros;
* auditoria;
* secrets no Railway;
* Supabase hardening.

---

# 103. RATE LIMIT

Especialmente:

```text
/login
/oauth
/recruitment/eligibility
/application/start
/application/save
/application/submit
/question/start
/question/submit
```

---

# 104. NÃO CONFIAR NO FRONTEND

Backend valida:

```text
qual pergunta foi atribuída
ordem
tentativa
timer
expiração
tamanho
estado da candidatura
permissão
```

---

# 105. TOKENS/NONCES DE QUESTÃO

Para avaliação rigorosa:

cada questão poderá possuir token temporário relacionado a:

```text
application
candidate
question
attempt
expiration
```

Não aceitar resposta enviada para questão diferente.

---

# 106. RLS

Candidato pode acessar:

```text
SOMENTE PRÓPRIA CANDIDATURA
```

Não candidatos alheios.

---

# 107. DADOS ADMINISTRATIVOS

Avaliações, integridade, notes e decisões:

somente backend e usuários autorizados.

---

# 108. PERMISSÕES

Criar:

```text
recruitment.view

recruitment.application.read
recruitment.application.review
recruitment.application.assign

recruitment.interview.manage
recruitment.evaluate

recruitment.approve
recruitment.reject

recruitment.integrity.read

recruitment.notes.read
recruitment.notes.create

recruitment.form.manage

recruitment.campaign.manage
recruitment.settings.manage
```

Deny by default.

---

# 109. AUDITORIA

Eventos:

```text
APPLICATION_STARTED
APPLICATION_SUBMITTED

QUESTION_STARTED
QUESTION_SUBMITTED
QUESTION_TIMEOUT

APPLICATION_ASSIGNED
REVIEW_STARTED

INTERVIEW_SCHEDULED
INTERVIEW_COMPLETED

APPLICATION_APPROVED
APPLICATION_REJECTED
APPLICATION_WITHDRAWN

PASTE_BLOCKED
COPY_BLOCKED

INTEGRITY_FLAG_CREATED

CANDIDATE_ROLE_ASSIGNED
RECRUIT_CREATED

DISCORD_SYNC_FAILED
DISCORD_SYNC_COMPLETED
```

---

# 110. NÃO POLUIR AUDIT LOG

Eventos técnicos massivos de focus podem ficar em:

```text
recruitment_integrity_events
```

e não na auditoria geral.

---

# 111. MODELOS CONCEITUAIS

Adapte à arquitetura real.

Possíveis entidades:

```text
recruitment_campaigns

recruitment_forms
recruitment_form_versions

recruitment_question_groups
recruitment_questions

recruitment_applications

recruitment_application_questions
recruitment_answers

recruitment_reviews

recruitment_interviews
recruitment_evaluations

recruitment_internal_notes

recruitment_integrity_sessions
recruitment_integrity_events

recruitment_history

recruitment_cooldowns
```

Evitar tabelas redundantes.

---

# 112. API

Conceitualmente:

```text
GET  /recruitment/current

GET  /recruitment/eligibility

POST /recruitment/applications/start

GET  /me/recruitment/application

POST /applications/:id/questions/:questionId/start

PATCH /applications/:id/questions/:questionId/autosave

POST /applications/:id/questions/:questionId/submit

POST /applications/:id/submit
```

Admin:

```text
GET  /admin/recruitment/applications

GET  /admin/recruitment/applications/:id

POST /admin/recruitment/applications/:id/assign

POST /admin/recruitment/applications/:id/interview

POST /admin/recruitment/applications/:id/evaluate

POST /admin/recruitment/applications/:id/approve

POST /admin/recruitment/applications/:id/reject
```

Adapte à arquitetura existente.

---

# 113. NÃO USAR PATCH GENÉRICO PARA STATUS

Não criar:

```text
PATCH /application/:id

{
  "status": "APPROVED"
}
```

Criar ação explícita:

```text
POST /application/:id/approve
```

A regra fica no Core.

---

# 114. TRANSAÇÃO DE APROVAÇÃO

Conceitualmente:

```text
BEGIN

lock application

validate status
validate permission
validate member duplication

mark application approved

create/link member

create recruit follow-up

create audit record

create Discord outbox event

COMMIT
```

---

# 115. IDEMPOTÊNCIA

Duplo clique em:

```text
APROVAR
```

não pode criar dois recrutas.

Duplo:

```text
ENVIAR CANDIDATURA
```

não gera duas candidaturas.

Retry da notificação:

não gera spam.

---

# 116. OUTBOX

Utilizar para integração com Discord.

```text
Supabase
↓
Outbox
↓
Worker/Bot
↓
Discord
```

---

# 117. RESTART

Bot/API reiniciar não pode apagar:

* timer;
* candidatura;
* respostas;
* entrevista;
* cooldown;
* notificações pendentes.

Tudo importante persistente.

---

# 118. FRONTEND

Continuar utilizando obrigatoriamente a:

# FRONTEND DESIGN SKILL

O formulário não deve parecer Google Forms.

A estética deve continuar:

```text
MILITAR CONTEMPORÂNEA
INSTITUCIONAL
TÁTICA
SÓBRIA
PRECISA
```

---

# 119. EXEMPLO DE TELA DA PROVA

```text
CHOQUE BGR
PROCESSO SELETIVO

AVALIAÇÃO DE ALISTAMENTO

QUESTÃO 12 DE 24

TEMPO RESTANTE
04:18

────────────────────────────

Por que você deseja ingressar na CHOQUE?

SUA RESPOSTA

┌───────────────────────────┐
│                           │
│                           │
│                           │
└───────────────────────────┘

428 / 800 caracteres

Mínimo: 300

Colagem está desabilitada nesta questão.

[ CONFIRMAR RESPOSTA ]
```

---

# 120. BARRA DE PROGRESSO

Discreta:

```text
12 / 24
██████████░░░░░░
```

Não revelar necessariamente nomes das próximas questões.

---

# 121. NÃO PERMITIR PRÉ-VISUALIZAÇÃO DO BANCO

Candidato não deve conseguir consultar:

```text
/api/questions
```

para baixar todas as questões.

API entrega apenas a questão atribuída no momento correto.

---

# 122. DADOS DAS RESPOSTAS

Nunca enviar ao frontend:

* resposta-modelo;
* critério administrativo secreto;
* respostas de outros candidatos;
* questões não atribuídas.

---

# 123. TESTES ANTI-COLA

Testar:

```text
Ctrl+C
Ctrl+V
Ctrl+X

Cmd+C
Cmd+V
Cmd+X

context menu
mobile paste
drag/drop
beforeinput
```

---

# 124. TESTES DE TIMER

Testar:

```text
F5
fechar aba
abrir aba
duplo start
alterar relógio local
rede lenta
rede offline
submit expirado
```

---

# 125. TESTES DE AUTORIZAÇÃO

```text
Candidato A → candidatura B
403

Membro comum → admin recruitment
403

Recrutador sem approve → approve endpoint
403

Recrutador sem integrity.read → integrity events
403
```

---

# 126. TESTES DE MANIPULAÇÃO

Testar requests alterados manualmente:

```text
expiresAt modificado
questionId diferente
applicationId diferente
maxLength burlado
status modificado
role enviado pelo browser
```

Backend deve rejeitar.

---

# 127. TESTES DE CONCORRÊNCIA

* duas abas iniciando mesma questão;
* submit duplo;
* dois recrutadores aprovando;
* approve e reject simultâneos;
* retry Discord.

---

# 128. TESTES DE RANDOMIZAÇÃO

Garantir:

* mesmo candidato recebe mesmas questões após refresh;
* candidato diferente pode receber outras;
* distribuição mantém categorias;
* dificuldade permanece equivalente.

---

# 129. RELATÓRIOS

Administradores poderão visualizar:

```text
Candidaturas
Aprovações
Reprovações
Tempo médio de análise
Tempo médio de avaliação
Entrevistas
Desistências
Candidaturas em atraso
```

---

# 130. O QUE MUDOU?

Integrar:

```text
RECRUTAMENTO

42 candidaturas recebidas
18 entrevistas
11 aprovados
25 reprovados
6 aguardando análise
```

---

# 131. CANDIDATO NÃO É MEMBRO

Nunca incluir candidatura em:

```text
efetivo ativo
ranking
meta semanal
patrulhamento
```

antes da aprovação.

---

# 132. APROVAÇÃO É A PORTA DE ENTRADA

Após aprovação:

```text
CANDIDATO
↓
RECRUTA
↓
MEMBRO CHOQUE
```

O histórico da candidatura deve permanecer vinculado.

---

# 133. NÃO USAR IA PARA APROVAR

Mesmo se houver IA futuramente:

pode:

* resumir respostas;
* organizar dados;
* localizar respostas semelhantes;
* apontar inconsistências.

Nunca:

```text
score IA
→ reprovação automática
```

Decisão continua humana.

---

# 134. INTEGRIDADE NÃO É DECISÃO

Da mesma forma:

```text
10 trocas de aba
```

não significa:

```text
REPROVADO
```

O sistema apresenta evidências.

O comando decide.

---

# 135. DEFINITION OF DONE

Este módulo somente estará pronto quando existir:

```text
Discord OAuth
Eligibility
Campaign
Form Builder
Question Bank
Form Versioning
Randomização
Snapshots

Anti Copy
Anti Paste
Timer server-side
Autosave
Focus monitoring
Integrity events

Candidatura
Protocolo
Minha Candidatura

Notificação Discord
Dashboard Admin
Inbox

Análise
Entrevista
Avaliação
Aprovação
Reprovação
Cooldown

Conversão para recruta
Discord Sync
Nickname
Patente inicial
Acompanhamento

RBAC
RLS
Auditoria
Idempotência
Concorrência
Security tests
Recovery
```

---

# 136. PRIORIDADE DE IMPLEMENTAÇÃO

## FASE 1 — DOMÍNIO

* schema;
* campaign;
* formulário;
* banco de questões;
* versionamento;
* state machine;
* RBAC.

## FASE 2 — CANDIDATO

* OAuth;
* eligibility;
* candidatura;
* interface;
* draft;
* progresso.

## FASE 3 — AVALIAÇÃO

* uma questão por vez;
* randomização;
* timer server-side;
* autosave;
* anti-copy/paste;
* integrity session.

## FASE 4 — INTEGRAÇÃO

* Supabase;
* eventos;
* outbox;
* notificação Discord.

## FASE 5 — ADMIN

* dashboard;
* lista;
* filtros;
* dossiê;
* relatório de integridade;
* inbox.

## FASE 6 — PROCESSO SELETIVO

* análise;
* entrevista;
* avaliação;
* decisão;
* cooldown.

## FASE 7 — INGRESSO

* member service;
* patente inicial;
* cargos;
* nickname;
* recruit follow-up.

## FASE 8 — HARDENING

* autorização;
* concorrência;
* idempotência;
* negative tests;
* security tests;
* reconciliação.

---

# 137. REGRA FINAL DE EXPERIÊNCIA DO CANDIDATO

O fluxo deverá parecer:

```text
ACESSAR
↓
ENTRAR COM DISCORD
↓
VALIDAÇÃO
↓
INICIAR ALISTAMENTO
↓
RESPONDER AVALIAÇÃO
↓
ENVIAR
↓
RECEBER PROTOCOLO
↓
ACOMPANHAR STATUS
↓
ENTREVISTA
↓
RESULTADO
```

---

# 138. REGRA FINAL DO RECRUTADOR

```text
ENTRAR NO CENTRO DE COMANDO
↓
ABRIR CAIXA DE ENTRADA
↓
CANDIDATURAS
↓
ABRIR DOSSIÊ
↓
ANALISAR RESPOSTAS
↓
ANALISAR INTEGRIDADE
↓
ENTREVISTAR
↓
REGISTRAR AVALIAÇÃO
↓
DECIDIR
```

---

# 139. FILOSOFIA FINAL

O objetivo NÃO é construir apenas:

```text
um formulário online
```

O objetivo é criar:

# O SISTEMA OFICIAL DE INGRESSO DA CHOQUE - BGR

A candidatura deverá ser o início da trajetória funcional:

```text
ALISTADO
↓
CANDIDATO
↓
AVALIAÇÃO
↓
ENTREVISTA
↓
APROVADO
↓
RECRUTA
↓
CURSOS
↓
PATRULHAS
↓
CARREIRA
↓
HISTÓRICO FUNCIONAL
```

Tudo utilizando:

* o mesmo Core;
* o mesmo Supabase;
* as mesmas permissões;
* a mesma auditoria;
* o mesmo sistema de identidade;
* o mesmo bot;
* o mesmo Centro de Comando.

Não crie um sistema de recrutamento isolado.

Integre-o ao ecossistema inteiro da **CHOQUE - BGR**.
