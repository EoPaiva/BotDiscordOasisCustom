# PROMPT DE IMPLEMENTAÇÃO — CENTRAL DE TAGS, SET E IDENTIDADE

## Contexto

Atualize o sistema existente da corporação CHOQUE no servidor BGR para implementar uma **Central de Tags / Set**, integrada ao sistema atual de identidade, recrutamento, cargos, efetivo e auditoria.

A funcionalidade deve aproveitar a arquitetura já existente. Antes de desenvolver, analise completamente o projeto e identifique:

* sistema atual de cadastro/identidade;
* cargos e sincronização de cargos do Discord;
* sistema de recrutamento;
* sistema de solicitações;
* sistema de auditoria;
* banco de dados;
* mensagens/painéis fixos;
* permissões administrativas;
* estruturas que já possam representar solicitações ou histórico.

Não criar sistemas paralelos caso já exista uma estrutura reutilizável.

A implementação precisa ser robusta, auditável, idempotente e preparada para futuras expansões.

---

# 1. OBJETIVO

Criar uma Central de Tags onde o membro consiga solicitar sua tag pelo Discord, informe/tenha seu ID do MTA vinculado, seja colocado automaticamente na fila de atendimento e acompanhe o processo até a confirmação definitiva.

O fluxo principal será:

**SOLICITAÇÃO → AGUARDANDO SET → SET REALIZADO → AGUARDANDO CONFIRMAÇÃO → CONCLUÍDO**

Com suporte adicional para:

* recusado;
* cancelado;
* expirado;
* pendência;
* reabertura;
* correção de ID;
* auditoria;
* reatribuição;
* sincronização de cargos.

---

# 2. CARGOS DO DISCORD

Criar ou utilizar os cargos configurados no sistema:

### TAG SETADA

Representa que o membro já recebeu sua tag no MTA.

### AGUARDANDO SET

Representa que o membro possui uma solicitação ativa e ainda precisa receber a tag.

### RESPONSÁVEL POR TAG

Cargo que identifica os membros responsáveis pelo atendimento das solicitações.

Os IDs desses cargos devem ser configuráveis e nunca ficar espalhados pelo código.

---

# 3. PAINEL DO MEMBRO

Criar/atualizar uma mensagem fixa com botão:

**[ SOLICITAR TAG ]**

Ao clicar:

1. Verificar identidade do membro.
2. Verificar se já possui `TAG SETADA`.
3. Verificar se existe solicitação ativa.
4. Validar se o membro pode solicitar uma nova tag.
5. Solicitar ou confirmar o ID do jogador no MTA.
6. Registrar a solicitação.
7. Adicionar automaticamente `AGUARDANDO SET`.
8. Notificar os responsáveis.
9. Informar ao membro que ele deve comparecer à **DP de Los Santos**.

Mensagem sugerida:

> **Solicitação registrada**
>
> Sua solicitação de tag foi criada com sucesso.
>
> **ID MTA:** 123
>
> Dirija-se à **DP de Los Santos** para realizar o set.
>
> Aguarde o atendimento e acompanhe o status da solicitação pelo painel.

---

# 4. PREVENÇÃO DE SOLICITAÇÃO DUPLICADA

Um membro não pode possuir duas solicitações simultâneas.

Caso já exista uma:

> **Você já possui uma solicitação de tag em andamento.**
>
> Status atual: `AGUARDANDO SET`

Mostrar, quando possível:

* ID da solicitação;
* status;
* horário;
* posição na fila.

---

# 5. STATUS DA SOLICITAÇÃO

Implementar estados formais:

```text
SOLICITADO
AGUARDANDO_SET
ATENDIMENTO_ASSUMIDO
SET_REALIZADO
AGUARDANDO_CONFIRMACAO
CONCLUIDO
PENDENCIA
RECUSADO
CANCELADO
EXPIRADO
```

As transições devem ser controladas pelo backend.

Não permitir que um botão altere arbitrariamente o status para qualquer estado.

---

# 6. FILA DE ATENDIMENTO

Criar uma fila operacional.

O painel dos responsáveis deve mostrar:

### AGUARDANDO SET

Quantidade total e lista ordenada por tempo de espera.

Exemplo:

```text
#01 João — ID MTA 183 — aguardando 42 min
#02 Pedro — ID MTA 241 — aguardando 35 min
#03 Lucas — ID MTA 392 — aguardando 18 min
```

Priorizar automaticamente quem está esperando há mais tempo.

Permitir pesquisa por:

* nome;
* ID MTA;
* ID Discord.

---

# 7. NOTIFICAÇÃO DOS RESPONSÁVEIS

Sempre que uma nova solicitação for criada:

1. localizar o cargo `RESPONSÁVEL POR TAG`;
2. notificar o cargo;
3. criar/atualizar o painel de atendimento;
4. inserir o novo membro na fila.

Evitar enviar mensagens desnecessárias em excesso.

Preferir atualização de uma mensagem/painel centralizado.

---

# 8. ASSUMIR ATENDIMENTO

Adicionar o botão:

**[ ASSUMIR SOLICITAÇÃO ]**

Quando um responsável assumir:

* registrar quem assumiu;
* registrar data/hora;
* bloquear o atendimento concorrente;
* mudar status para `ATENDIMENTO_ASSUMIDO`.

Somente um responsável pode assumir a solicitação simultaneamente.

Exemplo:

> **Responsável:** Cabo Carlos
> **Status:** Atendimento assumido
> **Horário:** 20:18

---

# 9. LIBERAR/REATRIBUIR

Adicionar:

**[ LIBERAR SOLICITAÇÃO ]**

Caso o responsável não consiga concluir:

* remover o responsável atual;
* voltar a solicitação para a fila;
* manter o histórico;
* registrar motivo;
* permitir que outro responsável assuma.

Nunca apagar o histórico do atendimento anterior.

---

# 10. REALIZAÇÃO DO SET

Depois que o responsável realizar o set no MTA:

**[ SET REALIZADO ]**

Não concluir a solicitação imediatamente.

Exigir confirmação das informações:

* membro;
* ID MTA;
* responsável;
* horário.

O status passa para:

`AGUARDANDO_CONFIRMACAO`

Registrar:

* quem realizou;
* data/hora;
* ID informado;
* ID utilizado no set, se houver confirmação separada.

---

# 11. CONFIRMAÇÃO DO MEMBRO

Quando o responsável marcar `SET REALIZADO`, o membro recebe uma notificação.

Exemplo:

> **Sua tag foi marcada como realizada.**
>
> Confira seu personagem no MTA.
>
> Caso a tag esteja correta, confirme abaixo.

Botões:

**[ ✅ CONFIRMAR TAG SETADA ]**

**[ ❌ NÃO RECEBI A TAG ]**

Somente o próprio membro poderá utilizar esses botões.

Nunca permitir que outro usuário confirme em nome dele.

---

# 12. CONFIRMAÇÃO POSITIVA

Quando o membro clicar:

**CONFIRMAR TAG SETADA**

Executar atomicamente:

1. alterar status para `CONCLUIDO`;
2. remover `AGUARDANDO SET`;
3. adicionar `TAG SETADA`;
4. salvar horário da confirmação;
5. registrar quem realizou o set;
6. registrar quem confirmou;
7. encerrar a solicitação;
8. atualizar o cadastro principal do membro;
9. atualizar o painel administrativo;
10. registrar auditoria.

---

# 13. TAG NÃO RECEBIDA

Se o membro clicar:

**[ ❌ NÃO RECEBI A TAG ]**

Alterar para:

`PENDENCIA`

Solicitar uma justificativa.

Exemplo:

> Explique o problema ocorrido.

Registrar:

* motivo;
* horário;
* membro;
* responsável anterior;
* solicitação;
* evidências, se necessário.

Notificar novamente os responsáveis.

Permitir que o atendimento seja retomado sem criar uma nova solicitação.

---

# 14. EXPIRAÇÃO

Criar mecanismo de expiração.

Solicitações que permanecerem sem atendimento durante o período configurado podem passar para:

`EXPIRADO`

Exemplo de configuração:

```text
Tempo máximo de espera: configurável
```

Não apagar pedidos expirados.

Manter o histórico para auditoria.

O membro poderá solicitar novamente quando permitido.

---

# 15. RECUSA

O responsável poderá utilizar:

**[ RECUSAR ]**

Mas deve informar obrigatoriamente:

* motivo;
* observação;
* responsável.

O status será:

`RECUSADO`

O membro será informado.

O histórico permanecerá armazenado.

---

# 16. CANCELAMENTO

Permitir cancelamento quando necessário.

Registrar:

* quem cancelou;
* motivo;
* data/hora;
* estado anterior.

Nunca excluir a solicitação do banco apenas porque foi cancelada.

---

# 17. CORREÇÃO DE ID MTA

O ID do MTA deve ser tratado como informação importante.

Se o ID estiver incorreto, o sistema deve permitir correção mediante permissão.

Nunca sobrescrever silenciosamente.

Registrar:

```text
ID anterior: 183
ID novo: 291
Alterado por: Cabo Carlos
Data: 23/08/2026 20:31
Motivo: ID informado incorretamente
```

---

# 18. VALIDAÇÃO DO ID

Sempre que possível, validar consistência do ID fornecido com o cadastro principal.

Se houver conflito:

> ⚠️ O ID informado não corresponde ao cadastro atual do membro.

Não impedir automaticamente toda situação excepcional sem permitir tratamento administrativo controlado.

---

# 19. PAINEL ADMINISTRATIVO — CENTRAL DE TAGS

Criar uma central com indicadores:

```text
CENTRAL DE TAGS

Solicitações abertas: 6
Aguardando set: 4
Atendimento assumido: 1
Aguardando confirmação: 1
Pendências: 0
Concluídas hoje: 17
Expiradas: 1
```

Adicionar botões:

**[ TODOS ]**
**[ FALTAM SETAR ]**
**[ EM ATENDIMENTO ]**
**[ AGUARDANDO CONFIRMAÇÃO ]**
**[ PENDÊNCIAS ]**
**[ HISTÓRICO ]**

---

# 20. BOTÃO "TODOS QUE FALTAM SETAR"

Implementar explicitamente:

**[ 👥 TODOS QUE FALTAM SETAR ]**

Esse botão deve listar todos os membros cujo status seja:

`AGUARDANDO_SET`

Exemplo:

```text
MEMBROS AGUARDANDO SET — 7

01. João Silva
ID MTA: 183
Solicitado: 20:14
Aguardando: 42 min

02. Pedro Souza
ID MTA: 241
Solicitado: 20:21
Aguardando: 35 min
```

Também permitir consulta por nome ou ID.

---

# 21. AGUARDANDO CONFIRMAÇÃO

Criar visão específica:

**[ AGUARDANDO CONFIRMAÇÃO ]**

Exemplo:

```text
Carlos — ID 301
Set realizado por: Cabo João
Horário: 20:45
Aguardando confirmação há: 4 min
```

O responsável deve conseguir visualizar rapidamente quem ainda não confirmou.

---

# 22. CHAMAR PARA A DP

Adicionar uma ação administrativa:

**[ CHAMAR MEMBRO ]**

Ao utilizar:

* enviar DM ou notificação apropriada;
* informar que o atendimento pode ser realizado;
* mencionar a **DP de Los Santos**;
* registrar a chamada no histórico.

Exemplo:

> 📍 Seu atendimento de tag está disponível.
>
> Dirija-se à **DP de Los Santos** para realizar o set.

Evitar spam. Implementar cooldown configurável.

---

# 23. TEMPO DE ESPERA

Registrar automaticamente:

* horário da solicitação;
* início do atendimento;
* realização do set;
* confirmação;
* encerramento.

Calcular:

* tempo de espera;
* tempo de atendimento;
* tempo até confirmação;
* tempo total.

Esses dados deverão ser preparados para relatórios futuros.

---

# 24. HISTÓRICO / TIMELINE

Cada solicitação deve possuir uma timeline.

Exemplo:

```text
20:14 — Solicitação criada
20:15 — João entrou na fila
20:18 — Cabo Carlos assumiu atendimento
20:22 — Set realizado
20:23 — Membro confirmou
20:23 — Solicitação concluída
```

Cada evento deve armazenar:

* tipo;
* usuário;
* horário;
* dados relevantes;
* valor anterior;
* valor novo, quando aplicável.

---

# 25. CADASTRO CENTRAL DA IDENTIDADE

A Central de Tags deve integrar-se ao cadastro principal do membro.

A identidade deve poder armazenar:

* ID Discord;
* nome Discord;
* ID MTA;
* nome MTA, quando disponível;
* cargo;
* status da tag;
* data da tag;
* responsável pelo set;
* data da última confirmação;
* histórico de solicitações.

A tag não deve existir como uma informação isolada do restante do sistema.

---

# 26. SINCRONIZAÇÃO DOS CARGOS

Criar rotina de consistência.

Exemplos:

### Banco diz:

`TAG SETADA`

### Discord:

não possui `TAG SETADA`

O sistema deve detectar a divergência.

Da mesma forma:

### Banco:

`AGUARDANDO SET`

### Discord:

possui `TAG SETADA`

Essa inconsistência deve ser:

* corrigida automaticamente quando seguro; ou
* marcada para intervenção administrativa.

Nunca simplesmente ignorar.

---

# 27. REGRAS DE INTEGRIDADE

Um membro não pode:

* possuir duas solicitações ativas;
* possuir dois IDs MTA ativos para a mesma identidade sem histórico;
* confirmar a solicitação de outra pessoa;
* estar simultaneamente em estados incompatíveis;
* ficar com `TAG SETADA` e `AGUARDANDO SET` ao mesmo tempo.

Uma solicitação não pode:

* ter dois responsáveis ativos;
* ser concluída sem passar pela confirmação;
* ser alterada por usuário sem permissão;
* desaparecer sem histórico.

---

# 28. PERMISSÕES

Todas as permissões devem ser verificadas no backend.

Não confiar apenas nos botões do Discord.

Separar permissões para:

### Membro

* solicitar;
* visualizar própria solicitação;
* confirmar;
* informar que não recebeu.

### Responsável por Tag

* visualizar fila;
* assumir;
* liberar;
* marcar set realizado;
* chamar membro;
* registrar pendência.

### Administração

* corrigir ID;
* cancelar;
* recusar;
* editar;
* corrigir inconsistências;
* consultar histórico;
* alterar configurações.

---

# 29. AUDITORIA

Toda alteração importante deve possuir log.

Registrar:

* usuário;
* ação;
* data/hora;
* solicitação;
* estado anterior;
* estado novo;
* motivo;
* entidade afetada.

Exemplos:

```text
TAG_REQUEST_CREATED
TAG_REQUEST_CLAIMED
TAG_REQUEST_RELEASED
TAG_SET_PERFORMED
TAG_CONFIRMED
TAG_NOT_RECEIVED
TAG_REQUEST_REJECTED
TAG_REQUEST_CANCELLED
TAG_REQUEST_EXPIRED
TAG_ID_CHANGED
ROLE_SYNC_CORRECTION
```

---

# 30. BANCO DE DADOS

Antes de criar novas tabelas, verificar se o projeto já possui estruturas equivalentes.

Caso necessário, criar entidades para conceitos como:

* `tag_requests`;
* `tag_request_events`;
* `member_identity`;
* `tag_assignments`;
* `tag_configuration`.

Os nomes reais devem seguir o padrão arquitetural já existente.

Utilizar:

* constraints;
* índices;
* foreign keys;
* unique constraints;
* timestamps;
* status controlado.

Garantir que uma solicitação ativa por membro seja uma regra de banco, quando tecnicamente viável.

---

# 31. IDEMPOTÊNCIA

Eventos e ações não podem duplicar registros.

Exemplo:

Se o responsável clicar duas vezes em `SET REALIZADO`, o sistema não deve:

* criar dois eventos de set;
* mudar novamente o status;
* enviar duas confirmações;
* duplicar cargo.

O mesmo vale para:

* confirmação;
* criação;
* encerramento;
* sincronização.

---

# 32. RECUPERAÇÃO APÓS RESTART

Após reinicialização do bot:

1. reconstruir o estado das solicitações;
2. identificar atendimentos ativos;
3. reconstruir a fila;
4. corrigir mensagens/painéis;
5. verificar cargos;
6. recuperar estados pendentes.

Nunca depender exclusivamente de memória RAM.

---

# 33. MÉTRICAS FUTURAS

Preparar a arquitetura para gerar futuramente:

* quantidade de tags realizadas;
* quantidade de solicitações;
* tempo médio de espera;
* tempo médio de atendimento;
* tempo médio de confirmação;
* quantidade de recusas;
* quantidade de pendências;
* quantidade de IDs corrigidos;
* responsáveis com maior volume;
* responsáveis com melhor tempo médio;
* solicitações expiradas;
* reincidências.

Não é necessário desenvolver um dashboard completo agora, mas os dados precisam ser armazenados corretamente.

---

# 34. EXPERIÊNCIA DO MEMBRO

O processo deve exigir o mínimo de interação manual possível.

O membro deve conseguir:

1. solicitar;
2. visualizar status;
3. comparecer à DP;
4. receber aviso de set realizado;
5. confirmar;
6. concluir.

Não criar fluxos complexos desnecessários.

---

# 35. EXPERIÊNCIA DO RESPONSÁVEL

O responsável deve conseguir trabalhar praticamente apenas pelo painel.

Exemplo:

```text
CENTRAL DE TAGS

🔴 Faltam setar: 4
🟡 Em atendimento: 1
🟠 Aguardando confirmação: 2

[ VER FILA ]
[ TODOS QUE FALTAM SETAR ]
[ AGUARDANDO CONFIRMAÇÃO ]
[ HISTÓRICO ]
```

Ao abrir uma solicitação:

```text
João Silva
Discord: @Joao
ID MTA: 183

Status: AGUARDANDO SET
Solicitado há: 42 min

[ ASSUMIR ]
[ CHAMAR MEMBRO ]
[ RECUSAR ]
```

Depois de assumir:

```text
Responsável: Cabo Carlos

[ SET REALIZADO ]
[ LIBERAR ]
[ RECUSAR ]
```

---

# 36. REGRAS DE UX

Não criar uma quantidade excessiva de mensagens.

Preferir:

* painéis fixos;
* embeds organizados;
* botões;
* modais;
* atualizações da mesma mensagem;
* respostas privadas quando apropriado.

Manter o padrão visual já utilizado pelo projeto.

---

# 37. TESTES OBRIGATÓRIOS

Testar pelo menos:

### Solicitação

* membro sem tag;
* membro já com tag;
* membro com solicitação existente;
* ID inválido;
* ID duplicado/conflitante.

### Atendimento

* responsável assume;
* segundo responsável tenta assumir;
* responsável libera;
* outro responsável assume.

### Set

* set realizado;
* clique duplicado;
* confirmação;
* não recebeu;
* reabertura.

### Finalização

* remoção de `AGUARDANDO SET`;
* adição de `TAG SETADA`;
* persistência;
* auditoria.

### Exceções

* recusa;
* cancelamento;
* expiração;
* restart do bot;
* queda durante operação;
* mensagem duplicada;
* divergência de cargos.

---

# 38. CRITÉRIO DE CONCLUSÃO

A implementação somente deve ser considerada concluída quando:

* o fluxo completo estiver funcional;
* o membro conseguir solicitar;
* a solicitação entrar na fila;
* o responsável conseguir assumir;
* o responsável conseguir marcar o set;
* o membro conseguir confirmar;
* os cargos forem atualizados corretamente;
* o botão de todos que faltam setar funcionar;
* o histórico estiver completo;
* as permissões estiverem protegidas;
* não existirem duplicidades;
* o estado sobreviver a reinicializações;
* as inconsistências de cargo puderem ser detectadas;
* os testes principais passarem.

---

# 39. ENTREGA TÉCNICA

Ao finalizar, apresentar:

1. arquivos alterados;
2. migrations criadas;
3. tabelas alteradas/criadas;
4. novas entidades;
5. novas regras de negócio;
6. permissões adicionadas;
7. eventos/listeners implementados;
8. testes executados;
9. problemas encontrados durante a integração;
10. decisões arquiteturais relevantes;
11. riscos ou limitações restantes.

Não considerar "compila" ou "bot inicia" como critério de sucesso.

A funcionalidade precisa ser validada ponta a ponta.

---

# 40. PRINCÍPIO FINAL

A Central de Tags deve ser tratada como parte da **identidade oficial do membro dentro da corporação** e não apenas como um formulário de solicitação.

O fluxo deve criar uma cadeia confiável:

**Membro → Identidade → Solicitação → Fila → Responsável → Set → Confirmação → Cargo → Histórico → Auditoria**

Todo o sistema deve ser projetado para que, posteriormente, a mesma identidade possa ser utilizada pelos módulos de:

* recrutamento;
* cursos;
* promoções;
* qualificações;
* efetivo;
* patrulhas;
* viaturas;
* relatórios;
* medidas administrativas;
* histórico disciplinar.

Antes de escrever código, analise a arquitetura existente e faça a integração de forma incremental, preservando funcionalidades atuais e evitando regressões.
