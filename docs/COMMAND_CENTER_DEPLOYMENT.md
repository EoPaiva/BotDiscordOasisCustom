# Implantação do Centro de Comando

O status público está na Vercel e o runtime combinado está ativo na Railway por exceção expressa do
proprietário. O gate de segurança continua `FAIL`; produção ativa não equivale a aprovação do gate:

```text
Navegador -> Next.js/Vercel -> runtime combinado/Railway -> SQLite em volume único
                              (FastAPI + bot)             -> outbox -> Discord
```

## Serviço Railway único

Enquanto SQLite for a fonte de verdade, use **um único serviço** apontando para o commit. O manifesto
canônico para deploy pelo repositório é `railway.toml`; `deploy/railway.combined.toml` preserva a
mesma configuração como referência explícita da topologia. `scripts/run_combined.py` executa o
check/migrations antes de iniciar FastAPI e bot, supervisiona os dois processos e encerra ambos se
um deles falhar.

O projeto `pure-connection`, ambiente `production`, reutiliza exclusivamente o serviço
`beautiful-laughter` para o CHOQUE-BGR. Configurações e deployments removidos do sistema antigo não
são reutilizados. O volume `beautiful-laughter-volume` possui 500 MB, está montado em `/data` e usa
`DATABASE_PATH=/data/choque_bgr.db`. O serviço executa uma única réplica em
`asia-southeast1-eqsg3a`, escolha operacional temporária porque as regiões mais próximas recusaram
deploy gratuito em horário de pico. O deployment `5bae72f3-6540-4da4-a78a-470e9dcbdd6f` ficou
`SUCCESS`, `/health` respondeu 200 e o bot conectou à guild oficial; a instância local permaneceu
desligada.

Monte um volume persistente somente nesse serviço, use `DATABASE_PATH=/data/choque_bgr.db`, mantenha
uma réplica e a mesma região durante todo o ciclo SQLite. Railway associa o volume ao serviço e não
permite réplicas com volume; por isso dois serviços não formam uma topologia SQLite compartilhada
válida. Os arquivos `railway.bot.toml` e `railway.api.toml` ficam apenas como referência para o corte
futuro PostgreSQL, quando processos separados poderão compartilhar a mesma fonte de verdade.

O runtime exige `DISCORD_TOKEN`, `DATABASE_PATH`, `DEFAULT_GUILD_ID`, `LOG_LEVEL`,
`APP_ENV=production`, `COMMAND_CENTER_INTERNAL_SECRET`,
`WEB_AUDIT_HASH_SALT`, `WEB_ALLOWED_ORIGINS` HTTPS e `WEB_ALLOWED_HOSTS` explícitos.
`WEB_ADMIN_DISCORD_IDS` só pode ser usado durante bootstrap controlado e requer
`WEB_ADMIN_BOOTSTRAP_ENABLED=true`; remova ambos depois. Defina também um
`RECRUITMENT_TOKEN_SECRET` aleatório e distinto, com pelo menos 32 caracteres. Não escale réplicas.

O worker do bot também é a autoridade única dos jobs do analista de recrutamento. Mantenha
`RECRUITMENT_AI_PROVIDER=disabled` até contratar/aprovar o tratamento externo. Para ativar, defina
provider, API key, base URL, modelo e timeout apenas no ambiente do bot; a API web nunca recebe ou
retorna a chave. Não execute um segundo worker, não envie dumps ao provedor e valide primeiro com o
preview sintético e uma campanha isolada de QA.

## Frontend Vercel

O diretório raiz do projeto Vercel deve ser `web`. A configuração tipada está em `web/vercel.ts`.
Cadastre `APP_ENV=production`, `AUTH_SECRET`, `AUTH_DISCORD_ID`, `AUTH_DISCORD_SECRET`, `AUTH_URL`,
`COMMAND_CENTER_API_URL`, `COMMAND_CENTER_INTERNAL_SECRET` e `DEFAULT_GUILD_ID` pelos ambientes da
Vercel. Não cadastre `DATABASE_URL`, chave Supabase `service_role`, token do bot ou bypass local.

No Discord Developer Portal, autorize apenas o callback Auth.js do domínio efetivo. Preview e
Production devem usar aplicações/callbacks separados quando possível. A sessão dura oito horas e a
API revalida RBAC em toda chamada. O callback OAuth consulta `users/@me/guilds` uma única vez e
guarda apenas a prova booleana de participação; o access token não vai para o browser nem para a API.

## Autenticação BFF -> API

O BFF assina cada requisição com HMAC-SHA256. O canonical inclui método, path/query, hash do body,
guild, ator, correlation ID, timestamp, nonce, emissão da sessão, identidade pública codificada e
prova de guild. A API aceita o nonce apenas uma vez e rejeita assinatura expirada/adulterada.
`COMMAND_CENTER_INTERNAL_SECRET` deve ter no mínimo 32 caracteres e ser igual somente entre BFF e
API daquele ambiente. `COMMAND_CENTER_ALLOW_LEGACY_AUTH` deve permanecer `false`; produção recusa
o fallback mesmo se alguém tentar ativá-lo.

O token Discord permanece restrito ao ambiente server-side do runtime Railway; nunca o cadastre na
Vercel nem o exponha por endpoint/log.

## Corte futuro para Supabase PostgreSQL

1. parar bot e API;
2. gerar backup consistente e testar restauração;
3. aplicar o schema PostgreSQL versionado;
4. importar um snapshot único, comparar contagens e checksums por tabela;
5. executar testes de domínio contra a cópia PostgreSQL;
6. trocar bot e API juntos para a nova `DATABASE_URL`;
7. manter SQLite somente como rollback imutável;
8. liberar tráfego web após health, outbox e reconciliação Discord.

Dual-write é proibido. O provisionamento Supabase permanece deliberadamente pendente até existir
projeto exclusivo, credenciais próprias, ensaio de restauração e autorização de rollout.

## Gate

Antes de publicar: `python -m ruff check .`, `python -m pytest -q`, compileall,
`python main.py --check`, `npm audit`, `npm run typecheck`, `npm run lint`, `npm test`,
`npm run build` e `npm run test:e2e`. Depois, valide login/logout, uma conta MEMBRO, uma conta
COMANDO e o processamento real da outbox em canais isolados de QA. Execute também secret scan,
dependency audits, SBOM, restore drill e a matriz em `docs/SECURITY_CONTROL_MATRIX.md`.

Por padrão, o deploy operacional permanece bloqueado enquanto o veredito de `SECURITY.md` for FAIL.
O corte de 2026-08-22 foi uma exceção pontual autorizada pelo proprietário e não deve ser reutilizado
como precedente. O Vercel CLI 59.4.0 publicou o deployment
`dpl_HdH2HSDYQrQUz3avDeppnDg35ZRr`; `/status`, `/login`, provider Discord e callback esperado foram
validados, sem 5xx. Login/logout humano, revogação real de sessão, contas MEMBRO/COMANDO, os seis
achados do audit Discord e a rotação de credenciais permanecem gates operacionais. Continue usando
`vercel env pull`, `vercel deploy` e `vercel logs` sem copiar segredos e sem cadastrar token Discord
ou credenciais de banco na Vercel.
