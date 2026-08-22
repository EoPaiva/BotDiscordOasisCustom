# Threat model — CHOQUE BGR

Revisado em 2026-08-22. Método principal: STRIDE com foco em abuso de negócio e Discord.

## Ativos e fronteiras

Ativos críticos: token do bot, OAuth/client secrets, segredo HMAC interno, salt de auditoria, banco,
backups, cadastros, candidaturas, decisões, auditoria, cargos/canais e sessões. Fronteiras de confiança:
navegador/BFF, BFF/API, API/banco, worker/Discord, administrador/ações sensíveis e futuro provider de IA.

| Fronteira | Entrada não confiável | Autoridade |
|---|---|---|
| Discord -> bot | interactions, modais, eventos e estado de cargos | services de domínio e RBAC |
| Browser -> Next.js | cookies, parâmetros e formulários | Auth.js/BFF |
| Next.js -> FastAPI | HTTP interno assinado | middleware HMAC + anti-replay |
| FastAPI/worker -> SQLite | dados validados | transactions/migrations |
| Worker -> Discord | outbox e IDs persistidos | bot com menor privilégio |
| Core -> provider IA opcional | conteúdo minimizado e host configurado | adapter sem tools, default disabled |

## STRIDE e mitigação

| Classe | Cenário principal | Mitigações | Risco residual |
|---|---|---|---|
| Spoofing | falsificar Discord ID/guild ou BFF | OAuth `identify guilds`, cookie seguro, assinatura HMAC, nonce, TTL, revalidação DB | segredo comprometido exige rotação |
| Tampering | alterar body/ator, sessão, decisão ou tempo | hash do body, schema estrito, RBAC, transactions, optimistic locking, ajustes append-only | administrador legítimo malicioso |
| Repudiation | negar ação administrativa | correlation/request IDs, audit/security logs append-only, actor/reason/before/after | host controla o disco SQLite |
| Information disclosure | vazar token, PII, candidatura ou canal privado | BFF, redaction, no-store, CSP, acesso por ID/RBAC, respostas ephemeral | configuração externa incorreta |
| Denial of service | spam de botão/API, body grande, regex ou fila | rate/body/query limits, timeouts, idempotência, concurrency cap, retries finitos | DDoS volumétrico sem WAF |
| Elevation of privilege | autoaprovação, cargo divergente, IDOR/BOLA | deny-by-default, perfis, segregação, validação de objeto/guild, RankSync fail-closed | Discord Administrator ignora overwrites |

## Abusos específicos

- Duplo clique/eventos concorrentes: índices únicos, update condicional e locks por membro.
- Candidato injeta instrução para IA: provider sem tools, schema/evidência validados e decisão humana.
- Visitante enxerga canal interno: registry por ID, política default restritiva e auditoria de drift.
- Bot perde `Manage Roles`: dados permanecem, sync fica pendente e alerta é criado; não solicita
  Administrator.
- Crash durante ponto/patrulha/ticket: heartbeat, estados persistidos, outbox e reconciliação.
- Insider aprova o próprio pedido/candidatura/patente: bloqueio explícito e trilha de auditoria.

## Premissas e risco residual

SQLite pressupõe uma instância de escrita e volume privado. PostgreSQL só entra por migração única,
sem dual-write. A segurança real também depende de token rotacionado, MFA, domínio/TLS, proteção do
host, backups fora do host e permissões Discord auditadas. Esses controles externos permanecem no
gate e impedem o veredito PASS até serem comprovados.

