# Fase 10 — Configurações e Controle de Módulos

## Escopo concluído

Calls, canais, cargos, RBAC e patentes já estavam configuráveis nas fases anteriores. Esta fase
conclui o item pendente: feature flags simples para os módulos principais, operadas integralmente
pela Central de Configuração.

O botão persistente **Módulos** abre um submenu ephemeral com:

- Cadastros;
- Bate-ponto;
- Solicitações;
- Carreira;
- Disciplina;
- Treinamentos;
- Atividade;
- Ranking;
- Recrutamento;
- Atendimento.

Cada botão mostra `Ativo` ou `Desativado`. A alteração é persistida em `guild_settings`, auditada
como `MODULE_ENABLED` ou `MODULE_DISABLED` e refletida imediatamente no submenu.

## Comportamento

- todos os módulos começam ativos;
- desativar bloqueia novas interações no backend, mesmo por componente antigo;
- o usuário recebe resposta ephemeral informando indisponibilidade administrativa;
- dados, mensagens, sessões e históricos não são apagados;
- jobs necessários para concluir estados existentes, expirações e recuperação continuam ativos;
- reativar restaura imediatamente o acesso normal;
- configuração, auditoria e gestão básica do efetivo não podem ser desligadas por essas flags.

O controle é propositalmente simples. Motivo, previsão e políticas avançadas de manutenção ficam no
Modo de Manutenção já registrado na expansão futura.

## Validação

- 63 testes passando;
- defaults, persistência, idempotência, auditoria, bloqueio e chave inválida cobertos;
- Ruff e compile smoke sem achados;
- `python main.py --check`: migration 7, 11 cogs e 10 views persistentes;
- validação ao vivo confirma o oitavo botão da configuração, estados dos dez módulos e zero
  comandos remotos.
