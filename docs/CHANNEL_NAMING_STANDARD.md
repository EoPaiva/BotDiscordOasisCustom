# Padrão obrigatório para nomes dos canais

Status: **IMPLEMENTADO E APLICADO AO VIVO EM 2026-08-22**.

Esta versão substitui o prompt anterior de nomes. A fonte e a separação passam a seguir
[`DISCORD_LAYOUT_REDESIGN_SPEC.md`](DISCORD_LAYOUT_REDESIGN_SPEC.md).

## Resultado obrigatório

Todos os canais de texto e voz criados ou renomeados pelo sistema seguem:

```text
EMOJI・ᴄᴀɴᴀʟ-ᴄᴏᴍ-ꜰᴏɴᴛᴇ-ꜱᴍᴀʟʟ-ᴄᴀᴘꜱ
```

Exemplos:

```text
🚓・ᴘᴀᴛʀᴜʟʜᴀ-1
📣・ᴀᴠɪꜱᴏꜱ
👑・ʜɪᴇʀᴀʀꞯᴜɪᴀ
📋・ꜱᴏʟɪᴄɪᴛᴀʀ-ᴄᴜʀꜱᴏ
⚖️・ᴅɪꜱᴄɪᴘʟɪɴᴀ
```

O hífen ASCII é o separador visível aprovado entre palavras. Não utilizar espaço, `_`, `│`,
`U+00B7`, `U+2022`, `U+3164` ou `U+2800` entre palavras.

```text
patrulha 1
solicitar_curso
chat·choque
⚖️│disciplina
```

## Função e constantes centrais

O código possui uma única função oficial `format_channel_name()` em `choque/channel_names.py`, que
delega ao formatador Small Caps aprovado. As constantes centrais são:

- `CHANNEL_EMOJI_SEPARATOR = "・"`;
- `SMALL_CAPS_WORD_SEPARATOR = "-"`;
- mapa interno de emoji por tipo de canal.

O emoji continua separado do nome por `U+30FB`; somente as palavras usam hífen:

```text
emoji + U+30FB + palavra-small-caps + "-" + palavra-small-caps
```

`format_legacy_italic_channel_name()` e as constantes `U+3164`/`U+2800` permanecem apenas para
rollback e diagnóstico histórico; nenhum fluxo novo as usa. Salas dinâmicas de ticket e labels das
calls autorizadas usam o mesmo padrão oficial.

### Evidência real de 2026-08-22

- O piloto `📢・ᴀᴠɪꜱᴏꜱ-ᴅᴏ-ᴄᴏᴍᴀɴᴅᴏ` foi aplicado por ID, relido pela API e aprovado pelo proprietário.
- O inventário provou cobertura completa: 97 canais no registry e uma sala dinâmica, sem IDs
  ausentes ou desconhecidos.
- A migração renomeou os 97 alvos restantes sem fallback/revisão e reconciliou 12 labels de calls.
- A comparação contra o snapshot confirmou os 98 canais com mesma categoria, posição e overwrites.
- O bot reiniciou em instância única e o validador ao vivo confirmou 19 categorias, 97 canais de
  layout, uma sala dinâmica e zero comandos publicados.

## Identificadores internos

O nome visual nunca será identificador do sistema. Localização e integração usarão:

- channel ID;
- `panel_type`;
- tipo interno estável, como `DISCIPLINE_PANEL`;
- configuração persistida no banco.

O remodelador usa IDs conhecidos e o registro persistido `discord_layout_registry_v2`. A busca pelo
nome visual existe apenas como recuperação de bootstrap para canais criados pela própria migração.

## Migração segura

1. inventariar canais, mensagens, permissões e integrações atuais;
2. mapear cada ID atual para sua finalidade futura;
3. validar a fonte e os separadores em um canal temporário;
4. criar backup do layout;
5. mover/renomear por ID, sem apagar canais com histórico;
6. atualizar configurações e painéis armazenados;
7. validar permissões, links, menções, botões e calls autorizadas;
8. manter rollback por snapshot.

Nenhuma migração em massa será executada apenas pela semelhança do nome visual.
