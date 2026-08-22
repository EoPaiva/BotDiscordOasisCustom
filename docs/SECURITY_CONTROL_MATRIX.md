# Matriz dos 220 controles de segurança

Revisada em 2026-08-22. Classificações: **IMPLEMENTADO** possui evidência no repositório/testes; **NÃO APLICÁVEL** não integra a arquitetura atual; **PENDENTE** depende de trabalho externo, autorização ou prova ainda ausente.

Resumo: 164 implementados, 27 não aplicáveis e 29 pendentes. Veredito do gate: **FAIL — NÃO PRONTO PARA PRODUÇÃO PÚBLICA**.

| # | Controle | Estado | Evidência / justificativa |
|---:|---|---|---|
| 1 | Princípio fundamental / Zero Trust | **IMPLEMENTADO** | ADR 010; identidade, request e autorização são revalidados em cada fronteira. |
| 2 | Referências de segurança | **IMPLEMENTADO** | Threat model, ASVS L2 como alvo e práticas OWASP registradas nesta documentação. |
| 3 | Threat model | **IMPLEMENTADO** | docs/THREAT_MODEL.md cobre ativos, fronteiras, STRIDE, abuso e risco residual. |
| 4 | Superfície de ataque | **IMPLEMENTADO** | Inventário Browser, BFF, API, DB, Discord, CI e provider opcional no threat model. |
| 5 | HTTPS obrigatório | **PENDENTE** | Código preparado; exige domínio/deploy real e validação externa antes de produção. |
| 6 | TLS | **PENDENTE** | Terminação e versão TLS pertencem ao provedor ainda não publicado. |
| 7 | HSTS | **IMPLEMENTADO** | command_center/app.py e web/src/proxy.ts ativam HSTS somente em produção. |
| 8 | Security headers | **IMPLEMENTADO** | CSP, frame, MIME, referrer, permissions policy e no-store aplicados. |
| 9 | Content Security Policy | **IMPLEMENTADO** | CSP estrita com nonce por request; sem unsafe-inline/eval em produção. |
| 10 | CORS | **IMPLEMENTADO** | Origens, métodos e headers explícitos; sem wildcard em produção. |
| 11 | Autenticação via Discord | **IMPLEMENTADO** | Auth.js OAuth com scopes identify/guilds e sessão server-side. |
| 12 | Não confiar apenas no Discord ID | **IMPLEMENTADO** | Prova OAuth assinada, membro/status/RBAC revalidados no backend. |
| 13 | Sessões | **IMPLEMENTADO** | Cookie HttpOnly, Secure em produção, SameSite Lax, expiração e emissão registradas. |
| 14 | Não armazenar token em localStorage | **IMPLEMENTADO** | Access token só é usado no callback e não é exposto na sessão/browser. |
| 15 | Session fixation | **IMPLEMENTADO** | Auth.js emite sessão própria; assinatura inclui sessionIssuedAt. |
| 16 | Session expiration | **IMPLEMENTADO** | Sessão de oito horas e assinatura interna de 90 segundos configurável. |
| 17 | Step-up authentication | **IMPLEMENTADO** | Mutações sensíveis exigem sessão recente; padrão 30 minutos. |
| 18 | MFA para administradores | **PENDENTE** | Deve ser exigido nas contas Discord, GitHub e provedores externos. |
| 19 | RBAC backend | **IMPLEMENTADO** | PermissionService/backend autorizam todas as superfícies privilegiadas. |
| 20 | Deny by default | **IMPLEMENTADO** | Permissões desconhecidas e perfis sem vínculo são negados. |
| 21 | Permissões granulares | **IMPLEMENTADO** | Ações usam capacidades específicas; security.manage fica restrita. |
| 22 | Princípio do menor privilégio | **IMPLEMENTADO** | Bot/API não requerem Administrator; permissões são auditadas. |
| 23 | Revalidação de privilégio | **IMPLEMENTADO** | Status, perfil, guild e RankSync são consultados por request. |
| 24 | Supabase RLS | **NÃO APLICÁVEL** | Fonte atual é SQLite privada; Supabase ainda não foi provisionado. |
| 25 | RLS default deny | **NÃO APLICÁVEL** | Sem Data API/RLS no desenho atual. |
| 26 | Não confiar somente em RLS | **NÃO APLICÁVEL** | Backend já autoriza; RLS só será definido na migração PostgreSQL. |
| 27 | Service role | **NÃO APLICÁVEL** | Nenhuma chave service_role existe no app atual. |
| 28 | Credencial de menor privilégio | **IMPLEMENTADO** | Browser não possui credencial DB; segredos são separados por serviço. |
| 29 | Postgres SSL | **NÃO APLICÁVEL** | Banco atual é SQLite local; será requisito do corte PostgreSQL. |
| 30 | Network restrictions | **PENDENTE** | Requer configuração Railway/Supabase e topologia externa. |
| 31 | Data API | **NÃO APLICÁVEL** | Nenhuma Data API Supabase está habilitada. |
| 32 | Banco não acessível pelo frontend | **IMPLEMENTADO** | Somente API/core acessam DATABASE_PATH; frontend usa BFF. |
| 33 | SQL injection | **IMPLEMENTADO** | Queries parametrizadas e schemas server-side; testes negativos. |
| 34 | Dynamic SQL | **IMPLEMENTADO** | Valores não são concatenados; fragmentos internos são allowlisted. |
| 35 | Security definer | **NÃO APLICÁVEL** | Não há funções PostgreSQL. |
| 36 | Grants | **NÃO APLICÁVEL** | Não há roles/grants PostgreSQL no runtime atual. |
| 37 | Backups | **IMPLEMENTADO** | choque/backups.py cria backup SQLite consistente e manifesto verificável. |
| 38 | Testar restore | **IMPLEMENTADO** | scripts/restore_drill.py e teste automatizado conferem hash/integridade/FK. |
| 39 | Dados críticos | **IMPLEMENTADO** | Backup cobre DB integral; registry, auditoria e outbox permanecem consistentes. |
| 40 | Segredos | **IMPLEMENTADO** | Somente ambiente; validação de força/separação em produção. |
| 41 | .env | **IMPLEMENTADO** | .gitignore exclui .env; exemplos permanecem vazios. |
| 42 | Secret rotation | **PENDENTE** | Token Discord exposto deve ser regenerado antes do deploy. |
| 43 | Secret scanning | **IMPLEMENTADO** | scripts/security_scan.py no gate CI sem imprimir valores. |
| 44 | Frontend secrets | **IMPLEMENTADO** | Sem NEXT_PUBLIC/VITE secret; HMAC apenas no BFF. |
| 45 | Input validation | **IMPLEMENTADO** | Pydantic strict, Zod e limites de comprimento/enum. |
| 46 | Validar no backend | **IMPLEMENTADO** | Core e API não confiam em validação de UI. |
| 47 | Mass assignment | **IMPLEMENTADO** | StrictBody extra=forbid e corpos explícitos; teste dedicado. |
| 48 | XSS | **IMPLEMENTADO** | React escaping, sanitização de análise e CSP enforcement. |
| 49 | Markdown / texto formatado | **IMPLEMENTADO** | Conteúdo ativo é rejeitado/sanitizado e não usa HTML arbitrário. |
| 50 | CSRF | **IMPLEMENTADO** | SameSite, mutações server-side e verificação estrita de Origin. |
| 51 | SSRF | **NÃO APLICÁVEL** | Não há fetch de URL fornecida por usuário; provider é configuração administrativa. |
| 52 | Open redirect | **IMPLEMENTADO** | Callbacks Auth.js são configurados por AUTH_URL/origens explícitas. |
| 53 | Path traversal | **NÃO APLICÁVEL** | APIs não recebem caminhos de arquivo do usuário. |
| 54 | File upload | **NÃO APLICÁVEL** | Nenhum upload de arquivo é exposto nesta entrega. |
| 55 | Arquivos executáveis | **NÃO APLICÁVEL** | Sem upload/storage executável. |
| 56 | Storage | **NÃO APLICÁVEL** | Sem bucket/storage público. |
| 57 | Rate limit | **IMPLEMENTADO** | RateLimiter central por ator/IP hash e superfície. |
| 58 | Limites fortes em endpoints sensíveis | **IMPLEMENTADO** | Regras específicas precedem regras administrativas genéricas. |
| 59 | Brute force | **IMPLEMENTADO** | OAuth delegado e rate limit; não há senha local. |
| 60 | Enumeração | **IMPLEMENTADO** | Erros externos genéricos e BOLA/RBAC antes de dados. |
| 61 | WAF | **PENDENTE** | Proteção de borda deve ser configurada no provedor após deploy. |
| 62 | Cloudflare | **PENDENTE** | Opcional e não provisionado; decidir com domínio/topologia real. |
| 63 | DDoS | **PENDENTE** | Rate limit de app existe; mitigação volumétrica depende da borda. |
| 64 | API body limit | **IMPLEMENTADO** | Middleware limita 256 KiB inclusive transfer chunked. |
| 65 | Query limit | **IMPLEMENTADO** | Paginação limitada e busca com max_length. |
| 66 | Regex DoS | **IMPLEMENTADO** | Nenhuma regex controlada pelo usuário; scanner usa padrões estáticos. |
| 67 | Request timeout | **IMPLEMENTADO** | BFF 15 s, OAuth 8 s e provider configurado com timeout. |
| 68 | Webhooks | **NÃO APLICÁVEL** | Não há endpoint de webhook externo ativo. |
| 69 | Discord bot token | **IMPLEMENTADO** | Somente worker recebe token; API/BFF não o utilizam. |
| 70 | Separação de serviços | **IMPLEMENTADO** | Configs distintas para bot, API e frontend; core compartilhado. |
| 71 | Private networking | **PENDENTE** | Depende de Railway/Supabase no rollout externo. |
| 72 | API pública | **PENDENTE** | Autenticação está implementada; exposição/topologia ainda não validada ao vivo. |
| 73 | Health endpoint | **IMPLEMENTADO** | Retorna apenas status ok, sem versão/schema/segredos. |
| 74 | Error handling | **IMPLEMENTADO** | Handler global retorna erro genérico e correlation ID. |
| 75 | Não expor tecnologia | **IMPLEMENTADO** | Server header desativado e health minimizado. |
| 76 | Source maps | **IMPLEMENTADO** | Production browser source maps desativados. |
| 77 | Logging | **IMPLEMENTADO** | Logs estruturados UTC com correlação. |
| 78 | Não logar segredos | **IMPLEMENTADO** | Filtro redige auth, cookies, tokens, senhas, API keys e URLs. |
| 79 | PII | **IMPLEMENTADO** | IP/UA são HMAC; eventos e dashboards minimizam dados. |
| 80 | Audit log | **IMPLEMENTADO** | Ações de domínio gravam auditoria na mesma transaction. |
| 81 | Auditoria de segurança | **IMPLEMENTADO** | security_events tipados e append-only. |
| 82 | Request ID | **IMPLEMENTADO** | Request/correlation IDs propagados BFF/API e exibidos em erros. |
| 83 | Alertas | **IMPLEMENTADO** | Cog periódico entrega findings e falhas relevantes ao canal configurado. |
| 84 | Incident response mode | **IMPLEMENTADO** | Lockdown persistido bloqueia mutações administrativas. |
| 85 | Revogar todas as sessões | **IMPLEMENTADO** | Endpoint/painel com confirmação literal e auditoria. |
| 86 | Revogação por usuário | **IMPLEMENTADO** | Revogação individual persistida e validada por request. |
| 87 | CI/CD | **IMPLEMENTADO** | security-gate.yml executa o gate completo em PR/push. |
| 88 | SAST | **IMPLEMENTADO** | CodeQL Python/JavaScript security-extended e Ruff. |
| 89 | Dependency scanning | **IMPLEMENTADO** | pip-audit e npm audit; resultado local sem vulnerabilidades conhecidas. |
| 90 | Lockfile | **IMPLEMENTADO** | web/package-lock.json versionado; Python possui pins exatos. |
| 91 | Dependências | **IMPLEMENTADO** | FastAPI/Starlette/dotenv/discord.py atualizados e testados. |
| 92 | Supply chain | **IMPLEMENTADO** | Dependabot semanal e Actions fixadas por major atual. |
| 93 | SBOM | **IMPLEMENTADO** | scripts/generate_sbom.py gera SPDX 2.3 no CI. |
| 94 | Pinning | **IMPLEMENTADO** | Dependências de produção Python possuem versões exatas. |
| 95 | Runtime | **IMPLEMENTADO** | CI usa Python 3.13 e Node 24; Ruff garante compatibilidade 3.12+. |
| 96 | Container hardening | **NÃO APLICÁVEL** | Deploy atual não possui imagem/container customizado. |
| 97 | Imagem Docker | **NÃO APLICÁVEL** | Nenhum Dockerfile é usado. |
| 98 | Filesystem | **NÃO APLICÁVEL** | Sem container rootfs; volume de produção será tratado no provedor. |
| 99 | Environments | **IMPLEMENTADO** | APP_ENV e validações separam desenvolvimento/produção. |
| 100 | Banco separado | **PENDENTE** | Produção ainda não possui projeto/volume exclusivo provisionado. |
| 101 | Migrations | **IMPLEMENTADO** | Versionadas, transacionais e sem apagar legado. |
| 102 | Migration review | **IMPLEMENTADO** | Backups, check offline, testes em DB legado e versionamento. |
| 103 | Production deploy | **PENDENTE** | Autorizado como último item, depois das fases complementares. |
| 104 | Branch protection | **PENDENTE** | Repositório privado ainda será criado; proteção será aplicada quando disponível. |
| 105 | GitHub Security | **PENDENTE** | Workflows/Dependabot existem localmente; recursos do repo serão ativados após publicação. |
| 106 | Access control de infraestrutura | **PENDENTE** | Revisão de membros/equipes/MFA nos provedores exige rollout. |
| 107 | Não compartilhar credenciais | **PENDENTE** | Política documentada; token anteriormente compartilhado ainda exige rotação. |
| 108 | DNS | **PENDENTE** | Domínio e registros ainda não configurados. |
| 109 | CSP reporting | **PENDENTE** | CSP enforcement existe; endpoint/report-to externo não foi provisionado. |
| 110 | Clickjacking | **IMPLEMENTADO** | frame-ancestors none e X-Frame-Options DENY. |
| 111 | MIME sniffing | **IMPLEMENTADO** | X-Content-Type-Options nosniff. |
| 112 | Referrer | **IMPLEMENTADO** | Referrer-Policy no-referrer. |
| 113 | Permissions Policy | **IMPLEMENTADO** | Recursos desnecessários são negados. |
| 114 | Cache de dados sensíveis | **IMPLEMENTADO** | API e BFF usam Cache-Control no-store. |
| 115 | Service worker | **NÃO APLICÁVEL** | Não existe service worker/PWA. |
| 116 | Browser autocomplete | **NÃO APLICÁVEL** | Não há formulário de senha/segredo no navegador. |
| 117 | Idempotency | **IMPLEMENTADO** | Keys/constraints/update condicional em tickets, outbox, recrutamento e operações. |
| 118 | Optimistic locking | **IMPLEMENTADO** | Version em fluxos administrativos e decisões concorrentes. |
| 119 | Database transactions | **IMPLEMENTADO** | Mudança/auditoria/outbox atômicas. |
| 120 | Outbox pattern | **IMPLEMENTADO** | Entrega Discord e sincronizações usam outbox persistida. |
| 121 | Retry | **IMPLEMENTADO** | Retry com backoff/limites e estado de falha. |
| 122 | Circuit breaker | **IMPLEMENTADO** | Providers opcionais falham fechados, timeouts/retries finitos e IA default disabled. |
| 123 | Discord rate limit | **IMPLEMENTADO** | discord.py coordena limites; refresh é agregado e persistente. |
| 124 | Reconciliação | **IMPLEMENTADO** | Startup reconcilia ponto, tickets, ranks, painéis e jobs. |
| 125 | Bot permissions | **PENDENTE** | Auditor existe; resultado real deve confirmar ausência de Administrator após rollout v19. |
| 126 | Hierarquia de cargos | **PENDENTE** | Há ressalva externa: cargo do bot abaixo de Comandante Geral para nickname. |
| 127 | Auditoria de permissões Discord | **IMPLEMENTADO** | SecurityService audita permissões e canais a cada seis horas. |
| 128 | Rate limit do bot | **IMPLEMENTADO** | Ações são idempotentes/ephemeral e tarefas globais, sem contador por segundo. |
| 129 | Security events | **IMPLEMENTADO** | Tabela tipada com severidade, ator, correlação e payload minimizado. |
| 130 | Auditoria de configurações | **IMPLEMENTADO** | Settings/lockdown/revogação registram before/after e motivo. |
| 131 | Proteger auditoria | **IMPLEMENTADO** | Sem endpoint de edição/exclusão; retenção é ação controlada. |
| 132 | Dados de auditoria | **IMPLEMENTADO** | IDs/reason/contexto necessários, sem secrets. |
| 133 | Error IDs | **IMPLEMENTADO** | Erros 5xx retornam identificador correlacionável. |
| 134 | Security dashboard | **IMPLEMENTADO** | Página /security restrita a security.manage. |
| 135 | Security health | **IMPLEMENTADO** | Métricas 24h, jobs, backup e estado de lockdown. |
| 136 | Security configuration drift | **IMPLEMENTADO** | Snapshots hash evitam spam e detectam mudanças Discord. |
| 137 | Pre-deploy security gate | **IMPLEMENTADO** | Workflow bloqueante e checklist documentado. |
| 138 | DAST | **PENDENTE** | Exige staging publicado, escopo e autorização; plano documentado. |
| 139 | Penetration test | **PENDENTE** | Teste profissional/controlado ainda não executado. |
| 140 | Não fazer pentest de fachada | **IMPLEMENTADO** | Plano proíbe apresentar scanner como pentest. |
| 141 | Authorization tests | **IMPLEMENTADO** | Testes cobrem RBAC, sessão, origem, segregação e security.manage. |
| 142 | IDOR / BOLA | **IMPLEMENTADO** | Objetos filtram guild/ator e testes de candidatura/ticket/requests. |
| 143 | API mass assignment test | **IMPLEMENTADO** | Unknown fields retornam 422 no teste dedicado. |
| 144 | Database security tests | **IMPLEMENTADO** | Migrations, constraints, integrity, FK, backup e restore cobertos. |
| 145 | Negative testing | **IMPLEMENTADO** | Replay, tamper, origem, body, concorrência e negações cobertos. |
| 146 | Fuzz testing | **PENDENTE** | Não há campanha de fuzz dedicada nesta entrega. |
| 147 | Business logic security | **IMPLEMENTADO** | Autoaprovação, dupla sessão e decisões concorrentes são impedidas. |
| 148 | Segregação de funções | **IMPLEMENTADO** | Solicitante/candidato/membro não aprova a própria ação/patente. |
| 149 | Two-person rule opcional | **NÃO APLICÁVEL** | Política opcional não foi habilitada; ações críticas têm confirmação/auditoria. |
| 150 | Bulk actions | **IMPLEMENTADO** | Alterações em massa existentes exigem preview/snapshot/confirm e rollback. |
| 151 | Security notifications | **IMPLEMENTADO** | Eventos críticos/drift/backup falho podem ser entregues ao canal de auditoria. |
| 152 | Alert fatigue | **IMPLEMENTADO** | Drift só alerta quando o hash muda; tarefas têm periodicidade central. |
| 153 | Time | **IMPLEMENTADO** | Timestamps UTC epoch; exibição America/Sao_Paulo. |
| 154 | Clock | **IMPLEMENTADO** | Clock injetável nos serviços e tempo server-side. |
| 155 | Data retention | **IMPLEMENTADO** | Cleanup de nonce/eventos e retenção de backups configurável. |
| 156 | Privacy by design | **IMPLEMENTADO** | Minimização, ephemeral, RBAC e fixtures sintéticas. |
| 157 | Não fazer fingerprint invasivo | **NÃO APLICÁVEL** | Não há fingerprinting; IP/UA apenas HMAC para segurança. |
| 158 | Security documentation | **IMPLEMENTADO** | SECURITY.md, matriz, threat model, ADR e runbooks. |
| 159 | Incident response | **IMPLEMENTADO** | docs/INCIDENT_RESPONSE.md com severidade, contenção e recovery. |
| 160 | Comprometimento do bot token | **IMPLEMENTADO** | Runbook específico; rotação real permanece controle 42 pendente. |
| 161 | Comprometimento do database secret | **IMPLEMENTADO** | Runbook de isolamento, rotação e restauração. |
| 162 | Comprometimento do OAuth secret | **IMPLEMENTADO** | Runbook revoga sessões e rotaciona OAuth/Auth/HMAC. |
| 163 | Recovery | **IMPLEMENTADO** | Critérios de recuperação e reconciliação documentados. |
| 164 | Infrastructure as code | **IMPLEMENTADO** | Railway TOML, vercel.ts, env examples e workflows versionados. |
| 165 | Observabilidade | **PENDENTE** | Logs/eventos existem; agregador/alerta externo ainda não provisionado. |
| 166 | Database connection pool | **IMPLEMENTADO** | SQLite centralizado em conexão única; múltiplas instâncias proibidas. |
| 167 | Connection exhaustion | **IMPLEMENTADO** | API tem limite de concorrência/backlog e DB busy_timeout. |
| 168 | Transaction timeout | **PENDENTE** | SQLite não possui statement timeout equivalente; monitorar operações longas. |
| 169 | Bot worker | **IMPLEMENTADO** | Scripts detectam/impedem instâncias órfãs e controlam launcher/runtime. |
| 170 | Queue poisoning | **IMPLEMENTADO** | Jobs têm tentativas/estado de falha; payload validado antes de processar. |
| 171 | Data integrity | **IMPLEMENTADO** | Constraints, FK, hashes, auditoria e checks de startup. |
| 172 | Check constraints | **IMPLEMENTADO** | Schema usa checks/índices únicos, inclusive índices parciais críticos. |
| 173 | Soft delete | **IMPLEMENTADO** | Fluxos arquivam/alteram status; evidência e histórico não são apagados. |
| 174 | Production data | **IMPLEMENTADO** | Testes e Lovable usam somente dados sintéticos. |
| 175 | Data masking | **IMPLEMENTADO** | Fixtures e logs minimizam/redigem dados sensíveis. |
| 176 | Error monitoring | **PENDENTE** | Correlation IDs existem; serviço externo de captura não provisionado. |
| 177 | Security scan recorrente | **IMPLEMENTADO** | CI em PR/push, CodeQL e Dependabot semanal. |
| 178 | Patch management | **IMPLEMENTADO** | Dependabot + audit gate e pins revisados. |
| 179 | Known exploited vulnerabilities | **IMPLEMENTADO** | Auditorias locais retornam zero vulnerabilidades conhecidas. |
| 180 | Dependency EOL | **IMPLEMENTADO** | Runtimes atuais e dependências atualizadas; revisão contínua no CI. |
| 181 | API versioning | **IMPLEMENTADO** | Rotas públicas do backend usam /v1. |
| 182 | Deprecated endpoint | **IMPLEMENTADO** | Nenhum fallback de produção ou endpoint deprecated exposto. |
| 183 | Admin routes | **IMPLEMENTADO** | RBAC server-side; security/manage somente ADMIN. |
| 184 | Security through obscurity | **IMPLEMENTADO** | Controles dependem de criptografia/autorização, não de rotas ocultas. |
| 185 | Database administration | **IMPLEMENTADO** | Nenhuma interface DB admin pública no projeto. |
| 186 | Supabase Security Advisor | **NÃO APLICÁVEL** | Supabase não provisionado; obrigatório se o corte ocorrer. |
| 187 | RLS review | **NÃO APLICÁVEL** | Sem RLS no SQLite. |
| 188 | Realtime security | **NÃO APLICÁVEL** | Supabase Realtime não é usado. |
| 189 | Realtime data minimization | **NÃO APLICÁVEL** | Sem canal realtime. |
| 190 | WebSocket auth | **NÃO APLICÁVEL** | Nenhum WebSocket de aplicação. |
| 191 | Security review de frontend | **IMPLEMENTADO** | CSP/nonce, sessão minimizada, no-store e build dinâmico revisados. |
| 192 | Debug | **IMPLEMENTADO** | Sem debug/traceback externo em produção. |
| 193 | Development routes | **IMPLEMENTADO** | Bypasses dependem de APP_ENV e são proibidos em produção. |
| 194 | Test accounts | **IMPLEMENTADO** | Fixtures sintéticas e nenhuma credencial default real. |
| 195 | Default credentials | **IMPLEMENTADO** | Produção falha com secrets fracos/ausentes. |
| 196 | Admin bootstrap | **IMPLEMENTADO** | Desabilitado por padrão e explicitamente proibido sem flag controlada. |
| 197 | Security fail closed | **IMPLEMENTADO** | Config inválida, RankSync divergente, sessão inválida e lockdown negam acesso. |
| 198 | Fallback | **IMPLEMENTADO** | Autenticação legada só em desenvolvimento com opt-in explícito. |
| 199 | Privilege escalation | **IMPLEMENTADO** | Testes e revalidação de perfil/status/RankSync bloqueiam escalada comum. |
| 200 | Security acceptance criteria | **PENDENTE** | TLS, rotação, MFA, WAF/monitoramento e testes externos ainda bloqueiam PASS. |
| 201 | Security review final | **IMPLEMENTADO** | Esta matriz emite resultado FAIL com justificativa e sem ocultar pendências. |
| 202 | Não declarar inviolável | **IMPLEMENTADO** | SECURITY.md registra risco residual e nunca usa essa alegação. |
| 203 | Princípio final | **IMPLEMENTADO** | Defesa em profundidade aplicada entre browser, BFF, API, DB e Discord. |
| 204 | Regra de implementação | **IMPLEMENTADO** | Controles possuem código, teste ou pendência explícita; sem checkbox vazio. |
| 205 | Não adicionar complexidade sem benefício | **IMPLEMENTADO** | Monólito modular/SQLite preservados para instância única. |
| 206 | Proibição de criptografia caseira | **IMPLEMENTADO** | HMAC-SHA256 e compare_digest de bibliotecas padrão. |
| 207 | Algoritmos | **IMPLEMENTADO** | SHA-256/HMAC e nonces criptograficamente aleatórios. |
| 208 | Senhas | **NÃO APLICÁVEL** | Autenticação local por senha não existe. |
| 209 | Encryption at rest | **PENDENTE** | Depende de volume/banco do provedor; backup externo deve ser criptografado. |
| 210 | Separação de chaves | **IMPLEMENTADO** | API HMAC, audit salt, recruitment secret, OAuth e Auth secret devem ser distintos. |
| 211 | Cache | **IMPLEMENTADO** | Dados sensíveis usam no-store; não há cache compartilhado de PII. |
| 212 | Permission cache | **IMPLEMENTADO** | RBAC é consultado no backend por request, sem cache privilegiado persistente. |
| 213 | Sessão de usuário desligado | **IMPLEMENTADO** | Status suspenso/desligado é negado e sessões podem ser revogadas. |
| 214 | Security UX | **IMPLEMENTADO** | Erros são claros/ephemeral sem detalhes internos; lockdown tem confirmação. |
| 215 | Security admin | **IMPLEMENTADO** | Dashboard restrito para eventos, health, lockdown e revogação. |
| 216 | Princípio de responsabilidade | **IMPLEMENTADO** | Deny-by-default, actor/reason e responsabilidade operacional documentados. |
| 217 | Defaults | **IMPLEMENTADO** | IA/bypass/bootstrap legados desativados; produção falha fechada. |
| 218 | Security regression tests | **IMPLEMENTADO** | 192 testes Python mais testes web/gate cobrem regressões críticas. |
| 219 | Post-incident | **IMPLEMENTADO** | Runbook exige postmortem com causa, impacto, ações e prazos. |
| 220 | Resultado esperado | **PENDENTE** | Base local entregue; produção só alcança o resultado após fechar pendências externas. |

## Critério para mudar o veredito

Um novo review poderá emitir PASS/WARNING somente depois de: rotacionar o token Discord; comprovar HTTPS/TLS/domínios; validar a auditoria real do bot sem Administrator; configurar MFA, branch protection, backups externos e observabilidade; executar DAST/pentest com escopo; e repetir o gate completo no commit publicado.

