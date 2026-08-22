# ADR 008 — Limite de confiança do recrutamento

## Estado

Aceito em 2026-08-22 para a entrega local; rollout externo pendente de infraestrutura exclusiva.

## Decisão

O navegador nunca acessa o banco diretamente. O Next.js autentica a sessão Discord e funciona como
BFF; a API FastAPI revalida identidade, guild, propriedade da candidatura e RBAC em todas as ações.
SQLite continua sendo a única fonte de verdade enquanto bot e API operarem em uma única instância.

Quando houver projeto Supabase exclusivo da CHOQUE BGR, a migração será feita por corte único, nunca
por dual-write. Todas as tabelas de recrutamento terão RLS `FORCE` e `anon`/`authenticated` sem
privilégios. O baseline verificável está em `deploy/supabase/recruitment_rls.sql`. O papel técnico do
backend será criado no rollout com grants mínimos e não será exposto ao Vercel ou ao navegador.

## Consequências

- Candidato acessa somente a própria candidatura por endpoints explícitos.
- Banco de questões, integridade, notas e decisões ficam restritos à API administrativa.
- O rollout Supabase exige schema PostgreSQL completo, role de backend, teste negativo de RLS,
  restore ensaiado e desativação definitiva do SQLite no mesmo change window.
- Aplicar apenas o arquivo de RLS sem o schema e sem o papel técnico não constitui deploy.
