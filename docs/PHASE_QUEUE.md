# Fila de Fases — CHOQUE BGR

Atualizada em 2026-08-23.

Esta é a ordem oficial de continuidade. Uma fase só sai da fila depois de implementação, testes,
validação proporcional ao risco e atualização do `PROJECT_HANDOFF.md`.

## Hotfixes publicados nesta continuidade

- ✅ **Dashboard de Qualificações — concluído e validado ao vivo em 2026-08-23**: o digest Vercel
   `1027291490` revelou que a matriz GET ainda devolvia snowflake como número JSON e o navegador o
   arredondava antes do POST. A API agora emite snowflakes como texto decimal e a página tipa o ID
   como string; 404 de membro/curso entre renderização e clique retorna à matriz com orientação, sem
   derrubar React. A prova humana concedeu Abordagem Avançada a Paiva e o cargo foi sincronizado em
   uma tentativa, sem erro.
- ✅ **Ficha temporária de cadastro — concluída em 2026-08-23**: a Portaria reinicia seu ciclo de
   entrega ao reutilizar um registro e a limpeza só aceita estados terminais com decisão. A
   recuperação pós-restart reparou a ficha pendente observada sem apagar histórico nem o painel
   fixo da Central Administrativa.
- ✅ **Ruído de Auditoria do Bot — concluído em 2026-08-23**: política de entrega por ação impede
   sucessos técnicos rotineiros de inundarem o canal, preservando-os no banco. Falhas, segurança,
   decisões e mudanças administrativas relevantes continuam visíveis. Gateway único e 324 pytest
   foram validados antes do rollout.

O inventário completo dos pedidos, incluindo as fontes originais, está em
`docs/REQUEST_LEDGER.md`. Nenhum item abaixo deve ser interpretado como implementado apenas por
estar documentado.

## Lote 0 — correções urgentes de produção

0. 🟡 **Dashboard de Recrutamento — hotfix web publicado em 2026-08-23**: a lista sem filtros deixou
   de assinar um `?` ausente na API e as Server Actions agora conduzem a expiração do step-up para
   reautenticação OAuth explícita, preservando RBAC e janela de 30 minutos. O deploy Vercel
   `dpl_9nW66UQb428mSuwR6YbWJvkT6DBe` está `READY`; falta validação humana autenticada de assumir,
   aprovar e reprovar. A continuação de Auditoria/Histórico e migrations permanece bloqueada pela
   suíte Python completa, nunca pelo hotfix web.
1. ✅ **Permissões de visitantes/novos membros — concluída em 2026-08-22**: política centralizada
   e aplicada pelos 19 IDs de categoria e 97 IDs de canal. Uma conta real sem cargos enxerga
   somente Recepção, Ticket, Recrutamento e Transferências e Parcerias; filas/resultados internos
   dessas categorias continuam privados. Snapshots e rollback verificável foram preservados.
2. ✅ **Canal privado por ticket — concluído em 2026-08-22**: cada atendimento recebe uma sala
   persistida, visível somente ao solicitante, perfis COMANDO/ADMINISTRADOR e bot. A confirmação
   menciona a sala; existe botão persistente de encerramento, decisão arquiva o canal, e o startup
   recupera tickets sem sala. A privacidade da sala real foi validada pela API.
3. ✅ **Contagem real da hierarquia — concluída em 2026-08-22**: o painel conta os membros
   efetivamente presentes em cada cargo Discord (sem bots), com fallback local apenas no
   `--check`; a reconciliação RankSync corrige `members.rank_id` e a mensagem persistida foi
   validada ao vivo para as 21 patentes.
4. ✅ **Caixa de cadastros analisados — concluída em 2026-08-22**: a mensagem pendente é persistida,
   o resultado idempotente é publicado no histórico privado por registry e só então a origem é
   removida. Decisão concorrente, recuperação no startup e legado sem repostagem foram cobertos.

## Lote 1 — apresentação e navegação do Discord

5. ✅ **Painel de cadastro — concluído em 2026-08-22**: mensagem persistente reutilizada com ordem de
   ingresso, dados, validações, privacidade e identidade militar; o custom ID foi preservado.
6. ✅ **Painel de bate-ponto — concluído em 2026-08-22**: mensagem persistente reutilizada com fluxo
   operacional, calls, tolerância, estados e integridade, sem alterar a máquina transacional.
7. ✅ **Medalhas — concluído em 2026-08-22**: novo quadro persistente para as sete condecorações,
   critérios consultáveis por select e texto conferido na única mensagem histórica, que foi mantida.
8. ✅ **Transferências e Parcerias — concluído em 2026-08-22**: três painéis funcionais publicados
   nos mesmos canais `1166861438728548432`, `1540590814839967784` e `1540590816383336520`, com
   transferência, proposta institucional, acompanhamento e links, sem trocar IDs/histórico.

## Correção ativa anterior às novas fases

9. ✅ **Renderização dos nomes dos canais — concluída em 2026-08-22**: o separador incompatível
   `U+17B5` foi substituído centralmente pelo ponto médio `U+00B7`, com `U+30FB` como fallback.
   A migração por registry/ID preservou canais, categorias, mensagens, posições, overwrites e
   menções; 68 canais fixos e uma sala dinâmica foram migrados, 10 labels de calls foram
   reconciliados e a leitura fresca terminou com zero divergências ou revisões.

## Fases funcionais do bot

10. ✅ **Fase 13 — RankSyncService — concluída em 2026-08-22**: serviço central, migration v10,
    listener com debounce, reconciliação de startup, histórico/auditoria, apelido oficial e
    políticas configuráveis implementados. Os 12 cenários passaram e a reconciliação real corrigiu
    3/3 cadastros. Resta somente a configuração externa de colocar o cargo do bot acima de
    Comandante Geral para o Discord permitir editar o apelido desse usuário.
11. ✅ **Catálogo de cursos e inscrições — concluído em 2026-08-22**: as nove mensagens históricas
    do canal `1162114694581059584` foram preservadas e importadas com 9 cursos, 10 requisitos,
    notas 80/90, cooldown e estado do edital. O painel persistente possui um botão por curso;
    elegibilidade, duplicidade e decisão concorrente são validadas no servidor e auditadas.
12. ✅ **Fase 14 — Tempo mínimo em patrulha — concluída em 2026-08-22**: migration v14 separa
    autorização de serviço e contagem de patrulha, preserva a classificação em cada segmento e
    invalida sessões abaixo do mínimo configurável de 5–120 minutos sem apagá-las. Totais,
    ranking, meta e relatórios consideram somente sessões válidas; saída antecipada exige
    confirmação e o override excepcional exige motivo, confirmação e auditoria. Os oito cenários
    temporais obrigatórios, concorrência, histórico e exclusões passaram localmente e o painel
    persistente/configuração foram validados ao vivo.
13. ✅ **Fase 15 — Operações Inteligentes — concluída em 2026-08-22**: migration v15, serviço
    transacional e cog visual entregam disponibilidade, fila FIFO, formação automática com rollback,
    ciclo/histórico/debrief de patrulhas, prontidão, flags não punitivas, integridade e identidade,
    matriz/requisitos/avaliações, recrutas, elegibilidade consultiva, dossiê, inbox, trocas com
    consentimento, decisões, resumo de mudanças e manutenção por módulo. Os painéis persistidos nos
    canais `1164363506083172413` e `1540590792522072155` foram editados no lugar; 141 testes e o
    validador real confirmaram 13/13 tabelas, 1 call de espera, 11 calls ativas, 3/3 painéis e zero
    comandos publicados.

## Programa Centro de Comando Web

14. ✅ **Programa Centro de Comando Web — concluído localmente em 2026-08-22**: as seis subfases
   (Fundação, Operação, Efetivo, Administração, Inteligência e Sistema) foram implementadas em
   Next.js + FastAPI sobre o core real. Migration v16, OAuth Discord, RBAC server-side, outbox
   Discord, configurações por registry, Vercel/Railway, refresh convergente e revisão visual
   1440/1280/1024/768/390 foram entregues. Publicação, projeto Supabase exclusivo e credenciais de
   produção não foram provisionados automaticamente.

Regras obrigatórias para o programa web:

- usar integralmente a skill de frontend design antes de implementar interfaces;
- utilizar Lovable para planejamento, prototipação e refinamento visual;
- iniciar o Lovable em modo de planejamento e revisar seus diffs antes de integrar código;
- não publicar, provisionar Supabase ou conectar produção automaticamente;
- definir ADRs para API, OAuth, PostgreSQL/Supabase, realtime e deploy antes da implementação;
- avaliar a topologia solicitada: Vercel para frontend, Supabase para PostgreSQL/auth/realtime e
  Railway para API/worker Python; escolher uma única fonte de verdade e proibir dual-write;
- Vercel CLI 59.4.0 instalado somente quando a fase de publicação começou;
- não apresentar como existente qualquer camada web ainda ausente do repositório;
- manter autorização e regras de negócio no backend/core compartilhado;
- realizar revisão visual por screenshots e testes Desktop/Mobile em cada subfase.

## Sistema de Alistamento, Recrutamento e Integridade

15. ✅ **Sistema de Alistamento, Recrutamento e Integridade — concluído em produção em 2026-08-23.**
   Executado a partir de `docs/RECRUITMENT_INTEGRITY_SYSTEM_SPEC.md`. O programa possui
   oito subfases: Domínio, Candidato, Avaliação, Integração, Admin, Processo Seletivo, Ingresso e
   Hardening específico. O portal público está em
   `https://web-plum-tau-82.vercel.app/recrutamento`, sem exigir OAuth, e a campanha inicial está
   `OPEN`. Um cenário sintético respondeu as 24 questões, submeteu `AL-00001`, entregou o dossiê
   pelo outbox no canal administrativo e foi retirado em seguida, permanecendo somente como trilha
   auditável. A falha descoberta no footer da notificação foi corrigida, coberta por regressão e
   publicada na mesma aplicação Discloud.

Regras obrigatórias:

- integrar e migrar o recrutamento básico atual; não criar módulo paralelo;
- utilizar Lovable e a skill de frontend design nas superfícies públicas e administrativas;
- usar apenas fixtures sintéticas no Lovable, sem candidatos, respostas ou questões reais;
- manter timer, elegibilidade, idempotência, autorização e integridade como decisões server-side;
- sinais anti-copy/paste/foco nunca podem reprovar automaticamente um candidato;
- aprovação final continua humana e reutiliza membro, patente, RankSync e outbox existentes.

## Robô Analista de Candidaturas

16. ✅ **Robô Analista de Candidaturas — concluído e ativo em produção em 2026-08-24.**
   A autoridade é determinística e local: rubricas/versionamento, pesos, critérios objetivos,
   cruzamentos configurados e sinais de integridade persistidos. Não depende de provedor externo,
   chave de IA ou envio de respostas a terceiros. O produto foi encerrado com o motor transparente
   `local-deterministic`; ele entrega resumo, organização de evidências e perguntas explicáveis sem
   calcular decisão final. O possível Qwen3-0.6B GGUF Q4_0 via `llama.cpp` ficou como experimento
   futuro opcional, fora da fila ativa, pois não é necessário para o sistema funcionar.

Regras obrigatórias:

- IA somente leitura, sem tools de banco, Discord, membros ou decisões;
- separar regras determinísticas do backend da análise qualitativa;
- proteger contra prompt injection e validar structured output server-side;
- preservar recomendação da IA e decisão humana como registros distintos;
- não utilizar atributos protegidos, perfil psicológico, detector de IA ou ranking de candidatos;
- utilizar Lovable somente para as interfaces/revisões com fixtures sintéticas e diffs inspecionados;
- manter provider de análise desacoplado do Lovable e de fornecedor específico.

## Security Hardening Completo

17. ✅ **Concluído localmente em 2026-08-22; gate público FAIL.** Executado a partir de
   `docs/SECURITY_HARDENING_SPEC.md`. Essa etapa é o hardening e
   gate final de produção da arquitetura completa, com 220 controles, threat model, revisão ASVS,
   testes de autorização, infraestrutura, backups, monitoramento e resposta a incidentes.

Regras obrigatórias:

- segurança básica é transversal e não pode ser adiada até esta etapa;
- classificar cada controle como IMPLEMENTADO, NÃO APLICÁVEL ou PENDENTE, sempre com evidência;
- utilizar Lovable somente nas superfícies web de segurança e revisar todo diff gerado;
- nunca fornecer secrets, cookies, dados pessoais, dumps ou configuração de produção ao Lovable;
- não executar pentest, DAST agressivo, deploy ou mudança de infraestrutura sem autorização e escopo;
- produzir `SECURITY.md`, threat model, runbooks e relatório final PASS/WARNING/FAIL;
- não declarar o sistema inviolável; registrar riscos residuais e pendências com honestidade.

## Itens complementares recebidos durante o Security Hardening

18. ⚠️ **Bloqueado pelo Discord em 2026-08-22, sem migração destrutiva.** Substituir o padrão atualmente validado com
   ponto médio pelo codepoint gerado `U+3164 HANGUL FILLER`. O emoji continua separado por `U+30FB`
   visível. Regenerar os nomes a partir do `display_name` canônico, nunca por substituição cega;
   validar codepoints localmente e reler todos os canais pela API depois da migração. Usar
   `U+2800` somente se o Discord comprovadamente remover `U+3164`.
19. ✅ **Fase 16 — Comandante automático da patrulha concluída em 2026-08-22.** Executado a partir de
   `docs/PATROL_COMMANDER_SPEC.md`: seleção determinística/configurável entre integrantes elegíveis,
   histórico, reatribuição somente quando necessária, override manual com RBAC e integração com
   painel, relatórios, feedback, startup e eventos existentes. Não usa IA nem altera patente.
20. ✅ **Fase 17 — Portaria Digital / cadastro obrigatório — concluída em 2026-08-22.** Executada a partir de
   `docs/REGISTRATION_GATE_SPEC.md`: estado persistido de cadastro, acesso mínimo antes do vínculo,
   painel sem comandos, prevenção de duplicidade, revisão administrativa, reentrada, startup,
   integrações com recrutamento/RankSync/onboarding, preview/rollback de permissões e página web.
   O caso observado de membro com patente mas sem identidade vinculada entrou na reconciliação e
   permaneceu restrito até cadastro/revisão humana, sem remover cargos protegidos nem bloquear owner,
   bots, administradores ou bypass autorizado. O painel existente foi movido por ID para a Recepção,
   121 contas foram sincronizadas e uma amostra real de dez visitantes terminou sem vazamentos.
21. ✅ **Fase 18 — Operação avançada de tickets — concluída em 2026-08-22.** Executada a partir de
   `docs/TICKET_OPERATIONS_EXPANSION_SPEC.md`: salas em categoria exclusiva, cargo responsável
   configurável e mencionado, privacidade efetiva e controles persistentes de assumir, participantes,
   prioridade, transcrição, notificação, encerramento e reabertura, sempre com auditoria. Duas
   categorias exclusivas foram criadas com snapshot reversível; a única sala histórica foi preservada
   e validada com 8/8 controles. Uma matriz temporária, removida ao final, comprovou as permissões
   efetivas de solicitante, visitante, membro-base, cargo responsável, Comando e bot.
22. ⚠️ **Publicação operacional concluída por exceção expressa em 2026-08-22; gate de segurança segue FAIL.** O repositório
   privado `EoPaiva/choque-bgr-gestao` recebeu um commit-raiz limpo, sem histórico legado, bancos,
   `.env`, logs ou secrets. Alertas de vulnerabilidade e correções automáticas foram ativados; o
   plano atual não oferece secret scanning privado. A página pública `/status` foi implementada,
   publicada em `https://web-plum-tau-82.vercel.app/status` e validada com HTTP 200, conteúdo
   esperado, zero erros de console/overlay e layout desktop/mobile. Depois de autorização pontual
   do proprietário para ignorar o gate, o banco v22 foi copiado para o volume Railway com SHA-256
   idêntico, integrity ok e FK=0. O serviço `beautiful-laughter` executa o runtime combinado em uma
   única réplica, deployment `5bae72f3-6540-4da4-a78a-470e9dcbdd6f`, com `/health` 200, Gateway
   conectado e bot local desligado. A região temporária é `asia-southeast1-eqsg3a`, porque as
   regiões mais próximas recusaram deploy gratuito no horário de pico. O frontend Vercel foi
   republicado no deployment `dpl_HdH2HSDYQrQUz3avDeppnDg35ZRr`; status, login, provider Discord,
   callback e redirecionamento protegido passaram e não houve 5xx.

   A exceção não aprova o gate: credenciais divulgadas continuam comprometidas, o cargo do bot ainda
   precisa de prova de menor privilégio, o audit Discord reportou seis achados e login/logout humano
   com contas MEMBRO/COMANDO continua pendente. O item permanece marcado com alerta por essas ações
   externas, embora a publicação operacional esteja ativa.

   O único alerta Dependabot encontrado (`pytest < 9.0.3`) foi corrigido com `pytest==9.0.3` e
   `pytest-asyncio==1.4.0`; o GitHub marcou o alerta como `fixed`. O Security gate da `main` ficou
   verde. Como o plano privado atual não aceita upload ao painel Code Scanning, o CodeQL continua
   executando a análise completa e preserva os relatórios SARIF como artefatos do workflow.
   A execução final passou e a inspeção dos artefatos encontrou zero resultados em Python e zero em
   JavaScript/TypeScript. A proteção da branch `main` foi tentada, mas a API recusou com HTTP 403:
   repositórios privados exigem upgrade para GitHub Pro; o repositório não foi tornado público.

   O snapshot integral do corte foi publicado no commit privado `5f1b8340410807c575780f17c1d25b9b60441eb5`.
   O Security gate `32587617947` passou todas as etapas e o CodeQL `32587617965` passou preservando
   SARIF. A observação posterior confirmou uma única instância Railway, volume `READY`, health ok,
   um único marcador de conexão Discord, zero marcadores fatais, bot local offline, Vercel 200 e
   redirecionamento 307 da rota protegida para login.

O formatador e os testes do item 18 usam `U+3164`, mas a API removeu primário, fallback e sequências
invisíveis em prova real. O item 18 permanece bloqueado até o Discord aceitar o codepoint ou o
usuário autorizar um separador visual diferente. No **item 22**, GitHub, Vercel e Railway estão
operacionais por exceção expressa, sem que o veredito `FAIL` tenha sido alterado. Rotação de
credenciais, menor privilégio e validações humanas continuam dívida obrigatória.

## Sincronização Discord, identidade funcional e RBAC

23. ✅ **Fase 19 — Sincronização Discord, identidade funcional e RBAC — concluída em produção em
    2026-08-23.** Executada a
    partir de `docs/DISCORD_IDENTITY_RBAC_SYNC_SPEC.md` e da fonte integral
    `docs/source-prompts/15-discord-role-access-sync-original.md`. Evoluir a reconciliação existente
    para a pipeline única `DISCORD -> IDENTIDADE -> RBAC -> BOT + SITE`, separando patente, cargo
    principal e funções secundárias, com mapping por role ID, versão de autorização, downgrade
    imediato, startup/periódico/sob demanda, histórico, observabilidade e superfícies web.

    Estado implementado: migration v23, pipeline, correlação, observabilidade, Portaria e
    restauração do apelido anterior ao cadastro estão implementados; **272 testes Python**, Ruff,
    compileall, secret scan, **29 Vitest**, ESLint, typecheck, build e migração sobre cópia v22
    passaram. A Portaria publica pedidos no canal administrativo, oferece botão persistente para a
    fila e arquiva a mensagem após decisão. Desligamentos capturam/restauram o apelido original.
    O rollout posterior na Discloud Diamond eliminou o bloqueio da Railway: banco v24 íntegro,
    reconciliação real sem falhas, Portaria validada por usuário e instância local desligada. O bot,
    a API e o site operam sobre uma única fonte SQLite na aplicação `choque-bgr-api`.

    Continuidade verificada às 17:09 BRT: nova tentativa de `railway up` foi novamente recusada
    pela indisponibilidade de deploy gratuito em `us-west2` durante o horário de pico. O checkpoint
    privado desta implementação foi publicado no `main` do repositório privado no commit
    `436aa57ba67b5bff6e81d455034b90904edc6d8b`, sem alterar o índice ou a árvore local. A página
    pública de acompanhamento permanece disponível e informa corretamente a manutenção do runtime.

Regras obrigatórias:

- reutilizar `RankSyncService`, `format_member_nickname()` e `PermissionService`; não criar fluxo
  paralelo de patente ou autorização;
- Discord é a fonte operacional de verdade para roles funcionais, mas cargos cosméticos e nomes
  visuais não participam da autorização sem mapping explícito por ID;
- preservar todas as funções secundárias e resolver a principal por prioridade configurada;
- calcular permissões efetivas por perfil, patente, funções, grants e denies, com deny by default e
  validação final sempre no backend;
- concessão e remoção manual de role devem atualizar banco, bot e site; downgrade invalida sessão e
  faz endpoint antigo responder `403` sem aguardar novo login;
- integrar Portaria Digital e recrutamento, sem liberar identidade não aprovada nem alterar horas,
  disciplina, candidaturas, avaliações ou cursos;
- entregar mapping/sincronização no Centro de Comando, preview e reparo por painéis, sem depender de
  comandos Discord;
- executar os nove testes obrigatórios, cobertura adicional, QA completo e validação real
  proporcional ao risco antes de marcar a fase como concluída.

## Cadastro, conformidade e acabamento visual

24. ✅ **Central Administrativa categorizada e exoneração segura — concluída e validada ao vivo em
    2026-08-22.** A mensagem persistida foi preservada e a entrada foi reduzida a cinco ações:
    `Efetivo`, `Disciplina`, `Processos`, `Serviço e operações` e `Atualizar resumo`. As doze funções
    anteriores continuam acessíveis em submenus explicados. `Exonerar membro` está visível em
    Disciplina, lista somente efetivo cadastrado/elegível, exige motivo e confirmação literal, não
    expulsa nem bane, remove cargos operacionais, fecha o ponto, aplica `Exonerado` por ID e restaura
    o apelido. Para históricos legados incorretos, o fallback remove somente `[PAT]` e `[ID]`,
    preserva o nome central, refaz a leitura pela API e tenta uma segunda vez se necessário. O caso
    real foi reparado para `Paiva Teste`, sem patentes restantes. Evidências: backup íntegro, painel
    único com cinco componentes, cargo sem permissões, **280 testes**, Ruff, compile, `--check` e
    validação REST. A filtragem dos demais seletores disciplinares permanece no item 28.

25. ✅ **Unicode Small Caps aprovado e migrado globalmente — concluído em 2026-08-22.** O piloto
    `📢・ᴀᴠɪꜱᴏꜱ-ᴅᴏ-ᴄᴏᴍᴀɴᴅᴏ` foi aplicado por ID e aprovado pelo proprietário. Depois do backup e
    snapshot integral, todos os 97 canais do registry e a sala dinâmica foram migrados para Small
    Caps com hífen visível entre palavras; categorias mantiveram o padrão próprio. As 12 labels de
    calls foram reconciliadas. Releitura REST, inventário e comparação com snapshot confirmaram os
    98 canais sem mudança de ID, categoria, posição ou overwrites, sem fallback/revisão. O
    formatador central passou a ser a autoridade para novas salas. QA: **281 testes**, Ruff,
    compile, `main.py --check`, validador ao vivo e bot online em instância única.

26. ✅ **Gerenciador de cadastros do Alto Comando — concluído em 2026-08-22.** Ampliada a Central Administrativa
    com lista paginada, busca, consulta, edição, desativação lógica e reabertura para análise de
    todos os cadastros. Cada ação deve exigir permissão exclusiva do Alto Comando, motivo,
    confirmação, auditoria e possibilidade de recuperação; nenhum registro ou histórico poderá ser
    apagado fisicamente. O fluxo deve reutilizar a Portaria, `MemberService`, `RankSyncService` e a
    outbox existentes, sem criar uma segunda autoridade de identidade.

27. ✅ **Conformidade de patente ou Companheiro sem cadastro em 72 horas — concluída em 2026-08-22.** Detectar por role ID quando
    uma patente gerenciada for concedida a uma conta sem cadastro aprovado. Enviar DM com prazo de
    três dias e link direto para o painel oficial de cadastro, registrar a pendência e os lembretes
    no banco e avisar o Alto Comando se a DM falhar. A aprovação cancela a cobrança; se o prazo
    expirar sem cadastro, remover somente a patente que originou a pendência, preservar os demais
    cargos e registrar auditoria. O processamento deve ser idempotente, sobreviver a restart e
    revalidar o estado antes de qualquer remoção.

28. ✅ **Filtrar os demais seletores disciplinares e auditar ações ocultas — concluído em 2026-08-22.** A exoneração e os demais seletores
    25–27.** A exoneração já usa fonte paginada derivada do banco; ocorrência, advertência,
    suspensão, histórico e gestão de medidas ainda devem abandonar seletores gerais de usuários e
    listar somente membros cadastrados/elegíveis, sempre com revalidação server-side. Depois,
    inventariar views persistentes e temporárias, botões, selects, modais, callbacks e ações de
    domínio. Para cada ação, provar caminho visível/autorizado e restauração após restart; detectar
    componentes órfãos, rotas sem entrada, custom IDs duplicados e permissões que tornem ações
    inacessíveis. Registrar a matriz `ação -> painel -> categoria -> permissão -> callback` no
    relatório vivo. Evidência: 292 testes, `docs/INTERACTION_ROUTE_AUDIT.md`, zero `custom_id`
    duplicado, zero callback ausente e zero classe ativa sem caminho.

## Empacotamento e publicação na Discloud

29. ✅ **Pacote final e publicação Discloud Diamond — concluídos operacionalmente em 2026-08-23
    sob a exceção de segurança já registrada.** A aplicação combinada `choque-bgr-api` está online
    como `TYPE=site`, com 1 GB,
    bot Discord, API/healthcheck e banco SQLite v24 no mesmo runtime. O frontend Vercel e o fluxo
    público de recrutamento responderam 200, e a instância local está desligada. O ZIP pós-hotfix
    `CHOQUE-BGR-Discloud-FINAL-20260823-041504.zip` foi gerado diretamente do commit, possui 107
    entradas, 450.193 bytes, zero caminho proibido e SHA-256
    `a453152690b8c183710ea4266c50da12857bf8f795507e40f465a9e75657d3cf`. `.env`, banco e segredos
    não estão no artefato. A Discloud mantém o `.env` privado fora do Git, conforme seu método
    oficial. A rotação das credenciais divulgadas continua dívida obrigatória e mantém o gate de
    segurança em `FAIL`, mas não há pendência funcional ou de hospedagem neste item.

Regras obrigatórias para o pacote Discloud:

- usar `TYPE=site`, porque o mesmo runtime publicará o bot Discord e a API do Centro de Comando;
- configurar o runtime para ouvir em `0.0.0.0:8080`, com subdomínio reservado, `MAIN`/`START`, versão
  Python suportada, `AUTORESTART=true` e RAM Diamond dimensionada por medição real, nunca abaixo de
  512 MB;
- incluir somente fontes e artefatos necessários ao runtime: core, cogs ativos, API, migrations,
  launcher de produção, `requirements.txt`, assets obrigatórios e `discloud.config` validado;
- excluir `.git`, `.env*` reais, tokens, secrets, bancos operacionais, backups, logs, caches,
  `__pycache__`, ambientes virtuais, arquivos temporários, testes, relatórios locais, `node_modules`
  e o frontend Vercel;
- nunca colocar credenciais reais no ZIP ou no `discloud.config`; cadastrar os valores apenas pelo
  mecanismo protegido da hospedagem e validar somente os nomes esperados;
- preservar o SQLite por fluxo separado e autenticado: parar a instância anterior, gerar backup
  consistente, registrar SHA-256, restaurar pelo gerenciador seguro de arquivos da Discloud e
  conferir novamente integridade, foreign keys, migrations e hash antes de liberar o bot;
- gerar inventário e SHA-256 do próprio ZIP, executar varredura de secrets e abrir o arquivo para
  confirmar caminhos, encoding e ausência de arquivos proibidos;
- antes do upload, passar Ruff, suíte pytest, compile/import smoke, `python main.py --check` e teste
  local do runtime combinado na porta 8080;
- depois do upload, validar healthcheck HTTP, conexão do bot, views persistentes, banco gravável,
  recuperação de startup, outbox, API usada pela Vercel e garantia de instância única;
- manter pacote e backup anteriores para rollback, registrar a versão implantada e atualizar
  `PROJECT_HANDOFF.md`, `docs/PHASE_QUEUE.md`, `docs/REQUEST_LEDGER.md` e
  `docs/IMPLEMENTATION_REPORT.md` com evidências reais.

O item 29 foi concluído após o ZIP passar pelas validações, a restauração segura do banco ser
comprovada e a aplicação permanecer operacional na Discloud Diamond. O pacote sanitizado deve ser
combinado com o `.env` privado mantido fora do Git; ele nunca deve receber segredos versionados.

## Acabamento da entrada pública

30. ✅ **Jornada intuitiva do visitante para o recrutamento — concluída em produção em 2026-08-23.**
    A mensagem persistente da Recepção passou a oferecer `Candidatar-me agora` em um clique e a
    distinguir candidatura de cadastro funcional. O painel de Recrutamento foi editado no lugar com
    candidatura, acompanhamento e requisitos, sem duplicar mensagens, canais ou IDs. A DM de entrada
    repete a mesma decisão simples. A validação REST confirmou os textos, links e componentes nas
    mensagens `MEMBER` e `RECRUITMENT`, além de zero comandos publicados.

    Durante o rollout, o pacote Discloud incluiu o SQLite local porque `data/*.db*` ainda não estava
    no `.discloudignore`. O erro foi detectado nos logs, a instância foi parada e o backup pré-deploy
    íntegro foi restaurado atomicamente antes do startup. O empacotamento agora bloqueia DB/WAL/SHM;
    o launcher valida e consome um candidato explícito `recovery-once` sem abrir o banco corrompido.
    Evidências finais: Discloud online, health 200, Gateway conectado, `quick_check=ok`, FK=0,
    migration 24, **296 pytest**, **29 Vitest**, Ruff, compile/check, ESLint, typecheck e build.

## Continuidade de produção

31. ✅ **Portaria segura, Recrutamento operacional e patrulhas ao vivo — concluído em produção em
    2026-08-23.** O atalho ambíguo de cadastro foi substituído por identificação de vínculo e um
    visitante comum não pode mais virar membro sem candidatura ou role funcional reconhecida. Os
    modais administrativos confirmam a interação antes do trabalho demorado. A jornada pública de
    Recrutamento recebeu matriz de leitura, Mesa privada, posto `Setar tag`, menção/DM do aprovado e
    atualização idempotente do protocolo anterior. A migration 25 e o frontend publicado mostram
    ocupação real das calls no painel sem criar patrulha falsa. O Centro de Comando ficou restrito a
    perfis `COMANDO` ou superiores.

    Evidências: snapshot de overwrites, três backups Discloud, banco v25, Gateway online, validação
    REST do protocolo e dos canais, Vercel 200, **300 pytest**, **32 Vitest**, Ruff, compileall,
    `main.py --check`, ESLint, TypeScript e build. Como não havia ninguém nas calls na hora do corte,
    a próxima ocupação real ainda deve ser observada no painel; isso não bloqueia o mecanismo já
    testado. Gestão bidirecional de qualificações e compactação do servidor permanecem na fila
    futura e não foram executadas nesta entrega.

## Fila consolidada após auditoria da conversa — prioridade operacional

Regra de andamento: item dependente de decisão, credencial ou validação humana permanece registrado
e recua atrás dos trabalhos independentes. Ele nunca é descartado nem bloqueia o próximo item seguro.

32. ✅ **Hotfix real de Patrulhas — concluído em produção em 2026-08-23.** A Patrulha Alfa estava
    no SQLite remoto, mas a rota publicada ainda chamava `active_patrols()` e ignorava ocupação ao
    vivo. A rota passou a usar `active_patrol_overview()`; leituras operacionais usam conexão SQLite
    nativa curta entre bot/API. O endpoint assinado retornou Patrulha Alfa, um ocupante e
    `presence_source=DISCORD_LIVE` após reinício em instância única.

33. ✅ **Paridade integral entre fonte local e Discloud — concluída em 2026-08-23.** O backup remoto
    foi comparado por conteúdo com todos os Python/JSON ativos. As únicas divergências eram
    `command_center/app.py` e `command_center/security.py`: rotas de presença/recrutamento e o gate
    exclusivo de Comando estavam antigos. Os arquivos foram alinhados, caches removidos e a
    aplicação reiniciada. Hashes finais dos dois arquivos coincidem com a árvore local; 302 testes,
    Ruff, compileall e `main.py --check` passaram. O endpoint real continuou retornando Patrulha
    Alfa ao vivo após o corte. O backup pré-paridade foi preservado fora do Git.

34. ✅ **Gestão bidirecional de qualificações — implementada e publicada em 2026-08-23.** A
    matriz web permite ao Alto Comando conceder ou revogar um curso; a decisão é append-only,
    auditada e envia uma ação idempotente para adicionar/remover somente o cargo mapeado no
    Discord. Alterações feitas diretamente nos cargos do Discord alimentam a mesma projeção sem
    criar eco na outbox. A migration 26, o RBAC `qualification.manage`, a rota protegida e a página
    foram publicados na Discloud/Vercel. Evidências: backup pré-corte íntegro, banco remoto v26,
    rota publicada, health 200, Gateway online, **306 pytest**, **32 Vitest**, Ruff, compileall,
    `main.py --check`, ESLint, TypeScript e build. A automação não alterou o curso de um membro real
    apenas para produzir evidência; o primeiro clique humano continua sujeito à confirmação e
    auditoria normais, sem reabrir a implementação.

35. ✅ **Superfícies vazias do dashboard — concluídas em produção em 2026-08-23.** A causa de
    Recrutas vazio era a comparação literal de `RECRUTA` com a patente visual `ʀᴇᴄʀᴜᴛᴀ`; a
    normalização canônica agora reconhece nome e prefixo Small Caps. Gestão de Carreira passou a
    expor efetivo, patente/tempo na patente, horas válidas, patrulhas, advertências e movimentações
    reais, com estados vazios úteis e links alcançáveis. O dossiê e a elegibilidade usam a projeção
    bidirecional atual de qualificações. Produção confirmou 12 membros ativos, 4 recrutas e 14
    mudanças de patente no banco remoto; `/v1/career` está publicada e protegida, Discloud v26 e
    Gateway estão online e o alias Vercel preserva o gate de Comando. Evidências: backup pré-corte,
    health 200, **307 pytest**, **32 Vitest**, Ruff, compileall, `main.py --check`, ESLint,
    TypeScript e build.

36. ✅ **Acabamento visual humano do recrutamento — concluído em produção em 2026-08-23.** A
    publicação adota o alistamento editorial militar contemporâneo definido na referência CHOQUE:
    grafite/vermelho, Barlow Condensed, composição assimétrica, processo em linha e diagonal
    institucional como âncora, sem cards genéricos. DFII 13/15. Capturas integrais em 1440 px e
    390 px confirmaram hierarquia, legibilidade e adaptação sem overflow. O E2E passou contra o
    alias público em Chromium desktop, Chromium mobile e Firefox, validando CTAs, dez questões,
    idioma, privacidade e nomes acessíveis; ESLint, TypeScript, **32 Vitest** e build continuam
    verdes. O Lovable não disponibilizou ferramenta callable nesta sessão e nenhum dado real foi
    reenviado; a referência já incorporada foi conferida nos artefatos e na publicação.

37. ✅ **Robô Analista — motor local concluído e ativo em produção.** A análise
    determinística será a autoridade e o fallback permanente. O assistente opcional de modelo
    aberto será prototipado apenas em processo/app isolado, com uma análise por vez, contexto curto,
    timeout, circuit breaker, dados minimizados/anônimos e schema de saída estrito. Capacidade
    registrada: plano Diamond 4096 MB; manter API (1024 MB) e standalone offline (900 MB), reservar
    inicialmente 1536 MB para o spike e medir pico real antes de qualquer decisão de rollout.
    O rollout final adotou `local-deterministic/transparent-rules-v1`, sem app separado, segredo ou
    envio externo. A associação de critérios não usa palavras inseridas pelo candidato; prompt
    injection é tratada como dado e força revisão humana. Benchmark: 500 execuções idênticas, p95
    1,517 ms e máximo 2,669 ms. Gates: 433 pytest, 41 testes web, Ruff, compileall,
    `main.py --check`, lint, typecheck e build. Produção: health 200, Gateway único, oito opções
    ativas e backup íntegro sem job ativo/esgotado. O Qwen permanece experimento futuro opcional,
    fora da fila ativa e sem RAM reservada.

38. ✅ **Domínio próprio do portal — concluído em 2026-08-24.** `choquebgr.online` e `www` estão
    vinculados à produção Vercel com TLS; `www` redireciona permanentemente para o domínio canônico.
    As rotas públicas e administrativas permanecem no mesmo domínio, o alias Vercel continua como
    apoio compatível ao OAuth e `/discord` redireciona permanentemente para o convite oficial.
    Provas finais: login e status 200, recrutamento público 200, áreas privadas redirecionam para
    login e nenhum erro de runtime nas rotas novas.

39. ✅ **Remoção intencional do módulo de medalhas — concluída em produção em 2026-08-23.** O canal
    apagado pelo proprietário não é mais exigido nem recriado: o cog saiu de `COGS`, o validador
    vivo registra o módulo como intencionalmente desabilitado e os scripts estruturais perderam o
    ID/chave de Medalhas. O fonte histórico e as sete definições ficam somente para consulta e
    rollback. Backup pré-corte, **309 pytest**, Ruff, check v27, logs sem novo alerta e validador
    vivo verde comprovam a entrega.

40. 🟡 **Compactação estrutural do Discord — adiada pelo proprietário.** Antes de excluir, capturar
    snapshot e pedir confirmação final. Plano preservado: remover Atendimento 2/3; Manual do Comando
    e Área de QA; Doutrina ROCAM/Águia; Eventos; Ausentes; Reunião; Arquivos Legados. Mover
    Bate-ponto/Efetivo para Patrulhas, Configurações do bot para Administração e Transferências/
    Parcerias para o fim. Manter Centrais, Auditoria, Recrutamento em destaque e Cursos intactos.

41. 🔒 **Dívida obrigatória de segurança — depende do proprietário.** Rotacionar credenciais
    divulgadas, revisar menor privilégio do bot e repetir login/logout/revogação com contas reais.
    Nunca colocar os novos valores em chat, Git, ZIP, logs ou handoff.

42. ✅ **Auditoria desta continuidade concluída em 2026-08-24; disciplina contínua preservada.**
    `PROJECT_HANDOFF.md`, fila, ledger e relatório foram reconciliados sem apagar o histórico.
    A auditoria AST percorreu 22 módulos, 279 interfaces e 390 componentes: 107 `custom_id`
    explícitos sem duplicidade, zero callback ausente e zero interface ativa órfã. O
    `main.py --check` confirmou migration 39, 18 cogs, 46 comandos e 25 views persistentes;
    `security_scan.py` terminou `SECRET_SCAN_OK` e `git diff --check` permaneceu verde. A mesma
    reconciliação documental continua obrigatória em toda entrega futura.

43. ✅ **Correções recuperadas da conversa — concluídas em produção em 2026-08-23.** A campanha
    ainda bloqueava candidatos de 15 anos embora a mensagem pública dissesse 15. A migration 27
    alinhou 16 → 15 com auditoria, backup e integridade comprovada. CNH B e porte de arma não fazem
    parte do fluxo ativo. O `/status` foi corrigido de Railway/v23/pausado para Discloud Diamond,
    Gateway ativo e banco v27, publicado no alias principal e validado com HTTP 200.

44. ✅ **Escopo da gestão de qualificações — confirmado em 2026-08-23.** O proprietário definiu que
    **todo o Alto Comando** pode conceder e revogar qualificações. O RBAC publicado já usa
    `qualification.manage` nesse perfil, portanto a decisão foi registrada sem alterar cargos,
    membros ou permissões em produção.

45. ✅ **Checkpoint sanitizado no repositório privado — concluído em 2026-08-23.** O remoto foi
    verificado como privado antes da operação. Após `SECRET_SCAN_OK`, revisão dos 38 arquivos e gates
    verdes, o estado consolidado foi enviado explicitamente somente para `private/main` no commit
    `1fa51db`. `.env`, tokens, bancos, WAL/SHM, backups, logs e dados pessoais não entraram; o remoto
    público não recebeu push.

46. ✅ **Mesa de Análise de candidaturas — concluída e publicada em 2026-08-23.** A mesma ficha
    privada agora apresenta estado, responsável, atribuição, decisão e datas, preservando os controles
    existentes e acrescentando Aprovar/Reprovar persistentes com modal, justificativa, RBAC único,
    anti-autoavaliação, idempotência e auditoria de origem Discord/correlation. Recuperação atualiza
    somente a ficha original em cadência segura; cartão inexistente nunca é recriado. O portal filtra
    por status/responsável. Produção confirmou Gateway único/migration 28; Vercel
    `dpl_EJZedEhLbTyjaJFYAjhVseEzhX9v` está READY. A demonstração isolada e sem mutação foi publicada
    uma vez na Mesa (`1541248708203774013`). Gates: 335 pytest, 40 Vitest, Ruff, compileall,
    `main.py --check`, lint, typecheck e build.

47. ✅ **Central de Tags, Set e Identidade — concluída e publicada em 2026-08-24.**
    Fonte integral imutável: `C:\Users\mpaii\.codex\attachments\827849b6-d049-43a9-ba32-c1ff7b9ee7f4\pasted-text.txt`
    (SHA-256 `6330CC70FE7920C2BA0DA5B4F85A9A29310F935530BDC837475DD8F81A8978B1`). A implementação deve
    reutilizar cadastro/identidade, solicitações, cargos, auditoria, painéis, banco e permissões
    existentes; não criar autoridade ou fluxo paralelo e não publicar parcialmente.

    Cobertura obrigatória, preservada pelas 40 seções da fonte:

    1. fluxo completo `SOLICITAÇÃO → AGUARDANDO SET → SET REALIZADO → AGUARDANDO CONFIRMAÇÃO → CONCLUÍDO`,
       inclusive recusa, cancelamento, expiração, pendência, reabertura, correção, auditoria,
       reatribuição e sincronização de cargos;
    2. cargos configurados por IDs (`TAG SETADA`, `AGUARDANDO SET`, `RESPONSÁVEL POR TAG`), sem nomes
       visuais como chave;
    3. painel fixo do membro, elegibilidade por identidade, ID MTA, persistência, cargo pendente,
       aviso aos responsáveis e orientação à DP de Los Santos;
    4. prevenção de solicitação duplicada e indicação clara de solicitação ativa;
    5. estados controlados, transições e mensagens coerentes;
    6. fila ordenada, pesquisável e atualizada para quem aguarda set;
    7. notificações centralizadas, sem spam, para os responsáveis;
    8. assumir atendimento com concorrência segura;
    9. liberar, reatribuir e manter o histórico de responsável;
    10. registrar realização do set com dados e responsável;
    11. confirmação exclusiva pelo próprio membro;
    12. confirmação positiva atômica: status, cargos, horários, executores, cadastro, painel e auditoria;
    13. caminho de tag não recebida, justificativa, pendência e reabertura;
    14. expiração configurável, recuperação e histórico;
    15. recusa com motivo obrigatório e observação;
    16. cancelamento seguro e histórico preservado;
    17. correção auditada do ID MTA;
    18. conflito de ID MTA tratado de modo controlado;
    19. painel administrativo Central de Tags com indicadores, busca e ações por permissão;
    20. visão completa de quem falta setar, com busca/listagem paginada;
    21. fila própria de aguardando confirmação;
    22. chamada para a DP por canal/DM, cooldown e trilha;
    23. tempos, timestamps e métricas operacionais;
    24. timeline integral e imutável por solicitação;
    25. integração bidirecional com o cadastro central de identidade;
    26. reconciliação segura banco/Discord dos cargos de tag, sem remoção indevida;
    27. integridade de dados e transições no domínio/banco;
    28. permissões distintas para membro, responsável por tag e administração;
    29. auditoria de toda ação administrativa e de identidade;
    30. arquitetura de banco com tabelas, índices, FKs e unicidade de ativo;
    31. idempotência de ações, entregas e eventos;
    32. recuperação persistente após restart, inclusive fila, atendimentos, painéis e pendências;
    33. base para métricas futuras;
    34. experiência simples do membro do pedido à conclusão;
    35. experiência operacional clara do responsável;
    36. UX por painéis/mensagens limitadas/modais, sem poluição;
    37. testes de solicitação, atendimento, set, finalização, exceções, concorrência e recuperação;
    38. critérios de conclusão integralmente validados, sem etapa manual implícita;
    39. entrega técnica com arquivos, migrations, entidades, regras, permissões, listeners, testes,
        problemas, decisões e riscos documentados;
    40. princípio de integração: identidade, cargos, solicitação, atendimento, confirmação e auditoria
        formam uma única cadeia extensível para módulos futuros.

    Gate de produção cumprido: migration 35, fluxo completo, painéis persistentes, reconciliação,
    idempotência, permissões e recuperação foram publicados após 386 testes verdes. O painel do membro
    possui Solicitar tag, Minha tag já foi setada e Minha tag; declaração legada sempre exige revisão.
    A confirmação por DM foi corrigida e a aplicação combinada permaneceu como único Gateway.

48. ✅ **Status do Bot — concluído e publicado em 2026-08-24.**
    Painel público persistente, em **uma única mensagem editável**, com estado global e componentes
    separados: Bot/Gateway; API/Site; Portaria/Cadastro; Recrutamento/Mesa; notificações e filas;
    Auditoria/Histórico; Bate-ponto/Patrulhas; Central de Tags quando disponível. Estados humanos
    permitidos: `OPERACIONAL`, `ATUALIZANDO`, `EM_MANUTENCAO`, `INSTAVEL_DEGRADADO`,
    `TEMPORARIAMENTE_DESATIVADO` e `INDISPONIVEL`. Cada componente informa resumo simples, início,
    última atualização, responsável e previsão **somente** quando registrada.

    A detecção automática só poderá refletir evidência confiável (health, Gateway, último sucesso,
    falha/idade de fila), com debounce/histerese e sem declarar normal apenas porque o processo
    respondeu. Overrides administrativos persistem componente, estado, motivo, responsável, início,
    previsão opcional, expiração/resolução e timeline; exigem RBAC backend, CAS, auditoria e modal.
    Público tem apenas Atualizar/Detalhes; administração possui ações explícitas de manutenção,
    instabilidade, desativação e normalização. Avisos ocorrem apenas no início/resolução relevante,
    com cooldown, e nunca expõem stack traces, IDs internos, segredos ou dados pessoais. Jobs críticos
    devem pausar/reter a fila com segurança e retomar sem perda. Testar restart, painel apagado,
    clique/override concorrente, detecção, fila atrasada, resolução, cooldown e falha do monitor.
    Publicação concluída após 395 testes, Ruff, compileall e `main.py --check`. O canal público
    `1541298034825236500` mantém uma única mensagem fixada (`1541298362450452531`) com Atualizar e
    Detalhes; o canal administrativo privado `1541298038117761084` mantém a mensagem fixada
    `1541298363134255175` com os seis controles explícitos. Migration 36, oito componentes, CAS,
    auditoria, timeline, detecção com histerese, cooldown, recuperação pós-restart e Gateway único
    foram confirmados. Falhas históricas terminais não degradam o estado atual; o painel ao vivo
    terminou com os oito componentes operacionais. Backup pós-publicação: `quick_check=ok`, FK=0.

49. ✅ **Evolução completa de bate-ponto, patrulhas e viaturas — concluída e publicada em 2026-08-24.**
    A migration 37, orquestração única de voz, ponto automático, viaturas duráveis, comando por
    hierarquia, timeline de composição, painel agrupado, relatórios PTR, ocorrências/evidências,
    configuração por ID e correções administrativas auditadas foram publicadas como um único conjunto.
    Trocas de call preservam a sessão; restart reconcilia presença sem duplicar tempo; capacidade e
    cargos são aplicados no backend. Gates: 419 pytest, 41 testes web, Ruff, compileall,
    `main.py --check`, lint, typecheck e build. Produção confirmou health 200, migration 37, um Gateway,
    backup íntegro, uma viatura real recuperada e zero duplicidade/inconsistência nas invariantes.

50. ✅ **Extensão integrada Viatura → Operação → PTR → Carreira → Mérito → Oficialato — concluída e publicada em 2026-08-24.**
    Fonte integral imutável: `docs/source-prompts/16-vehicle-operation-ptr-career-merit-officer-original.md`,
    importada de `C:\Users\mpaii\.codex\attachments\0c76f83a-06c6-4868-9af6-d576daef0804\pasted-text.txt`,
    SHA-256 `11EC9D26F62AB5C646C66CAE7215F633C6748A7E884AB9BAC020C15A5F12AD15`.
    Não é um projeto separado: deve consolidar e estender, sem recriar, identidade, Central de Tags,
    bate-ponto, patrulhas, cargos, auditoria, outboxes, painéis e banco. A premissa da fonte de que
    Central de Tags e as fundações de bate-ponto/patrulhas já foram cumpridas pelos itens 47 e 49.
    A continuação agora começa em progressão, carreira, mérito e oficialato, sempre reutilizando a
    identidade, os pontos, as viaturas, os relatórios e a auditoria canônicos. Não publicar
    implementação parcial: o conjunto relevante exige E2E, migrations seguras, idempotência,
    recovery, RBAC e testes completos.

    As 64 seções e todos os seus critérios são obrigatórios pela fonte integral preservada:
    1 Contexto; 2 Objetivo; 3 Princípio de integração; 4 Viaturas; 5 Call e viatura; 6 Identificador;
    7 Comandante automático; 8 Regras do comandante; 9 Histórico da viatura; 10 Efetivo em serviço;
    11 Membros sem viatura; 12 PTR; 13 Ocorrências/perdas; 14 Exemplo; 15 Categorias; 16 Artigos;
    17 Relatório final PTR; 18 Progressão automática; 19 Metas; 20 Horas acumuladas; 21 Tempo mínimo;
    22 Regras de promoção; 23 Promoção automática; 24 Processamento pós-restart; 25 Canais de promoção;
    26 Promoções manuais; 27 Rebaixamentos; 28 Canal de rebaixamento; 29 Mérito após Cadete;
    30 Histórico de carreira; 31 Candidatura para Oficial; 32 Requisitos; 33 Validação; 34 Formulário;
    35 Dimensões; 36 Qualidade; 37 Tipos de questão; 38 Pontuação; 39 Pesos; 40 Red flags;
    41 Consistência; 42 Análise de perfil; 43 Compatibilidade hierárquica; 44 Histórico do candidato;
    45 Relatório de candidatura; 46 Responsável por upamento; 47 Painel do avaliador; 48 Análise humana;
    49 Entrevista; 50 Aprovação condicionada; 51 Reprovação; 52 Versionamento; 53 Área do candidato;
    54 Canais necessários; 55 Gerenciamento de canais; 56 Auditoria; 57 Idempotência;
    58 Sincronização de cargos; 59 Segurança; 60 Configurações; 61 Dashboard de carreira;
    62 Testes obrigatórios; 63 Critério de conclusão; 64 Instrução final ao desenvolvedor.

    Entrega verificada: as fundações Viatura/Operação/PTR permanecem na migration 37 e a migration
    38 adiciona progressão automática até Cadete, mérito auditado e candidatura a Oficial com
    questionário versionado de 30 perguntas. A migration 39 adiciona notificações duráveis. A
    avaliação automática é apenas consultiva; elegibilidade, notas, entrevista e decisão final
    continuam protegidas por RBAC e autoridade humana. Produção confirmou health 200, banco v39,
    um Gateway, cinco canais configurados por ID e questionário ativo único. O portal publicou as
    áreas do candidato e dos responsáveis sem 5xx. Gates finais: 429 pytest, 41 testes web, Ruff,
    compileall, `main.py --check`, lint, typecheck e build; backup pós-publicação com
    `quick_check=ok`, zero violações de FK e zero notificação de carreira falha ou pendente.

51. 🟡 **Central de Auxílio Financeiro, Metas, Transparência e Honrarias — em desenvolvimento isolado.**
    Fonte integral imutável: `C:\Users\mpaii\.codex\attachments\dbcc3e73-3d46-4cc6-a021-2680bab85abc\pasted-text.txt`
    (SHA-256 `EC9FA0507AC4CC2F43C1CAD93BF739A050488FB57A8584573273CB7AF70F75B2`). O módulo deve reutilizar
    identidade, membros, RBAC, auditoria, settings, outbox, registro de painéis e padrão visual já
    existentes. Não pode criar um caixa, autoridade, sincronizador ou painel paralelo. Produção permanece
    inalterada até o fluxo completo, recuperação pós-restart, revisão adversarial e gate final.

    Os 40 blocos obrigatórios da fonte são preservados por referência integral e por esta cobertura:

    1. contribuições inteiramente voluntárias, sem mínimo, máximo, mensalidade ou penalidade;
    2. vedação absoluta de compra de poder, promoção, prioridade, influência ou acesso;
    3. canal e mensagem persistente `💰・auxílio-financeiro` como Central institucional;
    4. fluxo de doação com PIX configurado com segurança, cópia, declaração e cancelamento;
    5. declaração de valor, destino, observação, visibilidade e projeto ativo opcional;
    6. estados PENDENTE, CONFIRMADA, NÃO CONFIRMADA e CANCELADA, com confirmação administrativa;
    7. visibilidade pública/anônima sem expor valores individuais por padrão;
    8. metas/projetos com identificador, orçamento exato, responsável, prazo, estado e timeline;
    9. apresentação visual de meta, progresso e bloqueio de novas contribuições ao concluir;
    10. fundo geral com arrecadado, utilizado, saldo e movimentações;
    11. apadrinhamento voluntário de projeto, sem obrigação financeira;
    12. metas comunitárias e mensagem explícita de que pequenas contribuições importam;
    13. prestação de contas agregada, relevante e privada por padrão;
    14. lançamentos financeiros imutáveis, auditáveis, canceláveis/estornáveis, nunca apagados;
    15. sugestões de melhoria via painel administrativo;
    16. mural de apoiadores sem ranking financeiro;
    17. honrarias simbólicas com regras claras e Patrono sempre humano/discricionário;
    18. cargos Discord simbólicos, sem permissões administrativas ou operacionais;
    19. perfil de honrarias e conquistas do membro;
    20. conquistas automáticas explicáveis e não orientadas por faixas de dinheiro;
    21. certificado digital sem valor financeiro por padrão, com código de validação;
    22. eventual preview antecipado somente não sensível;
    23. créditos de projeto apenas com autorização;
    24. concessão manual de honraria com justificativa, responsável e duração opcional;
    25. remoção de honraria preservando trilha completa;
    26. log de honrarias auditável;
    27. painel financeiro administrativo protegido e dividido por ações;
    28. permissões separadas para Financeiro, Projetos, Honrarias, Auditor e Administração;
    29. PIX somente em configuração segura, alteração elevada e auditada;
    30. validação server-side, valores exatos positivos, idempotência e auditoria;
    31. minimização de dados e comprovantes sempre restritos;
    32. jornada completa feita por botões, selects, modais e embeds, sem comandos de texto;
    33. conclusão automática idempotente de projeto e suas atualizações correlatas;
    34. reconhecimento institucional de toda contribuição, sem loja de títulos;
    35. pontos de extensão documentados para automação PIX e relatórios futuros;
    36. entidades com IDs, constraints, FKs e timestamps consistentes;
    37. UX militar/institucional da CHOQUE, legível e sem aspecto comercial;
    38. regras de negócio financeiras e de igualdade protegidas por testes;
    39. mensagem institucional de encerramento;
    40. resultado integrado Auxílio + Projetos + Transparência + Reconhecimento, sem regressões.

52. ⏳ **Revisão de canais e painéis persistentes já publicados — adiada até a conclusão financeira.**
    Começará pelo painel de bate-ponto, cuja mensagem poderá estar desatualizada. O inventário deverá
    comparar cada painel persistente ao comportamento canônico atual de ponto, patrulhas, viaturas,
    carreira e demais fluxos; editará a mensagem original somente quando o conteúdo estiver comprovadamente
    obsoleto. Não recriará canais, não duplicará mensagens, não mencionará membros e preservará permissões,
    IDs, recuperação pós-restart e histórico. Cada alteração só será publicada após testes de apresentação,
    recovery e validação ao vivo, com registro posterior em Atualizações do Bot.

53. ⏳ **Notificações institucionais de promoção e rebaixamento — sistema futuro.**
    Depois da Central Financeira e da revisão dos painéis, publicar uma única mensagem no canal próprio
    somente após a transação canônica de carreira: militar, patente anterior/nova, responsável, data e
    origem. Distinguir explicitamente `PROMOÇÃO`, `REBAIXAMENTO`, `CORREÇÃO` e `REVERSÃO`; a publicação
    nunca espera o motivo. Um controle RBAC separado **Incluir motivo** editará a mesma mensagem e a auditoria,
    com versionamento e autor da inclusão/alteração, sem criar duplicata. Garantir idempotência e recovery.
    Reconciliação/sincronização técnica de cargos nunca pode gerar publicação. Não mencionar todos nem
    expor dados privados, e preservar o histórico inclusive em correções ou reversões.

54. ✅ **Simplificação da Central de Tags — concluída e publicada em 2026-08-25.**
    Cada solicitação ativa mantém **uma única ficha editável** no canal da Central. Pedido novo mostra
    somente `Assumir` e `Ver detalhes`; após assumir, a própria ficha oferece `Chamar para DP`,
    `Tag aplicada`/validação e `Mais ações`, com ações raras protegidas. A conclusão mantém o histórico
    em cinza e sem controles. A migration 43 versiona a projeção, e todas as treze pendências existentes
    foram migradas para o novo layout. Após reinício controlado continuaram treze fichas, zero ausentes,
    zero desatualizadas e zero duplicidades; 58 testes focados e 507 testes da suíte completa passaram.

55. ✅ **Unidades Especiais e Comandos — concluída e publicada em 2026-08-26.**
    Fonte: `C:\Users\mpaii\.codex\attachments\ad3d5ab5-22e3-4c12-bcfe-71388bb58cb0\pasted-text.txt`,
    SHA-256 `65075C64A46ECEF620FB0BBA63DE51C89E88057FA96F3841E32DF510AC0FA701`.
    ROCAM, TÁTICO, ELITE e CORREGEDORIA reutilizam identidade, patente, promoções, Qualificações,
    Central de Tags, RBAC, auditoria, painéis e outbox canônicos. A migration 46 adiciona somente
    candidaturas, vínculos, recursos Discord por guild e timeline imutável das unidades.
    Produção mantém quatro centrais privadas no servidor principal e candidatura/mesa mínimas no REC,
    com três cargos hierárquicos por unidade em ambos os servidores, todos sem permissões globais.
    Aprovação sincroniza cargos nos dois servidores, nunca reduz patente e eleva somente quem estiver
    abaixo de Cabo, usando o fluxo canônico de promoção e notificação. Designações e saídas são
    versionadas, auditadas e recuperadas após reinício. Gate: 546 testes, Ruff, compileall,
    `main.py --check`, backup íntegro, migration 46, health 200 e Gateway único. O reinício de prova
    preservou os mesmos seis IDs de painéis e oito conjuntos de recursos, sem duplicação.

56. 🟡 **Prompt Master — Evolução Completa do Ecossistema CHOQUE — registrado e em execução por fases.**
    Fonte integral: `C:\Users\mpaii\.codex\attachments\2fa5a165-f89d-4795-a943-564a5d0b87c6\pasted-text.txt`,
    SHA-256 `797967256032CBA953CC3493D745E4706AD5EDC506EAF2D2AE68444B170B44A6`. As 65 seções
    permanecem obrigatórias, mas não autorizam recriar módulos já concluídos. A execução segue
    `mapear → reutilizar → corrigir → integrar → criar`, usando identidade, RBAC, auditoria, outbox,
    painéis persistentes, banco e sincronização multi-servidor existentes. O inventário e as decisões
    técnicas estão em `docs/ECOSYSTEM_SITE_AUDIT_20260826.md`. Os blocos restantes avançam por
    dependência após a fase visual ativa, começando por ADV/cursos, sincronização/transferências e
    analytics factuais. Dados simulados apresentados como produção, IA decisora e sistemas paralelos
    continuam proibidos. O primeiro bloco, **ADV**, está concluído localmente sobre o ledger disciplinar
    canônico: quatro gravidades, prazo configurável, expiração idempotente, histórico/auditoria e painel
    global paginado recuperável. Gate local: 53 testes focados e 559 testes da suíte completa, com Ruff,
    compileall, `main.py --check` e `git diff --check` verdes. O segundo bloco, **Cursos**, também está
    concluído localmente: cada curso possui canal/painel persistente próprio; requisitos exibem patente,
    cargos, horas, tempo de corporação, curso anterior, suspensão e ADV; a conclusão aprovada grava o
    histórico canônico e enfileira uma única sincronização do cargo do curso. A migration 50 preserva o
    índice agregado apenas como orientação, sem concentrar candidaturas. Gate local consolidado: 68 testes
    focados e 561 testes da suíte completa, além de Ruff, compileall, `main.py --check` e `git diff --check`.
    O terceiro bloco, **Transferências**, está concluído localmente na migration 51. O ticket existente
    continua sendo a entrada e a sala privada; o novo agregado cobre somente protocolo estável, snapshot,
    teto de patente por guild, timeline e aplicação. Aprovar o ticket cria uma ficha pendente e não altera
    vínculo; outra decisão humana aplica exatamente a patente autorizada e então usa a outbox canônica.
    Cancelar/reabrir mantém ticket e protocolo no mesmo estado; patente desativada bloqueia a aplicação
    em vez de acionar fallback; e o solicitante vê o protocolo em seu histórico. Migração de legado não
    concede patente retroativamente. Gate consolidado: 68 testes focados, **569 testes Python**, scanner
    de segredos, `pip-audit`, Ruff, compileall, `main.py --check`, 57 testes
    web, `npm audit`, typecheck, lint e build. A sincronização multi-servidor existente não foi duplicada
    nem alterada neste corte. ADV, Cursos e Transferências ainda não foram publicados em produção.

57. 🔄 **Prompt Master — Reformulação Completa do Site CHOQUE — fase visual ativa.**
    Fonte integral: `C:\Users\mpaii\.codex\attachments\89ef54de-2878-4b01-8ba7-9c600f45a3ad\pasted-text.txt`,
    SHA-256 `808436337D493D5548FF12696DEC465A2DC6BF6B6A983FF191861D6AD25D3B45`. A referência visual
    aprovada é o mosaico tático escuro encaminhado em 26/08/2026: preto/grafite, verde oliva como
    acento, tipografia condensada, painéis densos, navegação militar e brasão oficial. Essa imagem é
    contrato visual para todas as superfícies restantes; não deve ser reinterpretada como SaaS
    genérico, cyberpunk ou interface clara. A primeira entrega já está publicada: identidade e
    metadados oficiais, brasão otimizado, recrutamento, avaliação acessível, acompanhamento humano e
    status com fonte real. Gates: 57 testes web, lint, typecheck e build. Permanecem ativos o Centro
    de Comando, telas administrativas, mobile/acessibilidade e consolidação visual completa, sem
    alterar contratos, URLs, RBAC ou regras de negócio existentes. O primeiro corte local do Centro
    de Comando tornou o drawer móvel modal e acessível: estado expandido explícito, foco contido,
    fechamento por `Escape` e retorno do foco ao acionador. TDD preservado nos commits `2ca8770`
    (RED) e `20d4153` (GREEN). O segundo corte fez o cabeçalho do dashboard mostrar o timestamp do
    snapshot real da API em `<time>`, sem usar o relógio do render; `5e36506` preserva o RED e
    `098fea0` entrega o GREEN. O terceiro corte tornou todas as faixas `MetricStrip` listas de
    descrição com pares semânticos `<dt>/<dd>`, sem alterar visual ou valores; `093a1cf` preserva o
    RED e `d0eecb6` entrega o GREEN. Gate consolidado: 8 testes focados, 60 testes web, `npm audit`
    sem vulnerabilidades, typecheck, lint e build. O quarto corte expôs a fila operacional FIFO como
    `<ol>` nomeada, com itens `<li>`, preservando posição, duração e visual; `03b2bd6` registra o RED
    e `ff86f4e` entrega o GREEN. O quinto corte expôs as pendências administrativas recentes como
    `<ul>` nomeada, com links preservados dentro de itens `<li>`; `b52379c` registra o RED e `d0681c6`
    entrega o GREEN. Gate atual: 10 testes focados, 62 testes web, `npm audit` sem vulnerabilidades,
    typecheck, lint e build. Os cortes permanecem somente locais e não publicados.

58. ⏳ **Prompt Master — Identidade Visual / Design System CHOQUE — registrado na fila.**
    Fonte recebida: `C:\Users\mpaii\.codex\attachments\8f7db861-0f81-4655-a0fc-b3fc90133b12\pasted-text.txt`,
    SHA-256 `78C71E32434F0B6B1DC711B51E2BC872A5406B47E043817BD7624038ADFA5221`. A imagem tática
    encaminhada junto é a referência visual obrigatória. O contrato exige military tech institucional,
    base preto/grafite, verde funcional controlado, superfícies sólidas, tipografia condensada,
    design tokens, acessibilidade, performance e UX `ver → entender → agir`, sem remover qualquer
    função. O arquivo recebido termina incompleto na seção 65, após `Status com:`; esse limite foi
    registrado sem inventar conteúdo. A execução visual entra depois dos blocos funcionais locais em
    andamento e continua proibida de rollout na Discloud sem autorização explícita.
