# ADR 007 — Atualização do Centro de Comando

## Status

Aceito em 22/08/2026.

## Contexto

O Discord e a web alteram o mesmo domínio. A interface precisa apresentar mudanças recentes sem
abrir uma segunda fonte de verdade ou depender de acesso direto do navegador ao banco.

## Decisão

- A primeira entrega usa revalidação Server Component a cada 30 segundos, no retorno de foco e na
  reconexão de rede.
- Toda revalidação atravessa o BFF Next.js e a API FastAPI; a API reautentica membro e RBAC.
- Ações Discord continuam assíncronas pela `web_action_outbox`, com estado consultável por
  correlação.
- Supabase Realtime ou WebSocket será habilitado somente no corte PostgreSQL, emitindo invalidações
  por evento e nunca decisões de domínio ou dados administrativos diretamente ao navegador.

## Consequências

- Não existe infraestrutura realtime paralela antes do PostgreSQL ser a fonte única.
- A UI converge em até 30 segundos e imediatamente ao recuperar foco/conectividade.
- O mecanismo pode ser substituído por invalidação dirigida sem alterar páginas ou regras do core.
