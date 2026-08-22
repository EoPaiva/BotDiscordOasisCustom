# ADR 010 — Fronteiras de confiança e autenticação interna

Status: aceito em 2026-08-22.

## Contexto

O Centro de Comando separa navegador, BFF Next.js, API FastAPI, core/banco e worker Discord. Um
header secreto estático não prova usuário, integridade, atualidade ou unicidade da requisição.

## Decisão

- Discord OAuth prova identidade e participação na guild no login; o JWT guarda somente identidade,
  emissão e resultado minimizado, nunca o access token.
- O BFF assina cada request com HMAC-SHA256 sobre método, path/query, hash do body, guild, ator,
  correlação, timestamp, nonce, emissão de sessão e prova de guild.
- A API valida assinatura em tempo constante, TTL e nonce persistido único, revalida membro/status,
  RankSync e RBAC, e aplica step-up em mutações sensíveis.
- O segredo legado só existe em desenvolvimento quando explicitamente habilitado. Produção falha ao
  iniciar com segredo fraco, origem/host curinga, bootstrap/bypass ou secrets reutilizados.
- Lockdown, revogação e security events pertencem ao backend; a UI não é autoridade.

## Consequências

Há uma escrita de nonce por request, aceitável para a instância única SQLite e removida por retenção.
Escalar API/worker exige PostgreSQL compartilhado antes de múltiplas réplicas. Comprometimento do BFF
ainda exige rotação, mas replay e adulteração fora dele deixam de ser aceitos.
