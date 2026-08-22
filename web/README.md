# CHOQUE BGR — Centro de Comando Web

Frontend Next.js App Router do mesmo domínio transacional do bot. O navegador autentica por
Discord OAuth; Server Components chamam o BFF, que encaminha a identidade à API FastAPI. O
frontend não acessa banco ou Discord diretamente.

```powershell
Copy-Item .env.example .env.local
npm install
npm run typecheck
npm run lint
npm test
npm run build
npm run test:e2e
```

Para desenvolvimento autenticado sem OAuth, `WEB_DEV_DISCORD_ID` só é aceito quando
`NODE_ENV != production`. Nunca configure esse bypass na Vercel.

As decisões de arquitetura estão em `../docs/adr/004-command-center-topology.md` até
`../docs/adr/007-command-center-refresh.md`; o runbook está em
`../docs/COMMAND_CENTER_DEPLOYMENT.md`.
