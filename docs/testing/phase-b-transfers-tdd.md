# Evidência TDD — Fase B — Transferências

Data: 2026-08-26
Escopo: ciclo auditável de transferência, somente local, sem rollout.

## Contrato protegido

- protocolo estável por guild/ticket e snapshot imutável do pedido;
- timeline append-only;
- teto de patente configurável e bloqueio de escalada;
- aprovação do ticket sem alteração de vínculo;
- segunda decisão humana aplicando a patente previamente autorizada;
- sincronização posterior pela outbox canônica;
- decisão concorrente criando no máximo uma ficha.

## RED

Comando:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_transfer_lifecycle.py
```

Resultado antes da implementação: `4 failed`. As falhas eram as ausências esperadas de
`transfer_case_for_ticket`, `transfer_rank_options`, `decide_transfer` e da proteção contra o bypass
pelo decisor genérico. O primeiro teste inválido de ambiente (`pytest` ausente no Python global) foi
descartado; o ambiente do projeto foi criado por `uv` e o RED foi repetido corretamente.

Commit exclusivo dos testes: `8c20229 test: define auditable transfer lifecycle`.

## GREEN direcionado

O mesmo arquivo terminou com `4 passed`. O conjunto direcionado ampliado terminou com:

```text
66 passed, 2 warnings
```

As advertências são depreciações já conhecidas do `discord.py` em inspeções de labels; não são falhas
funcionais nem foram introduzidas no domínio de transferências.

Commit da implementação: `422e213 feat: add auditable transfer protocols`.

## RED/GREEN da revisão de alcançabilidade

A revisão da branch identificou que a ficha pendente criada por uma transferência aprovada ainda não
era publicada no painel visual de análise. O teste isolado falhou com `Awaited 0 times`, provando que
o fluxo dependeria do comando administrativo legado. O commit `d18e739` preserva esse RED; o commit
`06ae652` amplia o roteamento existente para `TRANSFER` e levou o mesmo teste a `1 passed`.

## Gate completo local

- Python: `567 passed, 21 warnings` em 162,75 s após a correção de alcançabilidade;
- scanner de segredos: `SECRET_SCAN_OK`;
- dependências Python: `No known vulnerabilities found`;
- Ruff: sem achados;
- compileall: aprovado;
- inicialização: `CHECK_OK`, migration 51, 20 cogs, 46 comandos e 34 views persistentes;
- diff: sem erro de whitespace;
- dependências web: zero vulnerabilidades;
- TypeScript e ESLint: aprovados;
- Vitest: 15 arquivos e 57 testes aprovados;
- Next.js: build aprovado.

## Limite operacional

Nenhum secret foi lido ou copiado. Nenhum push, merge, deploy, chamada ao Discord, migração remota,
backup remoto ou alteração de produção foi realizado neste computador. A validação de backup,
migration em cópia, smoke humano e rollout fica obrigatoriamente para a máquina principal e exige
nova autorização explícita do proprietário.
