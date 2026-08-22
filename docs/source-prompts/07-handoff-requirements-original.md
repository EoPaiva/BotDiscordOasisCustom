Analise **todo o repositório atual deste projeto** e gere na raiz um arquivo chamado:

`PROJECT_HANDOFF.md`

Esse arquivo será utilizado para transferir o desenvolvimento para outra conta/agente do Codex. Portanto, ele deve funcionar como uma **fotografia técnica fiel do estado atual do projeto**, permitindo que outro agente continue exatamente de onde paramos.

## Regra principal

NÃO escreva o `PROJECT_HANDOFF.md` com base apenas no README, comentários ou documentação existente.

Você deve inspecionar o **código real**.

O repositório é a fonte de verdade.

Antes de gerar o arquivo, faça uma auditoria completa de tudo que estiver disponível no projeto.

Analise, quando existirem:

* estrutura completa de diretórios;
* `package.json`;
* workspaces/monorepo;
* frontend;
* backend;
* Discord Bot;
* handlers;
* events;
* commands;
* buttons;
* selects;
* modals;
* persistent messages;
* services;
* repositories;
* controllers;
* APIs;
* middlewares;
* schemas;
* validações;
* sistema de permissões;
* autenticação;
* banco de dados;
* migrations;
* seeds;
* Supabase;
* PostgreSQL;
* RLS;
* triggers;
* functions;
* jobs;
* workers;
* queues;
* cron jobs;
* realtime;
* Railway;
* Docker;
* arquivos de deploy;
* `.env.example`;
* variáveis de ambiente referenciadas pelo código;
* integrações externas;
* testes;
* scripts;
* logs;
* auditoria;
* documentação;
* TODO;
* FIXME;
* HACK;
* código comentado relevante;
* features parcialmente implementadas.

Não exponha valores reais de secrets.

---

# OBJETIVO DO DOCUMENTO

O próximo agente deverá conseguir abrir o projeto, ler o `PROJECT_HANDOFF.md` e responder rapidamente:

1. O que é este sistema?
2. Como ele está arquitetado?
3. Como o Discord Bot funciona?
4. Como o painel web funciona?
5. Como bot, backend, banco e site se comunicam?
6. O que já está pronto?
7. O que está parcialmente pronto?
8. O que ainda não existe?
9. Onde estão as partes importantes do código?
10. Quais decisões arquiteturais já foram tomadas?
11. Quais problemas ainda existem?
12. Qual era o próximo passo lógico do desenvolvimento?
13. O que ele NÃO deve quebrar ou reescrever?
14. Como executar, testar e validar o projeto?

---

# MUITO IMPORTANTE — DISCORD BOT

Dê atenção especial ao Discord Bot.

O próximo agente precisa conseguir continuar **todo o desenvolvimento do bot**, e não apenas o site.

Documente detalhadamente a arquitetura real encontrada para o Discord.

Inclua:

* entrypoint do bot;
* inicialização do Discord client;
* intents utilizadas;
* partials, caso existam;
* loaders;
* registro de eventos;
* registro de interactions;
* estrutura de handlers;
* buttons;
* select menus;
* modals;
* commands, caso existam;
* mensagens persistentes;
* canais utilizados;
* categorias utilizadas;
* calls/canais de voz;
* movimentação automática de usuários;
* cargos;
* permissões;
* sincronização de cargos;
* regras de acesso;
* filas;
* patrulhas;
* logs;
* auditoria;
* tratamento de erros;
* reconnect;
* rate limits;
* proteção contra processamento duplicado;
* estado mantido em memória;
* estado persistido no banco.

Para cada módulo importante do bot, informe o arquivo ou diretório correspondente.

Exemplo:

`src/bot/interactions/patrol/joinPatrol.ts`

Função:
Entrada de membro na fila de patrulhamento.

Fluxo:
interaction → validação → service → banco → matching → Discord voice → audit.

Não invente caminhos. Use somente os encontrados no projeto.

---

# CENTRAL DE PATRULHA

Se estiver implementada ou parcialmente implementada, documente toda a lógica da Central de Patrulha.

Explique o fluxo real de:

* entrada na fila;
* saída da fila;
* quantidade mínima de membros;
* formação da patrulha;
* busca por call vazia;
* criação/utilização da call;
* movimentação dos usuários;
* registro da patrulha;
* encerramento;
* desconexões;
* abandono;
* falhas durante movimentação;
* estado no banco;
* proteção contra duas patrulhas pegarem o mesmo membro;
* proteção contra double click;
* concorrência.

Informe explicitamente o que está:

* `IMPLEMENTADO`;
* `PARCIAL`;
* `NÃO IMPLEMENTADO`.

---

# FUNCIONALIDADES DO PROJETO

Procure no código e documente o estado real de funcionalidades como:

* Central de Patrulha Inteligente;
* fila de formação;
* patrulhas ativas;
* validação de ponto;
* prontidão do efetivo;
* disponibilidade;
* escala;
* troca de escala;
* troca de atividade;
* matriz de qualificação;
* cursos;
* requisitos automáticos;
* elegibilidade para promoção;
* promoções;
* dossiê funcional;
* acompanhamento de recrutas;
* auditoria;
* administração;
* configurações Discord;
* painel web;
* dashboards;
* notificações.

Caso alguma dessas funcionalidades não exista no código, marque como:

`NÃO IMPLEMENTADO`

Não diga que está implementado apenas porque existe uma página vazia, um botão sem backend ou um schema ainda não utilizado.

---

# CLASSIFICAÇÃO DE ESTADO

Use obrigatoriamente quatro estados:

### IMPLEMENTADO

Funcionalidade realmente integrada e utilizável.

### PARCIAL

Existe código relevante, mas o fluxo ainda não está completo.

### NÃO IMPLEMENTADO

Não existe implementação funcional.

### PROBLEMA IDENTIFICADO

Existe uma implementação, mas contém bug, inconsistência, dívida técnica ou risco.

Não confunda frontend visual com implementação completa.

Exemplo:

Página de cursos existe, mas API não existe:

`PARCIAL`

---

# ESTRUTURA OBRIGATÓRIA DO PROJECT_HANDOFF.md

O documento deve seguir aproximadamente esta estrutura:

# PROJECT HANDOFF

## 1. Resumo Executivo

Explique resumidamente o objetivo do projeto e seu estado atual.

---

## 2. Arquitetura Geral

Inclua um diagrama textual, por exemplo:

```text
Discord
   │
   ▼
Discord Bot
   │
   ▼
Domain/Services
   │
   ├────────► PostgreSQL / Supabase
   │
   └────────► Audit / Jobs / Realtime
                  ▲
                  │
Panel Web ────────┘
```

O diagrama deve representar a arquitetura REAL encontrada.

---

## 3. Stack Encontrada

Liste tecnologias e versões importantes encontradas.

Exemplo:

* Node.js
* TypeScript
* discord.js
* Next.js
* React
* Supabase
* PostgreSQL
* Railway

Inclua somente tecnologias realmente utilizadas.

---

## 4. Estrutura do Repositório

Apresente uma árvore simplificada das áreas relevantes.

Não precisa listar `node_modules`, builds ou arquivos irrelevantes.

Explique o propósito de cada diretório importante.

---

## 5. Como o Projeto Inicializa

Explique os entrypoints.

Inclua:

* bot;
* frontend;
* backend;
* workers;
* jobs.

Informe os scripts existentes para execução.

---

## 6. Arquitetura do Discord Bot

Esta seção deve ser especialmente detalhada.

Explique toda a arquitetura encontrada.

---

## 7. Interactions do Discord

Crie uma tabela como:

| Interaction | Tipo | Arquivo | Função | Estado |
| ----------- | ---- | ------- | ------ | ------ |

Liste:

* buttons;
* selects;
* modals;
* commands;
* outros interactions.

---

## 8. Eventos do Discord

Tabela:

| Evento | Arquivo | Responsabilidade |
| ------ | ------- | ---------------- |

Exemplos possíveis:

* ready;
* interactionCreate;
* voiceStateUpdate;
* guildMemberUpdate;
* guildMemberRemove.

Somente os realmente encontrados.

---

## 9. Mensagens Persistentes

Documente mensagens fixas/controladas pelo bot.

Inclua:

* finalidade;
* canal;
* IDs/configuração utilizados;
* componentes;
* comportamento;
* como são recriadas ou atualizadas.

---

## 10. Sistema de Patrulha

Descreva o fluxo completo encontrado.

Inclua pseudofluxo.

---

## 11. Sistema de Voz

Explique como o bot trabalha com canais de voz.

Inclua:

* fila;
* calls;
* movimentação;
* criação;
* limpeza;
* encerramento;
* tratamento de desconexão.

---

## 12. Banco de Dados

Liste tabelas importantes.

Formato recomendado:

### `nome_da_tabela`

Objetivo:

Relacionamentos:

Campos relevantes:

Usada por:

RLS:

Observações:

Não precisa copiar todo o SQL se não for necessário.

---

## 13. Migrations

Informe:

* sistema utilizado;
* diretório;
* migrations importantes;
* migration mais recente encontrada;
* mudanças estruturais ainda pendentes, se identificadas.

Nunca delete migrations.

---

## 14. Modelo de Permissões

Explique exatamente como autorização funciona atualmente.

Inclua:

* cargos Discord;
* roles internas;
* RBAC;
* middleware;
* helpers;
* guards;
* RLS.

Liste vulnerabilidades caso encontre.

---

## 15. Autenticação do Painel

Explique:

* login;
* sessão;
* OAuth;
* Discord OAuth, se utilizado;
* Supabase Auth;
* callbacks;
* logout;
* autorização.

---

## 16. Frontend

Explique:

* estrutura;
* layouts;
* páginas;
* componentes;
* dashboard;
* módulos administrativos;
* chamadas para backend.

---

## 17. Backend / API

Liste endpoints relevantes.

Tabela:

| Método | Endpoint | Arquivo | Autorização | Função |
| ------ | -------- | ------- | ----------- | ------ |

Caso não exista API separada, explique a arquitetura encontrada.

---

## 18. Services / Domain

Liste os principais services.

Explique onde está a regra de negócio.

Identifique duplicações entre bot e site.

---

## 19. Realtime / Eventos

Se houver Supabase Realtime, WebSockets, Pub/Sub ou mecanismo similar, documente.

---

## 20. Jobs / Workers / Filas

Documente processamento assíncrono existente.

---

## 21. Auditoria

Explique:

* quais ações são auditadas;
* tabela;
* função/helper;
* dados registrados;
* pontos sem auditoria que deveriam possuir.

---

## 22. Logs e Observabilidade

Explique o sistema encontrado.

---

## 23. Variáveis de Ambiente

Liste os NOMES das env vars utilizadas.

Exemplo:

```env
DISCORD_BOT_TOKEN=
SUPABASE_URL=
```

NUNCA coloque valores reais.

Para cada uma, informe brevemente sua finalidade.

Marque quais existem no código mas estão ausentes do `.env.example`.

---

## 24. Infraestrutura

Documente Railway, Vercel, Docker, Supabase ou qualquer outra infraestrutura encontrada.

Inclua arquivos responsáveis.

---

## 25. Segurança

Faça uma análise específica.

Separe:

### Já implementado

### Problemas encontrados

### Melhorias recomendadas

Verifique especialmente:

* autorização no backend;
* secrets;
* RLS;
* IDOR;
* mass assignment;
* validation;
* injection;
* XSS;
* CSRF;
* rate limiting;
* Discord permissions;
* spoof de IDs;
* replay;
* double interaction;
* concorrência.

---

## 26. Concorrência e Idempotência

Analise fluxos críticos.

Especialmente:

* entrar na fila;
* formar patrulha;
* encerrar patrulha;
* promover membro;
* trocar escala;
* processar interaction Discord.

Documente proteções existentes e riscos.

---

## 27. Estado das Funcionalidades

Crie uma tabela ampla:

| Módulo | Estado | Frontend | Backend | Banco | Discord | Observações |
| ------ | ------ | -------- | ------- | ----- | ------- | ----------- |

Use:

* IMPLEMENTADO
* PARCIAL
* NÃO IMPLEMENTADO
* PROBLEMA IDENTIFICADO

---

## 28. Funcionalidades Implementadas

Liste objetivamente.

---

## 29. Funcionalidades Parciais

Para cada uma, explique exatamente o que falta.

---

## 30. Funcionalidades Não Implementadas

Liste apenas funcionalidades esperadas pelo projeto mas ausentes do código.

---

## 31. Bugs Conhecidos Encontrados

Inclua bugs reais identificados durante inspeção.

Adicione:

* impacto;
* arquivos envolvidos;
* possível causa.

Não precisa corrigir neste momento, a menos que seja algo necessário para conseguir analisar o projeto.

---

## 32. Dívidas Técnicas

Liste:

* duplicação;
* código morto;
* arquivos gigantes;
* acoplamento;
* falta de types;
* TODO/FIXME;
* regras hardcoded;
* falta de testes;
* arquitetura inconsistente.

---

## 33. Decisões Arquiteturais Existentes

Documente decisões inferíveis pelo código.

Exemplo:

“O PostgreSQL é utilizado como fonte de verdade para o estado da patrulha.”

Não transforme sua preferência pessoal em decisão existente.

---

## 34. Regras de Negócio Descobertas

Liste regras importantes presentes no código.

Exemplo:

* membro não pode estar em duas patrulhas simultaneamente;
* determinada qualificação é exigida para função X.

Somente regras realmente encontradas.

---

## 35. Arquivos Mais Importantes

Crie uma seção:

### Leia estes arquivos primeiro

Liste aproximadamente 10–30 arquivos essenciais com descrição.

Isso será utilizado pelo próximo Codex para recuperar contexto rapidamente.

---

## 36. Fluxos Críticos

Documente fluxos end-to-end.

Exemplo:

### Entrada na fila de patrulha

```text
Discord button
→ interaction handler
→ authorization
→ PatrolQueueService
→ database
→ matcher
→ voice move
→ patrol record
→ audit
→ dashboard realtime
```

Use os nomes reais encontrados.

Documente vários fluxos quando houver.

---

## 37. Como Executar Localmente

Escreva os passos baseados no projeto atual.

Não invente comandos.

Use os scripts encontrados.

---

## 38. Como Testar

Inclua:

* lint;
* typecheck;
* unit;
* integration;
* E2E;
* build.

Somente comandos existentes ou claramente suportados.

---

## 39. Estado dos Testes

Informe:

* quantidade aproximada;
* áreas cobertas;
* áreas sem cobertura;
* testes quebrados, caso existam.

---

## 40. Último Estado Validado

Execute, se possível:

* install/verificação das dependências;
* typecheck;
* lint;
* testes;
* build.

Registre no documento:

```text
Typecheck: PASS
Lint: PASS
Tests: PASS (X tests)
Build: PASS
```

Ou:

```text
Build: FAIL
Motivo: ...
```

NUNCA diga PASS sem executar.

---

## 41. Próximas Prioridades

Com base no estado real do código, proponha uma ordem de continuidade.

Classifique:

### P0 — Crítico

### P1 — Alta

### P2 — Média

### P3 — Baixa

Priorize primeiro:

1. falhas de segurança;
2. corrupção/inconsistência de dados;
3. bugs críticos;
4. fluxos principais incompletos;
5. melhorias operacionais;
6. UI.

---

## 42. Próximo Passo Recomendado

Informe claramente qual deveria ser a próxima tarefa do próximo agente.

Se houver uma feature parcialmente implementada que claramente estava em desenvolvimento, dê preferência à continuidade dela.

---

## 43. Não Quebrar

Crie uma seção:

# NÃO QUEBRAR / NÃO REESCREVER SEM ANÁLISE

Liste componentes estáveis ou decisões importantes que o próximo agente deve preservar.

---

## 44. Cuidados ao Continuar

Exemplos:

* sempre utilizar migrations;
* nunca alterar Discord IDs manualmente;
* manter compatibilidade com interações persistentes;
* preservar tabelas utilizadas pelo bot;
* não duplicar regra de negócio no frontend.

Use os cuidados identificados no projeto real.

---

## 45. Pendências de Configuração Externa

Documente itens que não estejam no código mas sejam necessários.

Exemplos:

* Discord Developer Portal;
* OAuth redirect;
* Supabase config;
* Railway variables;
* channel IDs;
* role IDs.

Nunca inclua secrets reais.

---

## 46. Contexto para o Próximo Codex

Finalize com uma seção curta explicando:

* onde o projeto está;
* o que funciona;
* o que está sendo construído;
* onde continuar.

O objetivo é permitir que o próximo agente retome o desenvolvimento sem precisar reconstruir todo o contexto do zero.

---

# REGRAS DE QUALIDADE DO HANDOFF

O arquivo deve ser:

* objetivo;
* técnico;
* detalhado onde necessário;
* factual;
* navegável;
* atualizado com o código atual;
* útil para outro agente de programação.

Evite textos genéricos como:

“o sistema possui uma arquitetura robusta”.

Prefira:

“`PatrolQueueService` concentra a regra de entrada/saída da fila e persiste registros em `patrol_queue`.”

---

# NÃO INVENTAR

Se você não conseguir determinar algo pelo código, escreva:

`Não foi possível determinar a partir do repositório.`

Se algo depender de infraestrutura externa que você não consegue acessar, escreva isso explicitamente.

Não faça suposições silenciosas.

---

# NÃO IMPLEMENTAR FEATURES NOVAS AGORA

A tarefa principal neste momento é produzir o handoff.

Não comece grandes refactors.

Não adicione funcionalidades novas.

Não reorganize o repositório.

Não “melhore” a arquitetura antes de documentá-la.

Correções pequenas só devem ser realizadas se forem indispensáveis para executar/verificar o projeto, e qualquer alteração feita deve ser mencionada no handoff.

---

# VALIDAÇÃO FINAL OBRIGATÓRIA

Antes de finalizar:

1. releia o `PROJECT_HANDOFF.md`;
2. compare com o código;
3. confirme que o Discord Bot recebeu atenção suficiente;
4. confirme que features parciais não foram marcadas como concluídas;
5. confirme que nenhum secret real foi incluído;
6. confirme que caminhos citados realmente existem;
7. confirme que comandos documentados realmente existem;
8. confirme que resultados de testes correspondem ao que foi executado.

Depois, salve o arquivo na raiz como:

`PROJECT_HANDOFF.md`

Ao terminar, responda com um resumo contendo somente:

* arquivo criado;
* principais áreas documentadas;
* validações executadas;
* resultado de lint/typecheck/tests/build;
* principais pendências críticas encontradas.

Não faça alterações adicionais no projeto após concluir o handoff, a menos que eu solicite.
