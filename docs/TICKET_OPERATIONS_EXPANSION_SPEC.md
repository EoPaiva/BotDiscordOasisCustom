# Expansão operacional de tickets — CHOQUE BGR

Status: concluído e validado localmente e no Discord real em 2026-08-22. Migration v22, operação
visual persistente, Centro de Comando Web, rollout com snapshot/rollback e matriz real de permissões
foram entregues. A sala histórica, seu ID, mensagem e histórico foram preservados.

## Objetivo

Cada ticket deve ser uma sala privada real, organizada em uma categoria exclusiva para atendimentos
ativos. A mensagem de abertura deve mencionar a sala e, dentro dela, mencionar o cargo configurado
como responsável por tickets. O fluxo continua integralmente por botões, selects e modais.

## Contrato funcional

- Persistir por ID a categoria de tickets ativos, a categoria de arquivo quando utilizada e o cargo
  responsável. Nunca localizar esses recursos pelo nome visual.
- Criar/mover a sala para a categoria exclusiva sem alterar a privacidade: solicitante, bot, cargo
  responsável configurado e perfis COMANDO/ADMINISTRADOR. `@everyone` permanece sem visualização.
- A primeira mensagem registra protocolo, solicitante, tipo, assunto, relato, evidências, prioridade,
  estado e responsável atual. A menção ao cargo ocorre uma única vez na criação para evitar spam.
- O painel persistente da sala oferece: assumir/liberar atendimento, alterar prioridade, adicionar ou
  remover participante autorizado, avisar solicitante, gerar transcrição, encerrar e, para quem tiver
  permissão, reabrir. Ações indisponíveis devem ser desabilitadas ou negadas de forma ephemeral.
- Encerramento exige motivo e confirmação, publica o resultado idempotente, gera transcrição
  minimizada, remove acesso operacional desnecessário e move/arquiva a sala. Reabertura restaura a
  mesma sala quando ainda existe; nunca cria duplicata silenciosa.
- Mudanças concorrentes usam versão/update condicional. Toda alteração relevante, participantes,
  responsável, prioridade, transcrição, encerramento e reabertura possui auditoria append-only.
- Configuração deve existir no painel administrativo e no Centro de Comando Web com preview e
  validação da hierarquia do bot, sem exigir Administrator.

## Segurança e testes mínimos

- Validar pela API as permissões efetivas de solicitante, visitante sem cargos, membro comum,
  responsável por tickets, Comando e bot.
- Cobrir criação na categoria, menção única, assumir concorrente, participante sem privilégio,
  fechamento idempotente, transcrição sem secrets, reabertura e recuperação no startup.
- Preservar o tipo já existente “Outro assunto” e todos os históricos, IDs e tickets anteriores.
