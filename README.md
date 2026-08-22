# CHOQUE - BGR • Sistema de Gestão

> Segurança: a implementação local possui hardening e testes, porém o gate público permanece
> **FAIL** até rotação do token Discord e validação da infraestrutura externa. Consulte
> `SECURITY.md` e `docs/SECURITY_CONTROL_MATRIX.md` antes de qualquer deploy.

Bot Discord em Python para cadastro do efetivo e bate-ponto por presença em calls autorizadas.
A operação no servidor é feita exclusivamente por mensagens fixas, botões, seletores e modais.

## Escopo desta entrega

- Cadastro pendente com aprovação ou negação, patente inicial, cargo, apelido e auditoria.
- RBAC central com os perfis `MEMBRO`, `GRADUADO`, `INSTRUTOR`, `COMANDO` e `ADMINISTRADOR`.
- Central administrativa visual para cadastros, solicitações, promoções, rebaixamentos, punições,
  históricos e ranking, sem exigir comandos para a operação.
- Central de Solicitações persistente para ausência/retorno, reserva, correção de horas, alteração
  cadastral e desligamento voluntário.
- Gestão de Carreira visual com escolha da patente, motivo, confirmação obrigatória, sincronização
  de cargo/apelido e histórico paginado.
- Gestão Disciplinar visual com ocorrências sem punição automática, advertências, suspensões
  agendáveis, confirmação humana e histórico imutável.
- Treinamentos visuais com criação, vagas, inscrições, presença, resultados, cursos e histórico.
- Atividade semanal com meta, isenções, snapshots append-only, monitoramento e relatórios visuais.
- Recrutamento público completo com Discord OAuth, formulário versionado, 24 questões balanceadas,
  autosave, timer server-side, integridade apenas evidencial e decisão final humana.
- Analista opcional de candidaturas, somente leitura, com rubrica/contexto versionados, evidências,
  histórico e decisão humana separada; permanece desativado até configuração explícita do provider.
- Transferência, denúncias e outros assuntos por painéis privados, com fila de análise e auditoria.
- Layout visual v2 com 19 categorias, nomes Mathematical Italic e registro interno por ID.
- Ponto por voz com estados `ACTIVE`, `GRACE`, `REVIEW_REQUIRED` e `CLOSED`.
- Segmentos por call, tolerância configurável, recuperação após restart e ajustes append-only.
- Painéis persistentes de ponto e cadastro, além de uma única mensagem de efetivo.
- Auditoria transacional com outbox, tentativa após commit e retry a cada minuto.
- SQLite em WAL, foreign keys, busy timeout, migrations versionadas e backup pré-migration.

Farm, Caixa, Resgate, RH e Ausência antigos estão em [`legacy/`](legacy/README.md) e não são
carregados. O Centro de Comando Web está em [`web/`](web/README.md) e sua API FastAPI em
[`command_center/`](command_center/app.py). Integração MTA fica para entrega futura.

## Instalação

Requer Python 3.12.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Configure o `.env` local:

```dotenv
DISCORD_TOKEN=token_regenerado_no_portal
DATABASE_PATH=data/choque_bgr.db
DEFAULT_GUILD_ID=123456789012345678
LOG_LEVEL=INFO
BRANDING_LOGO_URL=
RECRUITMENT_AI_PROVIDER=disabled
RECRUITMENT_AI_API_KEY=
RECRUITMENT_AI_BASE_URL=
RECRUITMENT_AI_MODEL=
RECRUITMENT_AI_TIMEOUT_SECONDS=45
```

Nunca versione `.env`, bancos ou configurações reais. O token encontrado no histórico antigo deve
ser considerado comprometido e revogado no Portal de Desenvolvedores do Discord.

## Validação e execução

Valide migrations, configuração, cogs, comandos e views sem conectar ao Discord:

```powershell
python main.py --check
```

Execute os controles locais:

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest -q
python -m compileall -q choque cogs main.py
```

Inicie o bot:

```powershell
python main.py
```

Na primeira abertura, se `data/choque_bgr.db` ainda não existir e houver
`oasis_custom_data.db`, o arquivo legado será copiado, o original ficará intacto e um backup
`*.migration-backup` será criado antes das migrations. Um `config.json` local válido é importado
uma única vez; depois, as configurações são mantidas no banco pelo painel administrativo.

## Interface no Discord

Nenhum slash command, prefix command ou comando de texto é publicado na guild. Os handlers legados
permanecem carregados internamente apenas durante a migração das últimas funções para componentes.

- `🏠・Central do membro`: navegação para os serviços disponíveis.
- `📝・Cadastro`: solicitação de ingresso por modal.
- `⏱️・Bate ponto`: início, encerramento, horas e histórico.
- `👥・Efetivo em serviço`: mensagem atualizada automaticamente.
- `📥・Solicitações`: ausência/retorno, reserva, correção de horas, dados e desligamento.
- `📈・Carreira`: ficha funcional, histórico e hierarquia.
- `⚖️・Disciplina`: situação pessoal e histórico disciplinar.
- `🎯・Treinamentos`: inscrições, treinamentos pessoais e cursos concluídos.
- `📊・Atividade semanal`: meta, quadro semanal e histórico pessoal.
- `📝・Recrutamento`: candidatura, requisitos e acompanhamento pessoal.
- `🎫・Atendimento`: candidatura, transferência, denúncia privada, outro assunto e histórico.
- `🏆・Ranking de horas`: ranking por período.
- `🛡️・Central administrativa`: gestão do efetivo por botões e seletores.
- `⚙️・Configurações do bot`: canais, calls, cargos, RBAC, patentes, regras e painéis.

Os nomes reais usam Mathematical Italic e um separador invisível centralizado; os exemplos acima
usam texto simples apenas para facilitar leitura e busca na documentação.

Respostas pessoais são ephemeral. O histórico do botão do painel usa páginas de dez sessões.

### Menu visual de configuração

O canal `⚙️│configurações-do-bot` contém uma central persistente com oito áreas:

- Vinte e um destinos operacionais de canal. O navegador mostra todos os canais de texto em páginas
  de 25, com categoria e busca por nome/ID.
- Calls autorizadas com adicionar/remover e navegador paginado de todas as calls do servidor.
- Cargos de membro, serviço, ausente, reserva e suspenso, além de vínculos RBAC com todos os cargos
  em páginas de 25 e busca por nome/ID.
- Patentes por formulários de criação, edição e desativação, incluindo importação
  idempotente dos cargos militares já existentes no Discord.
- Tolerância, meta semanal e timezone.
- Publicação guiada dos painéis de ponto, cadastro, efetivo, hierarquia, solicitações, carreira,
  disciplina, treinamentos, atividade semanal, ranking, recrutamento, atendimento e administração.
- Controle dos módulos principais, com estados ativos/desativados, persistência e auditoria.
- Status e progresso da configuração.

Somente owner, Administrator humano ou perfil RBAC autorizado pode operar esse painel. Todas as
alterações geram auditoria. O painel é restaurado no startup e reutiliza a mensagem armazenada.

### Gestão administrativa visual

A operação da Fase 4 é feita integralmente por mensagens com botões, seletores e formulários:

- `🛡️│central-administrativa`: canal privado com análise de cadastros, movimentação de patentes,
  punições, aprovação de solicitações, histórico e ranking.
- `📥│solicitações`: painel somente leitura com sete controles pessoais e respostas ephemeral.
- `🏆│ranking-de-horas`: painel somente leitura com ranking de hoje, semana, mês e total.

Promoções e rebaixamentos seguem a ordem das patentes no banco e sincronizam cargo e apelido.
Suspensão, desligamento e afastamento vigente encerram qualquer ponto ativo. Toda ação gera
histórico append-only e auditoria na mesma transação.

### Central de Solicitações — Fase 5

O membro pode solicitar ausência, retorno antecipado, entrada/saída da reserva, correção de uma
sessão, alteração de dados ou desligamento. O Comando recebe uma fila única com perfil, detalhes,
aprovação/negação e histórico. Correções de horas geram ajustes append-only; segmentos originais
nunca são alterados. Reserva e desligamento encerram o ponto ativo na mesma transação da decisão.

Os cargos `🟠 Ausente`, `🟡 Reserva` e `🔴 Suspenso` são sincronizados automaticamente. Retornos de
ausência e suspensão sobrevivem a restart pelo job idempotente de estados. Veja
[`docs/PHASE5.md`](docs/PHASE5.md).

### Gestão de Carreira — Fase 6

O Comando seleciona o membro e a patente de destino, informa o motivo e confirma em uma segunda
etapa. A decisão grava patente anterior/nova, responsável, motivo e auditoria na mesma transação.
Tempo na patente, horas do mês e advertências são apenas indicadores; nenhuma promoção é automática.
Veja [`docs/PHASE6.md`](docs/PHASE6.md).

### Gestão Disciplinar — Fase 7

Ocorrências podem ser registradas e arquivadas sem gerar punição. Advertências exigem tipo, motivo
e confirmação; podem ser cumpridas ou revogadas, mas nunca apagadas. Suspensões podem iniciar no dia
atual ou ficar agendadas, fecham o ponto ao entrar em vigor, bloqueiam novo serviço e sincronizam o
cargo de suspenso. Ativação, encerramento e restauração de status sobrevivem a restart.
Veja [`docs/PHASE7.md`](docs/PHASE7.md).

### Treinamentos e Cursos — Fase 8

Instrutores e Comando criam treinamentos por painel, selecionam o responsável, definem agenda,
vagas e qualificação e publicam uma mensagem atualizada após cada inscrição. Na finalização, cada
participante recebe presença e resultado; cursos aprovados ou reprovados permanecem no histórico
do membro. Veja [`docs/PHASE8.md`](docs/PHASE8.md).

### Atividade Semanal e Relatórios — Fase 9

O painel semanal mostra horas, meta, progresso e situação, com isenção por reserva ou afastamento.
Cada semana concluída gera snapshots append-only e idempotentes. A Central Administrativa oferece
monitoramento de inatividade e relatórios diário, semanal, mensal, por membro, pontos, ausências e
treinamentos. Nenhum indicador aplica punição ou desligamento automaticamente.
Veja [`docs/PHASE9.md`](docs/PHASE9.md).

### Configurações e Módulos — Fase 10

A Central de Configuração permite ativar ou desativar cadastros, ponto, solicitações, carreira,
disciplina, treinamentos, atividade e ranking. O bloqueio é aplicado no backend, não apaga dados e
mantém jobs de recuperação necessários para ações existentes. Veja
[`docs/PHASE10.md`](docs/PHASE10.md).

### Recrutamento e Atendimento — Fase 11

Candidaturas e transferências usam formulários privados, histórico pessoal e uma fila persistente
para recrutadores. Denúncias escolhem o membro por seletor e ficam restritas ao Comando. O botão
**Outro assunto** abre um atendimento privado com assunto, descrição e referência opcional. Aprovar uma
candidatura cria atomicamente a solicitação pendente no cadastro existente, preservando uma única
regra de ingresso. Veja [`docs/PHASE11.md`](docs/PHASE11.md).

### Remodelação Visual — Fase 12

A guild possui 19 categorias ordenadas e 97 canais mapeados por identificador interno. Canais
existentes mantiveram IDs, mensagens e permissões específicas; nomes visuais nunca são usados como
chaves do sistema. Veja [`docs/PHASE12.md`](docs/PHASE12.md) e o
[`mapa interno`](docs/DISCORD_LAYOUT_MAP.md).

### Manter o bot online localmente

Em Windows, os scripts abaixo evitam iniciar duas instâncias e mantêm o processo oculto:

O startup usa primeiro `.venv\Scripts\python.exe` quando o ambiente virtual existe e recorre ao
`python` do `PATH` somente como fallback.

```powershell
.\scripts\start_bot.ps1
.\scripts\status_bot.ps1
.\scripts\stop_bot.ps1
```

Logs locais ficam em `logs/bot.out.log` e `logs/bot.err.log`. Na operação definitiva, a Discloud
substitui esse processo local.

## Permissões do bot

Conceda somente: visualizar/enviar mensagens, embeds, histórico, anexos, gerenciar cargos e
gerenciar apelidos. O cargo do bot precisa ficar acima dos cargos que ele gerenciará. Não conceda
`Administrator` ao bot.

Usuários owner da guild ou com permissão Discord `Administrator` fazem o bootstrap controlado do
RBAC. Depois, vincule cargos aos perfis pelo botão **Cargos e RBAC** do painel de configuração.

## Provisionamento do servidor

O layout oficial pode ser auditado ou reaplicado de forma idempotente:

```powershell
python -m scripts.provision_discord_layout
python -m scripts.provision_discord_layout --apply
```

Sem `--apply`, o script apenas salva o inventário. Antes de toda execução, um snapshot de canais,
cargos e permissões é gravado em `data/server_layout_backups/`. Canais com histórico são movidos
para `99・ARQUIVO LEGADO`; somente canais confirmadamente vazios são excluídos.

O comando público usa o remodelador visual v2. A entrada explícita equivalente é
`python -m scripts.remodel_discord_layout --apply`.

## Operação e rollback

SQLite pressupõe uma única instância do bot. Não execute duas instâncias usando o mesmo arquivo.
No rollout oficial, use canais/calls/cargos isolados de QA, valide os dez cenários de ponto e só
então publique os painéis definitivos. Em caso de rollback, pare o bot, preserve o banco atual para
análise e restaure a cópia `choque_bgr.db.migration-backup`.

Decisões técnicas estão em [`docs/adr/`](docs/adr/) e o estado da entrega em
[`docs/IMPLEMENTATION_REPORT.md`](docs/IMPLEMENTATION_REPORT.md). Para continuidade, consulte o
[`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md), a [`fila oficial`](docs/PHASE_QUEUE.md) e o
[`registro de cobertura dos pedidos`](docs/REQUEST_LEDGER.md).
