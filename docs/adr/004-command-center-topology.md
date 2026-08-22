# ADR 004 — Topologia do Centro de Comando Web

## Status

Aceito em 22/08/2026.

## Contexto

O bot já concentra regras transacionais maduras em Python. O Centro de Comando precisa expor essas capacidades na web sem duplicar decisões de domínio no React, sem expor o banco ao navegador e sem manter duas fontes de verdade.

## Decisão

- `web/`: Next.js App Router, TypeScript estrito e Server Components, destinado ao Vercel.
- `command_center/`: API FastAPI, destinada ao Railway junto do bot/worker.
- Navegador conversa somente com o servidor Next.js. O BFF valida a sessão Discord e chama a API com identidade e segredo internos.
- A API revalida cadastro e RBAC no banco em toda requisição; menus ocultos e botões desabilitados nunca são tratados como autorização.
- Ações que dependem do Discord usam `web_action_outbox`. A alteração transacional e o pedido de sincronização são persistidos juntos; o bot aplica cargo/nickname e registra o resultado.
- SQLite permanece a única fonte de verdade no desenvolvimento e na instância atual. O corte para Supabase PostgreSQL será único, validado e reversível; não haverá dual-write.
- Supabase será o PostgreSQL principal após o ensaio de migração, backup, checksum, contagem e janela de corte. Vercel não recebe `DATABASE_URL` nem chave administrativa.

## Consequências

- A interface pode ser desenvolvida e testada contra dados reais locais sem inventar registros.
- Indisponibilidade do Discord fica explícita como sincronização pendente.
- A API precisa permanecer compatível com o núcleo Python e executar migrations antes de servir tráfego.
- Provisionamento e publicação exigem autorização/configuração externas; não serão feitos automaticamente durante a implementação local.

