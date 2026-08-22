# Sincronização automática de patente, cargo e nickname

Status: **IMPLEMENTADO E VALIDADO EM 2026-08-22**.

Implementação: `choque/rank_sync.py`, `cogs/rank_sync_system.py`, migration v10 e
`tests/test_rank_sync.py`. A reconciliação real convergiu três cadastros que estavam em Recruta no
banco para os cargos manuais existentes no Discord (Comandante Geral, Comandante e Coronel), sem
duplicar histórico. `scripts/validate_live_rank_sync.py` confirmou banco, 21 patentes e contagens do
painel. Ressalva externa: o cargo do bot precisa ser movido acima de Comandante Geral para o Discord
permitir corrigir o apelido desse usuário; a recusa já é auditada como `NICKNAME_PERMISSION_ERROR`.

## Objetivo

Manter sincronizados, mesmo quando um administrador alterar cargos manualmente no Discord:

```text
CARGO DO DISCORD
→ PATENTE NO BANCO
→ ABREVIAÇÃO CONFIGURADA
→ NICKNAME
→ HISTÓRICO
→ AUDITORIA
```

A solução deve ser um `RankSyncService` central reutilizado por cadastro, painel de carreira,
alteração de dados, eventos do Discord e reconciliação de startup.

## Fontes de verdade

- Discord: referência operacional do cargo de patente atual.
- Banco: dados estruturados, configuração e histórico.
- Nickname: somente representação visual; nunca deve ser interpretado para recuperar dados.

O cadastro deve armazenar separadamente nome, ID interno e `rank_id`. A patente deve armazenar nome,
abreviação, nível e `discord_role_id`. Nomes e abreviações não podem ficar hardcoded no formatador.

## Nickname obrigatório

Formato:

```text
[ABREVIAÇÃO] NOME [ID]
```

Exemplo:

```text
[RCT] Lucas [152]
```

Uma única função, `format_member_nickname()`, deve ser usada por cadastro, promoção, rebaixamento,
sincronização, alteração de nome e alteração de ID.

## Eventos e origens

O listener de atualização de membro deve comparar os conjuntos anterior e atual de cargos. Somente
cargos vinculados a `ranks.discord_role_id` participam da resolução. Alterações em cargos comuns
devem ser ignoradas.

Quando possível, a auditoria deve diferenciar:

- `PANEL_ACTION`;
- `DISCORD_ROLE_CHANGE`;
- `SYSTEM_RECONCILIATION`;
- `REGISTRATION`;
- `MANUAL_DATA_UPDATE`.

Se o evento não identificar o administrador responsável, o sistema deve registrar responsável não
identificado. Não deve inventar ator nem consultar o audit log do Discord sem justificativa segura.

## Resolução da patente

- Avaliar sempre o conjunto final de cargos, não somente o cargo adicionado ou removido.
- Se houver várias patentes, escolher deterministicamente a de maior `level`.
- Registrar a inconsistência e os cargos encontrados.
- Não remover cargos automaticamente por padrão.
- `AUTO_REMOVE_OLD_RANK_ROLES=false`: resolver a maior patente e registrar alerta.
- `AUTO_REMOVE_OLD_RANK_ROLES=true`: pode remover cargos inferiores após autorização explícita.
- Se não existir cargo de patente, não inventar patente nem apagar histórico.
- A política para membro sem cargo deve permitir manter a última patente ou marcar como não
  sincronizada.

## Idempotência, debounce e concorrência

- Comparar o estado atual com o desejado antes de qualquer escrita.
- Eventos disparados por alterações do próprio bot não podem criar loop.
- Alterações de nickname feitas pelo bot não podem gerar nova alteração inútil.
- Eventos próximos devem ser coalescidos para evitar múltiplos históricos e auditorias.
- Uma troca rápida que adiciona a patente nova e depois remove a antiga deve produzir uma única
  movimentação funcional baseada no estado final.
- Proteções por membro devem ser descartadas após o uso.

## Reconciliação após restart

No startup, para cada membro cadastrado, comparar:

- cargos atuais;
- patente no banco;
- nickname atual;
- patente e nickname esperados.

Divergências devem ser corrigidas com origem `SYSTEM_RECONCILIATION`, sem duplicar histórico. Membro
não cadastrado não deve ser criado automaticamente só por possuir um cargo de patente.

## Enforcement de nickname

Configuração `ENFORCE_MEMBER_NICKNAME`:

- quando habilitada, restaura o nickname esperado após alteração manual;
- somente edita quando o nickname atual for diferente;
- respeita owner, permissões e hierarquia do Discord;
- falhas devem gerar `ROLE_HIERARCHY_ERROR` ou `NICKNAME_PERMISSION_ERROR` sem desfazer a gravação
  segura no banco nem iniciar retries infinitos.

## Cadastro e alterações de dados

- O cadastro solicita nome e ID separadamente.
- Se o membro já possuir um cargo de patente configurado, essa patente deve ser reconhecida.
- Alterar apenas nome preserva ID e patente.
- Alterar apenas ID preserva nome e patente.
- Alterar apenas patente preserva nome e ID.
- Movimentação feita pelo painel e alteração manual de cargo devem convergir para a mesma regra de
  sincronização e o mesmo formatador.

## Histórico e auditoria

Toda mudança funcional automática deve registrar:

- membro;
- patente anterior e atual;
- origem;
- nickname anterior e atual;
- data;
- ator quando conhecido;
- inconsistências encontradas;
- erro de permissão ou hierarquia quando ocorrer.

Uma sincronização de cargo pode ser registrada como `RANK_SYNC`, distinta de `FORMAL_PROMOTION`, e
não deve gerar publicação pública de promoção sem configuração própria.

## Testes obrigatórios

1. Recruta → Soldado atualiza nickname e banco.
2. Soldado → Cabo atualiza nickname e banco.
3. Cabo → Soldado registra rebaixamento.
4. Cargo não relacionado não altera nickname nem patente.
5. Soldado + Cabo resolve Cabo pelo maior nível e registra inconsistência.
6. Perda de todas as patentes aplica a política configurada sem apagar histórico.
7. Nickname alterado manualmente é restaurado com enforcement ativo.
8. Restart com nickname ou banco divergente executa reconciliação.
9. Cargo atualizado pelo próprio bot não gera loop ou histórico duplicado.
10. Troca rápida de cargos gera uma única patente final e uma única movimentação.
11. Falta de permissão para nickname registra erro sem quebrar o banco.
12. Membro não cadastrado é ignorado e não recebe cadastro implícito.

## Critério de conclusão

A pendência só pode ser marcada como concluída quando:

- existir `RankSyncService` central;
- `format_member_nickname()` for a função única de apresentação;
- listener de atualização possuir debounce e idempotência;
- painel, cadastro, atualização manual e startup reutilizarem o mesmo serviço;
- políticas de múltiplas patentes e ausência de patente forem configuráveis;
- cargos não relacionados forem ignorados;
- os doze cenários obrigatórios passarem;
- o fluxo real for validado com alteração manual de cargos no servidor de QA;
- histórico e auditoria forem conferidos sem duplicações.
