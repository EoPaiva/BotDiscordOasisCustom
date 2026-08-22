# Fase 11 — Recrutamento e Atendimento

## Escopo concluído

Os placeholders públicos de recrutamento e ticket foram substituídos por painéis persistentes e
funcionais. Toda a operação acontece por botões, seletores e modais, sem comandos publicados.

O candidato pode:

- enviar uma candidatura com dados de personagem, idade, experiência e disponibilidade;
- solicitar transferência de outra corporação;
- acompanhar privadamente o histórico e a situação de seus pedidos;
- consultar os requisitos no canal oficial configurado.

O canal de atendimento também permite denúncias privadas. O autor escolhe o membro denunciado e
preenche os fatos por modal; o conteúdo só aparece na fila administrativa e na auditoria. A extensão
posterior adicionou **Outro assunto**, com assunto, descrição e referência opcional, usando a mesma
privacidade, fila, idempotência e auditoria.

## Análise administrativa

A fila persistente separa candidaturas, transferências, denúncias e outros assuntos. Recrutadores
analisam os dois primeiros tipos; o Comando analisa denúncias e outros assuntos. A decisão exige motivo, usa update condicional contra
dupla análise e gera auditoria na mesma transação.

Ao aprovar uma candidatura, o sistema cria automaticamente uma solicitação de membro pendente para
o fluxo de cadastro já existente. Aprovação, cargo e apelido continuam sendo responsabilidade desse
fluxo, sem duplicar regras. O solicitante recebe aviso privado quando possível e o resultado é
publicado no canal institucional configurado.

## Dados e segurança

A migration v8 cria `service_tickets`; a migration v9 preserva os registros existentes e acrescenta
o tipo `OTHER` aos tipos `CANDIDACY`, `TRANSFER` e `REPORT`. Há um índice
parcial que impede duas solicitações abertas do mesmo tipo por pessoa. Registros decididos nunca
são apagados e a carga sensível fica em JSON estruturado no banco, sem publicação no canal público.

Os módulos **Recrutamento** e **Atendimento** podem ser desativados pela Central de Configuração.
Os sete destinos de canal e os três painéis também são configuráveis visualmente.

## Validação

- 75 testes passando na suíte completa atual;
- concorrência de decisão, duplicidade, privacidade e criação atômica do cadastro cobertas;
- Ruff e compile smoke sem achados;
- `python main.py --check`: migration 9, 12 cogs e 13 views persistentes;
- validação ao vivo verifica os painéis, IDs persistentes, sete canais, módulos ativos e zero
  comandos remotos, sem criar candidatura, denúncia ou atendimento fictício.
- extensão `OTHER` validada ao vivo com cinco componentes no painel, ticket pendente na fila e
  `SERVICE_TICKET_SUBMITTED` na auditoria.
