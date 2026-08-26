# Auditoria de evolução do ecossistema e do portal CHOQUE

Data de referência: 26/08/2026  
Escopo: BotDiscordOasisCustom, portal `choquebgr.online`, servidor principal e REC CHOQUE.

## Regra de execução

Toda evolução segue a ordem **mapear → reutilizar → corrigir → integrar → criar**. Nenhuma regra de negócio, permissão, histórico, protocolo ou fluxo já funcional será substituído apenas por mudança visual. Métricas, saúde, relações e recomendações só podem usar dados reais do sistema.

## Auditoria técnica em 20 pontos

1. **Arquitetura atual:** aplicação combinada Python/discord.py + FastAPI na Discloud, banco SQLite versionado e portal Next.js 16 no Vercel.
2. **Autoridade de dados:** banco canônico e serviços do backend permanecem responsáveis por identidade, estados, RBAC, auditoria e idempotência.
3. **Gateway:** manter uma única aplicação Discord conectada; o standalone legado continua desligado.
4. **Multi-servidor:** principal e REC devem ser diferenciados por IDs imutáveis, nunca somente por nomes de servidor, canal ou cargo.
5. **Recrutamento existente:** já oferece campanha, elegibilidade, criação, retomada, protocolo, avaliação, autosave, envio e acompanhamento.
6. **Avaliação existente:** uma questão por vez, cronômetro controlado pelo servidor, registro de integridade e retomada segura serão preservados.
7. **Decisão humana:** análises automáticas apenas auxiliam; aprovação, reprovação, punição e mudança sensível continuam sob autoridade humana.
8. **Cursos existentes:** catálogo, qualificações, cargos e histórico devem ser reutilizados antes da criação de novos agregados.
9. **ADV:** consolidar painel, regras, expiração e auditoria sobre as estruturas disciplinares existentes, evitando um segundo sistema paralelo.
10. **Sincronização Discord:** nome, patente e cargos precisam funcionar para membros online ou fora do cache, com retry e reconciliação.
11. **Transferências:** usar protocolo próprio, trilha auditável e limite de patente definido; nunca alterar vínculo por simples evento de interface.
12. **Painéis Discord:** mensagens persistentes devem ser editadas e recuperadas por ID, sem flood ou duplicação após reinício.
13. **Portal:** preservar App Router, TypeScript, Server Actions, autenticação Discord e contratos atuais da API.
14. **Design:** adotar linguagem militar tecnológica sóbria, legível e oficial; evitar aparência genérica de SaaS, IA ou cyberpunk.
15. **Mobile e acessibilidade:** navegação por teclado, foco visível, contraste, alvos de toque e redução de movimento entram como gate de entrega.
16. **Desempenho:** otimizar imagens, reduzir JavaScript desnecessário e não ampliar polling; telemetria deve ser agregada no backend.
17. **Segurança:** validação no servidor, RBAC por ação, proteção contra destino externo no OAuth, snowflakes como texto no navegador e auditoria sem segredos.
18. **Observabilidade:** mostrar somente saúde, filas, latência e eventos comprovados; nenhum número ou topologia pode ser inventado.
19. **Itens removidos desta reformulação:** previsão operacional, replay, máquina do tempo, DNA operacional e capacidade operacional não serão implementados.
20. **Publicação:** cada fase exige testes focados, suíte compatível, lint, typecheck, build, backup proporcional ao risco, deploy controlado e smoke humano quando houver interação real no Discord.

## Estado por domínio

| Domínio | Decisão |
| --- | --- |
| Recrutamento | Reutilizar o fluxo atual e reformular apresentação, orientação e acessibilidade. |
| Avaliação | Preservar regras; aprimorar legibilidade, progresso e revisão final. |
| Cursos | Integrar os painéis e requisitos existentes; ampliar somente após inventário por curso. |
| ADV | Refatorar sobre disciplina e auditoria existentes. |
| Sincronização | Fortalecer fila, retry e reconciliação multi-servidor. |
| Transferências | Criar agregado auditável apenas onde os modelos atuais não comportarem o ciclo. |
| Analytics | Usar consultas reais; nunca preencher a interface com demonstrações apresentadas como produção. |
| QG 3D / Neural Core | Fases posteriores, condicionadas a telemetria real, custo medido e utilidade operacional comprovada. |

## Marco local da Fase B — ADV

- gravidades `LEVE`, `MODERADA`, `GRAVE` e `GRAVISSIMA` persistidas no registro disciplinar canônico;
- prazo configurável em dias, expiração automática transacional e auditoria única por encerramento;
- painel global paginado, sem evidência privada, com IDs de mensagens duráveis e recuperação após reinício;
- publicação administrativa por canal configurado, sem duplicar o painel disciplinar existente;
- gate local: 53 testes focados, 559 testes na suíte completa, Ruff, compileall, inicialização e diff verdes;
- estado: pronto para rollout controlado, ainda sem migration ou recursos novos em produção.

## Fases de entrega

### Fase A — Recrutamento e identidade visual

- aplicar o brasão oficial fornecido;
- consolidar cabeçalho, hero, etapas, ficha, avaliação e acompanhamento;
- preservar URLs, Server Actions, contratos e regras atuais;
- validar desktop, mobile, teclado, contraste, lint, typecheck, testes e build.

### Fase B — Operações administrativas integradas

- ADV, cursos, sincronização e transferências;
- painéis persistentes, RBAC, timeline e recuperação;
- testes de concorrência, idempotência e reinício.

### Fase C — Comando e analytics factuais

- indicadores derivados do banco canônico;
- filtros, exportação e alertas com origem e horário;
- nenhuma métrica simulada.

### Fase D — Visualizações avançadas

- QG 3D e Neural Core somente após contrato de dados, orçamento de desempenho e critérios de avaliação;
- manter alternativa 2D acessível e funcional.

## Gate da primeira entrega

A primeira entrega visual é o recrutamento público com o brasão oficial, sem alterar o comportamento do formulário. Só depois de testes verdes e prévia funcional a reformulação será ampliada para as demais telas.
