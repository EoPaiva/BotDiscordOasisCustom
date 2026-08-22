# Remodelação visual do Discord — referência CHOQUE - BGR

Status: **CONCLUÍDO — REFERÊNCIA PRINCIPAL APLICADA**.

Este documento substitui o prompt visual semelhante registrado anteriormente. A referência veio de
outro servidor, mas será usada apenas como linguagem visual e princípio de separação. A estrutura
final será adaptada às funcionalidades reais do bot CHOQUE - BGR, sem copiar fluxos comerciais ou
canais sem função.

## Direção visual

- Categorias numeradas e separadas por finalidade.
- Canais no padrão `EMOJI・Nome em Mathematical Italic`.
- Sem hífens visíveis, `_` ou o separador vertical `│`.
- Emoji semântico único antes do caractere `・`.
- Primeira letra em maiúscula estilizada; restante em caixa coerente com o nome.
- Canais de voz seguem o mesmo padrão dos canais de texto.
- Painéis do bot permanecem como mensagens fixas com botões, seletores e modais.

Exemplos de destino:

```text
🏠・𝐶𝑒𝑛𝑡𝑟𝑎𝑙 𝑑𝑜 𝑀𝑒𝑚𝑏𝑟𝑜
⏱️・𝐵𝑎𝑡𝑒 𝑃𝑜𝑛𝑡𝑜
👥・𝐸𝑓𝑒𝑡𝑖𝑣𝑜 𝑒𝑚 𝑆𝑒𝑟𝑣𝑖𝑐𝑜
📥・𝑆𝑜𝑙𝑖𝑐𝑖𝑡𝑎𝑐𝑜𝑒𝑠
📈・𝐶𝑎𝑟𝑟𝑒𝑖𝑟𝑎
⚖️・𝐷𝑖𝑠𝑐𝑖𝑝𝑙𝑖𝑛𝑎
🏆・𝑅𝑎𝑛𝑘𝑖𝑛𝑔 𝑑𝑒 𝐻𝑜𝑟𝑎𝑠
```

## Estrutura adaptada proposta

A ordem abaixo mantém a linha da referência, mas troca **Loja** por **Central do Membro** e adiciona
**Auditoria** e **Arquivo Legado**, exigências do sistema atual.

### 01・RECEPÇÃO

- `🚤・𝐸𝑛𝑡𝑟𝑜𝑢`
- `🚤・𝑆𝑎𝑖𝑢`
- `🚪・𝐶𝑜𝑛𝑣𝑖𝑡𝑒`

Entradas e saídas podem continuar restritas conforme a política de logs; o layout não torna dados
administrativos públicos automaticamente.

### 02・TICKET

- painel de atendimento;
- fila de atendimento;
- tickets de candidatura, transferência e denúncia;
- calls `Aguardando Atendimento` e `Atendimento 1–3` quando o módulo for implementado.

Não serão publicados botões desativados como se fossem funções reais.

### 03・SUPERIORES

- avisos do Comando;
- chat privado;
- registros superiores;
- manual e painel do Comando;
- área isolada de QA/testes administrativos.

### 04・ADMINISTRAÇÃO

- Central Administrativa existente;
- gestão disciplinar;
- movimentações de carreira;
- relatórios administrativos;
- revisão disciplinar e arquivos de medidas.

Não haverá “Loja de Advertência” nem compra de punições.

### 05・CENTRAL DO MEMBRO

- navegação principal;
- solicitações;
- carreira;
- disciplina;
- ranking de horas;
- atalhos para cadastro, ponto e treinamentos.

Esta categoria assume o lugar funcional da categoria **Loja** da referência.

### 06・REGISTRO

- cadastro de membro;
- fila/aprovação de registros;
- membros registrados;
- retirada de tag quando existir fluxo aprovado.

### 07・INFORMAÇÕES

- avisos e anúncios;
- regras CHOQUE e regras BGR;
- regulamento e procedimentos de patrulha;
- hierarquia;
- viaturas, fardamentos, binds e códigos;
- doutrinas, medalhas e condecorações.

O canal encoberto na referência não será inventado.

### 08・MEMBROS CHOQUE

- chat CHOQUE e chat público;
- avisos públicos;
- sugestões;
- mídia, momentos e clips;
- divulgação institucional.

Canais de música, OLX ou lojas externas só serão criados se houver uma necessidade real aprovada.

### 09・BATE-PONTO

- `⏱️・𝐵𝑎𝑡𝑒 𝑃𝑜𝑛𝑡𝑜`: painel persistente existente;
- `👥・𝐸𝑓𝑒𝑡𝑖𝑣𝑜 𝑒𝑚 𝑆𝑒𝑟𝑣𝑖𝑐𝑜`: mensagem única atualizada;
- relatórios e revisão de sessão apenas quando necessários;
- nenhum canal redundante de ativos/inativos se o painel já apresentar a informação.

### 10・EVENTOS

- notificações de eventos;
- call de espera;
- call de evento.

O painel funcional será criado somente na fase de Eventos.

### 11・PATRULHAS

- relatório PTR;
- `Aguardando PTR`, sem contagem de ponto;
- calls de patrulha operacionais;
- ROCAM, Águia/Helicóptero, Blitz, Comboio e Reunião conforme necessidade real.

Calls de patrulha autorizadas continuam ligadas por ID. A futura regra de 15 minutos seguirá
[`MINIMUM_PATROL_TIME_SPEC.md`](MINIMUM_PATROL_TIME_SPEC.md). A call de espera não conta para ponto
nem para o mínimo. `Apaesana` permanece como nome não confirmado e não será criado automaticamente.

### 12・GERENCIAMENTO

- configuração visual do bot;
- configuração de canais, cargos, calls e patentes;
- solicitação/gestão de tags quando implementada;
- status e diagnóstico do sistema.

### 13・TRANSFERÊNCIAS E PARCERIAS

- solicitação de transferência;
- fila administrativa de transferências;
- parceiros e termos institucionais;
- registros históricos sem exposição indevida.

### 14・RECRUTAMENTO

- requisitos e perguntas;
- painel de recrutamento;
- fila e relatórios;
- calls de espera, entrevista/recrutamento e resultado;
- aprovados e reprovados.

O fluxo funcional de recrutamento substituirá o painel “em preparação”.

### 15・CURSOS

- avisos de cursos;
- painel para solicitar/inscrever-se;
- relatórios e resultados;
- instrutores;
- calls de espera, salas de curso, aprovados e reprovados.

### 16・AUSENTE

- call opcional `💤・𝐴𝑢𝑠𝑒𝑛𝑡𝑒`.

Essa call é apenas visual. O estado oficial continua vindo do banco e do cargo sincronizado pelo bot.

### 17・REUNIÃO

- call `📞・𝑅𝑒𝑢𝑛𝑖𝑎𝑜` para reuniões institucionais.

Ela só contará para ponto se for explicitamente autorizada por configuração; por padrão, não conta
para o mínimo de patrulha.

### 18・AUDITORIA

- auditoria do bot;
- moderação Discord;
- alterações administrativas;
- falhas de sincronização e outbox.

### 99・ARQUIVO LEGADO

- canais com histórico que deixarem de ter função ativa;
- mensagens e evidências antigas preservadas;
- acesso privado e somente leitura.

## Regras de adaptação funcional

1. Cada painel persistente terá um canal oficial e uma mensagem reutilizada por ID.
2. Não criar canais duplicados quando um painel único resolve a necessidade.
3. Não excluir canais com mensagens; mover para `99・ARQUIVO LEGADO`.
4. Calls autorizadas e calls válidas para o mínimo de patrulha são conceitos distintos.
5. Permissões serão derivadas da finalidade, não copiadas do servidor de referência.
6. Administração, Superiores, Auditoria e Arquivo permanecem privados.
7. Nomes visuais nunca serão chaves internas do bot.
8. O layout deve continuar compatível com os módulos de Cadastro, Ponto, Solicitações, Carreira e
   Disciplina já publicados.

## Plano executado

1. gerar inventário atual por ID, categoria, permissões, painel e volume de mensagens;
2. produzir mapa `ID atual → categoria/canal futuro → identificador interno`;
3. testar fonte, `・` e separador entre palavras em Desktop, Web e Mobile;
4. apresentar o mapa de criação, movimentação, arquivamento e exclusão segura;
5. criar snapshot completo do servidor;
6. migrar categorias e canais por ID;
7. atualizar `guild_settings`, `panels`, calls autorizadas e links centrais;
8. validar botões, menções, permissões, histórico, voz e zero comandos remotos;
9. manter snapshot de rollback e relatório pós-migração.

## Critérios de conclusão

- padrão visual aplicado a texto e voz;
- categorias na ordem aprovada;
- todas as funcionalidades atuais acessíveis de forma intuitiva;
- nenhuma dependência operacional de nome visual;
- nenhuma perda de mensagens, permissões ou configuração;
- Desktop, Web e Mobile aprovados;
- calls de ponto e patrulha validadas por ID;
- painéis persistentes e Central do Membro atualizados;
- backup e rollback confirmados.
