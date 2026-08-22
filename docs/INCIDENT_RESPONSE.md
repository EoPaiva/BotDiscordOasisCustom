# Resposta a incidentes — CHOQUE BGR

## Severidade

- **SEV-1:** token/segredo/banco comprometido, acesso administrativo indevido, vazamento material.
- **SEV-2:** bypass de autorização, exposição limitada, alteração indevida recuperável.
- **SEV-3:** tentativa bloqueada, drift sem exploração, vulnerabilidade sem evidência de abuso.

## Fluxo comum

1. Registrar horário UTC, correlation IDs e evidência sanitizada; não copiar secrets para tickets.
2. Ativar `Security Lockdown` se novas mutações aumentarem o dano.
3. Revogar todas as sessões ou o usuário afetado pelo painel `/security`.
4. Conter credenciais/canal/serviço, preservar logs e criar backup consistente somente se o banco
   não estiver sob controle do atacante.
5. Determinar escopo, timeline, dados/ações afetados e necessidade de comunicação.
6. Corrigir, testar em ambiente isolado, restaurar/reconciliar e observar.
7. Encerrar lockdown somente após dupla verificação operacional e documentar postmortem sem culpa.

## Token do bot comprometido

1. Parar todas as instâncias e confirmar offline.
2. Regenerar o token no Discord Developer Portal; o valor antigo não é reutilizável.
3. Atualizar o secret manager de cada ambiente, nunca arquivo versionado.
4. Revisar audit log Discord: cargos, canais, webhooks, integrações e ações do bot.
5. Validar permissões mínimas/hierarquia, iniciar uma instância e reconciliar outbox/painéis.

## Segredo do banco ou acesso ao volume

1. Isolar API/worker e revogar a credencial/volume exposto.
2. Preservar snapshot forense e hashes; não sobrescrever a evidência.
3. Rotacionar credenciais e salts relacionados, revisar sessões e exportações.
4. Restaurar em destino limpo, executar integrity/FK/migrations e comparar contagens/checksums.
5. Reconciliar Discord e auditar ações administrativas no intervalo afetado.

## OAuth/Auth.js ou HMAC interno comprometido

1. Revogar todas as sessões e ativar lockdown.
2. Rotacionar OAuth client secret, `AUTH_SECRET` e segredo HMAC, todos distintos.
3. Remover callbacks desconhecidos e revisar origens/hosts/domínios.
4. Buscar replay, falhas de assinatura, ator/guild divergentes e elevação de privilégio.
5. Reimplantar BFF/API juntos; não habilitar autenticação legada em produção.

## Recuperação e postmortem

O critério de recuperação inclui health, login/logout, autorização MEMBRO/COMANDO/ADMIN, uma mutação
auditada, outbox sem poison job, bot único, DB íntegro e auditoria Discord sem finding crítico novo.
O postmortem registra impacto, causa raiz, detecção, contenção, correção, lacunas, responsáveis e
prazos. Nunca afirma “zero risco” ou remove evidência para melhorar métricas.

