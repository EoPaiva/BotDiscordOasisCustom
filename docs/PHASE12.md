# Fase 12 — Remodelação Visual do Discord

## Escopo concluído

A guild foi reorganizada em 19 categorias (`01`–`18` e `99`) seguindo a referência visual adaptada
às funções reais do CHOQUE - BGR. Canais existentes foram movidos e renomeados pelo ID; nenhum canal
com histórico foi excluído.

O resultado ao vivo contém 97 canais e 116 itens contando as categorias. Foram criadas apenas as
áreas que possuem finalidade clara: recepção, atendimento, superiores, administração, central do
membro, registro, informações, comunidade, ponto, eventos, patrulhas, gerenciamento,
transferências/parcerias, recrutamento, cursos, ausente, reunião, auditoria e arquivo legado.

## Padrão de nomes

`choque/channel_names.py` centraliza `format_channel_name()`, `format_category_name()`, o separador
`・` após o emoji e o ponto médio `U+00B7` entre palavras. Todos os canais usam Mathematical Italic, sem hífens,
underscore, espaço ASCII ou `│`. Categorias mantêm a identidade monoespaçada.

O teste ao vivo comprovou que o Discord converte espaços Unicode usuais em hífen e remove fillers.
O antigo `U+17B5`, apesar de preservado pela API, renderizava como quadrado. A correção final testou
dez candidatos em canal temporário e escolheu `U+00B7`, com `U+30FB` como fallback. A migração por
ID atualiza somente o nome, valida a menção, reconcilia labels de calls e cobre salas dinâmicas.

## Identidade interna e segurança

- os 19 IDs de categoria e 97 IDs de canal ficam em `discord_layout_registry_v2`;
- módulos usam `guild_settings`, `panels`, `panel_type` e IDs, nunca o nome visual;
- chamadas autorizadas continuam ligadas pelos 11 IDs originais de patrulha;
- novas calls não entram no ponto automaticamente;
- snapshots completos foram salvos antes do inventário e de cada tentativa de aplicação;
- permissões específicas foram preservadas ao mover canais existentes;
- o provisionador público agora encaminha para a referência visual v2 e não reverte o layout.

## Validação

- 112 testes passando, Ruff e compile smoke limpos;
- `LIVE_PHASE12_OK`: 19 categorias, 97 canais fixos, uma sala dinâmica e 117 itens exatos;
- nomes, tipos e categorias comparados com leitura fresca da API;
- 11 calls autorizadas dentro de Patrulhas, com labels atualizados;
- Central de Configuração em `29/29`;
- painéis de recrutamento, atendimento e administração preservados;
- migration v12, zero comandos remotos e bot online sem erros recentes;
- 68 canais fixos e uma sala de ticket migrados, 10 labels reconciliados e segunda varredura com
  `identified=0`, `review=0` e `fallback=0`.
