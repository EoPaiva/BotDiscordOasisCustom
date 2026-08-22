# Catálogo histórico de cursos

Status: **IMPLEMENTADO E VALIDADO EM 2026-08-22**.

## Fonte preservada

O canal `1162114694581059584` contém nove editais históricos. As mensagens originais continuam no
mesmo canal e são identificadas por `source_message_id`; o importador registra também SHA-256 do
conteúdo para detectar alteração posterior. O novo painel `COURSE_CATALOG` é uma mensagem separada
e persistida, editada no lugar nos próximos startups.

| Curso | Cargo do curso | Requisito(s) | Nota | Edital importado |
|---|---:|---|---:|---|
| Membro Águia | `1161840644394860636` | Oficiais | 80 | fechado |
| Atirador de Elite | `1147057930491920404` | Praças Graduados | 80 | aberto |
| Modulação | `1162972445888745472` | Praças | 80 | aberto |
| Membro ROCAM | `1161841078069121115` | Praças Graduados | 80 | aberto |
| P1 Tático | `1146622062912344089` | Praças Graduados + P1 Oficial | 80 | aberto |
| P1 Oficial | `1147057821020590100` | Praças Graduados | 80 | aberto |
| ROCAM Elite | `1165176915502571571` | Praças Graduados | 90 | fechado |
| Abordagem Básica | `1165358478227939338` | Praças | 90 | aberto |
| Abordagem Avançada | `1165360167815229511` | Abordagem Básica | 90 | aberto |

Todos preservam o intervalo histórico de 14 dias depois de uma rejeição.

## Regras de solicitação

`TrainingService.apply_to_course()` valida dentro da transação:

- cadastro aprovado e status `ACTIVE`;
- edital aberto;
- todos os cargos exigidos presentes no membro Discord;
- ausência do cargo/qualificação do próprio curso;
- inexistência de solicitação pendente;
- cooldown depois da rejeição.

A aplicação persiste um snapshot da elegibilidade. Instrutor/Comando decide pela Central
Administrativa; updates condicionais impedem duas decisões vencedoras. Aprovar a solicitação não
concede o cargo: a qualificação continua dependendo de treinamento, presença e resultado humano.

## Schema e operação

Migration v13:

- `course_catalog`;
- `course_requirements`;
- `course_applications`;
- índice parcial de uma solicitação pendente por membro/curso.

Importação reproduzível:

```powershell
python -m scripts.import_historical_courses
```

Validação ao vivo:

```powershell
python -m scripts.validate_live_course_catalog
```
