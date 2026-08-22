# Plano de testes de segurança — CHOQUE BGR

## Automatizado em todo PR/push

- scanner de segredos sem imprimir o valor;
- `pip-audit`, `npm audit`, CodeQL, Ruff, pytest, compile/import smoke e `main.py --check`;
- typecheck, ESLint, Vitest, build CSP/nonce e E2E browser;
- SBOM SPDX como artefato;
- testes negativos de assinatura, replay, body tamper, origem, tamanho, mass assignment, BOLA/RBAC,
  sessão revogada, segregação de função, concorrência, backup e restore.

## Pré-produção manual

- OAuth/logout/expiração/step-up com MEMBRO, COMANDO e ADMIN;
- visitante, candidato, recruta e membro com permissões efetivas pela API Discord;
- bot sem Administrator e apenas acima dos cargos gerenciados;
- lockdown e revogação em sessão isolada;
- backup fora do host e restore drill cronometrado;
- CSP em modo enforcement sem erro funcional; cookies e secrets ausentes do bundle/log;
- DAST passivo/autenticado somente em staging dedicado e com rate limit acordado.

Pentest ou DAST agressivo exige autorização explícita, escopo, janela, contatos, limites e plano de
interrupção. Scanner sem escopo não será apresentado como pentest.

