# ADR 001 — Monólito modular

## Status

Aceito em 2026-08-21.

## Contexto

O bot opera em uma única guild e precisa compartilhar configuração, RBAC, auditoria e transações
entre comandos e eventos de voz. Separar serviços agora aumentaria a coordenação operacional sem
resolver uma necessidade presente.

## Decisão

Manter um único processo Python com módulos de domínio em `choque/`, adaptadores Discord em
`cogs/` e uma composição explícita em `ChoqueBot.setup_hook`. Cogs legados ficam fora da lista de
carregamento.

## Consequências

O deploy e as transações ficam simples, e regras podem ser testadas sem Discord. Uma futura API ou
múltiplas instâncias exigirão reavaliar fronteiras e banco.
