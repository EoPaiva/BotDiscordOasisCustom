# Fase 7 — Disciplina

## Interfaces

- `⚖️│disciplina`: painel persistente do membro com **Minha situação** e **Meu histórico**.
- Central Administrativa: **Registrar ocorrência**, **Aplicar advertência**, **Suspender membro**,
  **Consultar histórico**, **Ocorrências abertas** e **Gerenciar medidas**.
- Todas as respostas pessoais e administrativas são ephemeral.
- Nenhum comando é publicado no Discord.

## Ocorrências

Ocorrência é um registro de fato e não aplica punição automaticamente. Ela armazena membro,
descrição, evidência opcional, observação, responsável e data. Seus estados são:

- `OPEN`: aguardando decisão;
- `ARCHIVED`: encerrada sem advertência, preservando responsável, data e motivo;
- `CONVERTED_TO_WARNING`: vinculada de forma permanente à advertência criada.

A conversão e a criação da advertência acontecem na mesma transação.

## Advertências

O fluxo exige membro, tipo (`LEVE`, `MODERADA`, `GRAVE` ou `ADMINISTRATIVA`), motivo e confirmação
explícita. Evidência e observação são opcionais. Estados:

- `ACTIVE`: em vigor;
- `FULFILLED`: cumprida, com responsável, data e motivo;
- `REVOKED`: revogada, sem apagar o registro.

## Suspensões

O Comando informa membro, início, duração, motivo, observação e evidência opcional. A segunda etapa
mostra o resumo e exige confirmação. Suspensão iniciada no dia atual:

1. altera o membro para `SUSPENDED`;
2. fecha o ponto e o segmento aberto na mesma transação;
3. bloqueia novos pontos pela validação de elegibilidade existente;
4. sincroniza o cargo configurado `🔴 Suspenso`;
5. grava medida e auditoria.

Suspensão futura fica `SCHEDULED`. O job persistente ativa e encerra medidas por timestamps do banco,
portanto o agendamento sobrevive a restart. No encerramento, o status anterior elegível é restaurado,
o cargo é sincronizado e o membro é notificado. Updates condicionais e índice parcial impedem decisões
concorrentes ou duas suspensões abertas para o mesmo membro.

## Dados

Migration v5:

- recria `punishments` preservando todos os registros antigos e adiciona tipo de advertência,
  evidência, observação, agendamento e metadados de cumprimento;
- amplia os estados para `SCHEDULED`, `ACTIVE`, `FULFILLED`, `REVOKED` e `EXPIRED`;
- cria `disciplinary_occurrences` e índices de consulta/concorrência;
- cria `ux_open_suspension_per_member` para uma suspensão ativa ou agendada por membro/guild.

Segmentos de ponto e medidas disciplinares nunca são apagados ou reescritos para esconder o histórico.

## Validação

- 49 testes automatizados passando, incluindo ocorrência sem punição, arquivamento, conversão
  transacional, cumprimento append-only, suspensão imediata, encerramento do ponto, agendamento,
  recuperação pelo banco, expiração e corrida concorrente.
- `python main.py --check`: migration 5, 9 cogs e 8 views persistentes.
- `python -m scripts.validate_live_phase7`: canal, mensagem, botões, link, migration e zero comandos
  remotos confirmados pela API do Discord.
