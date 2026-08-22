# ADR 005 — Discord OAuth e autorização web

## Status

Aceito em 22/08/2026.

## Contexto

O sistema deve usar “Entrar com Discord”, mas o Discord User ID autenticado não basta para autorizar dados administrativos sensíveis.

## Decisão

- Auth.js executa Discord OAuth no servidor Next.js, com sessão JWT cifrada e cookies seguros.
- O `discord_id` do provedor é a identidade externa canônica.
- O frontend envia à API somente chamadas servidor-servidor, usando `COMMAND_CENTER_INTERNAL_SECRET`, `discord_id`, `guild_id` e ID de correlação.
- A API carrega o membro e a patente atuais no banco e deriva permissões de `PROFILE_PERMISSIONS` a cada chamada.
- `WEB_ADMIN_DISCORD_IDS` é um bootstrap explícito e auditável, nunca um fallback automático.
- Usuário inexistente ou desligado recebe `403`; sessão válida não concede acesso por si só.
- IP e user-agent, quando auditados, são armazenados apenas como HMAC, nunca em texto puro.

## Consequências

- Alterações de cargo/patente refletidas no banco mudam o acesso sem depender de um token antigo.
- Segredos Discord, Auth.js, banco e API nunca entram no bundle do navegador.
- A implantação requer callback Discord configurado para `/api/auth/callback/discord`.

