# CONTEXTO

Este prompt é COMPLEMENTAR a todos os prompts anteriores do projeto:

# CHOQUE - BGR

Já existe ou está sendo desenvolvido:

* Bot Discord;
* Site administrativo;
* Frontend;
* Backend/API;
* Supabase/PostgreSQL;
* Railway;
* Discord OAuth;
* sistema de membros;
* patrulhas;
* bate-ponto;
* administração;
* auditoria;
* configurações;
* permissões;
* dados administrativos.

Agora realize um:

# SECURITY HARDENING COMPLETO

em toda a arquitetura.

Segurança NÃO deve ser tratada como uma etapa final.

Ela deverá fazer parte:

```text
ARQUITETURA
↓
DESENVOLVIMENTO
↓
DEPLOY
↓
BANCO
↓
AUTENTICAÇÃO
↓
AUTORIZAÇÃO
↓
MONITORAMENTO
↓
BACKUP
↓
RESPOSTA A INCIDENTES
```

---

# 1. PRINCÍPIO FUNDAMENTAL

Nenhuma camada deve ser considerada confiável por padrão.

Utilizar:

# ZERO TRUST

Princípios:

```text
Never trust.
Always verify.
Least privilege.
Assume breach.
Defense in depth.
```

Não considerar seguro apenas porque:

* usuário está logado;
* usuário possui determinada página aberta;
* botão está escondido;
* request veio do frontend;
* usuário possui um cookie;
* dado veio do Discord;
* conexão veio de outro serviço interno.

Toda ação sensível deverá ser validada novamente no backend.

---

# 2. REFERÊNCIAS DE SEGURANÇA

Utilizar como baseline:

* OWASP ASVS 5.0;
* OWASP Top 10;
* OWASP API Security;
* NIST Cybersecurity Framework 2.0;
* CISA Secure by Design;
* princípio de menor privilégio;
* defense-in-depth;
* secure-by-default.

Objetivo inicial:

# OWASP ASVS LEVEL 2

Para operações administrativas mais críticas, aplicar controles adicionais equivalentes aos requisitos relevantes de maior segurança.

---

# 3. THREAT MODEL

Antes de finalizar a arquitetura, criar um threat model real.

Mapear:

```text
Frontend
API
Bot Discord
OAuth
Supabase
Railway
Banco
Realtime
Scheduler
CI/CD
GitHub
DNS
Sessões
Administradores
```

Identificar ameaças como:

```text
Spoofing
Tampering
Repudiation
Information Disclosure
Denial of Service
Elevation of Privilege
```

Documentar:

```text
ameaça
impacto
probabilidade
controle
risco residual
```

---

# 4. SUPERFÍCIE DE ATAQUE

Mapear todos os pontos expostos.

Exemplo:

```text
https://choque.example.com

https://api.choque.example.com

/oauth/callback

/api/auth/*
/api/members/*
/api/admin/*
```

Eliminar endpoints desnecessários.

Serviços internos não devem ficar expostos publicamente sem necessidade.

---

# 5. HTTPS OBRIGATÓRIO

Toda comunicação pública deve utilizar:

```text
HTTPS
```

Nunca aceitar produção via:

```text
HTTP
```

Configurar redirect:

```text
HTTP → HTTPS
```

---

# 6. TLS

Utilizar apenas versões modernas.

Aceitar:

```text
TLS 1.2
TLS 1.3
```

Não permitir protocolos obsoletos.

Não aceitar:

```text
SSLv2
SSLv3
TLS 1.0
TLS 1.1
```

Railway deverá utilizar seus certificados SSL automáticos ou certificado do domínio configurado.

---

# 7. HSTS

Adicionar:

```http
Strict-Transport-Security
```

Configuração forte após domínio e HTTPS estarem validados.

Exemplo:

```text
max-age=63072000
includeSubDomains
```

Considerar `preload` somente quando toda infraestrutura estiver realmente preparada para HTTPS permanente.

---

# 8. SECURITY HEADERS

Implementar headers adequados.

No mínimo:

```text
Content-Security-Policy
Strict-Transport-Security
X-Content-Type-Options
Referrer-Policy
Permissions-Policy
```

Também impedir framing por terceiros através de CSP:

```text
frame-ancestors 'none'
```

ou política equivalente.

---

# 9. CONTENT SECURITY POLICY

Criar CSP restritiva.

Não utilizar:

```text
unsafe-eval
```

Não utilizar:

```text
unsafe-inline
```

sem necessidade real.

Para scripts inline inevitáveis:

utilizar:

```text
nonce
```

ou hashes adequados.

Definir explicitamente origens permitidas.

---

# 10. CORS

Nunca utilizar:

```text
Access-Control-Allow-Origin: *
```

em endpoints autenticados.

Permitir somente os domínios oficiais.

Exemplo:

```text
https://painel.choque...
```

Validar:

* origin;
* métodos;
* headers;
* credentials.

---

# 11. AUTENTICAÇÃO VIA DISCORD

Utilizar OAuth Authorization Code Flow.

Implementar:

```text
state
```

obrigatoriamente para evitar ataques de CSRF/login injection.

Quando suportado pela arquitetura:

utilizar PKCE.

Validar completamente o callback OAuth.

---

# 12. NÃO CONFIAR APENAS NO DISCORD ID

Após autenticação:

verificar também:

* usuário pertence ao servidor correto;
* usuário está cadastrado;
* status do cadastro;
* cargos;
* permissões internas;
* conta não está bloqueada.

---

# 13. SESSÕES

Preferir sessão server-side ou estratégia segura equivalente.

Cookies:

```text
HttpOnly
Secure
SameSite=Lax ou Strict
```

Nunca permitir JavaScript acessar token sensível quando não for necessário.

---

# 14. NÃO ARMAZENAR TOKEN EM LOCALSTORAGE

Proibido armazenar credenciais ou tokens sensíveis em:

```text
localStorage
sessionStorage
```

quando puderem ser protegidos por cookie HttpOnly/server-side.

Principalmente:

* refresh token;
* sessão administrativa;
* token Discord;
* tokens internos.

---

# 15. SESSION FIXATION

Após login:

gerar nova sessão.

Nunca reutilizar session ID pré-autenticação.

---

# 16. SESSION EXPIRATION

Implementar:

* idle timeout;
* absolute timeout;
* revogação;
* logout real;
* invalidação administrativa.

Exemplo conceitual:

```text
sessão normal:
algumas horas

sessão privilegiada:
tempo menor
```

Adapte conforme UX.

---

# 17. STEP-UP AUTHENTICATION

Para ações extremamente sensíveis:

* rebaixamento;
* suspensão;
* desligamento;
* alteração de permissões;
* configuração de cargos;
* gerenciamento de administradores;
* ações em massa;

considerar exigir autenticação recente.

Exemplo:

```text
Sua autenticação possui mais de X minutos.
Confirme sua identidade novamente.
```

---

# 18. MFA PARA ADMINISTRADORES

Para contas com privilégios elevados, suportar ou exigir MFA quando possível.

Preferência moderna:

```text
WebAuthn / Passkeys
```

ou TOTP como alternativa.

Não depender exclusivamente de senha.

Se o projeto utilizar somente Discord OAuth, analisar formas seguras de step-up authentication para Alto Comando.

---

# 19. RBAC BACKEND

Todas as permissões devem ser verificadas no servidor.

Nunca fazer apenas:

```ts
if (user.role === "admin")
```

no frontend.

Backend deve decidir.

---

# 20. DENY BY DEFAULT

Se uma permissão não estiver explicitamente concedida:

```text
NEGAR
```

Nunca:

```text
permitir por padrão
```

---

# 21. PERMISSÕES GRANULARES

Utilizar permissões semelhantes a:

```text
member.read
member.manage

shift.read
shift.adjust

patrol.manage

rank.promote
rank.demote

discipline.read
discipline.manage

training.manage

requests.review

audit.read

settings.read
settings.write

security.manage
```

Evitar papel:

```text
ADMIN = tudo
```

quando puder separar responsabilidades.

---

# 22. PRINCÍPIO DO MENOR PRIVILÉGIO

Cada usuário, serviço e token deve possuir apenas acesso necessário.

Isso vale para:

* usuário;
* bot;
* API;
* banco;
* CI/CD;
* GitHub;
* Railway;
* Supabase.

---

# 23. REVALIDAÇÃO DE PRIVILÉGIO

Uma sessão não deve manter acesso administrativo indefinidamente após o cargo ter sido removido no Discord.

Ao alterar cargo/permissão:

invalidar ou atualizar imediatamente a autorização.

Para ações críticas:

revalidar permissões atuais antes de executar.

---

# 24. SUPABASE — RLS

Ativar:

# ROW LEVEL SECURITY

em TODAS as tabelas expostas por API.

Nenhuma tabela administrativa sensível pode ficar exposta com RLS desativado.

---

# 25. RLS DEFAULT DENY

Começar com:

```text
nenhum acesso
```

Depois adicionar policies explicitamente.

Não criar policy ampla como:

```text
authenticated users can everything
```

---

# 26. NÃO CONFIAR SOMENTE EM RLS

Utilizar várias camadas:

```text
API authorization
+
Postgres grants
+
RLS
+
validation
```

RLS é proteção adicional, não substituto da autorização da aplicação.

---

# 27. SERVICE ROLE

A chave:

```text
SUPABASE_SERVICE_ROLE_KEY
```

NUNCA deve aparecer:

* frontend;
* bundle JavaScript;
* HTML;
* source map;
* log;
* response;
* GitHub.

Somente server-side quando absolutamente necessário.

---

# 28. PREFERIR CREDENCIAL DE MENOR PRIVILÉGIO

Não utilizar `service_role` para todas as operações do backend por comodidade.

Criar roles PostgreSQL adequadas quando possível.

Exemplo:

```text
app_runtime
bot_runtime
migration_role
```

Cada uma com somente privilégios necessários.

---

# 29. POSTGRES SSL

Ativar enforcement de SSL no Supabase.

Nenhuma conexão do banco em produção deve ocorrer em texto puro.

---

# 30. NETWORK RESTRICTIONS

Quando a infraestrutura permitir:

restringir acesso direto ao PostgreSQL apenas aos IPs/serviços autorizados.

Se Railway disponibilizar outbound IP fixo na configuração utilizada:

usar allowlist no Supabase.

Não abrir banco ao mundo sem necessidade.

---

# 31. DATA API

Se o frontend NÃO precisar acessar diretamente a Data API do Supabase:

considerar desabilitar exposição desnecessária.

Preferência arquitetural:

```text
Browser
↓
API
↓
Database
```

para operações administrativas.

---

# 32. BANCO NÃO ACESSÍVEL PELO FRONTEND

O browser nunca deverá receber:

```text
DATABASE_URL
POSTGRES_PASSWORD
```

---

# 33. SQL INJECTION

Todas as queries devem utilizar:

* ORM seguro;
* queries parametrizadas;
* prepared statements.

Nunca montar SQL concatenando dados do usuário.

Proibido:

```ts
`SELECT * FROM users WHERE id = '${input}'`
```

---

# 34. DYNAMIC SQL

Evitar SQL dinâmico.

Quando necessário:

* allowlist;
* parametrização;
* validação rigorosa.

---

# 35. SECURITY DEFINER

Functions PostgreSQL com:

```text
SECURITY DEFINER
```

devem ser usadas com extrema cautela.

Quando utilizadas:

fixar `search_path`.

Validar entrada.

Conceder EXECUTE apenas aos roles necessários.

---

# 36. GRANTS

Auditar:

```text
GRANT
```

de todas as tabelas.

Remover privilégios desnecessários de:

```text
public
anon
authenticated
```

---

# 37. BACKUPS

Configurar backups automáticos do banco.

Se o plano suportar:

utilizar Point-in-Time Recovery.

---

# 38. TESTAR RESTORE

Backup sem teste de restauração não é suficiente.

Periodicamente validar:

```text
backup
↓
restore staging
↓
integrity check
```

---

# 39. DADOS CRÍTICOS

Manter backup de:

* membros;
* cargos;
* histórico;
* pontos;
* patrulhas;
* auditoria;
* configurações.

---

# 40. SEGREDOS

Nunca armazenar secrets no código.

Usar Railway Variables ou mecanismo equivalente.

Exemplos:

```text
DISCORD_TOKEN
DATABASE_URL
SUPABASE_SERVICE_ROLE_KEY
SESSION_SECRET
OAUTH_CLIENT_SECRET
ENCRYPTION_KEY
```

---

# 41. .ENV

`.env` deve estar no:

```text
.gitignore
```

Criar apenas:

```text
.env.example
```

sem valores reais.

---

# 42. SECRET ROTATION

Criar processo documentado para rotação de:

* Discord token;
* OAuth secret;
* database credentials;
* Supabase keys;
* session secret;
* encryption keys.

---

# 43. SECRET SCANNING

CI deve detectar secrets acidentalmente enviados ao repositório.

Se secret for encontrado:

NÃO apenas remover do commit.

Considerar comprometido e ROTACIONAR.

---

# 44. FRONTEND SECRETS

Variáveis expostas ao browser devem ser consideradas públicas.

Nunca colocar segredo em:

```text
NEXT_PUBLIC_*
VITE_*
```

ou equivalentes.

---

# 45. INPUT VALIDATION

Validar todos os requests do backend.

Utilizar schema validation.

Exemplo:

```text
Zod
Valibot
Joi
```

ou solução compatível com stack existente.

---

# 46. VALIDAR NO BACKEND

Não confiar somente na validação do frontend.

Frontend:

```text
UX
```

Backend:

```text
SEGURANÇA
```

---

# 47. MASS ASSIGNMENT

Não enviar objetos inteiros diretamente para ORM.

Errado:

```text
updateMember(req.body)
```

Usar allowlist explícita:

```text
name
internalId
```

etc.

---

# 48. XSS

Escapar conteúdo exibido.

Não renderizar HTML de usuário diretamente.

Evitar:

```text
dangerouslySetInnerHTML
```

Quando inevitável:

sanitizar rigorosamente.

---

# 49. MARKDOWN / TEXTO FORMATADO

Caso permita markdown:

usar parser seguro.

Desabilitar:

* scripts;
* HTML bruto;
* URLs perigosas.

---

# 50. CSRF

Toda operação mutável baseada em cookie deve possuir proteção contra CSRF.

Utilizar:

* SameSite;
* token CSRF quando adequado;
* validação de Origin/Referer.

Principalmente:

```text
POST
PUT
PATCH
DELETE
```

---

# 51. SSRF

Se futuramente backend buscar URLs fornecidas pelo usuário:

proteger contra SSRF.

Bloquear acesso a:

```text
localhost
127.0.0.1
169.254.169.254
private networks
internal services
```

Utilizar allowlist de protocolos/domínios quando possível.

---

# 52. OPEN REDIRECT

Redirect após login deve usar destinos permitidos.

Não aceitar:

```text
?redirect=https://site-malicioso.com
```

sem validação.

---

# 53. PATH TRAVERSAL

Nunca concatenar nome fornecido pelo usuário diretamente em caminho de arquivo.

Validar uploads e paths.

---

# 54. FILE UPLOAD

Caso existam uploads:

validar:

* MIME;
* assinatura real;
* tamanho;
* extensão;
* quantidade.

Renomear arquivo no servidor.

Nunca confiar no filename original.

---

# 55. ARQUIVOS EXECUTÁVEIS

Não permitir upload de:

```text
.exe
.sh
.bat
.cmd
.ps1
.js executável
```

quando não forem necessários.

---

# 56. STORAGE

Se utilizar Supabase Storage:

RLS/policies obrigatórias.

Buckets sensíveis:

```text
PRIVATE
```

Acesso via URL assinada com expiração curta.

---

# 57. RATE LIMIT

Implementar rate limiting.

Camadas:

```text
IP
usuário
sessão
endpoint
```

---

# 58. LIMITES MAIS FORTES EM ENDPOINTS SENSÍVEIS

Exemplo:

```text
/login
/oauth
/password/mfa
/admin
/promote
/demote
/adjust-shift
```

devem possuir limites mais agressivos.

---

# 59. BRUTE FORCE

Detectar tentativas repetidas.

Responder com:

* rate limit;
* cooldown;
* alertas internos.

Não revelar informações que ajudem enumeração de contas.

---

# 60. ENUMERAÇÃO

Evitar mensagens como:

```text
Este usuário existe.
Este usuário não existe.
```

quando isso puder ajudar ataques.

---

# 61. WAF

Recomendar camada de proteção na frente do Railway.

Exemplo:

```text
Cloudflare
↓
Railway
```

Utilizar:

* WAF;
* bot protection;
* rate limiting;
* DDoS protection;
* DNS security.

Não depender do WAF como única defesa.

---

# 62. CLOUDFLARE

Se utilizado:

configurar corretamente SSL com Railway conforme documentação atual da infraestrutura.

Não ativar opções aleatórias que causem loops ou degradem TLS.

---

# 63. DDOS

Arquitetura deve suportar mitigação de:

* HTTP floods;
* abusive clients;
* connection floods dentro das capacidades da plataforma.

Utilizar edge/WAF quando necessário.

---

# 64. API BODY LIMIT

Limitar tamanho máximo de requests.

Exemplo:

```text
JSON body pequeno
```

Não aceitar payloads gigantes sem necessidade.

---

# 65. QUERY LIMIT

Paginação obrigatória.

Nunca permitir:

```text
GET /members?limit=999999999
```

Impor limites.

---

# 66. REGEX DOS

Evitar regex vulnerável a catastrophic backtracking.

---

# 67. REQUEST TIMEOUT

Definir timeout de requests externos.

Nenhuma integração deve ficar aguardando indefinidamente.

---

# 68. WEBHOOKS

Se futuramente utilizar webhooks:

validar assinatura criptográfica.

Nunca confiar somente em IP.

---

# 69. DISCORD BOT TOKEN

Bot token deve existir somente no serviço do bot.

A API/web não deve receber o token se não precisar.

---

# 70. SEPARAÇÃO DE SERVIÇOS

Arquitetura recomendada:

```text
Railway Project

web
api
bot
worker
```

Cada serviço recebe apenas as secrets necessárias.

Exemplo:

```text
web:
nenhum Discord Bot Token

bot:
Discord Bot Token

api:
database credentials específicas
```

---

# 71. PRIVATE NETWORKING

Serviços Railway que não precisam ser públicos devem utilizar rede privada.

Exemplo:

```text
worker
bot
```

não precisam necessariamente possuir endpoint público.

---

# 72. API PUBLICA

Somente serviços que realmente necessitam receber requests públicos devem possuir domínio público.

---

# 73. HEALTH ENDPOINT

Criar:

```text
/health
```

mas não revelar:

* versões;
* secrets;
* stack trace;
* banco;
* environment variables.

Resposta mínima.

---

# 74. ERROR HANDLING

Em produção:

NUNCA enviar stack trace ao usuário.

Exemplo público:

```text
Falha ao processar a operação.
ID: ERR-8F2A
```

Log interno contém detalhes.

---

# 75. NÃO EXPOR TECNOLOGIA

Remover headers desnecessários como:

```text
X-Powered-By
```

quando possível.

---

# 76. SOURCE MAPS

Não publicar source maps sensíveis publicamente sem necessidade.

Se forem necessários para observabilidade:

armazenar de maneira privada no serviço de monitoramento.

---

# 77. LOGGING

Criar logs estruturados de segurança.

Registrar:

* login;
* logout;
* falha de autorização;
* alteração administrativa;
* alteração de permissão;
* rate limit;
* tentativa suspeita;
* alteração de configuração;
* ação em massa;
* falhas de sincronização.

---

# 78. NÃO LOGAR SECRETS

Proibido logar:

* tokens;
* cookies;
* passwords;
* database URL;
* OAuth secret;
* Authorization header.

Aplicar redaction automático.

---

# 79. PII

Não logar dados pessoais desnecessários.

Quando ID técnico for suficiente:

usar ID.

---

# 80. AUDIT LOG

Auditoria administrativa deve ser append-only para usuários normais da aplicação.

Aplicação runtime não deve possuir permissão para modificar logs antigos sem necessidade.

---

# 81. AUDITORIA DE SEGURANÇA

Registrar:

```text
actor
target
action
source
timestamp
requestId
ipHash ou IP conforme política
userAgent quando necessário
result
```

Respeitar privacidade.

---

# 82. REQUEST ID

Cada request deve possuir:

```text
requestId
```

para correlação entre:

```text
frontend
api
database
bot
```

---

# 83. ALERTAS

Criar alertas para:

* muitas falhas de login;
* muitas negações de permissão;
* volume anormal de requests;
* alteração de permissões críticas;
* erro de banco repetitivo;
* falha de OAuth;
* muitas ações administrativas.

---

# 84. INCIDENT RESPONSE MODE

Criar modo de emergência administrativo.

Exemplo:

# SECURITY LOCKDOWN

Quando ativado:

* bloquear alterações administrativas;
* preservar leitura;
* invalidar sessões quando necessário;
* impedir novas operações sensíveis;
* manter auditoria funcionando.

Apenas usuários com permissão específica podem ativar/desativar.

---

# 85. REVOGAR TODAS AS SESSÕES

Criar capacidade administrativa para:

```text
LOGOUT GLOBAL
```

em caso de incidente.

---

# 86. REVOGAÇÃO POR USUÁRIO

Se conta for comprometida:

```text
revogar sessões daquele usuário
```

sem afetar todos.

---

# 87. CI/CD

Pipeline mínimo antes de produção:

```text
lint
typecheck
unit tests
integration tests
security checks
dependency scan
secret scan
build
```

---

# 88. SAST

Adicionar análise estática de segurança.

Exemplos possíveis:

```text
CodeQL
Semgrep
```

Escolher solução adequada ao repositório.

---

# 89. DEPENDENCY SCANNING

Monitorar CVEs em dependências.

Exemplos:

```text
Dependabot
Renovate
npm audit
pnpm audit
SCA
```

Não considerar `npm audit` sozinho suficiente.

---

# 90. LOCKFILE

Commitar lockfile.

Utilizar instalação determinística:

```text
npm ci
```

ou equivalente do package manager utilizado.

---

# 91. DEPENDÊNCIAS

Não adicionar package simplesmente porque facilita uma função pequena.

Antes de adicionar:

verificar:

* manutenção;
* downloads;
* vulnerabilidades;
* última atualização;
* reputação;
* dependências transitivas.

---

# 92. SUPPLY CHAIN

Proteger contra ataques de dependência.

Evitar packages:

* abandonados;
* sem origem clara;
* duplicando funções simples;
* recém-publicados sem necessidade.

---

# 93. SBOM

Gerar Software Bill of Materials para releases importantes.

Formato:

```text
CycloneDX
```

ou:

```text
SPDX
```

---

# 94. PINNING

Fixar versões importantes.

Não utilizar ranges excessivamente permissivos para componentes críticos sem necessidade.

---

# 95. RUNTIME

Utilizar versão LTS/estável suportada do Node.js ou runtime atual.

Nunca manter runtime EOL em produção.

---

# 96. CONTAINER HARDENING

Se utilizar Docker:

executar aplicação como:

```text
NON-ROOT USER
```

Não executar como root sem necessidade.

---

# 97. IMAGEM DOCKER

Utilizar imagem mínima.

Não incluir:

* Git;
* ferramentas de compilação;
* shell extras;

na imagem final se não forem necessários.

Preferir multi-stage build.

---

# 98. FILESYSTEM

Quando compatível:

reduzir permissões de escrita.

Aplicação não deve escrever arbitrariamente no sistema.

---

# 99. ENVIRONMENTS

Separar completamente:

```text
development
staging
production
```

---

# 100. BANCO SEPARADO

Staging NÃO deve usar banco de produção.

Nunca testar migrations diretamente em produção.

---

# 101. MIGRATIONS

Toda alteração de banco deve ocorrer por migration versionada.

Não editar schema de produção manualmente pelo dashboard como fluxo normal.

---

# 102. MIGRATION REVIEW

Migration destrutiva precisa de revisão.

Exemplo:

```text
DROP TABLE
DROP COLUMN
TRUNCATE
```

exigir confirmação explícita.

---

# 103. PRODUCTION DEPLOY

Deploy de produção deve ocorrer apenas a partir de branch protegida.

Exemplo:

```text
main
```

---

# 104. BRANCH PROTECTION

Configurar:

* pull request;
* checks obrigatórios;
* review;
* impedir force push;
* impedir delete da branch principal.

---

# 105. GITHUB SECURITY

Ativar:

* 2FA;
* secret scanning;
* Dependabot;
* CodeQL quando possível.

Não compartilhar conta administrativa.

---

# 106. ACCESS CONTROL — INFRA

Supabase, Railway, GitHub e DNS devem possuir:

* contas individuais;
* MFA;
* menor privilégio;
* acesso removido imediatamente quando alguém sair do projeto.

---

# 107. NÃO COMPARTILHAR CREDENCIAIS

Nunca usar:

```text
conta compartilhada do Railway
```

ou:

```text
senha compartilhada do Supabase
```

Cada operador deve possuir sua própria conta.

---

# 108. DNS

Proteger conta do provedor DNS com MFA.

Bloquear transferências de domínio quando possível.

Ativar proteção contra alteração não autorizada.

---

# 109. CSP REPORTING

Quando possível:

monitorar violações de CSP.

Usar primeiro em:

```text
Report-Only
```

para ajustar política.

Depois aplicar enforcement.

---

# 110. CLICKJACKING

Impedir site de ser embutido em iframe de terceiros.

Utilizar:

```text
frame-ancestors 'none'
```

salvo necessidade específica.

---

# 111. MIME SNIFFING

Adicionar:

```text
X-Content-Type-Options: nosniff
```

---

# 112. REFERRER

Utilizar política restritiva.

Exemplo:

```text
strict-origin-when-cross-origin
```

ou ainda mais restritiva conforme necessidade.

---

# 113. PERMISSIONS POLICY

Desabilitar APIs de navegador desnecessárias.

Por exemplo:

* câmera;
* microfone;
* geolocalização;

caso o site não utilize.

---

# 114. CACHE DE DADOS SENSÍVEIS

Endpoints administrativos não devem ficar em cache público.

Utilizar:

```text
Cache-Control: no-store
```

quando apropriado.

---

# 115. SERVICE WORKER

Se não houver necessidade real de PWA:

não criar service worker.

Se existir:

garantir que dados administrativos não sejam cacheados indevidamente.

---

# 116. BROWSER AUTOCOMPLETE

Campos extremamente sensíveis devem possuir comportamento adequado de autocomplete.

---

# 117. IDEMPOTENCY

Ações administrativas críticas devem suportar idempotência.

Exemplo:

```text
PROMOVER
```

clicado duas vezes:

resultado deve ser uma única promoção.

---

# 118. OPTIMISTIC LOCKING

Para registros críticos, considerar versionamento.

Exemplo:

```text
version = 7
```

Dois administradores editando simultaneamente não podem sobrescrever silenciosamente alterações.

---

# 119. DATABASE TRANSACTIONS

Operações compostas devem utilizar transaction.

Exemplo promoção:

```text
BEGIN

update membro
insert rank_history
insert audit
enqueue discord_sync

COMMIT
```

---

# 120. OUTBOX PATTERN

Para sincronizações críticas entre banco e Discord, considerar transactional outbox.

Exemplo:

```text
Banco alterado
+
evento criado
```

na mesma transaction.

Worker posteriormente executa:

```text
Discord sync
```

Isso evita estado:

```text
Banco atualizou
Discord não
```

sem rastreamento.

---

# 121. RETRY

Retries:

* limitados;
* com backoff;
* idempotentes.

Nunca loop infinito.

---

# 122. CIRCUIT BREAKER

Para integrações externas críticas, considerar circuit breaker quando apropriado.

Exemplo:

Discord indisponível.

Evitar bombardear API com milhares de tentativas.

---

# 123. DISCORD RATE LIMIT

Respeitar rate limits oficiais.

Nunca contornar rate limits.

---

# 124. RECONCILIAÇÃO

Se Discord ficar indisponível:

marcar:

```text
SYNC_PENDING
```

Depois reconciliar automaticamente.

---

# 125. BOT PERMISSIONS

Bot Discord NÃO deve possuir:

```text
Administrator
```

por padrão.

Conceder somente:

* gerenciar apelidos;
* gerenciar cargos necessários;
* mover membros;
* visualizar canais necessários;
* enviar/editar mensagens necessárias;

e demais permissões estritamente necessárias.

---

# 126. HIERARQUIA DE CARGOS

Cargo do bot deve estar apenas acima dos cargos que precisa administrar.

Não posicioná-lo acima de cargos administrativos desnecessariamente.

---

# 127. AUDITORIA DE PERMISSÕES DISCORD

Criar verificação periódica.

Detectar:

* bot ganhou Administrator;
* cargo crítico mudou;
* permissão inesperada;
* canais sensíveis públicos.

Notificar Alto Comando.

Não corrigir ações delicadas automaticamente sem autorização.

---

# 128. RATE LIMIT DO BOT

Também limitar spam de:

* botões;
* modais;
* solicitações;
* cadastro;
* ponto.

---

# 129. SECURITY EVENTS

Criar tipos de eventos:

```text
SECURITY_AUTH_FAILED

SECURITY_PERMISSION_DENIED

SECURITY_RATE_LIMIT

SECURITY_ROLE_CHANGED

SECURITY_BULK_ACTION

SECURITY_CONFIG_CHANGED

SECURITY_SESSION_REVOKED
```

---

# 130. AUDITORIA DE CONFIGURAÇÕES

Qualquer alteração em:

* cargos;
* canais;
* patentes;
* permissões;
* tempo mínimo;
* módulos;
* segurança;

deve registrar:

```text
antes
depois
responsável
timestamp
```

---

# 131. PROTEGER AUDITORIA

Usuário que pode alterar membro NÃO deve automaticamente poder apagar audit logs.

Idealmente:

```text
audit logs = append-only
```

para aplicação normal.

---

# 132. DADOS DE AUDITORIA

Não permitir edição histórica silenciosa.

Correção deve gerar novo evento.

---

# 133. ERROR IDS

Erros devem possuir ID.

Exemplo:

```text
SEC-20260822-AB821
```

Facilita investigação sem expor detalhes ao usuário.

---

# 134. SECURITY DASHBOARD

Dentro do painel administrativo, criar página restrita:

# SEGURANÇA DO SISTEMA

Mostrar somente dados úteis.

Exemplo:

```text
STATUS

API
OPERACIONAL

BANCO
OPERACIONAL

DISCORD
CONECTADO

────────────────

ÚLTIMAS 24 HORAS

Tentativas bloqueadas
23

Rate limits
18

Falhas de autorização
5

Erros críticos
0
```

Não mostrar dados úteis para atacantes a usuários comuns.

---

# 135. SECURITY HEALTH

Adicionar checks internos:

* CSP;
* HTTPS;
* database SSL;
* backups;
* RLS;
* secrets;
* migrations;
* serviços;
* versões.

---

# 136. SECURITY CONFIGURATION DRIFT

Detectar configuração insegura.

Exemplo:

```text
RLS desligado
```

ou:

```text
Admin route sem auth
```

deve bloquear release quando detectável automaticamente.

---

# 137. PRE-DEPLOY SECURITY GATE

Produção não deve receber deploy se houver:

```text
secret vazado
critical dependency vulnerability
tests críticos falhando
migration inválida
TypeScript build error
```

---

# 138. DAST

Executar testes dinâmicos em staging.

Pode utilizar:

```text
OWASP ZAP Baseline
```

ou ferramenta equivalente.

Nunca executar scans agressivos contra produção sem planejamento.

---

# 139. PENETRATION TEST

Antes de considerar sistema maduro:

realizar teste de penetração autorizado.

Escopo:

```text
website
API
OAuth
RBAC
Supabase policies
admin actions
```

---

# 140. NÃO FAZER "PENTEST" DE FACHADA

Não considerar apenas:

```text
npm audit
```

como pentest.

Testar fluxos reais de autorização.

---

# 141. AUTHORIZATION TESTS

Criar testes específicos:

```text
Membro tenta ver outro dossiê → 403

Instrutor tenta alterar patente → 403

Superior tenta alterar segurança → 403

Admin correto → permitido
```

---

# 142. IDOR / BOLA

Testar Broken Object Level Authorization.

Exemplo:

usuário autorizado a:

```text
/members/152
```

não significa automaticamente que pode acessar:

```text
/members/153/discipline
```

Cada objeto precisa de autorização.

---

# 143. API MASS ASSIGNMENT TEST

Testar request malicioso adicionando:

```json
{
  "name": "Joao",
  "role": "SUPER_ADMIN"
}
```

Backend deve ignorar/rejeitar campo não permitido.

---

# 144. DATABASE SECURITY TESTS

Testar RLS para cada papel.

Exemplo:

```text
anon
authenticated
member
superior
admin
```

Garantir que nenhuma policy permita acesso indevido.

---

# 145. NEGATIVE TESTING

Testar entradas:

* vazias;
* enormes;
* Unicode;
* HTML;
* scripts;
* SQL fragments;
* IDs inválidos;
* UUIDs aleatórios;
* datas inválidas;
* valores negativos.

---

# 146. FUZZ TESTING

Para parsers/endpoints relevantes, considerar fuzz tests básicos.

---

# 147. BUSINESS LOGIC SECURITY

Testar abuso das regras.

Exemplo:

* promover duas vezes;
* aprovar própria solicitação;
* corrigir próprio ponto sem permissão;
* rebaixar alguém superior;
* modificar solicitação já aprovada;
* reusar request antigo;
* repetir confirmação.

---

# 148. SEGREGAÇÃO DE FUNÇÕES

Quando possível:

usuário não deve aprovar a própria ação sensível.

Exemplo:

```text
administrador solicita correção do próprio ponto
```

deve exigir outro aprovador autorizado.

---

# 149. TWO-PERSON RULE OPCIONAL

Para ações extremamente sensíveis, considerar aprovação dupla.

Exemplo:

```text
alterar configuração global de segurança
```

ou:

```text
ação em massa sobre todo efetivo
```

Somente quando fizer sentido.

Não burocratizar atividades normais.

---

# 150. BULK ACTIONS

Ações em massa devem:

* mostrar preview;
* quantidade afetada;
* exigir confirmação;
* gerar auditoria;
* possuir rollback lógico quando possível.

---

# 151. SECURITY NOTIFICATIONS

Notificar responsáveis quando ocorrer:

* login administrativo incomum;
* alteração de permissão;
* alteração de configurações de segurança;
* muitas falhas de autenticação;
* secret rotation;
* lockdown.

---

# 152. ALERT FATIGUE

Não enviar alerta para tudo.

Classificar:

```text
INFO
LOW
MEDIUM
HIGH
CRITICAL
```

Só alertar imediatamente eventos realmente importantes.

---

# 153. TIME

Usar UTC internamente.

Logs de segurança devem possuir timestamps consistentes.

---

# 154. CLOCK

Servidores devem utilizar tempo confiável da infraestrutura.

Evitar lógica de segurança baseada em relógio do browser.

---

# 155. DATA RETENTION

Definir política de retenção para:

* logs;
* sessions;
* audit;
* security events.

Não armazenar indefinidamente dados desnecessários.

---

# 156. PRIVACY BY DESIGN

Coletar somente dados necessários.

Não armazenar:

* IP;
* device fingerprint;
* localização;

sem necessidade clara.

---

# 157. NÃO FAZER FINGERPRINT INVASIVO

Não criar sistema invasivo de fingerprint para “segurança” sem justificativa.

Segurança não deve virar coleta excessiva.

---

# 158. SECURITY DOCUMENTATION

Criar:

```text
SECURITY.md
```

Contendo:

* arquitetura;
* secrets;
* incident response;
* dependency policy;
* vulnerability reporting;
* backups;
* key rotation.

Sem incluir secrets.

---

# 159. INCIDENT RESPONSE

Criar runbook.

Exemplo:

```text
INCIDENTE DETECTADO
↓
CLASSIFICAR
↓
CONTER
↓
REVOGAR SESSÕES/KEYS
↓
INVESTIGAR LOGS
↓
CORRIGIR
↓
RECUPERAR
↓
ROTACIONAR SECRETS
↓
POST-MORTEM
```

---

# 160. COMPROMETIMENTO DO BOT TOKEN

Documentar:

```text
Reset Discord Bot Token
↓
Atualizar Railway
↓
Revogar anterior
↓
Revisar logs
↓
Investigar origem
```

---

# 161. COMPROMETIMENTO DO DATABASE SECRET

Processo:

```text
revogar
rotacionar
atualizar serviços
revisar logs
validar integridade
```

---

# 162. COMPROMETIMENTO DO OAUTH SECRET

Rotacionar imediatamente e invalidar sessões relacionadas quando apropriado.

---

# 163. RECOVERY

Manter capacidade de reconstruir serviços a partir de:

```text
Git repository
migrations
environment configuration
backup
```

Não depender de configuração manual esquecida.

---

# 164. INFRASTRUCTURE AS CODE

Quando fizer sentido, documentar/configurar infraestrutura de forma reprodutível.

---

# 165. OBSERVABILIDADE

Monitorar:

```text
latência
erros
uso de memória
CPU
event loop
database connections
queue
failed jobs
Discord latency
```

Problemas operacionais também podem indicar incidentes.

---

# 166. DATABASE CONNECTION POOL

Utilizar pool adequado.

Definir limite.

Não abrir conexão nova para cada request.

---

# 167. CONNECTION EXHAUSTION

Impedir DoS por esgotamento de conexões.

Configurar:

* pool;
* timeout;
* queue;
* rate limit.

---

# 168. TRANSACTION TIMEOUT

Não manter transactions abertas indefinidamente.

---

# 169. BOT WORKER

Jobs críticos devem ser:

```text
idempotentes
retry-safe
observáveis
```

---

# 170. QUEUE POISONING

Job inválido não deve bloquear fila inteira.

Registrar dead-letter/failure state conforme arquitetura.

---

# 171. DATA INTEGRITY

Aplicar constraints no banco.

Exemplos:

```text
UNIQUE discord_id
UNIQUE internal_member_id
```

quando adequado.

Utilizar foreign keys.

---

# 172. CHECK CONSTRAINTS

Exemplo:

```text
patrol_duration >= 0
```

Não confiar apenas na aplicação.

---

# 173. SOFT DELETE

Para dados administrativos importantes, preferir status/soft delete quando apropriado.

Não apagar histórico silenciosamente.

---

# 174. PRODUCTION DATA

Nunca utilizar dados reais de produção automaticamente em ambiente de desenvolvimento.

---

# 175. DATA MASKING

Caso seja necessário copiar dados para staging:

anonimizar dados sensíveis.

---

# 176. ERROR MONITORING

Utilizar serviço de error tracking quando possível.

Exemplo:

```text
Sentry
```

ou equivalente.

Redact secrets antes de enviar eventos.

---

# 177. SECURITY SCAN RECORRENTE

Configurar scans recorrentes de:

* dependências;
* secrets;
* infraestrutura;
* headers;
* vulnerabilities.

---

# 178. PATCH MANAGEMENT

Dependências críticas vulneráveis devem ser atualizadas rapidamente.

Manter processo de atualização contínua.

---

# 179. KNOWN EXPLOITED VULNERABILITIES

Priorizar correções de vulnerabilidades ativamente exploradas.

---

# 180. DEPENDENCY EOL

Detectar bibliotecas/frameworks fora de suporte.

Planejar atualização antes de ficarem EOL.

---

# 181. API VERSIONING

Mudanças incompatíveis devem utilizar estratégia de versionamento adequada.

Evitar endpoints legados esquecidos.

---

# 182. DEPRECATED ENDPOINT

Endpoint antigo deve ser removido após período planejado.

Não deixar APIs antigas inseguras funcionando indefinidamente.

---

# 183. ADMIN ROUTES

Não confiar em URLs obscuras.

Exemplo:

```text
/secret-admin-panel-123
```

não é controle de acesso.

Toda rota precisa de authorization real.

---

# 184. SECURITY THROUGH OBSCURITY

Nunca considerar nomes escondidos ou URLs secretas como segurança.

---

# 185. DATABASE ADMINISTRATION

Evitar alterações diretas em produção via dashboard.

Utilizar migrations e workflows controlados.

---

# 186. SUPABASE SECURITY ADVISOR

Utilizar regularmente o Security Advisor do Supabase.

Corrigir alertas relevantes antes de produção.

---

# 187. RLS REVIEW

Toda nova tabela deve possuir uma decisão explícita:

```text
exposta?
RLS?
policies?
grants?
```

PR que cria tabela sem análise de segurança deve falhar no review.

---

# 188. REALTIME SECURITY

Se utilizar Supabase Realtime:

não publicar tabelas sensíveis indiscriminadamente.

Autorizar subscriptions conforme permissão.

---

# 189. REALTIME DATA MINIMIZATION

Evento realtime deve enviar apenas dados necessários.

Não transmitir dossiê completo porque o frontend precisa saber apenas:

```text
patrol_count changed
```

---

# 190. WEBSOCKET AUTH

Subscriptions devem possuir autenticação e autorização.

Reconectar exige revalidação quando necessário.

---

# 191. SECURITY REVIEW DE FRONTEND

Antes de release:

verificar bundle.

Pesquisar accidental secrets.

Verificar:

* source maps;
* envs;
* endpoints internos;
* debug flags.

---

# 192. DEBUG

Produção:

```text
DEBUG = false
```

Não habilitar ferramentas administrativas internas publicamente.

---

# 193. DEVELOPMENT ROUTES

Rotas como:

```text
/debug
/test
/dev
```

não podem existir publicamente em produção.

---

# 194. TEST ACCOUNTS

Nenhuma conta:

```text
admin/admin
test/test
```

em produção.

---

# 195. DEFAULT CREDENTIALS

Proibido utilizar credenciais padrão.

---

# 196. ADMIN BOOTSTRAP

Primeiro administrador deve ser criado por processo seguro e auditável.

Não deixar endpoint público:

```text
/create-admin
```

após instalação.

---

# 197. SECURITY FAIL CLOSED

Quando serviço de autorização falhar:

```text
NEGAR
```

e não:

```text
permitir porque o banco caiu
```

---

# 198. FALLBACK

Nunca criar fallback:

```text
if permission service unavailable:
  allow admin
```

---

# 199. PRIVILEGE ESCALATION

Testar explicitamente tentativas de:

* alterar role via request;
* alterar própria patente;
* manipular Discord ID;
* reutilizar token;
* alterar targetId;
* chamar endpoint administrativo diretamente.

---

# 200. SECURITY ACCEPTANCE CRITERIA

O projeto NÃO poderá ser marcado como pronto para produção enquanto:

* HTTPS não estiver ativo;
* TLS estiver inadequado;
* secrets estiverem no código;
* RLS estiver ausente em tabelas expostas;
* permissões backend estiverem incompletas;
* endpoints administrativos estiverem sem authorization;
* CI security checks falharem;
* backup não estiver configurado;
* logging/auditoria não existirem;
* vulnerabilidade CRITICAL conhecida estiver aberta sem avaliação;
* testes de autorização falharem.

---

# 201. SECURITY REVIEW FINAL

Antes do deploy final, produzir relatório:

```text
SECURITY REVIEW — CHOQUE BGR
```

Com:

```text
Authentication
Authorization
Session Security
Database
Supabase
Railway
Discord Bot
API
Frontend
Secrets
CI/CD
Dependencies
Backups
Logging
Monitoring
Incident Response
```

Classificar:

```text
PASS
WARNING
FAIL
```

---

# 202. NÃO DECLARAR "INVIOLÁVEL"

Nunca escrever que:

```text
o sistema é impossível de hackear
```

Isso é tecnicamente falso.

A conclusão correta é:

```text
Nenhuma vulnerabilidade conhecida crítica permanece aberta dentro do escopo testado.
```

---

# 203. PRINCÍPIO FINAL

O sistema deverá trabalhar assumindo:

```text
uma camada pode falhar
```

Portanto:

```text
WAF
↓
HTTPS/TLS
↓
Authentication
↓
Authorization
↓
Validation
↓
Application Logic
↓
Database Grants
↓
RLS
↓
Audit
↓
Monitoring
↓
Backups
```

Se uma camada falhar:

as outras continuam protegendo o sistema.

---

# 204. REGRA DE IMPLEMENTAÇÃO

Não apenas documente essas recomendações.

Analise o repositório existente e implemente tudo que for aplicável.

Para cada controle:

```text
IMPLEMENTADO
NÃO APLICÁVEL
PENDENTE
```

Quando classificar como `NÃO APLICÁVEL`, justificar tecnicamente.

---

# 205. NÃO ADICIONAR COMPLEXIDADE SEM BENEFÍCIO

Segurança precisa ser forte, mas também sustentável.

Não adicionar:

* tecnologia exótica;
* criptografia própria;
* firewall caseiro;
* autenticação própria desnecessária;
* bibliotecas abandonadas;
* sistema complexo sem threat model.

Preferir controles:

```text
simples
testados
padronizados
auditáveis
mantidos
```

---

# 206. PROIBIÇÃO DE CRIPTOGRAFIA CASEIRA

Nunca implementar algoritmo criptográfico próprio.

Usar primitives e bibliotecas consolidadas.

---

# 207. ALGORITMOS

Não utilizar algoritmos obsoletos como:

```text
MD5
SHA-1 para segurança
DES
RC4
```

Utilizar algoritmos modernos adequados à finalidade.

---

# 208. SENHAS

Caso o projeto futuramente tenha senhas próprias:

não armazenar senha criptografada reversivelmente.

Utilizar password hashing moderno:

```text
Argon2id
```

ou algoritmo padrão moderno equivalente.

Mas enquanto Discord OAuth for suficiente:

NÃO criar sistema próprio de senha desnecessariamente.

---

# 209. ENCRYPTION AT REST

Supabase/PostgreSQL e infraestrutura devem utilizar os mecanismos de criptografia da plataforma.

Para secrets/tokens particularmente sensíveis armazenados pela aplicação:

considerar criptografia de campo com chave fora do banco.

---

# 210. SEPARAÇÃO DE CHAVES

Não armazenar:

```text
encrypted_data
+
encryption_key
```

no mesmo banco.

Chave deve permanecer no secret manager/ambiente seguro.

---

# 211. CACHE

Nunca armazenar secrets em cache distribuído sem necessidade.

Dados administrativos em cache devem respeitar autorização.

---

# 212. PERMISSION CACHE

Se cachear permissões:

utilizar TTL curto e mecanismo de invalidação.

Mudança de cargo deve refletir rapidamente.

---

# 213. SESSÃO DE USUÁRIO DESLIGADO

Quando membro for:

```text
DESLIGADO
SUSPENSO
```

invalidar acesso correspondente imediatamente.

---

# 214. SECURITY UX

Erro de segurança não deve revelar:

```text
qual role exata falta
qual tabela falhou
qual SQL executou
```

para usuário sem necessidade.

Mensagem:

```text
Você não possui autorização para realizar esta ação.
```

Detalhes permanecem no log interno.

---

# 215. SECURITY ADMIN

Somente usuários autorizados podem visualizar:

* security logs;
* falhas de login;
* configuração de infraestrutura;
* health detalhado.

---

# 216. PRINCÍPIO DE RESPONSABILIDADE

O sistema não deve depender de:

```text
"o administrador vai lembrar de configurar isso depois"
```

Configurações seguras devem ser padrão.

# SECURE BY DEFAULT.

---

# 217. DEFAULTS

Quando configuração de segurança estiver ausente:

utilizar opção mais restritiva.

Exemplo:

```text
unknown permission → deny
unknown origin → deny
unknown redirect → deny
unknown file type → deny
```

---

# 218. SECURITY REGRESSION TESTS

Toda vulnerabilidade corrigida deve gerar teste de regressão quando possível.

Assim ela não reaparece em atualização futura.

---

# 219. POST-INCIDENT

Após qualquer incidente real:

documentar:

* causa;
* impacto;
* timeline;
* correção;
* prevenção;
* controles adicionais.

Sem esconder falhas.

---

# 220. RESULTADO ESPERADO

Arquitetura final:

```text
                         INTERNET
                             │
                       WAF / EDGE
                             │
                          HTTPS
                             │
                         WEB / API
                             │
                 AUTH + RBAC + VALIDATION
                             │
                    APPLICATION CORE
                      │             │
                  DISCORD        WORKERS
                      │             │
                      └──────┬──────┘
                             │
                      SUPABASE POSTGRES
                             │
                  GRANTS + RLS + AUDIT
                             │
                          BACKUPS
```

---

# REGRA FINAL

A segurança do CHOQUE - BGR deverá seguir:

# DEFENSE IN DEPTH

# ZERO TRUST

# LEAST PRIVILEGE

# SECURE BY DESIGN

# SECURE BY DEFAULT

# ASSUME BREACH

Não dependa de apenas HTTPS.

Não dependa de apenas login.

Não dependa de apenas Cloudflare.

Não dependa de apenas RLS.

Não dependa de apenas obscuridade.

Crie múltiplas camadas independentes de proteção.

Ao final, execute uma revisão completa baseada em OWASP ASVS e somente considere a aplicação pronta para produção quando não houver vulnerabilidades críticas conhecidas dentro do escopo testado.
