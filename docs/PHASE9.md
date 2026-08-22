# Fase 9 — Atividade Semanal e Relatórios

## Interfaces

O canal `📊│atividade-semanal` possui um painel persistente, somente leitura, com:

- **Minha atividade**: horas, meta, progresso, situação e eventual isenção;
- **Quadro semanal**: efetivo paginado com situação e horas da semana;
- **Meu histórico**: snapshots das últimas semanas encerradas.

A Central Administrativa recebe **Atividade**, que abre:

- monitoramento de atividade normal, baixa e inexistente;
- relatórios diário, semanal, mensal, por membro, pontos, ausências e treinamentos;
- configuração de meta e faixas de atividade;
- fechamento manual idempotente de semanas pendentes.

Não existem comandos publicados. Respostas pessoais e administrativas são ephemeral.

## Regras

A meta padrão é de 360 minutos semanais. O quadro classifica o membro como `FULFILLED`, `NEAR`,
`NOT_MET` ou `EXEMPT`. O percentual de proximidade e os limites de dias sem atividade são
configuráveis no painel.

Membros em reserva ou afastados são isentos. Um afastamento aprovado que intersecte a semana
também gera isenção, mesmo que o pedido já tenha sido encerrado. Sessões em revisão continuam fora
dos totais, seguindo a regra do bate-ponto.

O monitor de inatividade é somente informativo: ele nunca cria ocorrência, advertência, suspensão
ou desligamento. Toda decisão disciplinar permanece humana e usa o módulo próprio.

## Fechamento semanal

Ao detectar uma nova semana, o job grava um snapshot por membro com período, horas, meta, situação,
motivo de isenção e status do membro. O registro possui unicidade por membro/semana, é append-only e
o fechamento pode ser repetido após restart sem duplicar snapshots ou auditoria.

## Schema e validação

Migration v7 cria `weekly_activity_snapshots` e índices por membro, período e situação.

- 60 testes passando;
- classificação, isenção, fechamento append-only, idempotência, restart, inatividade sem punição e
  regras auditadas cobertos;
- `python main.py --check`: migration 7, 11 cogs e 10 views persistentes;
- `python -m scripts.validate_live_phase9` valida painel, Central Administrativa, Central do Membro,
  migration e ausência de comandos remotos.
