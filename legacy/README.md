# Área legada

Estes módulos foram preservados para consulta e migração futura, mas não são carregados pelo bot.

- `farm_system.py`: Farm antigo.
- `cash_control.py`: Caixa antigo.
- `rescue_system.py`: Resgate antigo.
- `absence_system.py`: ausência antiga, desativada para não conflitar com status de membro.
- `hr_system.py`: RH antigo.
- `registration_system.py`: cadastro antigo, substituído pelo fluxo pendente/aprovação.
- `database.py`: camada SQLite anterior.

Não adicione estes módulos à lista `COGS` sem uma migração explícita de dados e regras.
