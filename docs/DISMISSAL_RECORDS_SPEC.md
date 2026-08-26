# Registro de Desligamento de Efetivo

## Estado

Implementado e validado somente no checkout local em 26/08/2026. Nenhum canal foi criado no Discord
real e nenhum rollout foi executado.

## Regra pública

O texto administrativo informado pelo operador continua obrigatório para auditoria, punição ou
decisão interna, mas nunca entra no boletim público. O boletim usa somente uma das duas frases fixas
definidas em `choque/dismissals.py`.

O responsável é classificado como Alto Comando somente quando a identidade canônica da guild possui
o perfil `ALTO_COMANDO` por perfil direto, patente, projeção de cargo Discord ou função habilitada.
Ausência dessa evidência usa o texto administrativo padrão.

## Fluxos cobertos

1. punição/exoneração por `PersonnelService.apply_punishment`;
2. solicitação administrativa de desligamento aprovada por `RequestService`;
3. desligamento humano decorrente de alerta de inatividade por `ActivityService`;
4. alteração direta para `DISMISSED` por `MemberService.change_status`.

Cada transição grava, na mesma transação, uma notificação `DISMISSAL` no outbox durável
`career_notifications`. Correlações únicas impedem repetição do mesmo evento. O destino não recebe
DM; a entrega ocorre somente no canal configurado por `dismissal_log_channel_id`.

## Apresentação

O embed contém título `⚔️ DESLIGAMENTO DE EFETIVO` e campos Militar, Responsável, Situação, Data e
Motivo. A data usa o instante persistido da decisão. O renderizador recalcula a frase pelo snapshot
booleano de Alto Comando e não aceita motivo livre do payload.

O layout declara `superiors.dismissals`, canal de texto privado na categoria Superiores. A aplicação
futura do remodelador cria ou reutiliza o canal e grava seu ID na configuração. A auditoria de
segurança trata exposição desse canal ao cargo padrão como achado crítico.

## Persistência e rollout

A migration 52 reconstrói o `CHECK` do outbox para aceitar `DISMISSAL`, copiando todos os registros e
estados anteriores. Antes de produção: backup íntegro, ensaio da migration em cópia, execução dos
gates na máquina principal, revisão do diff, aplicação com escritor único parado e smoke humano do
canal, RBAC, embed, retry e idempotência. Exige nova autorização explícita do proprietário.
