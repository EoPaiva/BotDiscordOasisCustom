# Auditoria de rotas de interação

Data: 2026-08-22

## Resultado

- 20 módulos Discord analisados por AST.
- 229 classes de interface (`View`, `Select` e `Modal`).
- 331 componentes interativos.
- 87 `custom_id` explícitos, sem duplicidade.
- zero callbacks ausentes.
- zero classes de interface ativas sem referência.
- 22 views persistentes carregadas em `main.py --check`, além das views de eventos restauradas por
  `message_id`.

`AbsencePanelView` e `AbsenceListView` permanecem preservadas como implementação aposentada. Elas
não possuem entrada ativa porque afastamentos foram consolidados no painel de Solicitações; reativá-las
criaria duas autoridades para o mesmo processo.

## Matriz de entrada

| Área | Painel raiz | Categoria funcional | Permissão | Callback/rota |
|---|---|---|---|---|
| Configuração | `ConfigurationMenuView` | Administração | `settings.manage` | canais, calls, cargos, patentes, regras, painéis e módulos |
| Portaria | `RegistrationPanelView` | Recepção | público controlado | formulário, situação e suporte |
| Revisão de cadastro | `RegistrationReviewQueueView` | Alto Comando | `registration.view` | fila e decisão humana |
| Pessoal | `PersonnelAdminView` | Administração | `personnel.manage` | efetivo, disciplina, processos e serviço |
| Disciplina | `DisciplinePanelView` | Membro | `discipline.view.self` | situação e histórico pessoal |
| Ponto | `PointPanelView` | Bate-ponto | `shift.start` | iniciar, finalizar, horas e histórico |
| Solicitações | `RequestPanelView` | Central do Membro | por ação | afastamento, retorno, reserva, dados e desligamento |
| Carreira | `CareerPanelView` | Central do Membro | membro | perfil, histórico e hierarquia |
| Atividade | `ActivityPanelView` | Central do Membro | membro | atividade, quadro e histórico |
| Operações | `PatrolCentralView` | Patrulhas | membro elegível | fila, prontidão e patrulha |
| Pós-patrulha | `PatrolReportView` | Patrulhas | participante | última patrulha e avaliação |
| Treinamentos | `TrainingPanelView` | Cursos | membro | eventos, inscrições e qualificações |
| Cursos | `CourseCatalogView` | Cursos | requisitos server-side | candidatura por curso |
| Tickets | `TicketPanelView` | Ticket | público controlado | candidatura, transferência, denúncia e outro assunto |
| Sala de ticket | `TicketRoomView` | Atendimentos ativos | solicitante/equipe | assumir, prioridade, participante, aviso, transcript e encerramento |
| Recrutamento | `RecruitmentPanelView` | Recrutamento | público controlado | candidatura, situação e requisitos |
| Medalhas | `MedalsPanelView` | Informações | leitura | catálogo militar |

## Validação reproduzível

```powershell
python scripts/audit_interaction_routes.py
python main.py --check
```

O auditor falha quando encontra `custom_id` duplicado, componente sem callback ou classe ativa sem
referência. A autorização de cada ação continua sendo revalidada no callback; visibilidade do botão
não substitui RBAC.
