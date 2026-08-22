# ADR 002 — SQLite transacional

## Status

Aceito em 2026-08-21.

## Contexto

A operação inicial terá uma única instância. O ponto precisa impedir sessões/segmentos duplicados e
gravar ação e auditoria atomicamente.

## Decisão

Usar uma conexão `aiosqlite` central com WAL, foreign keys, `busy_timeout`, lock assíncrono de
escrita e `BEGIN IMMEDIATE`. Migrations são versionadas e transacionais. Índices parciais garantem
um único ponto ativo por membro/guild e um único segmento aberto por sessão. Auditoria usa outbox
no mesmo commit da ação.

## Consequências

SQLite é suficiente e fácil de restaurar, desde que exista uma única instância. PostgreSQL será
reconsiderado se houver API externa concorrente ou múltiplas instâncias.
