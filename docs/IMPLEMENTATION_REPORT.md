# Relatório vivo — Primeira entrega CHOQUE - BGR

## 2026-08-23 — Mesa de Análise: decisão direta e demonstração segura

- A ficha privada passou a renderizar uma única visão operacional: aguardando análise, em análise,
  aprovada ou reprovada; responsável, data de atribuição, decisor, data final e justificativa são
  editados na mesma mensagem. Não há repostagem de ficha para atualização de portal, restart ou
  decisão via Discord.
- Foram adicionados botões persistentes **Aprovar** e **Reprovar**. Ambos solicitam justificativa e
  mensagem ao candidato e chamam a mesma transição de domínio usada pelo portal. O serviço revalida
  RBAC, evita autoavaliação, é idempotente para clique repetido do mesmo resultado e rejeita uma
  decisão final incompatível; origem Discord e correlation ID ficam na auditoria.
- O worker edita somente o cartão original e espaça atualizações de recuperação em seis segundos.
  Eventos legados sem cartão não o recriam: são concluídos com histórico preservado, evitando uma
  segunda ficha. O portal recebeu filtros de status e responsável.
- Rollout: app combinado com `CHECK_OK`, migration 28 e Gateway único; standalone offline. Vercel
  `dpl_EJZedEhLbTyjaJFYAjhVseEzhX9v` READY no alias principal, sem erro recente em Recrutamento.
  A única mensagem de demonstração segura é `1541248708203774013`; ela não aciona candidatura real.
- QA: 56 testes focados, 335 pytest, 40 Vitest, Ruff, compileall, `main.py --check`, ESLint,
  TypeScript e build. O backup pré-corte está preservado e validado.

## 2026-08-23 — Integridade da ficha temporária da Portaria

- A evidência remota mostrou um cadastro ainda em `REQUIRES_REVIEW`, sem `reviewed_at`, que herdava
  `DELIVERED` e o resultado de um ciclo anterior. Por isso a ficha era publicada e removida pelo
  retry de cleanup antes da análise humana.
- A transição para uma nova revisão agora é atômica: limpa decisão, resultado, ponteiros e claims
  antigos; a recuperação de startup corrige o legado preservando uma ficha pendente já existente.
  Cleanup exige `REGISTERED`/`BLOCKED` + `reviewed_at`; o caminho de applications usa a regra
  simétrica `APPROVED`/`REJECTED`.
- Corte controlado: backup remoto prévio, stage de deploy limpo, `CHECK_OK`, Gateway único e app
  standalone offline. A verificação pós-start confirmou o registro afetado como pendente com nova
  mensagem de revisão e sem resultado herdado.
- QA: 39 testes focados, 326 na suíte completa, Ruff e `main.py --check`. As novas regressões cobrem
  reuso após `DELIVERED`, recovery/restart e proibição de cleanup em ficha pendente.

## 2026-08-23 — Qualificações: validação final humana

- A concessão de Abordagem Avançada ao Paiva foi executada pelo dashboard sem React #441 nem 404;
  banco e Discord registraram o GRANT Web e a sincronização do cargo em uma única tentativa.

## 2026-08-23 — Segundo hotfix de Qualificações: contrato de IDs exatos

- O teste humano posterior ao primeiro deploy não repetiu o `Zod too_big`/digest `1761130017`, mas
  expôs o digest `1027291490`: o membro listado na matriz chegava ao navegador com `discord_id` JSON
  numérico, era arredondado por JavaScript e o POST buscava um cadastro inexistente. O backup remoto
  pré-corte confirmou que o cadastro ativo de Paiva existe; a divergência era somente de transporte.
- `/v1/qualifications` passa a emitir todos os snowflakes expostos por essa matriz como strings
  decimais. O core de operações preserva inteiros para SQLite e Discord. O frontend recebe e devolve
  o mesmo texto; 404 esperado por remoção concorrente mostra aviso de atualização, sem tornar a página
  indisponível.
- Publicação controlada: backup remoto íntegro (quick check/FK/migration 28), app combinado online
  com `CHECK_OK` e um Gateway; Vercel `dpl_GDP7NteVNqxrSLMTXYWuC5mmHiY9` `READY`. Gates: 40 Vitest,
  typecheck, build local/remoto, 24 testes API, Ruff e `main.py --check`.
- Pendente: repetir o clique autenticado no curso do Paiva. Só essa prova humana poderá encerrar o
  incidente; até lá, não há mudança de dados reais de qualificação atribuída a este hotfix.

## 2026-08-23 — Hotfix de produção: Qualificações e contenção de Auditoria

- O runtime Vercel agrupou sete ocorrências do digest `1761130017` em `/qualifications`. A exceção
  real foi `ZodError too_big` em `discordId`, porque IDs do Discord excedem `Number.MAX_SAFE_INTEGER`.
  A ação agora valida o snowflake como string de 15–22 dígitos e envia esse texto à API; o FastAPI
  mantém a conversão exata no limite Python.
- Publicação web: `dpl_JADvS3uvzJdQoHynjvJX9wWK1zCA`, produção `READY`, alias
  `https://web-plum-tau-82.vercel.app`. O build remoto foi verde; a verificação posterior não encontrou
  erro de runtime nesse deployment e o acesso sem sessão ainda responde com o redirect seguro a
  `/login`.
- QA: 39 Vitest, typecheck, build Next.js local e remoto, 24 testes API dirigidos, Ruff,
  `main.py --check` e `git diff --check`. A nova regressão verifica um snowflake real sem arredondamento
  e uma entrada inválida sem chamada à API.
- Auditoria do Bot: a medição mostrou 11.188 eventos `REGISTRATION_ACCESS_GRANTED` em 24 h. A política
  fechada de entrega deixa esses sucessos técnicos append-only no banco sem postá-los no canal; erros,
  segurança, decisões e mudanças administrativas sensíveis seguem entregues. A validação anterior de
  324 pytest, Gateway único e o rollout no app combinado permanecem válidos.

## 2026-08-23 — Hotfix seguro do Dashboard de Recrutamento

- Produção Vercel: `dpl_9nW66UQb428mSuwR6YbWJvkT6DBe`, `READY`, alias
  `https://web-plum-tau-82.vercel.app`. O build remoto Next.js 16.3.2 passou; o escopo publicado foi
  somente o frontend `web/`, sem tocar no runtime Discord/API.
- A canonicalização do destino assinado remove a query vazia antes de assinar e enviar, corrigindo o
  401 `Credencial interna inválida.` da lista de Recrutamento.
- O step-up de mutações continua exigindo autenticação recente. A expiração deixa de gerar exceção de
  Server Component e conduz para OAuth de renovação com retorno seguro, evitando a boundary React #441.
- Validações concluídas: 37 testes Vitest, typecheck, ESLint, build local e build remoto. A página de
  renovação foi consultada ao vivo e expõe o fluxo correto. Assumir/decidir aguardam confirmação por
  usuário autenticado; nenhuma decisão de candidatura foi simulada em produção.
- A validação do pacote Python encontrou um buraco em migrations ao introduzir a v28. O executor foi
  corrigido para verificar todas as versões aplicadas, e o rollout do bot/API permanece bloqueado até
  a suíte completa passar.

## 2026-08-23 — Auditoria recuperada, migration 27 e status público

- A mensagem de Requisitos já publicava idade mínima de 15 anos, mas o backup remoto revelou a
  campanha `OPEN` em 16. A migration 27 registra a divergência em `audit_logs`, atualiza campanhas
  não arquivadas para 15 e torna 15 o default de campanhas criadas em bancos novos.
- Antes do corte, o backup remoto estava íntegro em v26 e mostrava `OPEN/16`. Depois do rollout, o
  novo backup retornou `quick_check=ok`, zero violações de foreign key, v27, `OPEN/15` e auditoria
  `RECRUITMENT_MINIMUM_AGE_ALIGNED` com `{"minimum_age":16}` → `{"minimum_age":15}`.
- A auditoria textual confirmou que CNH categoria B e porte de arma regularizado não existem no
  código ativo dos requisitos. A publicação conserva os requisitos institucionais e as dez questões
  de RP policial/códigos Q solicitadas.
- O status público foi refeito para a topologia vigente: Discloud Diamond, instância única,
  Gateway ativo e migration 27. O alias Vercel respondeu 200, contém o estado novo e não contém
  `Railway bloqueou`, `PAUSADO` ou `V23`.
- QA: **309 pytest**, **32 Vitest**, Ruff, compileall, `main.py --check`, `SECRET_SCAN_OK`, ESLint,
  TypeScript, build Next.js e `git diff --check`.
- O remoto `EoPaiva/CHOQUE-BGR` foi confirmado como privado. Trinta e oito arquivos de fonte,
  testes e documentação foram revisados e publicados em `private/main` no commit `1fa51db`; dados,
  logs, backups e segredos permaneceram ignorados, e nenhum push foi feito para `origin`.
- A decisão de acesso pendente foi fechada pelo proprietário: `qualification.manage` pertence a
  todo o Alto Comando. Como a matriz de produção já implementava esse escopo, não houve mutation de
  cargos, membros ou banco; somente a documentação autoritativa foi reconciliada.

## 2026-08-23 — Remoção intencional de Medalhas

- `cogs.medals_system` não integra mais a lista explícita de cogs. A ausência do canal foi removida
  dos requisitos do validador vivo, que agora reporta `medals_module=INTENTIONALLY_DISABLED`.
- Os scripts `provision_discord_layout.py` e `remodel_discord_layout.py` não contêm mais a chave
  `info.medals`, o nome visual ou o ID removido; um teste impede regressão e recriação acidental.
- O fonte legado e o catálogo histórico continuam versionados para consulta/rollback, sem comandos,
  painel persistente ou alertas ativos. A Discloud reiniciou com 16 cogs, Gateway conectado e logs
  sem nova mensagem “Canal de medalhas não encontrado”.

## 2026-08-23 — Acabamento visual do Recrutamento

- A skill de frontend design foi aplicada sobre a publicação existente. A direção foi formalizada
  como alistamento editorial militar contemporâneo, com DFII 13/15 e uma única âncora memorável:
  a diagonal vermelha que separa ordem operacional e chamada para ação.
- O layout evita a aparência de template usando tipografia condensada em grande escala, etapas em
  trilho vertical, formulário por linhas e assimetria controlada no lugar de cards repetidos.
  Barlow Condensed, Source Sans 3 e IBM Plex Mono mantêm a hierarquia tipográfica já carregada.
- Capturas full-page do alias público em 1440 × 1200 e 390 × 844 foram inspecionadas. Não houve
  corte, sobreposição ou rolagem horizontal; CTA, requisitos, etapas e formulário permanecem claros.
- O cenário Playwright foi atualizado para o texto vigente e ganhou verificações de idioma,
  overflow e nome acessível de controles. Passou em Chromium desktop/mobile e Firefox diretamente
  contra produção. ESLint, TypeScript, **32 Vitest**, build Next.js e `git diff --check` passaram.
- O Lovable não ofereceu capacidade callable nesta sessão; a referência editorial já incorporada
  foi comparada pelos registros existentes. Nenhum candidato, resposta ou segredo saiu do ambiente.

## 2026-08-23 — Recrutas e Gestão de Carreira

- A auditoria provou que havia quatro recrutas no banco remoto, mas todos usavam a patente visual
  Small Caps `ʀᴇᴄʀᴜᴛᴀ`. A comparação literal anterior foi substituída por normalização central de
  rótulos estilizados, preservando nomes visuais e identificadores internos separados.
- A nova visão de Carreira consulta membros ativos, patente e tempo na patente, horas válidas,
  patrulhas encerradas, advertências e mudanças formais ou recebidas pelo RankSync. Quando não há
  histórico, a interface explica o estado em vez de simular conteúdo.
- Recrutas ganharam progresso de requisitos, acesso ao dossiê e navegação para recrutamento/efetivo.
  Dossiê e elegibilidade passaram a consumir a projeção atual das qualificações bidirecionais.
- Rollout: backup remoto pré-corte preservado; os fontes ativos de Operações e normalização têm os
  mesmos hashes da cópia remota, e `command_center/app.py` difere somente por duas linhas em branco.
  Após reinício, `/health` respondeu 200 e `/v1/career` respondeu 401 sem autenticação, provando que
  a rota existe e continua protegida. Discloud v26 e Gateway estão online; Recrutamento público
  responde 200 e Recrutas/Carreira/Patrulhas redirecionam para login no alias Vercel.
- Evidência de dados: 12 membros ativos, 4 recrutas e 14 mudanças reais de patente. QA: **307 testes
  Python**, **32 testes web**, Ruff, compileall, `main.py --check`, ESLint, TypeScript, build Next.js
  e `git diff --check`.

## 2026-08-23 — Hotfix de presença real em Patrulhas

- A prova real mostrou que o listener atualizava `patrol_voice_presence`, mas a rota remota ainda
  executava `active_patrols()` e exibia vazio sem patrulha formal aberta.
- Leituras operacionais ganharam conexão SQLite nativa curta entre bot e API. A rota passou a usar
  `active_patrol_overview()`, combinando presença real e operação formal sem criar histórico falso.
- Após reinício em instância única, a chamada assinada retornou Patrulha Alfa, um ocupante,
  `VOICE_ACTIVE` e `DISCORD_LIVE`.
- QA final: 302 testes, Ruff, compileall e `main.py --check` passaram.
- O rollout revelou que o commit incremental ignorou fonte da API. Um backup remoto foi comparado
  com todos os Python/JSON ativos; somente `app.py` e `security.py` divergiam. Ambos foram alinhados,
  os hashes finais coincidem com a árvore local e o backup pré-paridade foi preservado fora do Git.

## 2026-08-23 — Portaria, resultado de recrutamento e patrulhas ao vivo

- Corrigido o timeout de decisões da Portaria: a interação é reconhecida antes de RBAC, banco,
  sincronização e arquivamento. O fluxo mantém respostas ephemeral e o handler global usa follow-up
  quando a resposta já foi confirmada.
- `Identificar vínculo` substituiu o convite ambíguo para cadastro. Visitante comum recebe apenas
  identidade de visitante; criação de membro exige candidatura aprovada, membro já existente ou
  conformidade funcional por role ID. Companheiro de Farda continua sem patente hierárquica.
- Aplicada, com snapshot, a matriz pública do Recrutamento e criado o posto privado `Setar tag`.
  Aprovados recebem menção pública, DM operacional e acesso individual; falhas de DM geram aviso
  restrito aos responsáveis. `AL-00005` foi atualizado editando as mensagens existentes.
- A migration 25 criou `patrol_voice_presence`; o listener observa calls na entrada, em eventos de
  voz e a cada minuto. API e frontend unem presença real e patrulha formal e atualizam a tela a cada
  dez segundos. A validação real posterior confirmou uma pessoa na Patrulha Alfa, sem fabricar
  amostra nem criar patrulha formal.
- Todo endpoint interno do Centro de Comando exige `COMANDO`, `ALTO_COMANDO` ou bootstrap técnico.
  A autenticação pública das candidaturas permanece separada.
- Publicação validada: Discloud online, migration 25, Gateway conectado; Vercel no alias principal,
  Recrutamento HTTP 200 e Patrulhas redirecionando para login. QA: **300 testes Python**, **32 web**,
  Ruff, compileall, `--check`, ESLint, TypeScript e build aprovados.

## 2026-08-23 — Entrada de recrutamento em um clique

- A Recepção passou a ser também o ponto de entrada do candidato: a mensagem `MEMBER` existente foi
  editada com `Candidatar-me agora`, apontando diretamente para o portal público. Cadastro funcional,
  consulta e suporte permanecem na segunda linha e são explicados como fluxo de aprovados/membros.
- O painel `RECRUITMENT` existente foi editado sem duplicação. O CTA de candidatura e o acompanhamento
  agora são links diretos; requisitos continua como controle persistente. A mensagem apresenta quatro
  passos, tratamento após envio e a distinção entre candidato e membro já aprovado.
- Novos visitantes recebem a mesma orientação por DM com link do processo seletivo e link da Portaria;
  bloqueio de DM continua sem impacto no ingresso.
- `validate_live_phase11` aprovou os componentes, links e conteúdo nas duas mensagens reais, os demais
  painéis do lote, sete configurações, módulos ativos e zero comandos remotos.
- No primeiro rollout, os logs detectaram `database disk image is malformed`. A causa foi o upload de
  `data/*.db*` pelo commit Discloud, que misturou banco local antigo e WAL remoto. A instância foi
  parada, o backup pré-deploy foi validado e restaurado atomicamente, e o launcher passou a aceitar
  recuperação única validada antes de abrir o banco. O `.discloudignore` agora bloqueia DB/WAL/SHM.
- Estado final: Discloud online, health 200, Gateway conectado, SQLite `quick_check=ok`, FK=0 e
  migration 24. Gates: **296 pytest**, **29 Vitest**, Ruff, compileall, `main.py --check`, ESLint,
  TypeScript e build Next.js.

## 2026-08-23 — Recrutamento público e runtime combinado em produção

- `choque-bgr-api` opera na Discloud Diamond como `TYPE=site`, 1 GB, executando o bot e a API; o
  healthcheck respondeu `status=ok`, o bot local permaneceu `BOT_OFFLINE` e a aplicação antiga está
  offline.
- O portal `https://web-plum-tau-82.vercel.app/recrutamento` respondeu HTTP 200 com campanha
  `OPEN`, formulário público sem OAuth, 24 questões por candidatura e acesso à consulta de status.
- Configurações persistidas: URL pública do recrutamento, canal administrativo de notificações e
  campanha inicial aberta com idade mínima de 16 anos e cooldown de 30 dias.
- QA sintético em produção: candidatura `AL-00001`, 24 respostas, transição `DRAFT -> SUBMITTED`,
  estágio `REVIEW`, outbox `COMPLETED` no canal configurado e retirada posterior `WITHDRAWN` para não
  poluir a fila. O histórico permanece auditável e não contém pessoa real.
- A primeira entrega do outbox falhou por uma referência antiga a `Branding.footer_text`. O código
  foi corrigido para `Branding.footer`, recebeu teste de regressão e foi publicado na mesma
  aplicação; o retry concluiu na sexta tentativa, sem duplicar evento.
- Gates pós-hotfix: **293 pytest**, **29 Vitest**, Ruff, compileall, `main.py --check`, ESLint,
  TypeScript e build Next.js. O frontend foi revalidado pela integração Vercel com HTTP 200 e headers
  de segurança.
- Estado histórico daquela entrega: o Robô Analista ainda estava desativado. Esse bloqueio foi
  superado em 2026-08-24 pelo motor local determinístico documentado ao final deste relatório.
- O pacote final pós-hotfix foi gerado do commit com 107 entradas e 450.193 bytes. O inventário
  confirmou zero `.env` real, banco, log, cache, teste, frontend ou segredo; SHA-256
  `a453152690b8c183710ea4266c50da12857bf8f795507e40f465a9e75657d3cf`. O `.env` de produção
  permanece somente no armazenamento privado da Discloud, que documenta esse arquivo como seu
  método principal de variáveis. A rotação das credenciais expostas segue obrigatória.

## 2026-08-22 — Smoke funcional na Discloud

A instância Diamond foi confirmada online e conectada ao Discord, com a instância local desligada.
O banco recuperado diretamente do backup remoto passou em integridade, foreign keys e migration 24.
Foram aprovados 15 validadores ao vivo, o validador de sincronização de patentes contra o banco remoto,
292 testes, Ruff, compilação e a auditoria de rotas de interação. Validadores históricos foram atualizados
para a Central Administrativa categorizada e para as regras atuais de `KEEP_LAST`, exoneração e
Companheiro de Farda. O deploy atual cobre o bot; site/API combinado permanece como parte não concluída
do item 29.

Atualizado em 2026-08-23.

## Estado

Implementação local concluída para as Fases 1–12. O token autenticou, o `Server Members Intent` foi
aceito e a guild `CHOQUE - # BGR 1` foi remodelada para operação exclusivamente visual. Os comandos
publicados foram removidos da API da guild (`0` comandos remotos). Gateway, heartbeat, painéis
persistentes e restauração após restart foram validados. O deploy Discloud e os testes humanos dos
fluxos no cliente Discord continuam pendentes.

## Diagnóstico e correções

- O projeto antigo carregava todo arquivo Python de `cogs/`; agora usa doze extensões explícitas.
- Bancos, bytecode, configurações reais, arquivos Node sem uso e artefatos antigos saíram do
  versionamento.
- O banco legado é copiado sem alteração e recebe backup antes da primeira migration.
- IDs são inteiros no banco; timestamps são UTC epoch e a apresentação usa `America/Sao_Paulo`.
- Token legado é tratado como comprometido. Não houve rewrite/force-push do histórico.
- Farm, Caixa, Resgate, RH, Cadastro e Ausência antigos foram preservados em `legacy/`, desativados.
- O erro Discord “O aplicativo não respondeu” foi reproduzido com os comandos sincronizados e sem
  processo Python ativo. A causa era operacional: o bot estava offline após o teste controlado.
- Foi criado um menu administrativo persistente com botões, seletores e modais para toda a
  configuração das Fases 1–3. A mensagem inicial foi publicada no canal privado `moderator-only`.
- Os seletores nativos que ocultavam itens em servidores grandes foram substituídos por navegadores
  explícitos de 25 itens por página, com busca por nome/ID. A API confirmou 63 canais de texto,
  25 calls e 91 cargos disponíveis no servidor.
- A importação de patentes foi reconciliada com a hierarquia real do Discord: 21 cargos, de Recruta
  a Comandante Geral, recebem níveis sequenciais pela posição real. Praças, Praças Graduados,
  Oficiais, Sub Comandante, Comandante e Comandante Geral passaram a ser reconhecidos; Alto Comando
  e Xenon permanecem cargos funcionais ignorados. Registros antigos são preservados e desativados,
  nunca apagados.
- O painel persistente de hierarquia passou a editar a mesma mensagem no import, em alterações
  manuais e após restart. A API confirmou os 21 campos e todas as menções de cargo esperadas.
- A Fase 4 foi entregue sem dependência operacional de comandos: uma Central Administrativa
  privada concentra cadastros, patentes, punições, afastamentos, histórico e ranking.
- Foram criados os canais `🛡️│central-administrativa`, `🗓️│afastamentos` e
  `🏆│ranking-de-horas` dentro da categoria `CHOQUE • GESTÃO`. Os dois painéis públicos são
  somente leitura e operados por botões.
- A outbox agora preserva eventos enquanto o canal de auditoria ainda não estiver configurado, sem
  consumir tentativas de retry durante o bootstrap.
- O servidor foi reorganizado em nove áreas numeradas: Informações, Central do Membro, Operações,
  Formação, Recrutamento, Administração, Auditoria, Comunidade e Arquivo Legado.
- Canais úteis foram renomeados e realocados sem perder mensagens. Treze canais históricos ficaram
  no arquivo privado; cinco canais vazios e quatro categorias substituídas foram removidos.
- A Central do Membro recebeu navegação por botões de link e painéis funcionais de cadastro, ponto,
  efetivo, afastamentos e ranking. Administração e configuração ficaram em uma categoria privada.
- Onze calls operacionais foram autorizadas no banco; a sala de espera e as calls de curso não
  contam horas. Dezessete vínculos RBAC foram aplicados aos cargos reais do servidor.
- Os painéis mortos de ticket, ponto e central antiga deixaram de ser expostos como funções ativas.
  Recrutamento e ticket exibem estado de preparação sem botões clicáveis falsos.
- A identidade visual do servidor foi padronizada: categorias usam Texto Monoespaçado Elegante,
  enquanto canais de texto e voz usam Sans-Serif Itálico, com emojis semânticos e ordem numérica.
- Uma categoria duplicada criada durante a execução interrompida foi identificada e removida com
  seus quatro canais vazios; a categoria original e todas as mensagens dos painéis foram preservadas.
- A Fase 5 converteu o painel de afastamentos na Central de Solicitações sem trocar a mensagem
  existente. Sete botões persistentes cobrem ausência/retorno, reserva, correção de horas, alteração
  cadastral, desligamento e histórico pessoal.
- O Comando recebeu fila unificada, detalhes, perfil, histórico e decisão de solicitações. Reserva e
  desligamento encerram ponto ativo; correções geram ajustes append-only; nenhuma ficha é apagada.
- Os cargos `🟠 Ausente`, `🟡 Reserva` e `🔴 Suspenso` são configuráveis e sincronizados com o status.
- A Fase 6 criou um painel persistente de carreira, ligado à Central do Membro e à Central
  Administrativa. Promoção/rebaixamento agora seguem seleção de membro, patente de destino, motivo e
  confirmação explícita.
- A ficha de carreira mostra tempo na patente, horas do mês e advertências ativas sem automatizar a
  decisão. O histórico funcional possui paginação e continua append-only.
- A Fase 7 criou o canal e painel persistente de Disciplina, ligados às centrais do Membro e
  Administrativa. Ocorrências são fatos sem punição automática e podem ser arquivadas ou convertidas
  transacionalmente em advertência.
- Advertências possuem tipo, evidência, observação e estados ativo/cumprido/revogado sem exclusão.
  Suspensões imediatas fecham o ponto na mesma transação; suspensões futuras sobrevivem a restart,
  ativam pelo job persistente e restauram o status ao encerrar.
- A Fase 8 substituiu o placeholder de Treinamentos pelo painel funcional com três ações pessoais e
  gestão administrativa de criação, inscrições, presença, resultado e histórico.
- Cada evento reutiliza a própria mensagem, protege capacidade e duplicidade e restaura seus botões
  após restart. A conclusão grava cursos/qualificações no histórico do membro sem apagar resultados
  reprovados ou eventos cancelados.
- A Fase 9 criou atividade semanal com meta configurável, quatro situações, isenções por reserva ou
  afastamento, snapshots semanais append-only e fechamento idempotente após restart.
- O painel administrativo reúne monitor de inatividade e sete relatórios. Os indicadores são
  somente informativos e nunca geram punição ou desligamento automático.
- A Fase 10 acrescentou controle visual e auditado para oito módulos. A desativação bloqueia novas
  interações no backend sem apagar dados e preserva jobs necessários para estados em andamento.
- A Fase 11 substituiu os placeholders de recrutamento e ticket por painéis funcionais de
  candidatura, transferência, denúncia privada, outro assunto, histórico pessoal e fila administrativa.
- A aprovação de candidatura cria a solicitação pendente de membro na mesma transação; decisões
  concorrentes são condicionais e toda análise mantém o histórico e a auditoria.
- Recrutamento e Atendimento entraram no controle de módulos. Sete destinos de canal e três painéis
  passaram a ser configuráveis visualmente, elevando o progresso essencial para `29/29`.
- A Fase 12 aplicou a referência visual v2 em 19 categorias e 97 canais, preservando IDs, mensagens,
  históricos e permissões específicas. O registro interno completo foi persistido no banco.
- O Discord converteu espaços em hífen e removeu fillers nos testes reais. O antigo `U+17B5`,
  apesar de preservado pela API, virou quadrado no cliente e foi substituído por `U+00B7`, com
  `U+30FB` como fallback único; a função central evita espalhar o caractere pelo código.
- O provisionador oficial agora resolve canais por ID/identificador interno e encaminha sempre para
  a referência v2, impedindo reversão acidental ao layout intermediário.

## Arquitetura e schema

- Núcleo: `choque/database.py`, `settings.py`, `rbac.py`, `members.py`, `shifts.py`, `audit.py`,
  `personnel.py`, `discipline.py`, `training.py`, `activity.py`, `requests.py`, `module_flags.py` e
  `tickets.py`.
- Discord: `cogs/shift_commands.py`, `member_commands.py`, `config_commands.py`,
  `config_ui.py`, `request_commands.py`, `career_commands.py`, `discipline_commands.py`,
  `training_commands.py`, `activity_commands.py`, `ticket_commands.py`, `member_sync.py`,
  `hierarchy_system.py` e `utility_commands.py`.
- Migrations atuais: v1 (schema-base), v2 (`guild_id` explícito em segmentos e ajustes), v3
  (carreira, punições e afastamentos), v4 (solicitações administrativas e restauração de status) e
  v5 (ocorrências e ciclo disciplinar completo), v6 (treinamentos, inscrições e qualificações) e
  v7 (snapshots semanais de atividade), v8 (recrutamento, transferências e denúncias) e v9
  (outros assuntos, preservando os tickets existentes).
- Tabelas: `schema_migrations`, `guild_settings`, `authorized_voice_channels`, `rbac_bindings`,
  `panels`, `ranks`, `members`, `member_applications`, `shifts`, `shift_segments`,
  `shift_adjustments`, `voice_events`, `audit_logs`, `bot_runtime`.
- Fase 4: `personnel_actions`, `punishments` e `absence_requests`.
- Fase 5: `administrative_requests`; afastamentos ganharam observação e status anterior restaurável.
- Fase 6 reutiliza `ranks`, `members.rank_id` e `personnel_actions`; nenhuma migration adicional foi
  necessária.
- Fase 7 cria `disciplinary_occurrences` e amplia `punishments` sem apagar registros antigos.
- Fase 8 cria `training_events`, `training_enrollments` e `member_qualifications`.
- Fase 9 cria `weekly_activity_snapshots`.
- Fase 11 cria `service_tickets` e integra candidaturas aprovadas a `member_applications`.
- A extensão de atendimento adiciona `OTHER`, botão persistente, modal privado e fila própria do
  Comando sem criar canais individuais.

## Segurança e confiabilidade

- WAL, foreign keys, busy timeout, transações e encerramento gracioso.
- Locks descartáveis por membro, índices parciais e updates condicionais.
- Auditoria no mesmo commit; envio ao Discord somente após commit e retry periódico.
- Logs JSON em UTC e respostas globais ephemeral com ID de correlação.
- Bot não precisa de `Administrator`; o RBAC tem bootstrap por owner/admin humano.
- A auditoria ao vivo mostrou que o cargo atual do bot ainda possui `Administrator` no servidor.
  A implementação não depende disso; a permissão deve ser removida após conceder explicitamente
  visualizar/enviar mensagens, embeds, histórico, gerenciar canais, cargos e apelidos.

## Evidência local

| Controle | Resultado |
|---|---|
| `python main.py --check` | migration v10, 13 cogs e 13 views persistentes; handlers legados locais preservados |
| `python -m pytest -q` | 91 testes passando |
| `python -m ruff check .` | sem achados |
| Login Discord | token válido; Gateway conectado como `Choque#1319` na guild correta |
| API Discord | `0` application commands publicados na guild |
| Atendimento `OTHER` | botão persistente publicado; ticket real pendente e auditado |
| Runtime SQLite | heartbeat atualizado durante o ciclo e `clean_shutdown=1` após encerramento |
| Outbox legada | registro preservado sem novas tentativas para guild desconectada |
| Menu de configuração | mensagem persistente com 8 botões confirmada em `⚙️│configurações-do-bot` |
| Navegação completa | inventário atual e 91 cargos paginados; busca por nome/ID testada |
| Patentes importadas | 21 cargos persistidos, níveis 1–21; Alto Comando e Xenon ignorados |
| Painel de hierarquia | mesma mensagem reutilizada; 21 campos e menções validados pela API |
| Central administrativa | 10 botões persistentes publicados no canal privado |
| Central de Solicitações | mensagem anterior reutilizada; 7 botões persistentes validados pela API |
| Painel de carreira | 3 botões, canal próprio, link do membro e botão administrativo validados pela API |
| Painel de disciplina | 2 botões pessoais, canal próprio, link do membro e botão administrativo validados pela API |
| Painel de treinamentos | 3 botões pessoais, botão administrativo, mensagem reutilizada e link validados pela API |
| Painel de atividade | 3 botões pessoais, botão administrativo, link e migration v7 validados pela API |
| Painel de ranking | 4 períodos persistentes publicados e canal bloqueado para mensagens |
| Runtime local | processo oculto ativo, proteção contra segunda instância e heartbeat recente |
| Layout oficial | 19 categorias, 97 canais e 116 itens totais validados por leitura fresca da API |
| Configuração | progresso essencial `29/29`, 11 calls e 17 vínculos RBAC |
| Painéis | cadastro, ponto, efetivo, solicitações, carreira, disciplina, treinamentos, atividade, ranking, administração e configuração confirmados |
| Backup do servidor | snapshots JSON salvos em `data/server_layout_backups/` antes da migração |

A suíte cobre os dez cenários obrigatórios, migration sobre banco legado, importação de config,
RBAC, cadastro/aprovação, timezone, identidade de painel, falha/retry da outbox, decisões
concorrentes, reserva, retorno antecipado, correção append-only, alteração de dados e desligamento.
Também cobre escolha humana da patente, bloqueio de direção inválida e histórico de carreira
paginado. A disciplina cobre ocorrência sem punição, conversão atômica, cumprimento imutável,
suspensão imediata/agendada, encerramento de ponto, restauração após restart e concorrência.
Treinamentos cobrem capacidade concorrente, reinscrição sem duplicidade, bloqueio por status,
presença, resultado, qualificação, cancelamento e restauração da mensagem persistente. Atividade
semanal cobre classificação, isenção, fechamento idempotente, restart, monitoramento sem punição e
alteração auditada das regras.
Também há cobertura da detecção dos 21 nomes reais, incluindo small caps, acentos e `ғ`, da
reordenação transacional, da preservação de registros ignorados e da auditoria da reconciliação.

## Pendências de rollout

1. Regenerar o token novamente se ele tiver sido compartilhado fora do `.env` local.
2. Executar os dez cenários no Discord, inclusive concorrência e restart real.
3. Validar os fluxos com contas reais de membro, graduado e comando para confirmar a experiência
   de cada faixa de permissão.
4. Confirmar hierarquia do cargo do bot para gerenciar cargo em serviço e apelidos.
5. Analisar screenshots do sistema antigo quando forem enviados.
6. Após aprovação, implantar na Discloud e observar recuperação, erros e outbox.
7. Remover `Administrator` do cargo do bot após validar as permissões granulares necessárias.
8. ✅ **Sincronização Automática de Patente, Cargo e Nickname concluída em 2026-08-22** conforme
   `docs/RANK_SYNC_SPEC.md`. A ressalva de rollout é externa: o cargo do bot precisa ficar acima de
   Comandante Geral para corrigir o apelido desse usuário; a recusa `50013` já é auditada sem
   rollback do banco.
9. ✅ **Validação do Ponto por Tempo Mínimo em Patrulha concluída em 2026-08-22**, conforme
    `docs/MINIMUM_PATROL_TIME_SPEC.md`: padrão inicial de 15 minutos configuráveis, distinção entre
    call autorizada e call que conta como patrulha, invalidação sem exclusão, confirmação de saída
    antecipada, exclusão dos totais e override administrativo auditado. Evidências detalhadas na
    seção Fase 14 abaixo.
10. Implementar a **Expansão de Operações Inteligentes** definida em
    `docs/INTELLIGENT_OPERATIONS_EXPANSION_SPEC.md`, preservando todos os módulos existentes e a
    ordem interna obrigatória: Patrulha, Visão Operacional, Desenvolvimento do Membro e
    Administração. A expansão inclui fila FIFO e formação automática de patrulhas, disponibilidade,
    prontidão, flags não punitivas, integridade/identidade, qualificações, elegibilidade, dossiê,
    caixa de entrada, decisões, manutenção e o painel O que mudou?.

Fora do escopo atual: eventos, API e integração MTA.

## Fase 13 — RankSyncService (2026-08-22)

### Entrega

- `choque/rank_sync.py` centraliza resolução de patente, formato `[ABREVIAÇÃO] NOME [ID]`, escrita
  Discord, política sem cargo, múltiplos cargos, histórico e auditoria.
- `cogs/rank_sync_system.py` observa o estado final de `on_member_update`, ignora cargos alheios,
  agrega eventos rápidos por debounce, descarta tasks/locks e reconcilia somente cadastrados no
  startup.
- Os fluxos de cadastro, alteração de dados, promoção e rebaixamento reutilizam o mesmo serviço;
  os helpers divergentes de cargo/nickname foram removidos.
- A aprovação preserva a maior patente que o candidato já possua no Discord; sem patente, aplica a
  menor patente ativa configurada.
- A migration v10 adiciona `members.rank_sync_status`, `members.rank_sync_checked_at` e
  `rank_sync_events` append-only. Mudanças manuais aparecem no histórico de carreira sem virar
  promoção formal.
- O menu visual de Patentes ganhou **Sincronização**, com `ENFORCE_MEMBER_NICKNAME`,
  `AUTO_REMOVE_OLD_RANK_ROLES` e `KEEP_LAST`/`MARK_UNSYNCED`.
- O painel de hierarquia passou a contar membros reais dos cargos Discord, sem bots, e mantém o
  banco apenas como fallback offline.

### QA e rollout

- Backup SQLite consistente antes da migration:
  `data/choque_bgr.db.pre-rank-sync-v10-20260822-034811`, 331776 bytes, SHA-256
  `1E2C85F2A707A3ACCDD4ED4C146B8DEB0D678BEA507028113ACC94D8C5190FDB`.
- `python -m pytest -q`: 91 testes aprovados, incluindo os 12 cenários obrigatórios.
- Ruff e compile/import smoke: aprovados.
- `python main.py --check`: migration 10, 13 cogs, 46 handlers locais, 13 views persistentes.
- `scripts/validate_live_rank_sync.py`: `RANK_SYNC_LIVE_PASS`, 3 cadastrados, 3 eventos de
  reconciliação, 21 patentes e contagens do painel iguais ao Discord.
- Reconciliação real: uPaiva → Comandante Geral, Lopes → Comandante e Ricardo → Coronel.
- Ressalva externa: o Discord recusou somente o apelido de uPaiva com `50013 Missing Permissions`,
  pois o cargo do bot não está acima de Comandante Geral. O banco permaneceu correto e a falha foi
  registrada como `NICKNAME_PERMISSION_ERROR`; não há retry infinito.

## Hotfix de produção — acesso de visitantes (2026-08-22)

- `choque/visitor_access.py` tornou explícitas as únicas quatro categorias públicas: Recepção,
  Ticket, Recrutamento e Transferências e Parcerias. Categorias de membro e privadas falham
  fechadas; a fila de tickets e os resultados de recrutamento são exceções privadas dentro de
  categorias públicas.
- `scripts/enforce_visitor_permissions.py` resolve os 19 IDs de categoria e 97 IDs de canal pelo
  `discord_layout_registry_v2`, altera somente overwrites de `@everyone`/Membro e preserva todos os
  demais acessos por cargo ou usuário. O script suporta validação sem escrita e rollback por
  snapshot.
- O remodelador v2 deixou de classificar Central do Membro, Registro, Informações e Membros CHOQUE
  como públicos, impedindo que uma execução futura reintroduza o vazamento.
- Snapshot anterior à mudança:
  `data/server_layout_backups/visitor_permissions_1146622062895579186_20260822T070707Z.json`.
- Validação ao vivo: `VISITOR_ACCOUNT_VALIDATED=true visible_categories=4`; uma conta real sem
  cargos não possui acesso a nenhum canal interno.
- QA local após a entrega: Ruff aprovado e 105 testes aprovados, incluindo 14 casos da política de
  visitantes.

## Hotfix de produção — sala privada por ticket (2026-08-22)

- Migration v11 adiciona `ticket_rooms`, vínculo único entre atendimento e canal, mensagem de
  controle, estado `OPEN/CLOSED/ARCHIVED` e metadados de fechamento.
- Candidatura, transferência, denúncia e outro assunto provisionam a sala sob a categoria Ticket
  localizada pelo `discord_layout_registry_v2`. A resposta pessoal menciona o canal criado.
- Overwrites da sala permitem somente solicitante, cargos RBAC `COMANDO`/`ADMINISTRADOR` e bot;
  `@everyone` é negado. O nome não contém dados pessoais e o sistema nunca localiza a sala pelo
  nome visual.
- `TicketRoomView` adiciona o botão persistente **Encerrar atendimento**. Solicitante ou revisor
  autorizado informa o motivo em modal; a atualização é condicional/transacional e auditada.
- Decisão ou encerramento remove o acesso do solicitante, move o mesmo canal para o arquivo e
  preserva todo o histórico. O `on_ready` recria salas ausentes sem duplicar vínculos.
- Backup pré-migration:
  `data/choque_bgr.db.pre-ticket-rooms-v11-20260822-071446`, 331776 bytes, SHA-256
  `23C5CA71EE3E3FA907BBA28FDFBCE5E7835EA96E7D4F52F3E80AF3F55E87420B`.
- Validação real: `TICKET_ROOM_LIVE_PASS`, migration 11, `@everyone` negado, solicitante e bot
  permitidos, 11/11 cargos de Comando permitidos, nenhum usuário extra e botão persistente presente.
- QA final: Ruff aprovado, 108 testes aprovados, compile/import smoke aprovado,
  `main.py --check` com 13 cogs, 46 handlers locais e 14 views persistentes; comandos remotos = 0.

## Hotfix de produção — arquivo de cadastros analisados (2026-08-22)

- Migration v12 persiste canal/mensagem da solicitação, canal/mensagem do resultado e estado de
  entrega. Registros aprovados/negados anteriores à migration recebem `LEGACY` e não são repostados.
- `MemberService.review_application()` verifica `rowcount` na atualização condicional; duas decisões
  concorrentes produzem um único resultado. A entrega ao histórico também é idempotente e auditada.
- Novas solicitações reutilizam a mesma mensagem pendente quando possível. Após decisão, o resultado
  é enviado ao `registration_history_channel_id` e só então a mensagem de origem é removida da fila.
- O destino é configurável pelo painel visual. Na guild atual, o fallback seguro resolveu
  `archive.members` pelo `discord_layout_registry_v2` e persistiu o ID; `@everyone` não enxerga o
  canal.
- `on_ready` restaura mensagens pendentes e resultados ainda não entregues, sem tocar nos três
  cadastros históricos aprovados já existentes.
- Backup pré-migration:
  `data/choque_bgr.db.pre-application-archive-v12-20260822-072308`, 331776 bytes, SHA-256
  `23C5CA71EE3E3FA907BBA28FDFBCE5E7835EA96E7D4F52F3E80AF3F55E87420B`.
- Validação real: `APPLICATION_ARCHIVE_LIVE_PASS`, migration 12, 5/5 colunas, histórico igual ao
  registry e privado, 3 registros legados, 0 entregas pendentes e botão **Cadastros** presente.
- QA: Ruff aprovado, 109 testes aprovados, compile/import smoke aprovado e `main.py --check`
  aprovado com 13 cogs, 46 handlers locais e 14 views persistentes.

## Lote 1 — apresentação militar e navegação (2026-08-22)

- Cadastro: `build_registration_panel_embed()` apresenta ordem de ingresso, dados necessários,
  bloqueios de duplicidade e tratamento privado. O publicador edita `MEMBER` e não duplica a
  mensagem, inclusive quando acionado pelo menu visual de configuração.
- Ponto: `build_point_panel_embed()` documenta entrada, calls, troca de segmentos, grace, quatro
  estados e ajustes append-only. Os quatro custom IDs e todas as regras de `ShiftService` foram
  preservados; `POINT` também é editado no lugar.
- Medalhas: o conteúdo da mensagem histórica `1248833920917573745` foi lido pela API. O novo cog
  publica `MEDALS` com Bravura, Pacificador, Guerra, Sargento, Honra, Sheriff e Distinção, os sete
  cargos reais e consulta ephemeral por select. A mensagem-fonte não foi alterada ou removida.
- Transferências e Parcerias: `TRANSFER`, `PARTNERSHIP` e `PARTNERSHIP_TERMS` foram publicados nos
  três canais originais. Transferência reutiliza o fluxo estruturado existente; parceria abre
  atendimento privado com proposta institucional; termos possuem links por ID.
- Os canais `1166861438728548432`, `1540590814839967784` e `1540590816383336520` continuam sob a
  categoria `1540589594691772477`, com IDs, mensagens históricas e overwrites preservados.
- Validação real: `PRESENTATION_LIVE_PASS`, 6/6 painéis, 3/3 canais de parceria, fonte histórica de
  medalhas preservada e zero comandos publicados.
- QA: Ruff aprovado, 112 testes aprovados, `main.py --check` com migration 12, 14 cogs, 46 handlers
  locais e 17 views persistentes. Bot online em uma única instância.

## Correção de produção — nomes dos canais (2026-08-22)

- `scripts/probe_channel_separators.py` criou e removeu canais temporários privados para comparar
  dez candidatos. `U+3164`, `U+2800`, `U+115F`, `U+1160`, `U+FFA0`, `U+200B` e `U+2063` foram
  removidos pelo Discord; `U+00B7` e `U+30FB` foram preservados sem hífen e com menção funcional.
- `choque/channel_names.py` centraliza `CHANNEL_SEPARATOR = "·"` e fallback `"・"`. O antigo
  `U+17B5` não é mais produzido pelo sistema.
- `scripts/migrate_channel_names.py` exige registry exato, cria snapshot integral, edita somente o
  nome do mesmo channel ID, faz fetch/comparação e registra `CHANNEL_NAME_MIGRATED` ou
  `CHANNEL_NAME_REVIEW_REQUIRED`. O rollback restaura nomes a partir do snapshot.
- Foram migrados 68 canais fixos e a sala dinâmica do ticket `#1`; categorias, posições,
  overwrites, mensagens, tópicos e IDs não foram alterados. Dez labels de calls autorizadas foram
  reconciliados no banco pelos IDs.
- Snapshots imediatamente anteriores às duas aplicações finais:
  `data/server_layout_backups/discord_layout_1146622062895579186_20260822T073656Z.json` e
  `data/server_layout_backups/discord_layout_1146622062895579186_20260822T074104Z.json`.
- Segunda varredura: `identified=0`, `labels_identified=0`, `fallback=0`, `review=0`.
  `LIVE_PHASE12_OK` confirmou 19 categorias, 97 canais fixos, uma sala dinâmica, 11 calls e zero
  comandos remotos.
- QA final: Ruff aprovado, 112 testes aprovados, compile/import smoke aprovado e
  `main.py --check` em migration 12, 14 cogs, 46 handlers e 17 views. O bot voltou online como
  instância única; visitantes, apresentação, arquivo de cadastro e sala arquivada de ticket
  passaram novamente nos validadores ao vivo.

## Catálogo histórico de cursos (2026-08-22)

- As nove mensagens do canal `1162114694581059584` foram lidas pela API e mantidas intactas. O
  importador confere os IDs dos cargos mencionados e guarda o ID/hash de cada fonte.
- Migration v13 adiciona `course_catalog`, `course_requirements` e `course_applications`, com índice
  parcial que impede duas solicitações pendentes do mesmo membro/curso.
- Foram persistidos 9 cursos e 10 requisitos: Membro Águia, Atirador de Elite, Modulação, Membro
  ROCAM, P1 Tático, P1 Oficial, ROCAM Elite, Abordagem Básica e Abordagem Avançada. Notas mínimas,
  edital e cooldown histórico de 14 dias foram preservados.
- `COURSE_CATALOG` é publicado no mesmo canal histórico e reutiliza a mensagem persistida. O painel
  possui nove botões; respostas são privadas e a elegibilidade é refeita server-side no clique.
- A validação bloqueia cadastro ausente/inativo, edital fechado, requisito de cargo ausente, curso
  já obtido, solicitação duplicada e cooldown. O snapshot da elegibilidade fica no banco.
- A Central Administrativa ganhou a fila **Solicitações de curso**. Aprovar/rejeitar é condicional,
  concorrente e auditado; aprovação permite convocação, mas não concede o cargo antes da conclusão
  do treinamento.
- Backup pré-migration:
  `data/choque_bgr.db.pre-course-catalog-v13-20260822-074800`, 331776 bytes, SHA-256
  `23C5CA71EE3E3FA907BBA28FDFBCE5E7835EA96E7D4F52F3E80AF3F55E87420B`.
- `COURSE_CATALOG_LIVE_PASS`: migration 13, 9/9 fontes, 9 cursos, 10 requisitos, 9 campos, 9
  botões, zero cargos ausentes e zero comandos remotos.
- QA: Ruff aprovado, 117 testes aprovados, compile/import smoke aprovado e `main.py --check` com
  14 cogs, 46 handlers locais e 18 views persistentes. Bot online em uma única instância.

## Fase 14 — Tempo mínimo em patrulha (2026-08-22)

- Migration v14 separa `service_allowed` de `counts_toward_patrol_minimum`, fotografa a
  classificação em cada `shift_segment` e adiciona duração bruta, duração de patrulha, mínimo,
  instante de cumprimento, decisão automática, decisão efetiva, motivo e origem da validação.
- `choque/shift_validation.py` calcula progresso por timestamps e segmentos. O limiar é exato e
  sessões ativas tornam-se contabilizáveis sem depender do próximo heartbeat.
- Fechamentos manuais, grace, perda de cargo, suspensão e solicitações administrativas usam a
  mesma validação transacional. Sessões curtas ficam `INVALIDATED` com
  `MINIMUM_PATROL_TIME_NOT_REACHED`; nada é apagado ou reescrito.
- Totais diário/semanal/mensal/geral, ranking, meta semanal e relatórios excluem invalidadas,
  inclusive seus ajustes. O histórico preserva duração bruta, patrulha, mínimo e decisão.
- O painel de ponto explica a regra; início informa o mínimo; status/efetivo mostram progresso. A
  finalização curta exige **Finalizar mesmo assim** ou **Continuar em serviço**.
- Calls são configuradas visualmente como autorizadas e, separadamente, como contadoras de
  patrulha. O mínimo é configurável entre 5 e 120 minutos no modal de regras.
- A Central Administrativa ganhou **Revisar ponto**. Override exige permissão, justificativa e a
  confirmação literal `VALIDAR`; `automatic_validation_status` continua preservado e
  `shift_validation_overrides` é append-only.
- O arquivo inicialmente nomeado
  `data/choque_bgr.db.pre-minimum-patrol-v14-20260822-080000` foi posteriormente identificado como
  cópia simples do arquivo principal enquanto o WAL estava ativo. Ele permaneceu na migration 13 e
  **não é um backup autoritativo**; não deve ser usado para rollback sem reconstrução/verificação.
- QA: Ruff aprovado, 131 testes aprovados, compile/import smoke aprovado e `main.py --check` com
  migration 14, 14 cogs, 46 handlers locais e 18 views persistentes.
- Validação real: `MINIMUM_PATROL_LIVE_PASS`, mínimo 15 persistido, 11 calls classificadas, 7/7
  colunas principais, painéis `POINT`/`CONFIG` atualizados e zero comandos remotos. Catálogo,
  layout, ticket, arquivo de cadastros e Lote 1 também passaram novamente. Bot online como
  instância única.

## Fase 15 — Operações Inteligentes (2026-08-22)

- Migration v15 adiciona disponibilidade operacional, registry de calls de patrulha, patrulhas e
  integrantes, fila persistente, feedback privado, flags, achados de integridade, avaliações de
  treinamento/recruta, trocas consensuais, manutenção e eventos internos. Índices parciais impedem
  dupla fila, dupla patrulha por membro e duas patrulhas na mesma call.
- `choque/operations.py` centraliza a máquina operacional: FIFO, reserva, ativação, rollback,
  encerramento, histórico, prontidão, flags não punitivas, integridade classificada, matriz,
  requisitos de cursos, avaliações, recrutas, elegibilidade sem promoção, dossiê, inbox, trocas,
  decisões, mudanças e manutenção.
- `cogs/operations_commands.py` publica somente UI Discord. O listener reage a eventos de voz,
  forma grupos pelo mínimo configurável, move com rollback e não inicia ponto. Um refresh global de
  cinco minutos edita os painéis persistidos; a análise de flags roda por hora.
- `PATROL_CENTRAL` reutiliza `1164363506083172413` com oito botões; `PATROL_REPORT` reutiliza
  `1540590792522072155` com três botões; `MEMBER_CENTRAL` foi editado no lugar com cinco ações e os
  links dos módulos. Solicitações, Treinamentos, Carreira e Central Administrativa ganharam entradas
  para troca, matriz, elegibilidade e Operações.
- A call `patrol.waiting` é autorizada mas não conta para o mínimo; as 11 calls ativas contam. Os
  nomes/labels continuam sincronizados pelo ID e o validador da Fase 12 voltou a passar.
- Requisitos de curso agora incluem patente, horas válidas, tempo de corporação, suspensão ativa e
  pré-requisito. Avaliações pós-treinamento persistem presença, resultado, desempenho e observação.
- O gerenciador local de processos foi corrigido para localizar todos os processos pelo caminho
  exato de `main.py`; start/status registram os dois PIDs do launcher/runtime e stop encerra ambos.
- Backup SQLite consistente pré-v15:
  `data/choque_bgr.db.pre-intelligent-operations-v15-20260822-082100-consistent`, 475136 bytes,
  migration 14, `integrity_check=ok`, SHA-256
  `362092E9A39886C5F6327D2D25A3DCAD141ABF20CB769DAE18BA7F0D7380C302`. A cópia anterior com
  sufixo `.INVALID-INCOMPLETE` é deliberadamente inválida e não deve ser usada.
- QA local: Ruff e compileall aprovados; **141 testes**; ensaio da migration sobre cópia real com
  migration 15, 10/10 tabelas verificadas e `integrity_check=ok`; `main.py --check` com 15 cogs,
  46 handlers locais e 21 views persistentes.
- Rollout real: `INTELLIGENT_OPERATIONS_LIVE_PASS`, 13/13 tabelas, uma call de espera, 11 calls
  ativas, 3/3 painéis, 8/3/5 custom IDs e zero comandos. Mínimo, catálogo, arquivo de cadastros,
  ticket, Fases 11/12 e labels de calls também passaram. Bot online em uma única instância lógica.

## Programa Centro de Comando Web (2026-08-22)

- Seis subfases concluídas em `web/` (Next.js/Auth.js) e `command_center/` (FastAPI), consumindo o
  core Python real e sem duplicar regras de promoção, ponto, disciplina ou elegibilidade no React.
- Migration v16: outbox de ações web, auditoria de acesso com fingerprints HMAC e registry atual de
  canais/categorias/calls/cargos por ID. Promoção e aprovação de cadastro enfileiram efeito Discord
  na própria transação; o worker faz retry e auditoria.
- Rotas entregues: login, dashboard, prontidão, patrulhas, pontos, membros/dossiê, carreira,
  recrutas, qualificações, treinamentos, inbox/solicitações, disciplina, mudanças, relatórios,
  auditoria, integridade, configurações e manutenção.
- Sistema: edição de parâmetros, destinos, patentes, calls autorizadas e RBAC usando o registry do
  Discord, logout, loading/error/access denied e refresh em 30 segundos/foco/reconexão.
- Topologia documentada em ADRs 004–007, `web/vercel.ts`, configurações Railway e runbook de corte
  único para Supabase. Nenhum deploy, OAuth real ou banco externo foi provisionado.
- Revisão visual autenticada: 1440, 1280, 1024, 768 e 390 px, sem overflow global/console errors;
  Chromium desktop/mobile e Firefox passaram no Playwright. Lovable privado foi usado como
  referência e seu diff foi revisado, sem copiar a falha de colunas do protótipo.
- QA final do lote: Ruff/compileall, 146 testes Python, 6 testes Vitest, typecheck, ESLint, build,
  três E2E e `npm audit` com zero vulnerabilidades. `main.py --check` aprovado em migration 16.
- Backup pré-v16: `data/choque_bgr.db.pre-command-center-v16-20260822-064402`, 651264 bytes,
  `integrity_check=ok`, SHA-256
  `37838C26A54D807DC9C9B296CC2D675134ADA88765A7E865CA34639546151C29`.

## Sistema de Alistamento, Recrutamento e Integridade (2026-08-22)

- Migration v17 adiciona formulário/versionamento, grupos e banco de 45 questões, campanhas,
  candidaturas, respostas, eventos de integridade, avaliações humanas, entrevistas, notas,
  adaptações, cooldowns, bloqueios, histórico, follow-up de recruta e outbox de notificações.
- Cada candidatura recebe 24 questões balanceadas por grupo e dificuldade a partir do snapshot
  imutável publicado. Timer, token HMAC, autosave, expiração, condições, capacidade e idempotência
  são controlados pelo backend. Eventos de foco/cópia/colagem e similaridade são somente evidências.
- O portal público, avaliação e acompanhamento usam Discord OAuth. O admin possui fila, dossiê,
  formulário, preview, campanhas e bloqueios; aprovação/rejeição final permanecem humanas e RBAC.
- Aprovação persiste membro, origem, follow-up, auditoria e `MEMBER_SYNC` na mesma transação. A
  outbox entrega notificações, entrevista, resultado e logs com retry e reconciliação.
- Segurança específica: BOLA responde 404, consulta de elegibilidade revalida vínculo na guild,
  rate limit sensível, tokens assinados e RLS PostgreSQL default-deny preparado sem políticas de
  navegador. Dados reais não foram enviados a Lovable ou provedores de IA.
- QA: **169 testes Python**, Ruff, compileall, `main.py --check`, **16 testes Vitest**,
  typecheck/ESLint/build e **6 E2E** em Chromium desktop/mobile e Firefox. Banco v17 com
  `integrity_check=ok`, zero violações de FK, 12 grupos e 45 questões.
- Snapshot consistente pós-migration:
  `data/choque_bgr.db.post-recruitment-v17-20260822-081052`, 692224 bytes. O bot voltou online e a
  campanha padrão permanece `DRAFT`, sem abrir recrutamento automaticamente.
- Infra externa: não existe projeto Vercel para esta aplicação; Railway exige reautenticação; os
  dois projetos Supabase visíveis eram alheios e não foram tocados; Lovable estava sem créditos.
  Portanto nenhum deploy, domínio, OAuth de produção ou banco externo foi provisionado.

## Diretriz revisada do Robô Analista (2026-08-23)

- A dependência externa deixou de ser bloqueio: o motor determinístico local será a autoridade e o
  fallback, reaproveitando rubricas/versionamento, pesos, critérios objetivos, cruzamentos e sinais
  de integridade. O relatório será explicável; respostas abertas ficam limitadas a verificações
  transparentes, nunca a uma decisão automática simulando compreensão semântica.
- Depois da Central de Tags, será feito somente um spike isolado com Qwen3-0.6B GGUF Q4_0 via
  `llama.cpp` (Apache-2.0). O processo terá 1536 MB iniciais, contexto curto, concorrência 1,
  timeout, circuit breaker, dados minimizados/anônimos, schema estrito e benchmark de português,
  RAM, CPU, latência, repetição, consistência e concordância humana. Sem gate verde, seguem apenas
  regras. Não há deploy, nova aplicação ou mudança de RAM nesta decisão.
- O modelo opcional apenas resume, organiza evidências e sugere sinais; RBAC, privacidade,
  idempotência, auditoria, validação e decisão final continuam humanas. Nenhum endpoint ou job pode
  aprovar/reprovar baseado na saída do modelo.

## Robô Analista de Candidaturas (2026-08-22)

- Migration v18 adiciona contexto, rubrica/critérios, jobs, resultados e feedback versionados.
  Jobs são idempotentes por hash, usam cache, retry limitado, histórico imutável e estados explícitos.
- Na entrega original, o provider desacoplado começava desativado. Desde 2026-08-24, o motor local
  determinístico é o padrão; a integração OpenAI-compatible permanece apenas opcional. Nenhum dado
  real foi enviado a serviço externo.
- A validação server-side rejeita schema extra, recomendação inválida, evidência sem questão,
  conteúdo ativo e notas fora do limite. A nota ponderada e os thresholds são recalculados no core;
  sinais objetivos de integridade podem exigir revisão, mas nunca produzem culpa ou reprovação.
- Configuração, rubrica, contexto, preview sintético, histórico, feedback e divergências estão em
  `/recruitment/ai`. O dossiê exibe a análise recolhida e secundária às respostas apenas para RBAC
  autorizado; rotas de candidato não recebem o conteúdo automatizado.
- QA final do item: 183 testes Python, Ruff, compileall, check migration 18; 16 Vitest,
  typecheck/ESLint/build e 6 E2E. Screenshots autenticados em 1440 e 390 px sem overflow ou erros.
- Snapshot pré-v18: `data/choque_bgr.db.pre-recruitment-ai-v18-20260822-084125`, 1007616 bytes.
  Banco oficial íntegro, FK=0, uma rubrica/contexto padrão, zero jobs e bot conectado à guild.
- Provider permanece desligado até segredo e autorização próprios. Lovable sem créditos e nenhuma
  infraestrutura Vercel/Railway/Supabase foi criada ou alterada.

## Security Hardening completo (2026-08-22)

- Migration v19 adiciona eventos de segurança, revogação de sessões, nonces anti-replay e snapshots
  de auditoria Discord. O dashboard restrito `/security` controla lockdown e revogação global ou
  individual e exibe health/eventos append-only.
- BFF e API abandonaram o segredo estático por request HMAC-SHA256 com body hash, identidade, guild,
  timestamp, nonce persistido, emissão da sessão e prova OAuth de guild. Produção falha fechada com
  secret fraco/reutilizado, origem/host curinga, bypass legado ou bootstrap indevido.
- CSP com nonce, headers, CORS/origin/host allowlists, body/query/time limits, rate limit, redaction,
  error IDs, mass-assignment deny e segregação de autoaprovação foram implementados/testados.
- Backup consistente pré-v19: `data/security_backups/choque_bgr-20260822T125959Z.db`, 1077248
  bytes, migration 18, integrity ok, FK=0, SHA-256
  `e94b603cdbc4f7ed054c9f657b5a3eeb452afac2b6b09d9b112bf7a594338e14`; restore drill aprovado.
- Rollout real: migration 19 íntegra, backup diário pós-v19 criado, bot conectado. A auditoria
  detectou 6 findings reais: Administrator e cinco permissões excessivas no cargo do bot. Nenhuma
  correção destrutiva automática foi feita.
- Supply chain: dependências vulneráveis atualizadas; o extra de áudio não utilizado foi removido.
  `pip-audit` e `npm audit` retornaram zero vulnerabilidades conhecidas. CodeQL, Dependabot, scanner
  de segredos e SBOM SPDX entram no CI.
- QA: 192 testes Python, Ruff, compileall, check v19, 16 Vitest, typecheck, ESLint, build e 6 E2E.
  `/security` foi revisado em 1440/390 px, sem overflow ou erro de console.
- Documentação: `SECURITY.md`, threat model, incident response, backup/restore, security test plan,
  ADR 010 e matriz 1–220. Resultado: 164 IMPLEMENTADO, 27 NÃO APLICÁVEL, 29 PENDENTE; veredito
  **FAIL / não pronto para produção pública** até rotação do token e prova da infraestrutura.

## Correção U+3164 (2026-08-22)

- `DISCORD_INVISIBLE_SPACE` é gerado por `chr(0x3164)` e o fallback por `chr(0x2800)`; testes
  inspecionam os codepoints e proíbem espaço, ponto médio, bullet e U+30FB entre palavras.
- Probe real criou/releu canais temporários e comprovou que a API remove U+3164, U+2800 e todas as
  sequências invisíveis testadas que continham U+3164. U+00B7/U+30FB continuam preservados, mas não
  foram reaplicados por contrariar a correção solicitada.
- A migração em massa ficou bloqueada e os 69 nomes atuais foram preservados. Snapshot:
  `data/server_layout_backups/discord_layout_1146622062895579186_20260822T131041Z.json`.
- O migrador agora restaura automaticamente o nome anterior se primário e fallback forem
  normalizados. Salas dinâmicas usam um token único para não criar palavras coladas.

## Fase 16 — Comandante Automático da Patrulha (2026-08-22)

- Migration v20 adiciona comandante atual e lock manual em `patrols`, histórico temporal exclusivo
  por patrulha e flags administrativas `PATROL_WITHOUT_ELIGIBLE_COMMANDER`. `leader_member_id` e
  `member_role` permanecem sincronizados por compatibilidade, sem alterar a patente real.
- `OperationsService` seleciona apenas integrantes ativos/presentes e elegíveis. A ordenação é
  determinística e configurável: qualificação existente, patente, tempo na patente, horas válidas,
  tempo de corporação e ordem de entrada, com desempate estável por registro da patrulha.
- Status ativo, RankSync, nível mínimo, suspensão, afastamento e qualificação opcional/obrigatória
  são revalidados server-side. Comandante elegível não é trocado pela entrada de superior no padrão;
  override humano permanece bloqueado até perda real de elegibilidade.
- Saída da call/patrulha transfere o comando na mesma transação. Mudanças de cargo reagem pelo
  listener e uma reconciliação global de um minuto cobre status/qualificação/restart sem loop ou
  histórico duplicado. Encerramento fecha a janela temporal aberta.
- A Central Administrativa ganhou submenu visual com `Encerrar patrulha`, `Alterar comandante`,
  `Regra de comando`, `Prioridade` e `Histórico`. Override exige
  `patrol.commander.override`, integrante da patrulha, presença na call, motivo e nova validação.
- Central de Patrulha, consulta pessoal, relatório pós-patrulha e Centro de Comando Web exibem o
  comandante persistido. O feedback registra quem era o comandante final e se o avaliado exercia
  essa função; o relatório mostra todas as janelas de comando.
- Testes cobrem Cabo/Soldado, qualificação obrigatória, empate por ordem de entrada, superior que
  entra depois, saída/reatribuição, lock manual, ausência de elegíveis, flag e idempotência.
- Rollback verificado: backup v19 `data/security_backups/choque_bgr-20260822T130039Z.db`, 1122304
  bytes, integrity ok, FK=0, SHA-256
  `4ce50811763de8a900cc52cb18b69abedd342997721730c5be3c378340479f7c`. O `main.py --check`
  aplicou v20 antes de um novo snapshot específico; essa ordem ficou registrada. Backup pós-v20
  `choque_bgr-20260822T132741Z.db`, 1146880 bytes, integrity ok, FK=0, SHA-256
  `2417ce26877c2220c958699a25ac328747af67267d04f28bafb440621589e871`; ambos passaram restore drill.
- QA: Ruff, compileall, **198 testes Python**, check v20, typecheck, ESLint, build, **16 Vitest** e
  **6 E2E**. `PATROL_COMMANDER_LIVE_PASS` confirmou 2/2 tabelas, 4/4 colunas, 5/5 controles,
  zero comandos e bot online. Havia zero patrulhas ativas; nenhuma operação real foi fabricada.

## Fase 17 — Portaria Digital / cadastro obrigatório (2026-08-22)

- Migration v21 adiciona registros do gate, eventos, classificações de recursos, snapshots de
  permissão, achados e checklist de onboarding. Identidades Discord/BGR ativas são únicas e decisões
  usam updates condicionais/idempotência.
- O cadastro público substituiu o fluxo antigo por uma Portaria Digital com três ações persistentes:
  cadastrar, consultar situação e pedir ajuda. O modal recebe somente nick MTA e ID BGR. Visitantes
  desconhecidos, duplicidades, ex-membros e vínculos conflitantes exigem decisão humana.
- A Central Administrativa oferece fila, aprovação, vínculo, correção, rejeição, configuração por
  selects, bypass, preview, ativação, reconciliação e validação. Toda decisão persiste evento e
  auditoria na mesma transação; entrega Discord usa retry global para absorver rajadas de startup.
- Listener de entrada/cargos/canais, startup e retry mantêm os cargos gerenciados e registram falhas.
  RankSync continua soberano sobre patentes/apelidos de membros ativos; recrutamento e outbox
  convergem para o mesmo gate/checklist.
- O Centro de Comando ganhou página `/registration`, API de consulta/decisão/configuração, métricas,
  achados e integração com inbox, com RBAC e validação dos recursos por registry.
- Snapshot Discord reversível:
  `data/server_layout_backups/registration_gate_1146622062895579186_20260822T141811Z.json`.
  Backup pré-v21 restaurado: `data/security_backups/choque_bgr-20260822T141145Z.db`, migration 20,
  integrity ok, FK=0, SHA-256
  `1c7fa2d5bb301346775d416daa78693d438c8ef69ce448d56527e9b2e3f08ac9`.
- Rollout: painel preservado, 96 recursos protegidos, 21 públicos, 121 contas restritas e zero
  vazamentos/unclassified. `REGISTRATION_GATE_LIVE_PASS` validou bot, owner, painel e uma amostra de
  dez visitantes reais. O caso de patente sem identidade ficou restrito para cadastro/revisão.
- QA: **210 testes Python**, Ruff, compileall, check v21, **16 Vitest**, typecheck, ESLint e build.
  O bot voltou online em uma única instância. O token exposto e as permissões excessivas do cargo do
  bot continuam fora da capacidade de correção automática e mantêm o gate público geral em FAIL.

## Fase 18 — Operação avançada de tickets (2026-08-22)

- Migration v22 expande `service_tickets`/`ticket_rooms` e cria participantes, timeline operacional
  e metadados de transcrição. Updates condicionais e índices impedem duplo responsável/participante;
  nenhuma mensagem histórica ou segmento de dados foi reescrito.
- O painel persistente da sala passou de uma para oito ações: assumir/liberar, prioridade,
  adicionar/remover participante, avisar solicitante, transcrever, reabrir e encerrar. Encerramento
  exige motivo e confirmação literal; reabertura usa a mesma sala.
- Transcrições incluem timestamp, ID do autor, texto minimizado e contagem de anexos, redigem padrões
  comuns de segredo e persistem somente hash, contagem, finalidade e responsável. A entrega ocorre na
  sala e, quando configurado, em canal staff privado.
- Categoria ativa, arquivo, cargo responsável e canal de transcrição são configuráveis por ID no
  Discord e em `/tickets`. A API valida registry, categorias distintas e hierarquia do bot.
- Rollout reversível criou duas categorias, moveu a única sala arquivada sem alterar ID/histórico e
  atualizou sua mensagem no lugar. Snapshot:
  `data/server_layout_backups/ticket_operations_1146622062895579186_20260822T145310Z.json`.
- Backups v21/v22 passaram restore drill, integrity ok e FK=0. A aplicação final passou
  `TICKET_OPERATIONS_LIVE_PASS` e `TICKET_ROOM_LIVE_PASS`: dez visitantes, matriz completa de seis
  perfis, uma sala histórica, 8/8 controles, 11/11 cargos de Comando e zero vazamentos observados.
- QA final: **219 pytest**, Ruff, compileall, `main.py --check` (v22, 17 cogs, 46 handlers, 21 views),
  **16 Vitest**, ESLint, build, typecheck e **6 E2E**. Bot online em uma única instância.

## Publicação privada e preparação de deploy (2026-08-22)

- Repositório privado criado em `https://github.com/EoPaiva/choque-bgr-gestao` e povoado por
  commit-raiz limpo. O histórico antigo, token, `.env`, bancos, backups, logs e dados pessoais não
  foram enviados. Alertas de vulnerabilidade e correções automáticas estão ativos; secret scanning
  privado não está disponível no plano atual.
- Railway não recebe dois serviços sobre SQLite. O novo runtime combinado executa check/migrations,
  inicia bot e FastAPI no mesmo serviço/volume, supervisiona falhas e encerra os dois processos de
  forma coordenada. PostgreSQL/Supabase continua sendo um corte futuro único, não dual-write.
- O frontend ganhou `/status`, uma superfície pública sem integração administrativa, revisada em
  1440/390 px. Ela informa 20/22 fases e mantém o gate público como RETIDO.
- Regressão final local: **223 pytest**, Ruff, compileall, check v22, secret scan; **17 Vitest**,
  typecheck com `next typegen`, ESLint, build, npm audit e **6 E2E** aprovados.
- O alerta Dependabot `GHSA-6w46-j5rx-g56g` foi encerrado após atualizar `pytest` para 9.0.3 e
  `pytest-asyncio` para 1.4.0; a suíte completa continuou com 223 testes aprovados. O Security gate
  remoto ficou verde. CodeQL mantém a análise `security-extended` e arquiva SARIF no workflow,
  pois o plano atual não habilita upload de Code Scanning para este repositório privado.
- O workflow CodeQL final passou; os artefatos foram baixados e inspecionados com zero resultados em
  `python.sarif` e zero em `javascript.sarif`. A API recusou branch protection com HTTP 403 por
  exigir GitHub Pro no repositório privado; nenhuma redução de privacidade foi feita como contorno.
- O OAuth do CLI Vercel foi concluído e `/status` está publicado em
  `https://web-plum-tau-82.vercel.app/status`. A prova de produção registrou HTTP 200, título
  correto, indicadores `20 / 22`, `235+` e `RETIDO`, zero erros de console/overlay e capturas
  responsivas em desktop/mobile. O conector reconhece a equipe, mas retornou 403 ao listar o projeto;
  por isso a evidência de disponibilidade foi obtida diretamente da URL pública e pelo navegador.
- A Railway foi reautenticada. No projeto `pure-connection/production`, o serviço offline
  `beautiful-laughter` foi autorizado para uso exclusivo do CHOQUE. Variáveis do sistema anterior
  foram removidas sem revelar valores; um serviço temporário vazio foi excluído; um volume de
  500 MB foi montado em `/data`; 15 configurações e três segredos distintos foram cadastrados. O
  manifesto raiz `railway.toml` torna o runtime combinado reproduzível. `DISCORD_TOKEN` não foi
  cadastrado e nenhum deployment foi iniciado.
- O rollout completo de OAuth/API/worker permanece bloqueado por rotação do token e redução das
  permissões do cargo do bot; publicar antes disso contrariaria o gate `FAIL` documentado em
  `SECURITY.md`.

## Cutover operacional Railway + Vercel sob exceção (2026-08-22)

- O proprietário autorizou explicitamente ignorar o gate apenas para este corte. A decisão foi
  registrada sem valores secretos e não altera o veredito `FAIL` nem os requisitos de rotação e
  menor privilégio.
- O bot local foi desligado e o banco foi congelado sem shifts/patrulhas ativos. O backup
  `choque_bgr-20260822T163857Z.db` passou integrity/FK/migration 22 e teve SHA-256
  `59e9e8ffc8df52db31e245f6979c404fa64a526ecce7b537d82631845e3f62c3` antes do upload e depois do
  download do volume Railway.
- Um bootstrap neutro foi usado para ativar o volume. Limites de horário do plano gratuito exigiram
  mover a única réplica e o mesmo volume para `asia-southeast1-eqsg3a`. O runtime final ficou
  `SUCCESS` no deployment `5bae72f3-6540-4da4-a78a-470e9dcbdd6f`, com `/health` 200, Gateway
  conectado, banco íntegro e nenhuma segunda instância local.
- O healthcheck interno expôs um conflito com `TrustedHostMiddleware`. Foi criado um bypass somente
  para `GET /health`, mantendo hosts inválidos bloqueados nas rotas protegidas e preservando CSP,
  HSTS, `no-store`, correlation ID e demais headers. A regressão elevou a suíte para 225 testes.
- O frontend Vercel foi publicado no deployment `dpl_HdH2HSDYQrQUz3avDeppnDg35ZRr` e alias
  `https://web-plum-tau-82.vercel.app`. Status/login/provider/callback/redirecionamento passaram e a
  consulta de runtime encontrou zero 5xx. Login humano, revogação de sessão e contas MEMBRO/COMANDO
  continuam validações externas.
- Gates finais: Ruff, compileall, check v22, secret scan, **225 pytest**, ESLint, typecheck,
  **17 Vitest** e build Next.js. O audit Discord de startup ainda reporta seis achados; credenciais
  divulgadas e permissões excessivas continuam risco aceito, não correção concluída.
- O snapshot completo foi publicado no repositório privado no commit
  `5f1b8340410807c575780f17c1d25b9b60441eb5`. O Security gate `32587617947` passou todas as etapas;
  o CodeQL `32587617965` passou e preservou SARIF, embora o plano privado não habilite a interface de
  Code Scanning. A observação final confirmou uma instância Railway `RUNNING`, volume `READY`, health
  ok, um único marcador de conexão Discord, zero marcadores fatais, bot local offline e Vercel 200.

## Fase 19 — identidade/RBAC e correções da Portaria (em execução, 2026-08-22)

- A migration v23 consolida perfis de acesso, funções, mappings por role ID, projeções de identidade,
  versão de autorização, jobs de reconciliação, eventos correlacionados e observabilidade compartilhada
  por bot/API/site. A migração v22→v23 foi repetida sobre cópia do banco Railway com integrity ok e
  zero violações de foreign key.
- A Portaria Digital deixou de manter pedidos apenas na fila interna: a submissão publica ou restaura
  uma mensagem no canal de aprovação, com botão persistente para a fila administrativa. Decisões
  publicam resultado idempotente no histórico e retiram a mensagem pendente; startup e retry reparam
  entregas ausentes sem desfazer decisões já persistidas.
- O primeiro nickname oficial agora captura uma única vez o apelido anterior ao cadastro, inclusive o
  estado sem nickname. Desligamento administrativo ou voluntário passa pelo sincronizador central,
  remove cargos gerenciados e restaura o valor original, com auditoria de sucesso/falha.
- QA local final deste corte: **272 pytest**, Ruff, compileall, `main.py --check` com migration 23,
  scanner de segredos, **29 Vitest**, ESLint, TypeScript e build Next.js.
- Antes do rollout foi criado novo backup remoto íntegro. O deployment Railway anterior foi removido
  para garantir instância única, porém a plataforma bloqueou upload e redeploy durante a janela de pico
  do plano gratuito. Serviço, volume, variáveis e domínio permanecem preservados; o bot remoto está
  offline e a fase continua aberta até publicação, reconciliação e validação Discord reais.
- Uma nova tentativa controlada às 17:09 BRT recebeu o mesmo bloqueio regional de horário de pico.
  Nenhuma instância, banco ou recurso pago alternativo foi criado. O snapshot privado da fase foi
  publicado no commit `436aa57ba67b5bff6e81d455034b90904edc6d8b`; a árvore de trabalho local
  permaneceu preservada. O status Vercel segue em `https://web-plum-tau-82.vercel.app/status` com
  HTTP 200 e mensagem de manutenção coerente com o estado operacional.

## Pendências funcionais registradas durante a validação da Portaria (2026-08-22)

- O piloto visual Small Caps foi priorizado como item 24 e será aplicado em um único canal por ID
  logo após a validação da Portaria. O proprietário precisa aprovar a amostra.
- O Gerenciador de Cadastros do Alto Comando foi formalizado como item 25, sem exclusão física e
  com busca, edição, desativação lógica, reabertura, confirmação, motivo, auditoria e recuperação.
- A conformidade de patente sem cadastro foi formalizada como item 26: DM com link direto para a
  Portaria, prazo persistente de 72 horas, lembretes, alerta de falha ao Alto Comando e retirada
  idempotente apenas da patente concedida caso a conta continue sem cadastro ao vencer o prazo.
- O filtro dos seletores disciplinares foi registrado como item 27 no fim da fila funcional. A
  implementação futura deverá usar membros cadastrados/elegíveis do banco, excluir bots e visitantes
  e suportar paginação, busca e revalidação no backend.
- O mesmo item agora inclui a simplificação integral da Central Administrativa: entrada por poucas
  categorias, explicações curtas, submenus com retorno e preservação de todas as funções atuais.
- A exoneração foi anexada ao mesmo item: manter o usuário no servidor, remover cargos operacionais,
  restaurar o apelido anterior e atribuir um cargo `Exonerado` configurado por ID, sem kick ou ban.
  Reversão e auditoria permanecem obrigatórias.
- Uma auditoria completa de ações ocultas foi registrada como item 28: inventário de componentes e
  callbacks, prova de caminho visível, detecção de órfãos/custom IDs duplicados e matriz de
  alcançabilidade no relatório vivo.
- O pacote Discloud foi renumerado para o item 29, atualizado para o plano Diamond e continua sendo
  obrigatoriamente a última etapa, depois do Discord e do site.

## Central Administrativa, exoneração e migração Small Caps (2026-08-22)

- A Central Administrativa foi simplificada na mesma mensagem persistida: cinco ações raiz agrupam
  as doze funções existentes em Efetivo, Disciplina, Processos e Serviço/Operações, com descrições e
  retorno. O rollout REST confirmou um único painel e cinco componentes.
- A Gestão Disciplinar ganhou Exonerar visível, fonte de candidatos cadastrados/elegíveis, motivo e
  confirmação literal. A ação mantém a conta no servidor, fecha ponto, remove cargos gerenciados,
  aplica Exonerado por ID e audita a decisão.
- O teste humano revelou histórico legado de apelido incorreto. Foi adicionado fallback que preserva
  o nome entre `[PAT]` e `[ID]`, releitura REST, segunda tentativa, persistência do reparo e
  reconciliação no startup. O caso real terminou como `Paiva Teste`, com Exonerado e sem patente.
- O piloto visual Small Caps em Avisos do Comando foi aprovado pelo proprietário. O padrão oficial
  tornou-se `emoji・ꜱᴍᴀʟʟ-ᴄᴀᴘꜱ`, com hífen entre palavras; categorias continuam no padrão próprio.
  `format_channel_name()` agora governa criações futuras e o formato itálico/U+3164 ficou apenas
  para rollback/diagnóstico.
- Inventário pré-corte: 97 canais no registry, uma sala dinâmica e nenhum ID ausente/desconhecido.
  Após backup e snapshot, a migração renomeou 97 alvos restantes, atualizou 12 labels de calls e
  concluiu sem fallback/revisão. A comparação estrutural confirmou 98/98 IDs, categorias, posições
  e overwrites preservados; `LIVE_PHASE12_OK` permaneceu verde após o restart.
- Gates: 281 pytest, Ruff, compileall, `main.py --check`, banco v23 íntegro, bot online em instância
  única. Os 97 registros de auditoria provocaram apenas rate limit transitório tratado pelo
  `discord.py`; não houve erro fatal nem reversão de nome.
- Pendências seguintes: Gerenciador de Cadastros (item 26), conformidade de patente sem cadastro em
  72 horas (item 27), demais filtros disciplinares e auditoria de ações (item 28), depois site e
  Discloud Diamond conforme a fila.
# Atualização operacional — 2026-08-22 — Itens 26–28

- Gerenciador de cadastros exclusivo do Alto Comando: lista, busca, consulta, edição, desativação
  lógica e reabertura, sem exclusão física.
- Conformidade de 72 horas ativa para patentes gerenciadas e Companheiro de Farda. Cinco pendências
  reais foram criadas e cinco DMs entregues com link da Portaria; aprovação cancela a cobrança e a
  expiração remove somente o cargo que a originou.
- Companheiro de Farda usa `[COMP.F]` no apelido após cadastro aprovado; a única conta já cadastrada
  foi reconciliada, e as demais aguardam Portaria.
- Todos os seletores disciplinares usam o efetivo cadastrado e revalidam elegibilidade no callback.
- Auditoria estática: 20 módulos, 229 classes de interface, 331 componentes, 87 IDs explícitos,
  zero duplicidade, zero callback ausente e zero interface ativa órfã.
- QA: 292 testes, Ruff, compile e `main.py --check`; migration v24 e bot local online.

## Gestão bidirecional de qualificações — 2026-08-23

- A migration 26 adicionou `qualification_changes` como ledger append-only e ampliou a outbox web
  com `QUALIFICATION_SYNC`, preservando `member_qualifications` e os resultados de treinamento.
- `OperationsService` passou a projetar a decisão mais recente por membro/curso, registrar
  concessão ou revogação web na mesma transação da auditoria/outbox e absorver alterações de
  cargos Discord sem eco. O dispatcher revalida o estado atual antes de tocar no cargo.
- A API expõe `POST /v1/qualifications/manage` sob `qualification.manage`, exclusivo do Alto
  Comando. A matriz Next.js oferece ações acessíveis para quem possui a permissão e permanece
  somente leitura para os demais perfis autorizados ao Centro de Comando.
- Rollout: backup consistente da Discloud preservado, banco remoto migrado para v26, rota protegida
  confirmada, Gateway conectado, health 200 e frontend publicado no alias Vercel principal. O teste
  automatizado não concedeu/revogou curso de uma pessoa real apenas para gerar evidência.
- QA: **306 testes Python**, **32 testes web**, Ruff, compileall, `main.py --check`, ESLint,
  TypeScript e build Next.js; `git diff --check` sem erro.
# Canal de Status do Bot — concluído em 2026-08-24

- A migration 36 adiciona estado durável por componente e timeline imutável para os oito serviços
  exibidos no painel: Gateway, API/Site, Portaria/Cadastro, Recrutamento/Mesa, notificações/filas,
  Auditoria/Histórico, Bate-ponto/Patrulhas e Central de Tags.
- O painel público é uma única mensagem fixada, editada e recuperada após restart, com apenas
  Atualizar e Detalhes. O painel administrativo privado possui ações explícitas de atualização,
  manutenção, instabilidade, desativação, indisponibilidade e normalização.
- Overrides exigem permissão no backend, motivo e compare-and-set; responsável, previsão, expiração,
  auditoria e notificações com cooldown são persistidos. A detecção automática usa histerese e não
  trata falhas históricas terminais como indisponibilidade atual.
- Produção validada com os oito componentes operacionais, mensagens originais preservadas e fixadas,
  nenhuma duplicata, health 200 e somente um Gateway. Gates: 395 pytest, Ruff, compileall e
  `main.py --check`; backup pós-publicação com `quick_check=ok`, zero FK e migration 36.

# Bate-ponto, patrulhas e viaturas — concluído em 2026-08-24

- A migration 37 estende sessões, calls e patrulhas sem substituir a fonte existente, e adiciona
  timeline de composição, catálogo de ocorrências/artigos, relatórios congelados, integrantes,
  ocorrências, evidências e ajustes administrativos append-only.
- `DutyPatrolService` centraliza todos os eventos de voz. Entrada em call de patrulha inicia o ponto e
  cria/localiza a viatura; troca entre calls mantém a mesma sessão; saída, perda de cargo e restart
  encerram ou recuperam o fluxo pela política de grace sem duplicar tempo.
- Capacidade, cargos permitidos e ponto automático são configurados por ID. O comandante é escolhido
  pela hierarquia canônica e transferido na mesma cadeia transacional. A fila PTR antiga continua
  coexistindo pela fonte explícita, sem sistema paralelo.
- Central de Patrulha e Efetivo em Serviço agrupam militares por viatura e exibem quem ficou sem
  viatura. Atualizações são coalescidas para editar as mesmas mensagens e evitar flood.
- O relatório PTR congela viatura, comandante, integrantes e duração; administração adiciona
  ocorrência, artigo e evidência, enquanto o membro consulta somente seus próprios registros, sem
  URLs sensíveis de terceiros.
- Correções de composição, comando e ponto exigem RBAC, motivo, correlação e valores antes/depois. Se
  uma abertura excepcional encontra a viatura lotada, o ponto permanece auditado em “sem viatura”,
  sem estado parcial oculto.
- QA: 419 testes Python, 41 testes web, Ruff, compileall, `main.py --check`, lint, typecheck e build.
  Produção: health 200, migration 37, um único Gateway e backup pós-publicação com `quick_check=ok`,
  zero FK, uma viatura real recuperada e nenhuma duplicidade de sessão, call, comandante ou outbox.

# Carreira, mérito e oficialato — concluído em 2026-08-24

- A migration 38 estende a fonte canônica de ações de pessoal e adiciona regras/eventos de
  progressão, mérito e o ciclo versionado de candidatura a Oficial. A migration 39 adiciona a fila
  durável de notificações com retry, correlação e recuperação após restart.
- A progressão automática calcula somente horas de pontos válidos e tempo mínimo por patente,
  processa a cadeia na ordem e para em Cadete. Promoção manual, rebaixamento e mérito exigem
  permissão, motivo, auditoria e sincronização pela outbox já existente.
- O questionário de Oficial possui exatamente 30 perguntas em dez competências. Respostas são do
  próprio candidato; o relatório determinístico organiza evidências e sinais, mas não decide. O
  responsável assume com controle de versão, registra notas humanas e entrevista e toma a decisão
  final sem autoavaliação, com concorrência e idempotência protegidas no backend.
- A interface Discord ganhou candidatura persistente no painel de Carreira. O portal ganhou área do
  candidato, fila dos responsáveis, filtros e dossiê privado. Identificadores Discord permanecem
  texto no contrato web, e o acesso administrativo é limitado à permissão específica, com step-up
  nas mutações sensíveis.
- A configuração ao vivo reutilizou o cargo existente de responsável por upamento e vinculou cinco
  canais por ID. A inicialização simultânea do questionário revelou uma disputa real, corrigida por
  rechecagem dentro da transação e coberta por teste concorrente.
- Gates finais: **429 testes Python**, **41 testes web**, Ruff, compileall, `main.py --check`, lint,
  typecheck e build. Produção: health 200, migration 39, um Gateway, Vercel sem erros nas rotas novas
  e backup pós-publicação com `quick_check=ok`, zero FK, um questionário ativo com 30 perguntas e
  nenhuma notificação de carreira pendente ou falha.

# Robô Analista local — concluído em 2026-08-24

- `LocalDeterministicRecruitmentAnalysisProvider` substitui o estado desativado como motor padrão.
  Ele roda no mesmo backend, sem chave, HTTP, serviço externo, tool use ou acesso administrativo.
- A entrada continua minimizada e estruturada. Critérios são vinculados somente pela pergunta e pelo
  grupo versionados, impedindo que repetição de palavras pelo candidato escolha a rubrica. O motor
  mede estrutura/completude, sinaliza respostas genéricas, trata instruções maliciosas como dados e
  aponta contradições explícitas sem alegar culpa, autoria por IA ou perfil psicológico.
- O resultado contém resumo estrutural, critérios com evidências, pontos positivos/atenção,
  inconsistências e perguntas para entrevista. O backend recalcula o score e a faixa; nenhuma saída
  muda candidatura, membro, Discord, cooldown ou decisão humana.
- A ativação versionada aposentou um job esgotado do motor antigo como `OUTDATED`; como a candidatura
  já estava encerrada, ela não foi reanalisada. Novos envios geram jobs idempotentes e assíncronos;
  falha do analista nunca bloqueia o recrutamento.
- Benchmark sintético: 500 execuções, todas idênticas, mediana 1,385 ms, p95 1,517 ms e máximo
  2,669 ms. Gates: **433 testes Python**, **41 testes web**, Ruff, compileall, `main.py --check`,
  lint, typecheck e build.
- Produção: app combinado online com cerca de 166 MB, health 200, migration 39, um Gateway e Vercel
  sem erros nas rotas do analista. Backup pós-publicação: `quick_check=ok`, FK=0, oito configurações
  ativas, zero job ativo/esgotado e zero resultado criado com dados reais durante a validação.

# Auditoria final da continuidade — concluída em 2026-08-24

- A documentação viva foi reconciliada entre handoff, fila, ledger, especificação do analista e este
  relatório. Afirmações históricas foram mantidas como história e marcadas como superadas quando a
  produção posterior mudou o estado.
- `scripts/audit_interaction_routes.py` passou sobre 22 módulos, 279 classes de interface e 390
  componentes. Há 107 `custom_id` explícitos sem duplicidade, zero callback ausente e zero interface
  ativa órfã. `docs/INTERACTION_ROUTE_AUDIT.md` contém a matriz atualizada das entradas.
- `main.py --check` terminou `CHECK_OK` com migration 39, 18 cogs, 46 comandos e 25 views
  persistentes. O último gate funcional completo continua em 433 testes Python e 41 testes web,
  acompanhado por Ruff, compileall, lint, typecheck, build e `git diff --check` verdes.
- `scripts/security_scan.py` terminou `SECRET_SCAN_OK`. O scanner foi endurecido para diferenciar
  literais suspeitos de valores produzidos por chamadas de função, eliminando falso positivo sem
  ignorar segredos atribuídos diretamente.
- O escopo autônomo funcional foi encerrado. Compactação do Discord continua adiada por decisão do
  proprietário; rotação de credenciais, menor privilégio e validação humana de sessão continuam
  pendências externas obrigatórias e não foram declaradas concluídas.

# Canal oficial de atualizações — concluído em 2026-08-24

- Um novo canal de leitura foi criado na categoria Informações seguindo Small Caps e as permissões
  existentes da categoria. A mensagem inicial foi fixada e registra as cinco entregas principais e
  a validação final da produção.
- A publicação usa snapshot prévio, sem menções, e é idempotente. A repetição real reutilizou o
  canal e editou a mesma mensagem, preservando pin e permissões sem gerar flood.
- QA focado: dez testes de canal/conteúdo, Ruff e validação ao vivo de nome, categoria, pin e
  permissões. O script permanece disponível para atualizar o resumo nas próximas versões.

# Unidades Especiais e Comandos — concluído em 2026-08-26

- A implementação integra quatro unidades ao cadastro canônico e introduz somente o agregado próprio
  de candidatura/vínculo, com unicidade ativa, CAS, eventos imutáveis e recursos Discord por guild.
- Painéis persistentes recuperam candidaturas e administração no REC e uma central privada por unidade
  no principal. Cargos de Integrante, Auxiliar e Comando são hierárquicos e não têm permissões globais.
- Aprovar é idempotente, bloqueia autoavaliação, sincroniza ambos os servidores e não rebaixa patente.
  Quem está abaixo do piso é promovido a Cabo usando `personnel_actions`, `career_notifications` e
  `RANK_SYNC`; quem já está acima permanece inalterado.
- Validação: 7 testes focados, 546 na suíte completa, Ruff, compileall, diff e check de inicialização.
  Rollout com backup íntegro, migration 46, health 200, um Gateway e reinício sem duplicar 8 recursos
  nem 6 mensagens persistentes.

# Ecossistema CHOQUE — bloco ADV pronto localmente em 2026-08-26

- O módulo disciplinar existente foi ampliado, sem criar um ledger paralelo, com quatro gravidades e
  duração configurável para ADVs.
- A migration 49 preserva os registros legados, adiciona versão otimista e uma projeção durável das
  páginas do painel global.
- Expiração automática usa compare-and-set e grava uma única auditoria; concluir ou revogar continua
  preservando todo o histórico.
- O painel global mostra somente ADVs ativas em páginas de cinco itens, sem expor links de evidência,
  edita as mesmas mensagens e remove páginas excedentes da projeção sem apagar o histórico Discord.
- Gates locais: 53 testes focados, **559 testes Python** na suíte completa, Ruff, compileall,
  `main.py --check` e `git diff --check`. Produção ainda não foi alterada por este bloco.

# Ecossistema CHOQUE — transferências auditáveis prontas localmente em 2026-08-26

- O fluxo existente de ticket, sala privada e cadastro foi preservado. A migration 51 adiciona um
  agregado mínimo para protocolo estável, snapshot do pedido, decisão, patente autorizada e timeline.
- O teto de patente é configurável por guild e aparece na configuração administrativa. A seleção usa
  o ID canônico da patente e a decisão persiste o nível máximo vigente, impedindo elevação por nome,
  cargo visual ou alteração posterior da configuração.
- Aprovar a transferência apenas cria uma ficha pendente. O membro só é criado/reativado depois da
  segunda análise humana; a patente aplicada é a autorizada no protocolo e a sincronização Discord
  segue pela outbox já existente.
- Tickets históricos são migrados sem concessão retroativa. Casos pendentes podem seguir o ciclo
  novo; aprovações antigas ficam identificadas separadamente para revisão, sem patente inferida.
- Cancelamento e reabertura mantêm ticket/protocolo consistentes na mesma transação. Patente
  desativada entre as decisões bloqueia a aplicação sem fallback, e o protocolo fica visível no
  histórico privado do solicitante.
- TDD: `8c20229` registra quatro falhas esperadas antes da implementação; `422e213` entrega o GREEN.
  A revisão de alcançabilidade gerou outro RED em `d18e739`, corrigido por `06ae652`, para publicar a
  ficha de transferência no painel de revisão existente. Evidência detalhada:
  `docs/testing/phase-b-transfers-tdd.md`.
- Gates locais: 68 testes focados, **569 testes Python**, scanner de segredos, `pip-audit`, Ruff,
  compileall, `main.py --check`, diff, `npm audit`, typecheck, lint, **57 testes web** e build.
  Nenhuma ação de produção foi executada.

# Site CHOQUE — drawer móvel acessível pronto localmente em 2026-08-26

- O primeiro corte do Centro de Comando na Fase 57 preserva navegação, URLs, dados e RBAC e corrige
  somente o comportamento acessível do menu móvel.
- O acionador expõe `aria-controls`/`aria-expanded`; o drawer só entra na árvore quando aberto, usa
  semântica modal, recebe e contém o foco, fecha com `Escape` e devolve o foco ao acionador.
- TDD: `2ca8770` registra o contrato RED e `20d4153` entrega o GREEN.
- Gates locais: 3 testes focados, **58 testes web**, typecheck, ESLint e build Next.js. Nenhuma ação
  de produção foi executada.

# Site CHOQUE — timestamp factual do dashboard pronto localmente em 2026-08-26

- O cabeçalho do Centro de Comando deixou de usar o relógio do render para rotular a situação. A
  apresentação agora usa `generated_at`, já fornecido pela API, mantendo origem temporal coerente
  com patrulhas, fila e demais métricas do mesmo snapshot.
- O instante é exposto por `<time dateTime="...">`, com texto em `pt-BR`/`America/Sao_Paulo`, sem
  polling adicional, dado simulado ou mudança de contrato.
- TDD: `5e36506` registra o contrato RED e `098fea0` entrega o GREEN.
- Gate consolidado do portal: 4 testes focados, **59 testes web**, `npm audit` sem vulnerabilidades,
  typecheck, ESLint e build Next.js. Nenhuma ação de produção foi executada.

# Site CHOQUE — métricas semânticas prontas localmente em 2026-08-26

- `MetricStrip`, usado pelas superfícies administrativas, agora expõe a coleção como `<dl>` e cada
  rótulo/valor como `<dt>/<dd>`. Leitores de tela recebem a relação sem depender da posição visual.
- Classes, tons, conteúdo, ordem horizontal e comportamento responsivo foram preservados; somente
  margens nativas de `dl/dt/dd` foram neutralizadas no CSS existente.
- TDD: `093a1cf` registra o contrato RED e `d0eecb6` entrega o GREEN.
- Gate consolidado do portal: 8 testes focados, **60 testes web**, `npm audit` sem vulnerabilidades,
  typecheck, ESLint e build Next.js. Nenhuma ação de produção foi executada.

# Site CHOQUE — fila FIFO semântica pronta localmente em 2026-08-26

- A fila operacional do dashboard agora usa `<ol>` com nome acessível e um `<li>` por militar. A
  semântica comunica que posição é relevante, consistente com a regra FIFO já exibida.
- Número, nome, duração, limite de oito entradas, ordem do backend e visual existente foram
  preservados; o CSS apenas neutraliza estilos nativos da lista.
- TDD: `03b2bd6` registra o contrato RED e `ff86f4e` entrega o GREEN.
- Gate consolidado do portal: 9 testes focados, **61 testes web**, typecheck, ESLint e build Next.js.
  Nenhuma ação de produção foi executada.

# Site CHOQUE — pendências administrativas semânticas prontas localmente em 2026-08-26

- As pendências administrativas recentes do dashboard agora usam `<ul>` com nome acessível e um
  `<li>` por item. A coleção fica explícita para tecnologias assistivas quando `view_inbox` está ativo.
- Links para `/inbox`, protocolos, status, datas, ordem, dados e visual existentes foram preservados;
  o CSS apenas neutraliza estilos nativos da lista e mantém os seletores visuais equivalentes.
- TDD: `b52379c` registra o contrato RED e `d0681c6` entrega o GREEN.
- Gate consolidado do portal: 10 testes focados, **62 testes web**, `npm audit` sem vulnerabilidades,
  typecheck, ESLint e build Next.js. Nenhuma ação de produção foi executada.

# Site CHOQUE — briefing de mudanças semântico pronto localmente em 2026-08-26

- O briefing dos últimos sete dias agora usa `<ul>` com nome acessível e um `<li>` por contagem,
  tornando explícita a coleção quando `view_changes` está ativo.
- Chaves, valores, limite de seis entradas, ordem, ícones e estado sem alterações foram preservados;
  o CSS neutraliza somente os estilos nativos da lista.
- TDD: `6de2297` registra o contrato RED e `b3db98c` entrega o GREEN.
- Gate consolidado do portal: 11 testes focados, **63 testes web**, `npm audit` sem vulnerabilidades,
  typecheck, ESLint e build Next.js. Nenhuma ação de produção foi executada.

# Site CHOQUE — patrulhas ativas semânticas prontas localmente em 2026-08-26

- A coleção de patrulhas ativas do dashboard agora usa `<ul>` com nome acessível e um `<li>` por
  operação; cada ficha permanece um `<article>` independente dentro do item.
- Identificador, status, call, efetivo, comandante, duração, ordem e dados foram preservados; o CSS
  apenas neutraliza estilos nativos da lista.
- TDD: `c38d050` registra o contrato RED e `2fab9ce` entrega o GREEN.
- Gate consolidado do portal: 12 testes focados, **64 testes web**, `npm audit` sem vulnerabilidades,
  typecheck, ESLint e build Next.js. Nenhuma ação de produção foi executada.

# Site CHOQUE — seletor administrativo semântico pronto localmente em 2026-08-26

- A caixa administrativa deixou de declarar `listbox/option` sem implementar o modelo de teclado
  exigido por esse widget composto. Os processos agora formam `<ul>/<li>` com botões nativos.
- O processo ativo mantém classe visual e passa a expor `aria-current`; clique, painel, formulários,
  decisões, ordem e dados foram preservados.
- TDD: `d6fd37c` registra o contrato RED e `93bc047` entrega o GREEN.
- Gate consolidado do portal: 13 testes focados, **65 testes web em 17 arquivos**, `npm audit` sem
  vulnerabilidades, typecheck, ESLint e build Next.js. Nenhuma ação de produção foi executada.

# Site CHOQUE — painel de decisão associado pronto localmente em 2026-08-26

- Cada botão da caixa administrativa agora expõe `aria-controls` para o painel de decisão; o painel
  recebe nome acessível pelo título ativo com `aria-labelledby`.
- `useId()` mantém os identificadores únicos por instância. Troca de seleção, título, formulário,
  decisões, dados e aparência foram preservados.
- TDD: `2d1f744` registra o contrato RED e `e351128` entrega o GREEN.
- Gate consolidado do portal: 13 testes focados, **65 testes web em 17 arquivos**, `npm audit` sem
  vulnerabilidades, typecheck, ESLint e build Next.js. Nenhuma ação de produção foi executada.

# Site CHOQUE — horários administrativos legíveis por máquina prontos localmente em 2026-08-26

- Cada horário válido da lista administrativa mantém o texto humano e passa a expor ISO no atributo
  `dateTime`; valores ausentes, não finitos, não positivos ou inválidos não recebem o atributo.
- O helper defensivo evita `Invalid Date` e não altera seleção, ordem, dados ou decisões.
- TDD: `94b53ca` registra o contrato RED e `39e5a7c` entrega o GREEN.
- Gate consolidado do portal: 14 testes focados, **66 testes web em 17 arquivos**, `npm audit` sem
  vulnerabilidades, typecheck, ESLint e build Next.js. Nenhuma ação de produção foi executada.
