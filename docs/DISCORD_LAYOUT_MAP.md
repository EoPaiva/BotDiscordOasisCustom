# Mapa interno do layout Discord v2

O registro autoritativo completo é `discord_layout_registry_v2`, persistido em `guild_settings`.
Ele contém os 19 identificadores de categoria e os 97 identificadores internos de canal associados
a IDs Discord. A definição idempotente está em `scripts/remodel_discord_layout.py`.

| Ordem | Identificador interno | Finalidade |
|---:|---|---|
| 01 | `reception` | entradas, saídas e convite |
| 02 | `ticket` | painel, fila privada e calls de atendimento |
| 03 | `superiors` | comunicação e QA do Comando |
| 04 | `admin` | Central Administrativa |
| 05 | `member` | serviços e consultas pessoais |
| 06 | `registration` | cadastro de membro |
| 07 | `info` | regras, doutrina e hierarquia |
| 08 | `community` | chats, mídia e sugestões |
| 09 | `point` | bate-ponto e efetivo em serviço |
| 10 | `events` | avisos e calls de eventos |
| 11 | `patrol` | disponibilidade e calls operacionais |
| 12 | `management` | configuração e diagnóstico do bot |
| 13 | `partnerships` | transferências, parceiros e termos |
| 14 | `recruitment` | candidatura, resultado e entrevista |
| 15 | `courses` | treinamentos, cursos e salas |
| 16 | `away` | call visual de ausente |
| 17 | `meeting` | reunião institucional |
| 18 | `audit` | auditoria do bot e moderação Discord |
| 99 | `archive` | histórico legado privado |

IDs funcionais continuam também registrados individualmente em `guild_settings`; mensagens fixas
continuam identificadas por `panel_type`, `channel_id` e `message_id` em `panels`. O nome estilizado
é somente apresentação e nunca participa da resolução entre módulos.
