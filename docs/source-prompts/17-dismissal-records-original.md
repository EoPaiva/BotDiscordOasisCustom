# Instruções para o sistema de desligamento

## Criar o canal

Crie um sistema de registro de desligamentos da corporação com temática militar.

Sempre que um membro for desligado, o sistema deverá enviar automaticamente uma mensagem em um
canal específico de desligamentos, informando:

- Membro desligado
- Responsável pelo desligamento
- Data e horário
- Motivo do desligamento

O sistema deverá verificar automaticamente se o responsável pelo desligamento possui a tag/cargo
**Alto Comando**.

### Caso o responsável possua Alto Comando

O motivo exibido deverá ser automaticamente:

**“Por determinação do Alto Comando, em conformidade com as diretrizes internas e visando à
manutenção da ordem, disciplina e adequada organização do efetivo.”**

### Caso o responsável não possua Alto Comando

O motivo exibido deverá ser automaticamente:

**“Desligamento administrativo realizado em observância às normas internas, aos procedimentos
disciplinares e à organização do efetivo da Corporação.”**

A mensagem deve possuir aparência formal e militar, semelhante a um registro oficial ou boletim
interno.

Modelo de mensagem:

**⚔️ DESLIGAMENTO DE EFETIVO**

**Militar:** @membro\
**Responsável:** @responsável\
**Situação:** Desligado da Corporação\
**Data:** data e horário\
**Motivo:** motivo definido automaticamente pelo sistema

**Registro efetuado para controle, disciplina e organização do efetivo.**

O sistema não deverá permitir que o motivo padrão seja escolhido manualmente. Ele deve ser definido
automaticamente de acordo com o cargo/tag do responsável pelo desligamento.
