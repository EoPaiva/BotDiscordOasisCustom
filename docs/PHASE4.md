# Fase 4 — Gestão administrativa visual

## Interfaces

- Central privada: cadastros, promoções/rebaixamentos, punições, afastamentos, histórico e ranking.
- Afastamentos: solicitação, consulta e cancelamento de pedido pendente.
- Ranking: hoje, semana, mês e total.

Nenhum fluxo da Fase 4 exige comando. As mensagens são persistentes e restauradas no startup.

## Regras

- Promoção e rebaixamento avançam somente uma patente por decisão.
- Segmentos e histórico anteriores nunca são reescritos.
- Advertência não altera o status do membro.
- Suspensão muda o status para `SUSPENDED` e encerra o ponto.
- Desligamento muda o status para `DISMISSED`, encerra o ponto e remove cargos operacionais.
- Afastamento só muda o status após aprovação e ao atingir a data inicial.
- Decisões concorrentes usam updates condicionais e somente uma pode vencer.
- Sessões em revisão não entram no ranking.

## Schema

- `personnel_actions`: movimentações append-only de patente.
- `punishments`: advertências, suspensões e desligamentos com revogação/expiração.
- `absence_requests`: solicitação, aprovação, rejeição, cancelamento e encerramento.

Auditoria e alteração de estado são gravadas na mesma transação SQLite.
