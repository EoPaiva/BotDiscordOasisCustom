# Fase 6 — Carreira

## Interfaces

- Painel do membro: ficha de carreira, histórico paginado e hierarquia.
- Central Administrativa: promover, rebaixar e consultar histórico.
- Fluxo obrigatório: membro → nova patente → motivo → confirmação → aplicação.
- Respostas pessoais e administrativas são ephemeral; o painel público é persistente.

## Decisão humana

O sistema exibe tempo na patente, horas do mês e advertências ativas somente como informações. Não
há promoção, rebaixamento, recomendação ou decisão automática.

## Regras

- Patentes são lidas exclusivamente da tabela `ranks`; handlers não possuem hierarquia hardcoded.
- Promoção exige patente de destino com nível maior que a atual.
- Rebaixamento exige patente de destino com nível menor que a atual.
- A patente pode ser escolhida entre todos os destinos válidos; a decisão continua humana.
- Toda movimentação exige motivo e uma segunda confirmação explícita.
- A atualização do membro, a linha append-only em `personnel_actions` e a auditoria são gravadas na
  mesma transação.
- Update condicional impede que duas decisões concorrentes sobrescrevam a patente silenciosamente.
- O histórico registra patente anterior, nova patente, responsável, motivo e data.
- A sincronização do Discord remove apenas cargos de patente anteriores, preservando cargos de
  integrações e demais funções do membro.
- A ficha de membro nunca é apagada.

## Dados

A Fase 6 reutiliza o schema existente sem migration adicional:

- `ranks`: patente, nível, prefixo e cargo Discord;
- `members.rank_id`: patente atual;
- `personnel_actions`: histórico funcional append-only;
- `audit_logs`: evidência transacional da decisão.

O início na patente é derivado da última movimentação, com fallback para a data de ingresso.

## Validação

- Escolha humana de uma patente de destino não adjacente.
- Bloqueio de promoção/rebaixamento na direção errada.
- Histórico append-only e paginação.
- Três botões persistentes no painel de carreira.
- Botão de Carreira presente na Central Administrativa.
- Link de Carreira presente na Central do Membro.
- Zero comandos publicados na guild.

Validação ao vivo: `python -m scripts.validate_live_phase6`.

## Extensão colocada na fila

A sincronização automática de patente quando cargos forem alterados diretamente no Discord está
registrada como pendência separada em [`RANK_SYNC_SPEC.md`](RANK_SYNC_SPEC.md). Ela não faz parte da
entrega concluída desta fase até que debounce, reconciliação e os doze cenários obrigatórios sejam
implementados e validados.
