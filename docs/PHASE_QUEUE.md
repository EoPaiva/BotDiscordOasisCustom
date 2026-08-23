# Fila de Fases — CHOQUE BGR

Atualizada em 2026-08-23.

Esta é a ordem oficial de continuidade. Uma fase só sai da fila depois de implementação, testes,
validação proporcional ao risco e atualização do `PROJECT_HANDOFF.md`.

O inventário completo dos pedidos, incluindo as fontes originais, está em
`docs/REQUEST_LEDGER.md`. Nenhum item abaixo deve ser interpretado como implementado apenas por
estar documentado.

## Lote 0 — correções urgentes de produção

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

16. 🟡 **Robô Analista de Candidaturas — implementação concluída; ativação externa pendente.**
   Executado a partir de `docs/RECRUITMENT_AI_ANALYST_SPEC.md`. O módulo auxilia recrutadores por
   rubrica e evidências e não possui autoridade administrativa. A API de produção confirmou
   `enabled=false` e `provider_ready=false`: não existe `RECRUITMENT_AI_API_KEY`/provider no runtime.
   Ativar e validar a análise qualitativa exige cadastrar uma credencial de provedor compatível na
   hospedagem; até lá, o sistema não fabrica classificação e mantém a decisão exclusivamente humana.

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
