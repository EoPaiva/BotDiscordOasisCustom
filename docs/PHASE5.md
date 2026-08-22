# Fase 5 — Central de Solicitações

## Interfaces

- Painel do membro: ausência, retorno antecipado, reserva, correção de horas, alteração de dados,
  desligamento e histórico pessoal.
- Painel do Comando: contador, fila unificada, detalhes, perfil, aprovação/negação e histórico.
- Todas as respostas pessoais e administrativas são ephemeral; a mensagem pública é persistente e
  restaurada no startup.

## Regras

- Somente membro cadastrado e autorizado pelo RBAC pode abrir solicitações.
- Existe no máximo uma solicitação pendente do mesmo tipo por membro.
- Toda decisão usa update condicional; análises concorrentes têm um único vencedor.
- Aprovação e auditoria são gravadas na mesma transação SQLite.
- Entrada na reserva e desligamento encerram ponto e segmento aberto na mesma transação.
- Correção de horas insere ajuste positivo ou negativo; segmentos nunca são reescritos.
- Desligamento preserva cadastro, histórico, sessões, punições e solicitações.
- Ausência guarda o status anterior para restaurar `RESERVE` corretamente.
- Retorno automático, suspensão e ausência são reavaliados por job idempotente após restart.

## Schema

- `administrative_requests`: tipo, payload JSON, estado, autor, decisão e data de aplicação.
- `absence_requests.observation`: informação complementar opcional.
- `absence_requests.previous_member_status`: status restaurado no retorno quando aplicável.
- Índice parcial `ux_pending_administrative_request` impede duplicidade pendente por tipo/membro.

## Tipos

- `EARLY_RETURN`
- `RESERVE_ENTRY`
- `RESERVE_EXIT`
- `HOURS_CORRECTION`
- `DATA_CHANGE`
- `DISMISSAL`

Ausência permanece em `absence_requests` por compatibilidade e aparece na mesma fila administrativa.

## Validação

- `python main.py --check`: migration v4 e sete cogs carregados.
- `python -m pytest -q`: 41 testes aprovados.
- `python -m scripts.validate_live_phase5`: mensagem, sete componentes, três cargos de status e
  ausência de comandos publicados confirmados pela API do Discord.
