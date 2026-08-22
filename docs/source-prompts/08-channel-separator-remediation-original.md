Você já possui acesso ao repositório completo do projeto CHOQUE - BGR.

Existe um problema atual nos nomes dos canais importados/criados pelo bot:

* espaços normais foram removidos e os nomes ficaram colados;
* alguns caracteres usados como “espaço visual” estão aparecendo como quadrados `□`;
* exemplo atual incorreto:

```text
Avisos□□□□superiores
Chatsuperiores
Manual□□□□superior
```

Sua tarefa é corrigir isso de forma CENTRALIZADA, SEGURA e COMPATÍVEL com o Discord.

# 1. OBJETIVO

Os nomes dos canais devem continuar usando a fonte Unicode estilizada já definida no projeto, mas com separação visual correta entre palavras.

Exemplo desejado:

```text
📢・𝐴𝑣𝑖𝑠𝑜𝑠ㅤ𝑠𝑢𝑝𝑒𝑟𝑖𝑜𝑟𝑒𝑠
💬・𝐶ℎ𝑎𝑡ㅤ𝑠𝑢𝑝𝑒𝑟𝑖𝑜𝑟𝑒𝑠
📜・𝑅𝑒𝑔𝑖𝑠𝑡𝑟𝑜𝑠ㅤ𝑠𝑢𝑝𝑒𝑟𝑖𝑜𝑟𝑒𝑠
📖・𝑀𝑎𝑛𝑢𝑎𝑙ㅤ𝑠𝑢𝑝𝑒𝑟𝑖𝑜𝑟
🛡️・𝐶𝑒𝑛𝑡𝑟𝑎𝑙ㅤ𝑎𝑑𝑚𝑖𝑛𝑖𝑠𝑡𝑟𝑎𝑡𝑖𝑣𝑎
```

Visualmente deve parecer que existe um espaço normal entre as palavras.

# 2. CARACTERE DE ESPAÇO VISUAL

Utilizar prioritariamente:

```ts
const DISCORD_VISUAL_SPACE = "\u3164";
```

Esse caractere é:

```text
ㅤ
```

Hangul Filler — U+3164.

Criar também fallback:

```ts
const DISCORD_VISUAL_SPACE_FALLBACK = "\u2800";
```

Esse caractere é:

```text
⠀
```

Braille Pattern Blank — U+2800.

# 3. NÃO UTILIZAR O CARACTERE ATUAL

Localize no projeto qualquer caractere Unicode atualmente utilizado para simular espaço que esteja resultando em:

```text
□
```

Remova esse caractere de:

* helpers;
* formatters;
* constants;
* channel templates;
* seed data;
* importação de estrutura;
* migrações;
* configuração inicial;
* nomes hardcoded.

Não apenas corrija os exemplos visíveis.

Faça busca no repositório inteiro.

# 4. CRIAR UM FORMATADOR CENTRAL

Deve existir uma única função responsável por formatar nomes de canais.

Exemplo conceitual:

```ts
formatChannelName(input: string): string
```

Essa função deve:

1. receber nome normal;
2. normalizar espaços;
3. remover espaços duplicados;
4. remover espaços no início/fim;
5. remover acentos quando necessário;
6. aplicar a fonte Unicode matemática já utilizada no projeto;
7. substituir cada espaço entre palavras por `DISCORD_VISUAL_SPACE`;
8. retornar nome final.

Exemplo:

```ts
formatChannelName("Central administrativa")
```

resultado:

```text
𝐶𝑒𝑛𝑡𝑟𝑎𝑙ㅤ𝑎𝑑𝑚𝑖𝑛𝑖𝑠𝑡𝑟𝑎𝑡𝑖𝑣𝑎
```

# 5. NÃO INSERIR VÁRIOS ESPAÇOS

Um espaço lógico deve gerar exatamente:

```text
1 caractere visual
```

Nunca:

```text
ㅤㅤㅤㅤ
```

e nunca uma sequência enorme de invisíveis.

# 6. NÃO GUARDAR NOME ESTILIZADO COMO FONTE DE VERDADE

O sistema deve preferir guardar:

```ts
{
  key: "superior_announcements",
  displayName: "Avisos superiores",
  discordChannelId: "..."
}
```

E gerar o nome visual apenas através de:

```ts
formatChannelName(displayName)
```

Nunca utilizar o nome estilizado como identificador interno.

# 7. IDs DEVEM CONTINUAR INTACTOS

IMPORTANTE:

NÃO apagar canais existentes.

NÃO recriar canais só para corrigir nome.

A correção deve utilizar rename/edit nos canais atuais.

Preservar:

* channel ID;
* categoria;
* permissões;
* permission overwrites;
* posição;
* integrações;
* configurações;
* mensagens;
* painéis;
* referências no banco.

# 8. MIGRAÇÃO DOS CANAIS EXISTENTES

Criar uma rotina segura de migração.

Ela deve detectar canais com:

```text
□
```

ou nomes sem separação que deveriam possuir várias palavras.

Exemplos:

```text
Chatsuperiores
Centraladministrativa
Atividadesemanal
```

Utilizar o nome canônico/configurado no sistema para reconstruir corretamente.

Nunca tentar “adivinhar” palavras apenas olhando o nome colado se já existir configuração com nome original.

Prioridade:

```text
config/displayName
↓
template conhecido
↓
estrutura original
↓
fallback manual/review
```

# 9. NÃO RENOMEAR CEGAMENTE

Se o sistema não souber com segurança qual deveria ser o nome:

não invente.

Registrar:

```text
CHANNEL_NAME_REVIEW_REQUIRED
```

com:

* channelId;
* nome atual;
* motivo.

# 10. ATUALIZAR O IMPORTADOR

O importador/setup responsável por criar a estrutura do Discord deve utilizar obrigatoriamente:

```ts
formatChannelName()
```

Nunca possuir sua própria lógica.

# 11. ATUALIZAR O SETUP AUTOMÁTICO

Se existir:

```text
Instalar estrutura
Criar servidor
Importar estrutura
Repair server
Sync channels
```

todos devem utilizar o mesmo formatter.

# 12. EMOJIS

Preservar o padrão:

```text
EMOJI・NOME
```

Exemplo:

```text
📢・𝐴𝑣𝑖𝑠𝑜𝑠ㅤ𝑠𝑢𝑝𝑒𝑟𝑖𝑜𝑟𝑒𝑠
```

Não alterar emojis existentes durante essa correção.

# 13. CATEGORIAS

Verificar também nomes das categorias.

Se elas utilizarem estilo próprio, preservar.

Não aplicar automaticamente o mesmo formatter caso categorias usem outro padrão.

Centralizar também essa regra, se necessário.

# 14. TESTES UNITÁRIOS

Criar testes para:

```ts
formatChannelName("Chat superiores")
```

esperado:

```text
𝐶ℎ𝑎𝑡ㅤ𝑠𝑢𝑝𝑒𝑟𝑖𝑜𝑟𝑒𝑠
```

Teste:

```ts
formatChannelName("Central     administrativa")
```

deve produzir somente um espaço visual.

Teste:

```ts
formatChannelName("  Central administrativa  ")
```

mesmo resultado.

Teste:

```ts
formatChannelName("Atividade semanal")
```

resultado:

```text
𝐴𝑡𝑖𝑣𝑖𝑑𝑎𝑑𝑒ㅤ𝑠𝑒𝑚𝑎𝑛𝑎𝑙
```

# 15. TESTAR NO DISCORD REAL

Após corrigir:

criar/renomear temporariamente um canal de teste utilizando:

```text
𝐶ℎ𝑎𝑡ㅤ𝑠𝑢𝑝𝑒𝑟𝑖𝑜𝑟𝑒𝑠
```

Validar visualmente em:

* Discord Desktop;
* Discord Web;
* Discord Mobile quando possível.

Se U+3164 não renderizar corretamente em algum cliente importante:

utilizar fallback:

```text
U+2800
```

Não voltar ao caractere que gera quadrados.

# 16. VALIDAÇÃO PÓS-RENAME

Após renomear via API do Discord:

buscar novamente o canal e comparar o nome retornado.

Se Discord normalizar/remover o caractere:

registrar e usar fallback.

# 17. FALLBACK AUTOMÁTICO

Pode implementar estratégia:

```text
tentar U+3164
↓
validar
↓
se não preservado
↓
usar U+2800
```

Mas não ficar alternando infinitamente.

No máximo uma tentativa de fallback por rename.

# 18. LOGS

Registrar somente correções relevantes.

Exemplo:

```text
CHANNEL_NAME_MIGRATED

channelId: ...
before: "Chatsuperiores"
after: "𝐶ℎ𝑎𝑡ㅤ𝑠𝑢𝑝𝑒𝑟𝑖𝑜𝑟𝑒𝑠"
```

# 19. NÃO POLUIR LOG

Não registrar um log para cada chamada normal do formatter.

Somente:

* migração;
* erro;
* fallback;
* inconsistência.

# 20. IDEMPOTÊNCIA

Rodar a migração duas vezes não pode:

* inserir espaços extras;
* duplicar emojis;
* duplicar estilização;
* transformar novamente caracteres já formatados.

A função precisa ser idempotente para entradas já normalizadas ou deve receber sempre o displayName canônico.

# 21. EXEMPLOS QUE DEVEM SER CORRIGIDOS

Errado:

```text
Chatsuperiores
Avisos□□□□□□□□
Manual□□□□□□
Centraladministrativa
Atividadesemanal
```

Correto:

```text
𝐶ℎ𝑎𝑡ㅤ𝑠𝑢𝑝𝑒𝑟𝑖𝑜𝑟𝑒𝑠

𝐴𝑣𝑖𝑠𝑜𝑠ㅤ𝑠𝑢𝑝𝑒𝑟𝑖𝑜𝑟𝑒𝑠

𝑀𝑎𝑛𝑢𝑎𝑙ㅤ𝑠𝑢𝑝𝑒𝑟𝑖𝑜𝑟

𝐶𝑒𝑛𝑡𝑟𝑎𝑙ㅤ𝑎𝑑𝑚𝑖𝑛𝑖𝑠𝑡𝑟𝑎𝑡𝑖𝑣𝑎

𝐴𝑡𝑖𝑣𝑖𝑑𝑎𝑑𝑒ㅤ𝑠𝑒𝑚𝑎𝑛𝑎𝑙
```

# 22. NÃO ALTERAR OUTRAS FUNCIONALIDADES

Esta tarefa é exclusivamente uma correção da camada de nomenclatura visual dos canais.

Não modificar sem necessidade:

* botões;
* permissões;
* banco;
* painéis;
* ponto;
* patrulhas;
* membros;
* recrutamento;
* cargos;
* loja;
* site.

# 23. ENTREGA

Ao finalizar, informe:

```text
1. Qual caractere defeituoso foi encontrado.
2. Onde ele estava sendo utilizado.
3. Qual formatter foi criado/corrigido.
4. Quantos canais foram identificados para migração.
5. Quantos foram renomeados com sucesso.
6. Quantos precisaram do fallback.
7. Quantos ficaram para revisão manual.
8. Testes executados.
```

# 24. REGRA FINAL

A solução correta NÃO é:

```text
trocar manualmente o nome de cada canal
```

A solução correta é:

```text
NOME CANÔNICO
↓
FORMATADOR CENTRAL
↓
UNICODE COMPATÍVEL
↓
DISCORD
```

O resultado precisa ser sustentável.

Se no futuro o padrão visual mudar, deve ser possível migrar todos os canais alterando somente a lógica central do formatter, sem quebrar IDs ou configurações.
