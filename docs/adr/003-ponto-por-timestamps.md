# ADR 003 — Ponto por timestamps e segmentos

## Status

Aceito em 2026-08-21.

## Contexto

Contadores por segundo perdem precisão em restart e geram escrita excessiva. Trocas de call e
períodos fora de voz precisam ser excluídos do total.

## Decisão

Persistir timestamps UTC epoch em milissegundos. Cada período válido é um segmento
`started_at/ended_at`; o total é calculado por soma de segmentos mais ajustes append-only. Um
heartbeat global por minuto limita a incerteza de crash. Períodos ambíguos viram
`REVIEW_REQUIRED` e não contam até revisão.

## Consequências

Não há contadores em memória para reconstruir. Trocas autorizadas são contínuas no mesmo timestamp,
grace nunca contabiliza tempo fora da call e ajustes preservam os segmentos originais.
