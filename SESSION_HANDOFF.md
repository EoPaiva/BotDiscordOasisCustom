# SESSION_HANDOFF.md

> Checkpoint operacional atual. O código e o estado real do repositório prevalecem.
> Estado estrutural permanente: `PROJECT_STATE.md`.

## 0. Checkpoint mais recente — cortes 23 e 24 da Fase 57 publicados

**Branch:** `main`. **TDD:** `32b4bbf` registra os contratos RED e `a7314c6` entrega o GREEN para
os dois timestamps. Ambos foram enviados para `origin/main` e `private/main`.

**Entregue:** o instante `Desde` do lockdown e a coluna `DATA` dos eventos em `/security` agora usam
`<time dateTime="…">`. Ações sensíveis, controles, URLs, APIs, RBAC e regras permanecem iguais.

**Gates locais:** 2 testes focados; 99 testes em 25 arquivos; lint; typecheck; build;
`npm audit` sem vulnerabilidades; 8 E2E aprovados e 1 cenário visual Firefox intencionalmente
ignorado.

**Produção técnica:** deploy Vercel `dpl_BkSZCWmRcqrW4xvgVgea9vaqqgZW`, `READY` em 2026-08-27,
com alias `choquebgr.online`. `/login` e `/status` responderam HTTP 200 e o CSP estrito permaneceu
ativo. Isso é smoke técnico; sessão autenticada e leitor de tela real continuam validações humanas
distintas.

**Próxima ação exata:** selecionar e executar o próximo corte incompleto da Fase 57 e, depois,
retomar a Fase 56. Não avançar para a seção “após os Prompts Masters” antes de encerrar os dois.

## 0.1 Checkpoint anterior — Fase 58 concluída e publicada

**Branch:** `main`. **TDD:** `2f284ba` registra os contratos RED e `c704553` entrega o GREEN.
Ambos foram enviados para `origin/main` e `private/main`.

**Entregue:** estados compartilhados de erro, vazio e carregamento; mensagens públicas sem detalhes
internos; classificação de status sem falso positivo; 25 tabelas com captions contextuais únicos;
feedback de botões/formulários; contraste e responsividade; anúncios assistivos focados; e CSP por
nonce compatível com Next.js 16, sem liberar `unsafe-inline`/`unsafe-eval` em produção. O hash de
estilo autoriza somente `color:transparent`, valor fixo emitido pelo `next/image`.

**Gates locais:** 91 testes em 20 arquivos, lint, typecheck, build, `npm audit --omit=dev` com zero
vulnerabilidades, 8 E2E aprovados e 1 cenário visual Firefox intencionalmente ignorado. Login,
recrutamento e acesso negado foram capturados em 1440 e 390 px; as seis medições deram
`scrollWidth - clientWidth = 0`. QA visual e revisão de código independentes passaram; os três
achados do reviewer foram corrigidos e revalidados.

**Produção técnica:** deploy Vercel `dpl_DPCNG8jUHVzxVzFjncvqzF5CK9Js`, `READY` em 2026-08-27,
com aliases `choquebgr.online`, `www.choquebgr.online` e `web-plum-tau-82.vercel.app`. `/login` e
`/status` responderam 200; o header CSP contém nonce, `strict-dynamic` e o hash estreito, sem
`unsafe-inline`/`unsafe-eval`. O gate visual 1440/390 passou novamente no domínio público e não
foram encontrados logs de erro no deploy. Isso é smoke técnico; login humano real e uso assistivo
com leitor de tela continuam validações externas distintas.

**Próxima ação exata:** voltar aos Prompts Masters ainda ativos, começando pelo próximo corte
incompleto da Fase 57 e depois da Fase 56. Não avançar para a seção “após os Prompts Masters” antes
de encerrar esses dois prompts. O limite incompleto da fonte da Fase 58 após `Status com:` permanece
registrado e não pode ser inventado.

## 0.2 Checkpoint anterior — aviso privado da Central de Tags

O proprietário pediu que todos os membros CHOQUE já aprovados no cadastro recebam o mesmo aviso
privado da Central de Tags, em fila lenta. Antes da fila geral, o Discord ID
`395061579101503491` precisa receber uma prévia exatamente igual e o proprietário precisa liberar a
continuação.

**Concluído localmente:** migration 54; fila durável e idempotente por campanha; seleção de membros
`ACTIVE`, `AWAY`, `RESERVE` e `SUSPENDED`; exclusão de candidatos `PENDING` e desligados
`DISMISSED`; envio de no máximo uma DM a cada cinco segundos; retry exponencial de falhas
transitórias; bloqueio terminal para DM proibida ou membro ausente; recuperação de claim após
reinício; auditoria; link para o painel oficial; e ausência de menções coletivas. O aviso não cria
solicitação de tag nem concede cargo.

**Trava de segurança:** `tag_outreach_preview_discord_id=395061579101503491` e
`tag_outreach_rollout_approved=false`. A fila geral não é sequer criada antes de a prévia ficar
marcada como entregue e a segunda trava receber aprovação explícita. Prévia e lote usam o mesmo
conteúdo, embed, rodapé e botão.

**Validação concluída:** 595 testes Python verdes, 1 pulado e avisos de depreciação conhecidos;
Ruff, compileall, `main.py --check` com migration 54, scanner de segredos e `git diff --check`
verdes. A suíte foi executada integralmente em cinco blocos temporários no disco D devido ao espaço
insuficiente no disco C.

**Estado externo:** os blocos ADV, Cursos, Transferências, Registro de Desligamentos, controle de
`AGUARDANDO SET` e aviso privado foram publicados no app único `choque-bgr-api` em 2026-08-26
19:49 -03:00. O runtime aplicou migrations 49–54, terminou `CHECK_OK`, respondeu health 200 e
conectou um Gateway; o standalone `1787438463932` permanece Offline. O banco pós-corte passou
`quick_check=ok` e FK=0, preservando 171 membros e 22 solicitações de tag abertas.

A prévia `1542302969305890930` foi reconhecida sem duplicação e consta `DELIVERED`. A tabela possui
somente essa linha; `tag_outreach_rollout_approved` não tem override e continua no padrão `false`,
portanto nenhum outro membro recebeu o aviso. O backup frio v48 e o backup pós-v54 estão preservados
em `artifacts/pre-tags-v54-production-cold-20260826T1951` e
`artifacts/post-tags-v54-production-20260826T1953`.

**Alerta operacional separado:** o startup registrou falha no provisionamento automático de
Unidades Especiais porque o cargo `COMANDO • ROCAM` possui permissões globais indevidas. O arquivo
responsável é byte a byte igual ao anterior ao deploy; o app, API, Gateway e demais módulos seguem
online. Não alterar permissões do cargo sem autorização específica.

## 0.3 Checkpoint anterior — Controle de Tags

Esta seção supersede temporariamente a missão e a próxima ação antigas abaixo. O proprietário pediu
pausa imediata para trocar de computador; por isso o corte foi fechado em commits locais, sem push,
merge, deploy ou Discord real.

**Branch:** `codex/phase-b-transfers`

**Commits do corte e da auditoria:**

- `8757005` — `test: define waiting-role tag control` (contratos RED);
- `c29a726` — `feat: automate waiting-role tag control` (implementação GREEN);
- `2a6db1d` — `fix: reconcile externally assigned tag role` (convergência auditada).

**Concluído localmente:** migration 53; detecção periódica e por `on_member_update` do cargo
configurado `AGUARDANDO SET`; DM persistente e idempotente com respostas positiva/negativa;
encaminhamento à ficha única da Central; fallback para contato manual quando a DM é proibida;
assunção concorrente; aviso durável do responsável; finalização direta pelo responsável; cargos por
outbox; auditoria; arquivamento ao sair do servidor; e entrada `🏷️ Tags` na Central Administrativa.
O caso de `TAG SETADA` adicionada fora do fluxo agora conclui primeiro o agregado durável, registra
ator nulo/auditoria/outbox versionada e só então remove `AGUARDANDO SET`. A lista acionável continua
sem quem ainda não respondeu à DM; a visão `Todos` já inclui essas solicitações.

**Validação concluída:** 586 testes Python verdes, 1 pulado e 21 avisos conhecidos; Ruff do recorte,
compileall, `main.py --check` com migration 53, scanner de segredos, `git diff --check` e revisão
independente verdes. A primeira tentativa completa ficou sem espaço temporário; o lixo exclusivo do
pytest foi removido e a repetição com `--basetemp` dedicado passou integralmente.

**Próxima ação exata:** o corte de Tags está fechado localmente. Não tocar produção. O rollout
continua dependendo de auditoria na máquina principal, backup e migration em cópia, smoke humano e
nova autorização explícita. Até isso acontecer, a tarefa `AGORA` abaixo permanece válida.

## Handoff

**Última atualização:** 2026-08-26 19:53 -03:00

**Branch atual:** `codex/phase-b-transfers`

**Último commit funcional:**
`2a6db1d` — `fix: reconcile externally assigned tag role`

**Commit do protocolo:** este arquivo pertence ao commit de documentação imediatamente posterior;
confirmar seu hash com `git log -1 --oneline` em vez de manter uma autorreferência impossível.

**Estado esperado do repositório:** limpo após o commit deste checkpoint, sem push, merge ou deploy.

## 1. Missão atual

### Objetivo imediato

Na máquina principal, auditar os blocos locais ADV, Cursos, Transferências e Registro de
Desligamentos contra o checkout que opera o projeto, validar migrations 49–52 numa cópia do banco e
preparar um rollout controlado. As implementações locais estão concluídas. Enquanto essa etapa externa permanece
bloqueada, a Fase 57 pode avançar localmente em cortes pequenos e fecháveis; vinte e quatro cortes do Centro
de Comando estão concluídos e não há código parcial neste computador.

### Critério de conclusão

- [ ] O checkout da máquina principal contém exatamente os commits locais esperados.
- [ ] O teto de patente de transferência foi confirmado explicitamente para cada guild aplicável.
- [ ] Backup íntegro foi criado e validado com `quick_check` e foreign keys antes da migration.
- [ ] Migrations 49–52 e gates completos passaram primeiro numa cópia do banco.
- [ ] Smoke humano validou protocolo, duas decisões, outbox, recuperação e rollback.
- [ ] O proprietário concedeu nova autorização explícita antes de merge, push ou deploy.

## 2. Ponto exato de continuação

### Última ação concluída

O protocolo de continuidade foi instalado na raiz. Depois, a Fase 57 avançou em vinte e quatro cortes do
Centro de Comando: `2ca8770`/`20d4153` entregam o drawer móvel acessível;
`5e36506`/`098fea0` fazem o cabeçalho usar o `generated_at` real da API em um elemento `<time>`, em
vez do relógio do render; `093a1cf`/`d0eecb6` expõem todas as faixas de métricas como pares
semânticos `<dt>/<dd>`, preservando visual e conteúdo; `03b2bd6`/`ff86f4e` tornam a fila FIFO uma
lista ordenada acessível; `b52379c`/`d0681c6` expõem as pendências administrativas recentes como
lista semântica nomeada; `6de2297`/`b3db98c` fazem o mesmo com o briefing de mudanças dos últimos
sete dias; `c38d050`/`2fab9ce` expõem as patrulhas ativas como lista nomeada, preservando cada registro
como `<article>`; `d6fd37c`/`93bc047` substituem o padrão incompleto `listbox/option` da caixa
administrativa por lista nativa com botões de seleção e estado atual explícito; `2d1f744`/`e351128`
ligam esses botões ao painel de decisão nomeado com IDs únicos por instância; `94b53ca`/`39e5a7c`
adicionam ISO legível por máquina somente aos horários administrativos válidos; `0a45900`/`f13d2b0`
formatam também os campos detalhados `_at`/`_time` em `<time dateTime>` e eliminam o timestamp bruto;
`c5f7e2c`/`88dde3a` aplicam o mesmo contrato temporal às pendências recentes do dashboard e extraem
o formatador ISO seguro compartilhado; `9baa176`/`78c63d4` tornam a duração de patrulha legível por
máquina; `e6b26ae`/`2216250` fazem o mesmo com a espera da fila FIFO; e `d4829d9`/`4b08fb1`
expõem a coleção ativa da Central de Patrulhas como lista nomeada; e `2a227e6`/`b5f45bc` tornam a
duração das fichas legível por máquina; `4a42580`/`74bf8c7` fazem o mesmo com o instante “desde”; e
`c8ebb65`/`5703f8b` cobrem a coluna `ENTRADA` da fila FIFO; `85dd140`/`07880c4` marcam o início do
briefing de mudanças; `425a69f`/`8200b63` fazem o mesmo com a data de cada evento;
`c15202b`/`e019266` cobrem o início de manutenção; e `34843f8`/`756371d` cobrem o último sync do
perfil; e `32b4bbf`/`a7314c6` cobrem o início do lockdown e as datas dos eventos de segurança. Nenhum
contrato, URL, RBAC, API ou regra de negócio foi alterado.

Em seguida, o Registro de Desligamento de Efetivo foi concluído localmente. `25c593c` e `8d7a323`
preservam os contratos RED; `1526e03` entrega migration 52, política fechada pelo perfil
`ALTO_COMANDO`, quatro origens transacionais, outbox durável, embed formal e canal privado
declarativo. Nenhum Discord real ou produção foi tocado.

### Ação em andamento

Nenhuma alteração está em andamento. Transferências, os vinte e quatro cortes acessíveis da Fase 57 e o
Registro de Desligamentos terminaram em pontos seguros e commitados.

### PRÓXIMA AÇÃO EXATA

Na máquina principal, abrir o checkout oficial e executar primeiro, sem iniciar o bot nem carregar
segredos:

```powershell
git branch --show-current
git status --short
git log -1 --oneline
git log --oneline main..codex/phase-b-transfers
```

Comparar a lista obtida com os commits locais registrados abaixo e confirmar que não
há mudanças locais desconhecidas. Em seguida, reler somente:

- `choque/database.py`, migrations 49–52;
- `choque/tickets.py` e `choque/members.py`, fluxo de Transferências;
- `cogs/ticket_commands.py`, alcançabilidade visual;
- `tests/test_transfer_lifecycle.py`;
- `docs/testing/phase-b-transfers-tdd.md`;
- `choque/dismissals.py`, `choque/personnel.py`, `choque/requests.py` e `choque/activity.py`;
- `cogs/career_commands.py`, `scripts/remodel_discord_layout.py` e
  `tests/test_dismissal_notifications.py`;
- `docs/DISMISSAL_RECORDS_SPEC.md`;
- runbooks de backup/deploy pertinentes.

Não ler nem imprimir valores de ambiente durante essa auditoria. Antes de qualquer mutação, parar e
identificar o escritor único, gerar backup verificável e testar a migration numa cópia. Produção só
pode ser alterada depois dos gates e de nova autorização explícita do proprietário.

### Resultado esperado

Um relatório curto de compatibilidade entre esta branch e a máquina principal, com diferenças,
backup/migration em cópia, gates e smoke. Se tudo estiver verde, pedir autorização para o rollout;
se houver divergência, corrigir localmente e atualizar este handoff sem forçar o código a coincidir
com documentação antiga.

## 3. Estado dos arquivos

### Criados neste checkpoint

- `BOOTSTRAP_PROMPT.md`: protocolo permanente de inicialização e migração de sessão.
- `PROJECT_STATE.md`: estado estrutural consolidado.
- `SESSION_HANDOFF.md`: checkpoint operacional atual.
- `choque/dismissals.py`: política e persistência do boletim público.
- `docs/DISMISSAL_RECORDS_SPEC.md` e `docs/source-prompts/17-dismissal-records-original.md`.

### Modificado neste checkpoint

- `README.md`: a seção de continuidade agora aponta primeiro para o novo protocolo e mantém
  `PROJECT_HANDOFF.md` explicitamente como registro histórico.

### Código funcional alterado neste checkpoint

Migration 52, política de motivo, quatro integrações transacionais, entrega do embed, configuração do
canal privado e auditoria de exposição pública. Ver commits `25c593c`, `8d7a323` e `1526e03`.

### Arquivos que não devem ser alterados nesta etapa

- Qualquer `.env`, banco, backup ou log real.
- `C:\Users\mateu\OneDrive\Imagens\env` e todo o seu conteúdo.
- Configuração ou estado remoto de Discord, Railway, Vercel e Discloud.
- Mudanças não relacionadas que já existam no checkout da máquina principal.

## 4. Alterações não finalizadas

Não existe implementação parcial na branch. O canal de desligamentos existe somente no layout
declarativo; sua criação real é parte do rollout controlado. O trabalho pendente depende da máquina
principal: validar o delta contra o banco/runtime oficial e, depois de autorização, publicar.

## 5. Decisões que afetam a continuação

### S001 — Protocolo permanente

Novas sessões leem `PROJECT_STATE.md` e `SESSION_HANDOFF.md`, validam Git e continuam da próxima ação
exata. `PROJECT_HANDOFF.md` permanece como registro histórico, não como primeiro arquivo de leitura.

### S002 — Sem produção neste computador

Este computador é apenas para desenvolvimento e validação local. Não usar Discord real, banco
remoto, Vercel, Railway/Discloud, push ou deploy aqui.

### S003 — Transferência exige duas decisões humanas

Aprovar o ticket cria uma ficha pendente; somente a análise cadastral posterior aplica exatamente a
patente autorizada e enfileira `MEMBER_SYNC`. Não reativar/criar vínculo na primeira decisão.

### S004 — Teto por guild e legado conservador

`transfer_max_rank_level` tem padrão 3, mas deve ser confirmado na máquina principal. Casos legados
aprovados são `LEGACY_APPROVED` e não recebem patente inferida ou retroativa.

### S005 — Motivo público de desligamento não é entrada humana

Texto livre permanece privado na auditoria/decisão. O boletim usa somente as duas frases fixas,
selecionadas pelo snapshot canônico `ALTO_COMANDO`; não adicionar seletor ou campo de motivo público.

## 6. Bugs e problemas abertos

- Nenhum bug funcional conhecido no corte de Transferências após os gates finais.
- Há 21 avisos conhecidos de depreciação de `label` no `discord.py`; não falham a suíte atual.
- O gate público de segurança continua `FAIL` pelas pendências externas descritas em `SECURITY.md`.
- Estado ao vivo de produção não foi consultado nesta sessão e não deve ser presumido.

## 7. Testes

### Gate funcional do Registro de Desligamentos

- 7 testes focados do novo módulo passaram.
- 575 testes Python passaram; 21 avisos conhecidos de depreciação, sem falha.
- Ruff, compileall, `python main.py --check` e `git diff --check` passaram.
- `main.py --check` confirmou migration 52, 20 cogs, 46 comandos internos e 34 views persistentes.

Esses resultados pertencem ao checkpoint local anterior; devem ser repetidos na máquina principal
antes de qualquer rollout.

### Gate atual da Fase 57

- 1 teste focado da Central de Patrulhas passou.
- 92 testes Web passaram em 21 arquivos.
- Typecheck, ESLint e build Next.js passaram.
- `npm audit` encontrou 0 vulnerabilidades.
- 8 E2E passaram; 1 cenário visual Firefox foi intencionalmente ignorado.
- `git diff --check` passou antes dos commits.

### Validação deste checkpoint documental

- Confirmar que os três arquivos existem na raiz e não contêm placeholders de template.
- Executar `git diff --check`.
- Confirmar `git status` limpo após o commit.

## 8. Comandos úteis

### Check local sem Discord

```powershell
.\.venv\Scripts\python.exe main.py --check
```

### Gates Python

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q choque cogs main.py
```

### Gates Web

```powershell
Set-Location web
npm audit
npm run typecheck
npm run lint
npm test
npm run build
```

## 9. Fila de execução

### AGORA — auditoria na máquina principal

- [ ] Validar branch, commits, banco em cópia, teto de patente, gates e smoke das migrations 49–52,
  sem mutar produção.

### DEPOIS

- [ ] Com gates verdes e autorização nova, executar merge/push/deploy controlado, validar health,
  migration, Gateway único, duas decisões, outbox e rollback.
- [x] Fase 57 no dashboard: duração de patrulha publicada em `<time dateTime="PT…">`, preservando
  texto, cálculo, efetivo, ordem e dados. TDD `9baa176`/`78c63d4`; 82 testes web, lint, typecheck e
  build verdes; deploy `dpl_eZ6MKwqMesq5YDYQbK743DbC7iys` `READY` em 2026-08-27.
- [x] Fase 57 no dashboard: espera da fila FIFO publicada em `<time dateTime="PT…">`, preservando
  texto, cálculo e ordenação. TDD `e6b26ae`/`2216250`; 91 testes web e gates completos verdes;
  deploy `dpl_8ZDW7nFBeN8FAXcWVpDjnPhpRMtW` `READY` em 2026-08-27.
- [x] Fase 57 na Central de Patrulhas: coleção ativa publicada como lista nomeada, preservando cada
  cartão `<article>`. TDD `d4829d9`/`4b08fb1`; 92 testes web e gates completos verdes; deploy
  `dpl_5LmpUcqayK3kNBg9VePNNRE5nVZt` `READY` em 2026-08-27.
- [x] Fase 57 na Central de Patrulhas: duração operacional publicada em `<time dateTime="PT…">`.
  TDD `2a227e6`/`b5f45bc`; 92 testes web e gates completos verdes; deploy
  `dpl_HjGzeCa13MLxChutQDKMVHSTnnF5` `READY` em 2026-08-27.
- [x] Fase 57 na Central de Patrulhas: instante “desde” e entrada FIFO publicados em `<time
  dateTime>`. TDD `4a42580`/`74bf8c7` e `c8ebb65`/`5703f8b`; 93 testes web e gates completos
  verdes; deploy agrupado `dpl_HqFuYxqJM1LeocWRFDtDfR5rr68s` `READY` em 2026-08-27.
- [x] Fase 57 na Linha de mudanças: início do briefing e data dos eventos publicados em `<time
  dateTime>`. TDD `85dd140`/`07880c4` e `425a69f`/`8200b63`; 95 testes web e gates completos verdes;
  deploy agrupado `dpl_8DtbyzAS5p83KmJSwPWwMV24dtF4` `READY` em 2026-08-27.
- [x] Fase 57 em manutenção e perfil: `Desde` e `Último sync` publicados em `<time dateTime>`. TDD
  `c15202b`/`e019266` e `34843f8`/`756371d`; 97 testes web e gates completos verdes; deploy agrupado
  `dpl_Cmxd8P8muVj3Nc2U3CmnQsHHHwjC` `READY` em 2026-08-27.
- [x] Fase 57 em segurança: início do lockdown e datas dos eventos publicados em `<time dateTime>`.
  TDD `32b4bbf`/`a7314c6`; 99 testes web e gates completos verdes; deploy
  `dpl_BkSZCWmRcqrW4xvgVgea9vaqqgZW` `READY` em 2026-08-27.
- [x] Fase 58 consolidada e publicada em `2f284ba`/`c704553`, sem inventar o trecho ausente do
  prompt original; deploy `dpl_DPCNG8jUHVzxVzFjncvqzF5CK9Js` `READY`.
- [ ] Continuar os blocos restantes do Prompt Master do ecossistema pela ordem da fila oficial.

### BACKLOG

- [ ] Migração única para PostgreSQL/Supabase após ensaio e autorização.
- [ ] Empacotamento/publicação definitiva na Discloud por último.
- [ ] Integração MTA futura.

## 10. Bloqueios

### Máquina e autorização

O próximo passo exige a máquina principal e acesso controlado ao checkout/banco oficial. Esta sessão
não possui autorização para tocar produção. Trocar de máquina não autoriza deploy automaticamente;
o rollout depende de gates verdes e de um novo “pode publicar” explícito.

## 11. Contexto temporário essencial

- `main` e `origin/main` apontavam para `152a397` nesta inicialização.
- A branch de Transferências tinha 13 commits acima de `main` antes do commit documental:
  `8c20229`, `422e213`, `b989588`, `d18e739`, `06ae652`, `7e498b4`, `63da5fa`, `9b654d9`,
  `9a71063`, `0c3a989`, `305888c`, `fab9bbb`, `447ce5e`.
- A branch estava limpa antes da criação destes três documentos.
- Nenhuma variável local foi lida, impressa ou copiada.
- O protocolo e os cortes da Fase 57 acrescentaram `4a5faba`, `2ca8770`, `20d4153`, `5e36506`,
  `098fea0`, `093a1cf` e `d0eecb6`; confirmar o hash do commit documental final com
  `git log -1 --oneline`. O corte FIFO acrescentou `03b2bd6` e `ff86f4e`.
- Um cache antigo de build foi movido para `web/.next-stale-20260826-1542`. A exclusão autorizada
  removeu seu conteúdo comum, mas o Windows/OneDrive reteve cinco diretórios vazios/reparse por ACL;
  eles não aparecem no Git e não afetam build. Não alterar ACL do workspace para removê-los.
- O Registro de Desligamentos acrescentou `25c593c`, `8d7a323` e `1526e03`. O canal ainda não existe
  no Discord real; criar somente no rollout autorizado da máquina principal.

## 12. Não fazer

- Não recomeçar Transferências nem criar outro sistema de tickets/cadastro.
- Não aplicar migrations, inclusive a 52, diretamente no banco oficial antes do teste em cópia e
  backup íntegro.
- Não iniciar uma segunda instância do bot contra o mesmo SQLite.
- Não inferir patente por cargo Discord, nome ou dado legado.
- Não avançar para produção por considerar “deploy” implícito na troca de máquina.
- Não reler o histórico inteiro se estes arquivos e os trechos indicados forem suficientes.

## 13. Verificação de continuidade

Ao assumir:

- [ ] ler `PROJECT_STATE.md` e este arquivo;
- [ ] conferir branch, `git status` e último commit;
- [ ] confirmar que os arquivos citados existem;
- [ ] comparar os 13 commits funcionais;
- [ ] manter a tarefa AGORA;
- [ ] executar a próxima ação exata.
