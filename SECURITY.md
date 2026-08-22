# Segurança — CHOQUE BGR

Última revisão: 2026-08-22. Responsável técnico: mantenedor do repositório.

## Resultado da revisão

**FAIL — produção ativa somente por exceção expressa do proprietário.** O código possui defesa em
profundidade e HTTPS/serviços externos já estão operacionais, mas o gate não foi aprovado enquanto
permanecerem pendentes a rotação das credenciais expostas na conversa, MFA/branch protection,
monitoramento externo, DAST controlado e a validação final do menor privilégio no servidor.

Esse resultado não significa que a implementação local falhou. Significa que um sistema não deve ser
declarado pronto antes de comprovar também a camada operacional. A classificação individual está em
`docs/SECURITY_CONTROL_MATRIX.md`.

Em 2026-08-22, o proprietário autorizou de forma explícita e pontual ignorar o gate para o corte de
produção. A autorização não altera este veredito, não vale para futuros deploys e não transforma as
credenciais divulgadas em seguras. O runtime Railway e o frontend Vercel foram publicados sob risco
aceito, com backup e rollback preservados, sem registrar valores neste documento.

## Arquitetura de segurança

```text
Browser
  -> Auth.js + Discord OAuth (cookie HttpOnly/Secure/SameSite=Lax)
  -> BFF Next.js (prova de guild e assinatura HMAC por request)
  -> FastAPI (anti-replay, expiração, RBAC e validação server-side)
  -> core transacional
  -> SQLite WAL em instância única / futuro PostgreSQL por corte único
  -> outbox e worker Discord
```

O navegador nunca recebe o segredo interno, token do bot ou acesso ao banco. A assinatura interna
inclui método, path/query, hash do corpo, guild, ator, correlação, timestamp, nonce, emissão da sessão
e prova OAuth de guild. Nonces são persistidos e de uso único. Autorização é refeita no backend em
toda requisição; perfis privilegiados com patente divergente são bloqueados.

## Controles implementados

- migrations versionadas, transações, foreign keys, WAL, `busy_timeout`, constraints e outbox;
- RBAC deny-by-default e permissões granulares, incluindo segregação de autoaprovação;
- headers, CSP com nonce, CORS/origin/host allowlists, HSTS de produção e `no-store`;
- limite de corpo, paginação, timeout, rate limit por superfície e erros com correlation ID;
- security events append-only, dashboard, lockdown e revogação global/individual de sessões;
- auditoria periódica de permissões Discord, sem correção destrutiva automática;
- backup consistente com manifesto SHA-256, integrity/FK check, retenção e restore drill;
- secret scan, CodeQL, Dependabot, dependency audit, SBOM e gate CI;
- logs UTC com redaction de credenciais, cookies, URLs autenticadas e padrões de token.

## Política de segredos

Segredos existem somente em gerenciadores de ambiente, com valores distintos por serviço/ambiente.
`.env`, bancos, logs, backups e artefatos com dados são ignorados. Nunca use prefixos públicos no
frontend para segredos. O token Discord publicado anteriormente deve ser considerado comprometido e
regenerado no Developer Portal. O deploy excepcional de 2026-08-22 não remove essa obrigação;
depois da rotação, Railway e qualquer ambiente local autorizado devem ser atualizados de forma
coordenada, mantendo uma única sessão do bot.

## Relato de vulnerabilidade

Não abra issue pública com detalhes exploráveis. Envie ao proprietário do repositório privado:
componente, impacto, passos mínimos, evidência sanitizada e sugestão. Não inclua token, cookie, dump,
PII ou respostas de candidatura. O responsável classifica severidade e inicia o runbook em
`docs/INCIDENT_RESPONSE.md`.

## Documentação relacionada

- `docs/THREAT_MODEL.md`
- `docs/SECURITY_CONTROL_MATRIX.md`
- `docs/INCIDENT_RESPONSE.md`
- `docs/BACKUP_RESTORE_RUNBOOK.md`
- `docs/SECURITY_TEST_PLAN.md`
- `docs/adr/010-security-trust-boundaries.md`
