# CONTEXTO

Este prompt é **COMPLEMENTAR a todos os prompts anteriores do projeto CHOQUE - BGR**.

Você já possui acesso ao repositório e ao contexto completo do projeto.

Já existem ou estão sendo desenvolvidos:

* bot Discord da CHOQUE - BGR;
* sistema de membros;
* cadastro;
* hierarquia;
* patentes;
* sincronização automática de cargos;
* nickname `[ABREVIAÇÃO] NICK [ID]`;
* bate-ponto por call;
* mínimo de 15 minutos de patrulha;
* fila automática de patrulhamento;
* central de patrulhas;
* ausências;
* retornos automáticos;
* advertências;
* suspensões;
* treinamentos;
* cursos;
* qualificações;
* acompanhamento de recrutas;
* solicitações;
* caixa de entrada administrativa;
* dossiê funcional;
* auditoria;
* relatórios;
* configurações;
* Supabase como banco PostgreSQL;
* Railway para execução dos serviços.

Agora deverá ser criado o:

# CENTRO DE COMANDO WEB — CHOQUE BGR

O site deverá funcionar como a interface web administrativa e operacional do mesmo sistema utilizado pelo bot Discord.

---

# 1. INSTRUÇÃO OBRIGATÓRIA — FRONTEND DESIGN SKILL

Antes de implementar qualquer interface:

# UTILIZE A SKILL DE FRONTEND DESIGN DISPONÍVEL NO AMBIENTE.

Leia suas instruções completamente e utilize seus princípios durante:

* planejamento visual;
* design system;
* arquitetura da interface;
* escolha tipográfica;
* hierarquia;
* composição;
* responsividade;
* componentes;
* estados;
* interação;
* refinamento.

Não utilize a skill apenas superficialmente.

A qualidade visual deste projeto é uma prioridade.

---

# 2. OBJETIVO VISUAL

Quero um dashboard com identidade própria da:

# CHOQUE - BGR

A interface deverá transmitir:

* comando;
* organização;
* disciplina;
* ambiente operacional;
* precisão;
* autoridade;
* tecnologia;
* prontidão;
* segurança;
* identidade militar/tática.

Porém:

# NÃO TRANSFORME O SITE EM UMA CARICATURA MILITAR.

Evite:

* camuflagem espalhada pelo background;
* munições decorativas;
* armas como elementos de UI;
* caveiras aleatórias;
* excesso de brasões;
* textura militar em todos os componentes;
* verde neon;
* HUD de videogame;
* interface de Call of Duty;
* aparência de servidor FiveM/MTA genérico.

A inspiração deve ser:

**centro de comando operacional contemporâneo**

e não:

**menu de jogo militar**.

---

# 3. REGRA PRINCIPAL — NÃO PARECER SITE GERADO POR IA

Essa é uma exigência crítica.

O site NÃO pode possuir aquela estética genérica frequentemente encontrada em páginas produzidas automaticamente.

Evite especialmente:

* dezenas de cards arredondados iguais;
* radius exagerado em tudo;
* glassmorphism;
* blur excessivo;
* gradientes roxo/azul;
* glow neon;
* sombras enormes;
* headline gigante sem função;
* landing page de SaaS;
* blobs coloridos;
* ícones dentro de círculos em todo lugar;
* cada informação dentro de um card;
* excesso de pills;
* estatísticas gigantes sem contexto;
* grids simétricos demais;
* espaçamento excessivo;
* componentes genéricos de dashboard;
* textos como “Gerencie tudo em um só lugar”;
* slogans corporativos artificiais;
* ilustrações abstratas;
* animações gratuitas;
* componentes copiados visualmente de shadcn sem personalização;
* utilização indiscriminada de Lucide Icons;
* sidebar genérica de template SaaS.

Não produza uma interface que poderia servir igualmente para:

* fintech;
* CRM;
* clínica;
* e-commerce;
* software de RH.

Ela precisa parecer construída especificamente para a:

# CHOQUE - BGR.

---

# 4. DIREÇÃO ESTÉTICA

A linguagem visual deverá seguir:

```text
MILITAR CONTEMPORÂNEO
+
CENTRO DE COMANDO
+
PAINEL OPERACIONAL
+
ADMINISTRAÇÃO INSTITUCIONAL
```

Referência conceitual:

```text
Quartel
Centro de operações
Painel de controle
Terminal administrativo
Sistema interno governamental
```

Mas adaptado para uma aplicação web moderna.

---

# 5. DESIGN SYSTEM

Crie um design system próprio.

Não dependa exclusivamente de presets de bibliotecas.

## Paleta sugerida

### Fundo principal

```text
#0B0E0C
```

Quase preto com leve tom esverdeado.

### Superfície principal

```text
#111612
```

### Superfície secundária

```text
#161C17
```

### Superfície elevada

```text
#1C231D
```

### Olive institucional

```text
#667157
```

### Olive ativo

```text
#7C8969
```

### Khaki

```text
#B3A77F
```

### Steel / cinza tático

```text
#8C9690
```

### Texto principal

```text
#E6E9E4
```

### Texto secundário

```text
#9DA69E
```

### Linha / divisor

```text
#2A322B
```

### Sucesso

Verde militar discreto.

Não usar verde neon.

### Aviso

Âmbar/ocre.

### Erro

Vermelho queimado.

### Informação

Cinza-azulado muito discreto.

---

# 6. CORES DEVEM TER SIGNIFICADO

Não utilize cor apenas para decoração.

Exemplo:

```text
VERDE
Ativo / operacional

ÂMBAR
Atenção / aguardando

VERMELHO
Suspensão / erro / situação crítica

CINZA
Inativo / indisponível

OLIVE
Identidade principal
```

Uma mesma cor deve preservar significado no sistema inteiro.

---

# 7. TIPOGRAFIA

A tipografia deve contribuir bastante para a identidade.

## Títulos

Preferir fonte:

* condensada;
* técnica;
* institucional;
* forte.

Exemplos conceituais:

```text
Barlow Condensed
Roboto Condensed
DIN-like
```

Utilize a melhor opção disponível e compatível com o projeto.

## Corpo

Fonte altamente legível.

Exemplo:

```text
Inter
Roboto
system-ui
```

Não utilizar fontes futuristas difíceis de ler.

---

# 8. HIERARQUIA TIPOGRÁFICA

Títulos podem utilizar:

```text
CENTRAL DE PATRULHAS
EFETIVO
CAIXA ADMINISTRATIVA
```

em uppercase controlado.

Corpo:

```text
João Silva
Cabo
Ativo
```

Não colocar tudo em caixa alta.

---

# 9. LOGOTIPO

Se houver logo oficial da CHOQUE - BGR no projeto:

utilize-o.

Se não houver:

NÃO invente um brasão genérico usando IA.

Utilize temporariamente uma assinatura tipográfica:

```text
CHOQUE
BGR
```

com composição institucional.

Prepare o componente para receber a imagem oficial posteriormente.

---

# 10. ESTRUTURA PRINCIPAL

A aplicação deverá ter um layout de dashboard real.

Desktop:

```text
┌────────────────────────────────────────────┐
│ TOPBAR                                     │
├──────────────┬─────────────────────────────┤
│              │                             │
│ SIDEBAR      │        CONTEÚDO             │
│              │                             │
│              │                             │
└──────────────┴─────────────────────────────┘
```

---

# 11. SIDEBAR

A sidebar deve ser sólida e discreta.

Não utilizar sidebar flutuante dentro de um card arredondado.

Estrutura sugerida:

```text
CHOQUE BGR

VISÃO GERAL
Dashboard

OPERAÇÃO
Prontidão
Patrulhas
Pontos

EFETIVO
Membros
Recrutas
Carreira
Cursos

ADMINISTRAÇÃO
Solicitações
Disciplina
Caixa de Entrada

INTELIGÊNCIA
O que mudou?
Relatórios
Auditoria

SISTEMA
Identidade
Configurações
Manutenção
```

Não precisa escrever literalmente os títulos acima se outra organização funcionar melhor.

Preserve a hierarquia.

---

# 12. SIDEBAR ATIVA

Item atual deve possuir:

* pequeno indicador lateral;
* alteração discreta do fundo;
* contraste tipográfico.

Evitar:

```text
botão gigante verde
```

como item selecionado.

---

# 13. TOPBAR

Topbar deverá mostrar apenas informações úteis.

Exemplo:

```text
CENTRO DE COMANDO

Discord
● Conectado

Sistema
● Operacional

Patrulhas
6 ativas

[perfil]
```

Também poderá mostrar:

* servidor selecionado;
* notificações;
* usuário logado.

Não sobrecarregar.

---

# 14. LOGIN

Utilizar:

# ENTRAR COM DISCORD

Tela simples.

Visual institucional.

Exemplo conceitual:

```text
CHOQUE BGR

CENTRO DE COMANDO

Acesso restrito ao efetivo autorizado.

[ ENTRAR COM DISCORD ]
```

Não criar landing page comercial antes do login.

---

# 15. AUTORIZAÇÃO

Após Discord OAuth:

verificar:

* Discord User ID;
* vínculo com servidor;
* cadastro interno;
* cargo;
* patente;
* permissões.

O frontend jamais deve ser a única barreira de autorização.

Backend verifica tudo novamente.

---

# 16. PERFIS DE ACESSO

A interface deverá se adaptar conforme RBAC.

## Membro

Pode visualizar:

* próprio perfil;
* próprias horas;
* próprias patrulhas;
* próprios cursos;
* próprias solicitações.

## Superior

Pode visualizar adicionalmente:

* efetivo;
* prontidão;
* patrulhas;
* treinamentos;
* recrutas.

## Alto Comando

Pode visualizar:

* administração;
* carreira;
* disciplina;
* relatórios;
* auditoria;
* configurações;
* integridade.

Não exibir menu inútil para quem não possui acesso.

---

# 17. DASHBOARD PRINCIPAL

Não faça o dashboard como:

```text
12 cards quadrados de estatísticas
```

Organize por prioridade operacional.

Estrutura sugerida:

```text
PRONTIDÃO DO EFETIVO
────────────────────────────────────────────

EM PATRULHA      AGUARDANDO      DISPONÍVEIS
18               6               11

AUSENTES         TREINAMENTO     SUSPENSOS
12               4               2
```

Depois:

```text
PATRULHAS EM ANDAMENTO
```

Depois:

```text
PENDÊNCIAS ADMINISTRATIVAS
```

Depois:

```text
ATIVIDADE RECENTE
```

---

# 18. INDICADORES

Evite cada indicador dentro de um card isolado.

Pode utilizar uma faixa operacional:

```text
EFETIVO 128 │ PATRULHA 18 │ FILA 6 │ AUSENTES 12 │ SUSPENSOS 2
```

Com divisores.

Isso fica mais parecido com sistema de comando.

---

# 19. CENTRAL DE PRONTIDÃO

Página:

# PRONTIDÃO

Mostrar:

```text
EFETIVO OPERACIONAL

Em Patrulha
18

Aguardando
6

Disponíveis
11

Indisponíveis
7

Treinamento
4

Ausentes
12
```

Adicionar lista operacional abaixo.

---

# 20. LISTA DE EFETIVO

Utilizar tabela/lista real.

Colunas:

```text
Identificação
Patente
Status
Disponibilidade
Patrulha
Horas semanais
Última atividade
```

Não transformar cada membro em um card.

---

# 21. FILTROS

Filtros devem ser compactos.

Exemplo:

```text
[ Buscar membro... ]

Patente [ Todas ▼ ]
Status  [ Ativos ▼ ]
Atividade [ Todas ▼ ]
```

Não ocupar metade da tela.

---

# 22. PATRULHAS

Criar uma das telas visualmente mais importantes.

Layout possível:

```text
PATRULHAS ATIVAS                         FILA

PTR 01                                  01 João
────────────────                        02 Carlos
SGT João                                03 Pedro
SD Lucas
SD Marcos

01h24
Patrulha 1


PTR 02
────────────────
CB Pedro
SD André

42min
Patrulha 2
```

---

# 23. PATRULHAS NÃO DEVEM PARECER CARDS DE E-COMMERCE

Utilizar:

* linhas;
* headers;
* bordas;
* status;
* pequenos identificadores operacionais.

Evitar:

* cards enormes arredondados;
* sombras;
* emojis grandes.

---

# 24. FILA DE PATRULHA

Mostrar:

```text
AGUARDANDO PATRULHA

POS  MEMBRO              TEMPO
01   [SD] João [152]     06m
02   [CB] Pedro [084]    04m
03   [SD] Marcos [191]   01m
```

Quando patrulha for formada:

lista atualiza em realtime.

---

# 25. REALTIME

Quando tecnicamente adequado, utilizar Supabase Realtime, WebSocket ou arquitetura equivalente existente.

Atualizar sem refresh:

* patrulhas;
* fila;
* pontos;
* prontidão;
* solicitações;
* status.

Não recarregar a página inteira.

---

# 26. BATE-PONTO

Tela:

# CONTROLE DE PONTO

Dividir entre:

```text
PONTOS ATIVOS
PONTOS RECENTES
PONTOS INVALIDADOS
```

Tabela:

```text
Membro
Início
Patrulha
Tempo válido
Mínimo
Status
```

Exemplo:

```text
João    20:42    PTR 01    01h22    15m    VÁLIDO
Pedro   21:31    PTR 03    11m      15m    PENDENTE
```

---

# 27. PONTO INVALIDADO

Visual:

```text
INVALIDADO
11m / 15m
```

Vermelho discreto.

Não use alerta visual exagerado.

---

# 28. EFETIVO

Página:

# EFETIVO

Tabela principal.

Campos:

```text
Identificação
Patente
ID
Status
Horas
Patrulhas
Última atividade
```

Ao clicar:

abrir página individual.

---

# 29. PERFIL DO MEMBRO

Não montar perfil como dezenas de cards.

Utilizar uma composição de dossiê.

Exemplo:

```text
[SGT] JOÃO SILVA [152]

SARGENTO
ATIVO

────────────────────────────────────────────

INGRESSO          TEMPO NA PATENTE
10/05/2026        41 dias

HORAS TOTAL       PATRULHAS
284h52            173

────────────────────────────────────────────

VISÃO GERAL
ATIVIDADE
PATRULHAS
CARREIRA
CURSOS
DISCIPLINA
AUSÊNCIAS
HISTÓRICO
```

---

# 30. DOSSIÊ

Criar página ou drawer de:

# DOSSIÊ FUNCIONAL

Organizado como documento institucional.

Seções:

```text
01 IDENTIFICAÇÃO
02 SITUAÇÃO FUNCIONAL
03 ATIVIDADE
04 CARREIRA
05 QUALIFICAÇÕES
06 DISCIPLINA
07 AUSÊNCIAS
08 HISTÓRICO
```

Pode utilizar numeração para reforçar identidade documental.

---

# 31. CARREIRA

Timeline vertical.

Exemplo:

```text
21 AGO 2026
SARGENTO
Promoção

04 JUL 2026
CABO
Promoção

28 MAI 2026
SOLDADO
Promoção

10 MAI 2026
RECRUTA
Ingresso
```

---

# 32. ELEGIBILIDADE DE PROMOÇÃO

Tela:

```text
ANÁLISE DE ELEGIBILIDADE
```

Mostrar requisitos como checklist institucional:

```text
Tempo mínimo na patente               ATENDIDO
Horas mínimas                         ATENDIDO
Formação obrigatória                  ATENDIDO
Curso de Choque                       ATENDIDO
Advertência bloqueante                NENHUMA
Meta recente                          ATENDIDO
```

Resultado:

```text
SITUAÇÃO
ELEGÍVEL PARA ANÁLISE
```

Nunca usar:

```text
PROMOVER AUTOMATICAMENTE
```

---

# 33. PROMOÇÃO PELO SITE

Somente para usuários autorizados.

Fluxo:

```text
Selecionar nova patente
↓
Motivo
↓
Resumo da alteração
↓
Confirmar
```

Antes da confirmação:

```text
[SGT] João [152]

Sargento
↓
Subtenente
```

Após confirmação:

backend deve coordenar:

* banco;
* Discord;
* cargo;
* nickname;
* histórico;
* auditoria.

---

# 34. MATRIZ DE QUALIFICAÇÃO

Página dedicada.

Utilizar tabela.

Exemplo:

```text
MEMBRO          FORMAÇÃO   CHOQUE   INSTRUTOR   RECRUTADOR

João               ●          ●          —            ●
Pedro              ●          ●          ●            —
Lucas              ●          —          —            —
```

Legenda discreta.

Não utilizar 40 emojis.

---

# 35. CURSOS

Página:

# CURSOS E TREINAMENTOS

Mostrar:

* próximos treinamentos;
* cursos existentes;
* requisitos;
* inscritos;
* histórico.

Cada curso pode exibir:

```text
CURSO DE CHOQUE

Status
Ativo

Patente mínima
Soldado

Horas mínimas
20h

Pré-requisito
Formação
```

---

# 36. RECRUTAS

Página:

# ACOMPANHAMENTO DE RECRUTAS

Tabela:

```text
Recruta
Ingresso
Horas
Patrulhas
Cursos
Avaliações
Situação
```

Status:

```text
EM FORMAÇÃO
PENDENTE
APTO PARA ANÁLISE
```

---

# 37. DISCIPLINA

Tela restrita.

Não usar estética agressiva.

Estrutura:

```text
OCORRÊNCIAS
ADVERTÊNCIAS
SUSPENSÕES
HISTÓRICO
```

Tabela limpa.

---

# 38. CAIXA DE ENTRADA ADMINISTRATIVA

Essa deverá ser uma das páginas mais importantes.

Layout inspirado em:

* inbox;
* central administrativa;
* sistema de processos.

Estrutura:

```text
CAIXA DE ENTRADA

17 PENDÊNCIAS

TODAS             17
AUSÊNCIAS          5
PONTO              2
TREINAMENTOS       4
RECRUTAMENTO       3
DISCIPLINA         1
OUTROS             2
```

---

# 39. LISTA DA INBOX

Exemplo:

```text
#ABS-0192

AUSÊNCIA

João Silva
25 AGO → 30 AGO

Criado há 2h

PENDENTE
```

Ao selecionar:

mostrar detalhes ao lado.

Não abrir modal gigante para tudo.

---

# 40. PAINEL LATERAL DE DECISÃO

Desktop:

```text
LISTA                DETALHES
────────────────────────────────────────

#ABS-0192             JOÃO SILVA
João Silva            Ausência
Ausência
                      25/08 → 30/08
                      Motivo: Viagem

                      [ APROVAR ]
                      [ NEGAR ]
```

Isso dará sensação de aplicação administrativa real.

---

# 41. HISTÓRICO DE DECISÕES

Página:

# DECISÕES ADMINISTRATIVAS

Tabela:

```text
Data
Ação
Membro
Responsável
Origem
Resultado
```

Permitir filtros.

---

# 42. O QUE MUDOU?

Página:

# O QUE MUDOU?

Essa tela deve parecer um briefing operacional.

Exemplo:

```text
PERÍODO
15 AGO — 22 AGO

EFETIVO
+8 ingressos
-2 desligamentos

CARREIRA
5 promoções
1 rebaixamento

ATIVIDADE
217h patrulhadas
96 patrulhas

DISCIPLINA
2 advertências
1 suspensão

TREINAMENTO
19 qualificações concluídas
```

Abaixo:

timeline das principais mudanças.

---

# 43. CENTRAL DE IDENTIDADE

Página:

# INTEGRIDADE DE IDENTIDADE

Mostrar:

```text
121
IDENTIDADES CORRETAS

4
NICKNAMES DIVERGENTES

2
PATENTES INCONSISTENTES

1
MEMBRO SEM ID
```

Depois tabela dos problemas.

---

# 44. AÇÃO EM LOTE

Exemplo:

```text
4 correções seguras disponíveis.

[ REVISAR ALTERAÇÕES ]

[ SINCRONIZAR ]
```

Nunca executar correções sensíveis sem confirmação.

---

# 45. RELATÓRIOS

Evite criar uma página com 30 gráficos.

Comece com informação operacional.

Exemplo:

```text
ATIVIDADE — 30 DIAS

Horas
2.482h

Patrulhas
1.204

Média
2h03

Pontos invalidados
31
```

Depois gráficos realmente úteis.

---

# 46. GRÁFICOS

Utilizar com moderação.

Possíveis:

* horas por dia;
* patrulhas por semana;
* cumprimento de meta;
* evolução do efetivo;
* treinamentos concluídos.

Não usar gráfico para dados que uma tabela explica melhor.

---

# 47. GRÁFICOS DEVEM SEGUIR O DESIGN SYSTEM

Nada de:

* arco-íris;
* neon;
* gradiente chamativo;
* donut chart em todo canto.

Utilizar tons institucionais.

---

# 48. CONFIGURAÇÕES

Essa página deverá ser muito boa.

Categorias:

```text
GERAL
DISCORD
PATRULHAS
BATE-PONTO
PATENTES
CARGOS
CANAIS
TREINAMENTOS
PERMISSÕES
MÓDULOS
```

---

# 49. CONFIGURAÇÃO DE PATRULHA

Exemplo:

```text
FORMAÇÃO AUTOMÁTICA

Mínimo por patrulha
[ 2 ]

Máximo
[ 4 ]

Call de espera
[ Aguardando Patrulha ▼ ]

Prioridade
[ Completar patrulhas existentes ▼ ]
```

---

# 50. CONFIGURAÇÃO DO PONTO

```text
TEMPO MÍNIMO

[ 15 ] minutos

Grace period
[ 60 ] segundos
```

---

# 51. CONFIGURAÇÃO DE PATENTES

Tabela:

```text
NÍVEL  PATENTE       SIGLA    CARGO DISCORD

01     Recruta       RCT      @Recruta
02     Soldado       SD       @Soldado
03     Cabo          CB       @Cabo
04     Sargento      SGT      @Sargento
```

Permitir:

* editar;
* reordenar;
* adicionar.

---

# 52. CONFIGURAÇÃO DE CANAIS

Buscar canais reais do Discord através do backend.

Não exigir IDs manuais.

Exemplo:

```text
Call de espera
[ 🔊 Aguardando Patrulha ]

Painel de ponto
[ # Bate Ponto ]

Logs
[ # Registros Sup ]
```

---

# 53. MODO DE MANUTENÇÃO

Página:

# CONTROLE DE MÓDULOS

```text
BATE-PONTO
OPERACIONAL

PATRULHAS
OPERACIONAL

TREINAMENTOS
MANUTENÇÃO

RECRUTAMENTO
OPERACIONAL
```

Clicar abre configuração.

---

# 54. MODO MANUTENÇÃO VISUAL

Utilizar indicador forte porém sóbrio.

Exemplo:

```text
TREINAMENTOS

MANUTENÇÃO

Motivo
Atualização interna

Desde
21:32
```

---

# 55. AUDITORIA

Página:

# AUDITORIA DO SISTEMA

Filtros:

```text
Ação
Responsável
Membro
Origem
Período
```

Tabela:

```text
22/08 01:32
PROMOÇÃO

João
Soldado → Cabo

Responsável
Mateus

Origem
Dashboard
```

---

# 56. ORIGEM DA AÇÃO

Diferenciar:

```text
DISCORD
DASHBOARD
AUTOMAÇÃO
RECONCILIAÇÃO
```

Visualmente de forma discreta.

---

# 57. COMPONENTES

Crie componentes reutilizáveis.

Exemplos:

```text
OperationalStatus
MemberIdentity
RankBadge
StatusIndicator
DataTable
Timeline
FilterBar
MetricStrip
SectionHeader
DecisionPanel
AuditEntry
PatrolRow
QualificationMatrix
EmptyState
ConfirmationDialog
```

Não criar um componente gigante para cada página.

---

# 58. BOTÕES

Botões devem possuir hierarquia.

## Primário

Ação principal.

Exemplo:

```text
APROVAR
SALVAR ALTERAÇÕES
```

## Secundário

```text
CANCELAR
VER DETALHES
```

## Destrutivo

```text
SUSPENDER
REBAIXAR
DESLIGAR
```

Nunca fazer todos os botões com mesma importância visual.

---

# 59. BORDAS

Preferir:

* 1px;
* contraste discreto;
* radius baixo.

Exemplo:

```text
4px
6px
8px
```

Evitar:

```text
16px
24px
999px
```

em componentes principais.

---

# 60. PILLS

Pills são aceitáveis para pequenos statuses.

Exemplo:

```text
ATIVO
AUSENTE
PENDENTE
```

Mas não transformar todo texto em pill.

---

# 61. SOMBRAS

Utilizar minimamente.

A separação deverá vir principalmente de:

* superfície;
* borda;
* espaço;
* hierarquia.

Não de sombras enormes.

---

# 62. ÍCONES

Use ícones somente quando melhorarem reconhecimento.

Não coloque ícone em:

* cada título;
* cada label;
* cada célula;
* cada botão.

Evite estética de template.

---

# 63. MICROINTERAÇÕES

Permitidas:

* hover discreto;
* focus;
* mudança de status;
* skeleton;
* transição curta.

Não utilizar animações cinematográficas.

Duração:

```text
120–220ms
```

em geral.

---

# 64. LOADING

Não bloquear a página inteira para pequenas ações.

Utilizar:

* skeleton;
* estado no botão;
* atualização otimista quando segura.

---

# 65. EMPTY STATES

Nada de ilustrações genéricas.

Exemplo:

```text
NENHUMA PATRULHA ATIVA

As calls de patrulhamento estão disponíveis.
```

---

# 66. ERROS

Mensagem clara:

```text
Não foi possível atualizar a patente.

O cargo do bot está abaixo do cargo deste membro no Discord.
```

Não:

```text
Algo deu errado.
```

---

# 67. CONFIRMAÇÕES IMPORTANTES

Para:

* promoção;
* rebaixamento;
* suspensão;
* desligamento;
* ajuste de horas;
* sincronização em massa.

Mostrar:

```text
AÇÃO
ALVO
ANTES
DEPOIS
MOTIVO
```

antes de confirmar.

---

# 68. RESPONSIVIDADE

O sistema é prioritariamente administrativo e provavelmente será utilizado bastante em desktop.

Portanto:

# DESKTOP-FIRST, MAS RESPONSIVO.

No mobile:

* sidebar vira drawer;
* tabelas importantes podem virar listas;
* ações continuam acessíveis;
* não simplesmente comprimir tabela desktop.

---

# 69. BREAKPOINTS

Adapte corretamente para:

* desktop grande;
* notebook;
* tablet;
* smartphone.

Teste pelo menos:

```text
1440
1280
1024
768
390
```

---

# 70. ACESSIBILIDADE

Mesmo com estética militar escura:

* contraste AA;
* focus visível;
* teclado;
* labels;
* aria;
* estados não dependentes apenas de cor;
* touch targets adequados.

---

# 71. SUPABASE

Supabase será utilizado como banco principal.

O frontend NÃO deve receber credenciais administrativas do banco.

Nunca expor:

```text
service_role
DATABASE_URL
```

no navegador.

---

# 72. RAILWAY

Aplicações backend/bot poderão ficar no Railway.

O frontend deverá consumir API segura.

Fluxo:

```text
BROWSER
↓
WEB APP
↓
API
↓
SUPABASE
```

Para ações Discord:

```text
WEB
↓
API
↓
CORE
↓
DISCORD
```

---

# 73. NÃO DUPLICAR REGRA DE NEGÓCIO

O frontend NÃO decide:

```text
se membro pode ser promovido
```

Ele pergunta ao backend/core.

O frontend apresenta o resultado.

---

# 74. EXEMPLO CORRETO

```text
GET /members/152/promotion-eligibility
```

Retorno conceitual:

```text
eligible
requirements[]
```

Frontend renderiza.

Não recalcular tudo independentemente no React.

---

# 75. REALTIME E EVENTOS

Mudanças feitas no Discord devem aparecer no site.

Exemplo:

```text
@Soldado → @Cabo
```

Bot:

```text
detecta
↓
atualiza banco
```

Site:

```text
recebe atualização
↓
Cabo
```

---

# 76. AÇÃO DO SITE NO DISCORD

Exemplo:

```text
Dashboard
↓
Promover
↓
API
↓
Core
↓
Banco
↓
Discord Bot
↓
Cargo alterado
↓
Nickname alterado
↓
Auditoria
```

A UI deverá indicar:

```text
Sincronizado com Discord
```

quando concluído.

---

# 77. ESTADO PENDENTE

Caso banco atualize mas Discord fique indisponível:

mostrar status:

```text
SINCRONIZAÇÃO PENDENTE
```

Não fingir que tudo foi concluído.

---

# 78. ROTAS SUGERIDAS

Estrutura conceitual:

```text
/login

/dashboard

/readiness

/patrols
/patrols/:id

/shifts

/members
/members/:id

/recruits

/career

/qualifications
/trainings

/requests
/inbox

/discipline

/identity

/reports

/changes

/audit

/settings
/settings/general
/settings/discord
/settings/patrol
/settings/shifts
/settings/ranks
/settings/permissions

/maintenance
```

Adapte conforme arquitetura.

---

# 79. NAVEGAÇÃO

Não colocar todas as páginas na sidebar simultaneamente se ficar grande.

Use grupos recolhíveis com moderação.

O usuário precisa saber onde está.

---

# 80. BUSCA GLOBAL

Se fizer sentido:

campo discreto para encontrar rapidamente:

* membro;
* ID;
* patrulha;
* solicitação.

Não precisa criar command palette sofisticada sem necessidade.

---

# 81. DESIGN DE DADOS

Os dados são parte central desta aplicação.

Priorize:

* tabelas;
* listas;
* timelines;
* métricas;
* filtros;
* estados.

Não esconda tudo dentro de cards decorativos.

---

# 82. DENSIDADE

Dashboard administrativo pode ser moderadamente denso.

Não tenha medo de mostrar informação.

Mas preserve:

* alinhamento;
* hierarquia;
* espaçamento consistente.

---

# 83. GRID

Utilizar grid baseado em sistema consistente.

Evitar layouts perfeitamente simétricos quando a importância dos blocos é diferente.

Exemplo:

Patrulhas ativas podem ocupar:

```text
2/3
```

e pendências:

```text
1/3
```

---

# 84. DETALHES MILITARES SUTIS

Pode utilizar elementos como:

* numeração `01`, `02`, `03`;
* identificadores `PTR-001`;
* linhas técnicas;
* labels compactos;
* pequenos marcadores;
* divisores;
* timestamp;
* status operacional;
* monoespaçada para IDs quando apropriado.

Exemplo:

```text
PTR-0042
21:42:18
OPERACIONAL
```

Isso ajuda muito mais na temática do que camuflagem.

---

# 85. NÃO EXAGERAR NO MONO

Fonte monoespaçada apenas para:

* IDs;
* timestamps;
* códigos;
* audit IDs.

Não utilizar no site inteiro.

---

# 86. LINGUAGEM

Interface em:

# PORTUGUÊS DO BRASIL

Tom:

* direto;
* institucional;
* simples.

Exemplo:

```text
Patrulha formada
```

Não:

```text
Sua incrível patrulha foi criada com sucesso!
```

---

# 87. NOMES DE STATUS

Manter consistência.

Exemplo:

```text
ATIVO
AUSENTE
SUSPENSO
RESERVA
EM FORMAÇÃO
DESLIGADO
```

Não alternar entre sinônimos em páginas diferentes.

---

# 88. PERFORMANCE

Evitar:

* carregar histórico inteiro;
* queries duplicadas;
* rerenders desnecessários;
* subscriptions globais desnecessárias;
* bibliotecas gigantes para efeito visual.

Aplicar:

* paginação;
* caching;
* lazy loading;
* server rendering quando adequado;
* streaming quando útil.

---

# 89. SEO

Não é prioridade.

Este é um sistema autenticado.

Priorize:

* segurança;
* UX;
* performance;
* confiabilidade.

---

# 90. SEGURANÇA

Nunca confiar em:

```text
disabled button
hidden menu
frontend role
```

como segurança.

Backend valida autorização.

---

# 91. DADOS SENSÍVEIS

Disciplina, feedback e histórico administrativo devem possuir acesso restrito.

Nunca carregar dados que o usuário não tem autorização para visualizar apenas para escondê-los no frontend.

---

# 92. NÃO INVENTAR DADOS

Durante desenvolvimento:

utilize fixtures claramente identificadas quando necessário.

Não misture mock com produção.

Prepare estados reais:

* loading;
* empty;
* success;
* error;
* partial sync.

---

# 93. DESIGN REVIEW OBRIGATÓRIO

Depois de implementar cada página importante:

faça uma revisão visual.

Pergunte:

1. Isso parece um template genérico?
2. Tem cards demais?
3. Tem radius demais?
4. Há informação suficiente?
5. A hierarquia está clara?
6. Parece um sistema da CHOQUE?
7. A temática está sutil ou caricata?
8. Existe algum elemento sem função?
9. Mobile funciona?
10. Um superior entende a tela sem treinamento?

Se alguma resposta indicar problema:

refine antes de seguir.

---

# 94. PÁGINAS PRIORITÁRIAS

Implemente nesta ordem:

## FASE 1 — FUNDAÇÃO

* Frontend Design Skill;
* design tokens;
* tipografia;
* layout;
* sidebar;
* topbar;
* autenticação;
* RBAC.

## FASE 2 — OPERAÇÃO

* Dashboard;
* Prontidão;
* Patrulhas;
* Fila;
* Bate-ponto.

## FASE 3 — EFETIVO

* Lista de membros;
* Perfil;
* Dossiê;
* Carreira;
* Qualificações.

## FASE 4 — ADMINISTRAÇÃO

* Caixa de Entrada;
* Solicitações;
* Disciplina;
* Recrutas;
* Treinamentos.

## FASE 5 — INTELIGÊNCIA

* O que mudou?;
* Relatórios;
* Auditoria;
* Identidade.

## FASE 6 — SISTEMA

* Configurações;
* Patentes;
* Calls;
* Permissões;
* Modo manutenção.

---

# 95. QUALIDADE DE CÓDIGO

Utilize:

* TypeScript estrito;
* componentes pequenos;
* hooks focados;
* validação;
* tratamento de erro;
* loading states;
* boas boundaries;
* estrutura consistente.

Não criar:

```text
Dashboard.tsx
4000 linhas
```

---

# 96. COMPONENT LIBRARY

É permitido utilizar primitives/library existente no projeto.

Porém:

# NÃO ACEITE O VISUAL PADRÃO DA BIBLIOTECA.

Customize:

* radius;
* border;
* typography;
* colors;
* spacing;
* states.

O resultado não pode parecer uma demonstração de biblioteca de componentes.

---

# 97. ÍCONES E ASSETS

Não buscar ícones decorativos aleatórios.

Utilize um conjunto coerente.

Se houver assets oficiais da corporação no repositório:

prefira-os.

---

# 98. NÃO GERAR IMAGENS DECORATIVAS DESNECESSÁRIAS

Não crie:

* soldados genéricos;
* tropas;
* armas;
* helicópteros;
* background militar;

apenas para preencher tela.

O próprio sistema deve ser o protagonista.

---

# 99. TESTES VISUAIS

Validar:

* Chrome;
* Firefox ou equivalente;
* desktop;
* mobile;
* dark theme;
* zoom 125%;
* textos longos;
* tabelas grandes;
* estados vazios.

---

# 100. TESTES FUNCIONAIS IMPORTANTES

Testar:

* login;
* logout;
* autorização;
* refresh;
* realtime;
* erro da API;
* Discord offline;
* Supabase indisponível;
* atualização concorrente;
* ação administrativa;
* confirmação;
* paginação;
* filtros.

---

# 101. NÃO IMPLEMENTAR TELA FALSA

Se backend de determinada função ainda não existir:

não fingir funcionalidade.

Pode criar UI com estado:

```text
Integração pendente
```

somente quando solicitado.

Mas priorize integrar com funcionalidades reais já existentes.

---

# 102. DASHBOARD NÃO É LANDING PAGE

Nunca iniciar o dashboard com:

```text
Bem-vindo ao futuro da gestão da CHOQUE
```

ou:

```text
Controle total. Eficiência máxima.
```

Começar imediatamente com informação operacional.

Exemplo:

```text
CENTRO DE COMANDO
22 AGO 2026 • 01:42

STATUS OPERACIONAL
```

---

# 103. REFERÊNCIA DE SENSAÇÃO

Ao entrar no site, quero sentir:

```text
"Este é um sistema interno de uma corporação."
```

e não:

```text
"Este é um template bonito de SaaS."
```

---

# 104. PERSONALIDADE DA INTERFACE

A interface deverá ser:

```text
SÓBRIA
PRECISA
TÁTICA
DENSA NA MEDIDA CERTA
INSTITUCIONAL
FUNCIONAL
```

Nunca:

```text
FOFA
COLORIDA
FUTURISTA
GAMER
NEON
EXAGERADA
```

---

# 105. EXEMPLO DE CABEÇALHO

Algo conceitualmente próximo de:

```text
CHOQUE BGR / CENTRO DE COMANDO

EFETIVO OPERACIONAL
22 AGO 2026 • 01:42

● SISTEMA OPERACIONAL
● DISCORD CONECTADO
```

Sem hero.

Sem slogan.

---

# 106. EXEMPLO DE DASHBOARD COMPLETO

```text
CHOQUE BGR / CENTRO DE COMANDO

STATUS OPERACIONAL
─────────────────────────────────────────────────
EFETIVO 128 │ PATRULHA 18 │ FILA 6 │ AUSENTES 12


PATRULHAS EM ANDAMENTO                    PENDÊNCIAS
──────────────────────────               ──────────────

PTR-01                                   Ausências       5
SGT João                                 Correções       2
SD Lucas                                 Avaliações      4
01h24                                    Recrutas        3

PTR-02
CB Pedro
SD Marcos
42m


ATIVIDADE RECENTE
─────────────────────────────────────────────────

01:32  João       Soldado → Cabo
01:21  Lucas      Patrulha finalizada      01h42
01:09  Pedro      Ausência aprovada
00:58  Carlos     Curso concluído
```

Essa é apenas uma direção.

Use a Frontend Design Skill para refiná-la.

---

# 107. NÃO COPIAR O EXEMPLO LITERALMENTE

Os layouts fornecidos neste prompt são referências de hierarquia e comportamento.

A skill de Frontend Design deverá ser usada para chegar à melhor composição.

Não implemente tudo literalmente se existir uma solução visual melhor.

---

# 108. ENTREGA

Ao concluir uma fase, informe:

### Implementado

### Componentes criados

### Rotas criadas

### Integrações utilizadas

### Estados tratados

### Responsividade

### Acessibilidade

### Testes realizados

### Pendências

---

# 109. SCREENSHOTS

Ao finalizar as principais páginas:

gere ou capture screenshots através das ferramentas disponíveis para realizar revisão visual.

Analise criticamente:

* alinhamento;
* densidade;
* contraste;
* aparência genérica;
* consistência;
* temática.

Refine antes de considerar concluído.

---

# 110. REGRA FINAL

Este projeto não deve parecer um frontend criado rapidamente por um agente.

Não quero:

```text
template + verde + logo = temática militar
```

Quero uma linguagem visual própria.

O design deve demonstrar que houve intenção em:

* cada espaçamento;
* cada linha;
* cada estado;
* cada tabela;
* cada cor;
* cada ação;
* cada hierarquia.

A temática militar da CHOQUE deve surgir principalmente através de:

**disciplina visual, precisão, estrutura, tipografia, densidade, nomenclatura e informação operacional.**

E não através de decoração temática excessiva.

O resultado final deverá parecer um:

# SISTEMA INTERNO DE COMANDO E GESTÃO DA CHOQUE - BGR

integrado ao bot Discord e ao mesmo banco de dados do projeto, com experiência visual própria, profissional e reconhecível.
