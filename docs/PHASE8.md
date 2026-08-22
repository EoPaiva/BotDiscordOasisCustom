# Fase 8 — Treinamentos e Cursos

## Interfaces

Painel persistente do membro no canal de Treinamentos:

- **Treinamentos abertos**;
- **Meus treinamentos**;
- **Meus cursos**.

Central Administrativa:

- **Criar treinamento**;
- **Treinamentos ativos**;
- **Histórico**.

Não existem comandos publicados. Consultas e decisões administrativas são ephemeral.

## Criação e publicação

O Comando ou Instrutor seleciona o responsável e informa nome, data/horário, número de vagas,
curso/qualificação opcional e descrição. O serviço valida responsável cadastrado, data futura,
capacidade entre 1 e 100 e duplicidade de nome/data.

Cada treinamento recebe uma mensagem própria no canal oficial, com:

- responsável;
- data e horário;
- vagas ocupadas e capacidade;
- situação;
- curso concedido;
- botões **Participar**, **Cancelar participação** e **Detalhes**.

A mesma mensagem é editada após inscrições, cancelamentos e mudanças de status. IDs da mensagem e
do canal ficam no banco; views de eventos ativos são restauradas antes da conexão após restart.

## Inscrições

- somente membros `ACTIVE` podem participar;
- uma inscrição por membro/evento;
- cancelamento e nova inscrição reutilizam o mesmo registro;
- capacidade é verificada dentro da transação;
- inscrições duplicadas e vagas concorrentes são protegidas pelo banco;
- evento encerrado, cancelado, concluído ou iniciado não aceita novas inscrições.

## Presença e resultado

O responsável abre **Finalizar**, escolhe cada participante e marca:

- presente e aprovado;
- presente e reprovado;
- ausente, com resultado reprovado.

O treinamento só pode ser concluído quando todos os inscritos possuem presença e resultado. A
conclusão grava qualificações, responsável, data, resultado e auditoria no mesmo commit. Dados não
são apagados; treinamentos cancelados também permanecem no histórico.

## Schema

Migration v6:

- `training_events`: agenda, responsável, capacidade, curso, estado e mensagem persistente;
- `training_enrollments`: inscrição, presença, resultado e decisão;
- `member_qualifications`: curso, resultado, responsável e treinamento de origem.

Estados de treinamento: `OPEN`, `CLOSED`, `COMPLETED` e `CANCELLED`.

## Validação

- 55 testes passando;
- criação, inscrição, cancelamento/reinscrição, capacidade concorrente, bloqueio por status,
  presença, resultado, qualificação, cancelamento e recuperação de mensagem cobertos;
- `python main.py --check`: migration 6, 10 cogs e 9 views persistentes;
- `python -m scripts.validate_live_phase8`: três botões do membro, botão administrativo, link da
  Central do Membro e zero comandos remotos confirmados pela API.
