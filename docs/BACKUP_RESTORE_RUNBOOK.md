# Backup e restauração — CHOQUE BGR

## Backup consistente

Pare o bot antes de mudanças estruturais e confirme uma única instância. Execute:

```powershell
uv run python scripts/backup_database.py --database data/choque_bgr.db --destination data/security_backups
```

O utilitário usa a API de backup do SQLite e grava de forma atômica. O manifesto contém SHA-256,
tamanho, timestamp UTC, migration, `integrity_check` e contagem de violações de foreign key. Banco e
manifesto permanecem fora do Git.

## Restore drill isolado

```powershell
uv run python scripts/restore_drill.py --backup data/security_backups/ARQUIVO.db
```

O drill restaura para destino temporário, confere hash da origem, integridade, foreign keys e versão
de schema. Nunca aponta o bot diretamente para o arquivo de backup durante o ensaio.

## Restauração real

1. declarar incidente/janela e parar bot/API;
2. preservar banco atual com novo nome e hash, mesmo se corrompido;
3. verificar manifesto e executar restore drill no backup escolhido;
4. restaurar para caminho novo, nunca sobrescrever primeiro;
5. executar `main.py --check`, integrity/FK e contagens críticas;
6. trocar `DATABASE_PATH`, iniciar uma instância e reconciliar Discord/outbox;
7. manter os dois artefatos até aprovação e registrar auditoria externa da operação.

Retenção local automatizada não substitui cópia criptografada fora do host. A política de produção,
RPO/RTO e teste periódico precisam ser configurados no provedor antes do gate PASS.

