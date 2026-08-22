Você já possui acesso ao repositório completo do bot.

Sua tarefa agora é **analisar todo o projeto existente, executar um QA técnico completo, corrigir problemas, otimizar a arquitetura e converter o bot atual em um sistema completo para a corporação CHOQUE - BGR de um servidor MTA:SA Roleplay**.

Não peça novamente o código, estrutura do projeto ou repositório. Trabalhe diretamente sobre o que já está disponível.

# OBJETIVO PRINCIPAL

O objetivo não é simplesmente trocar nome, logo, cores e comandos.

Quero aproveitar a base existente, identificar tudo que está bem implementado e transformar o projeto em um bot profissional de gestão da **CHOQUE - BGR**, priorizando:

**confiabilidade > segurança > organização > performance > experiência do usuário > funcionalidades**

---

# 1. AUDITORIA COMPLETA DO REPOSITÓRIO

Antes de implementar novas funcionalidades, percorra o projeto inteiro.

Identifique:

* arquitetura atual;
* linguagem;
* framework;
* versão das bibliotecas;
* sistema de comandos;
* listeners/eventos;
* banco de dados;
* models/schemas;
* permissões;
* sistema de configuração;
* logs;
* integrações existentes;
* código morto;
* funcionalidades incompletas;
* arquivos duplicados;
* funções duplicadas;
* dependências desnecessárias.

Procure problemas como:

* bugs;
* comandos quebrados;
* race conditions;
* memory leaks;
* listeners duplicados;
* consultas excessivas ao banco;
* timers desnecessários;
* tratamento incorreto de async/await;
* Promises sem tratamento;
* exceções ignoradas;
* falta de validação;
* permissões excessivas;
* credenciais dentro do código;
* IDs hardcoded;
* arquitetura muito acoplada;
* arquivos excessivamente grandes;
* código repetido;
* problemas no tratamento de eventos do Discord;
* possibilidades de perda ou duplicação de dados.

Antes de fazer uma grande alteração, entenda por que a implementação existente foi feita daquela forma.

Não reescreva o projeto inteiro sem necessidade.

---

# 2. QA

Execute o projeto existente e valide o funcionamento atual.

Teste:

* inicialização;
* conexão com banco;
* carregamento dos eventos;
* carregamento dos comandos;
* registro dos slash commands;
* botões;
* modais;
* selects;
* permissões;
* tratamento de erros;
* reinicialização;
* persistência.

Corrija primeiro erros estruturais que possam comprometer funcionalidades novas.

Depois das alterações execute novamente:

* lint;
* build;
* testes;
* inicialização;
* fluxos principais.

Não considere uma funcionalidade concluída apenas porque o código parece correto.

---

# 3. CONVERTER A IDENTIDADE

Converter completamente o projeto para:

# CHOQUE - BGR

Localize referências ao projeto antigo em:

* embeds;
* comandos;
* mensagens;
* banco;
* arquivos;
* configurações;
* botões;
* footer;
* logs;
* comentários relevantes;
* documentação.

Centralize identidade visual.

Não espalhe nome, cor, imagem ou footer pelo projeto inteiro.

Criar uma configuração central semelhante a:

```ts
branding.name
branding.shortName
branding.embedColor
branding.logo
branding.footer
```

O visual deve ser:

* escuro;
* institucional;
* moderno;
* limpo;
* coerente com uma corporação de MTA;
* sem excesso de emojis.

---

# 4. SISTEMA PRINCIPAL: BATE PONTO POR CALL

Essa é uma das funcionalidades mais importantes.

O membro somente poderá bater ponto estando conectado em uma das calls autorizadas.

Fluxo:

`MEMBRO ENTRA EM CALL AUTORIZADA`

↓

`MEMBRO ABRE O PONTO`

↓

`BOT VALIDA CARGO + CALL + SESSÃO`

↓

`INICIA CONTAGEM`

↓

`BOT MONITORA O ESTADO DE VOZ`

↓

`MEMBRO SAI DAS CALLS AUTORIZADAS`

↓

`CONTAGEM ENCERRA`

---

# 5. CALLS AUTORIZADAS

Criar configuração para definir quais canais de voz contam como serviço.

Exemplo:

* Patrulhamento 01
* Patrulhamento 02
* Patrulhamento 03
* Operação
* Apoio
* Treinamento
* Comando

Não colocar esses IDs diretamente na regra de negócio.

Salvar em configuração ou banco.

---

# 6. INICIAR PONTO

Criar:

`/ponto iniciar`

E um painel com botão:

`🟢 Iniciar Serviço`

Para abrir o ponto verificar:

1. membro possui cargo autorizado;
2. membro está conectado em voz;
3. call atual está autorizada;
4. membro não possui outro ponto ativo;
5. membro não está afastado/suspenso caso essas funcionalidades existam.

Se tudo estiver correto, criar uma sessão.

Registrar:

* Discord ID;
* Member ID interno;
* guild;
* início;
* call;
* timestamp;
* status;
* identificador da sessão.

---

# 7. CONTAGEM DO TEMPO

NÃO criar um contador incrementando segundos.

Utilizar timestamps.

Exemplo:

```text
tempo = fimSegmento - inicioSegmento
```

Cada período válido dentro de uma call autorizada pode virar um segmento.

Estrutura conceitual:

```text
SHIFT

08:00 abertura

SEGMENT 1
08:00 → 08:47
Patrulhamento 01

SEGMENT 2
08:47 → 09:30
Patrulhamento 02

09:30 encerramento
```

Total:

`01h30`

Isso permite auditoria real e evita perda de informação.

---

# 8. TROCA DE CALL

Se ocorrer:

`CALL AUTORIZADA A → CALL AUTORIZADA B`

não finalizar o ponto.

Fechar o segmento A e iniciar o segmento B.

O tempo continua normalmente.

---

# 9. SAÍDA DA CALL

Se ocorrer:

`CALL AUTORIZADA → SEM CALL`

ou

`CALL AUTORIZADA → CALL NÃO AUTORIZADA`

interromper a contabilização.

Por padrão, finalizar automaticamente o ponto.

Implementar uma tolerância configurável para quedas rápidas.

Exemplo:

```env
VOICE_GRACE_PERIOD_SECONDS=60
```

Se o membro voltar antes do limite:

continuar a sessão.

Se não voltar:

finalizar.

Garantir que essa lógica não gere duas finalizações simultaneamente.

---

# 10. RECUPERAÇÃO APÓS RESTART

Esse ponto é obrigatório.

O bot não pode esquecer pontos porque reiniciou.

Pontos ativos devem existir no banco.

Quando o bot iniciar:

1. buscar pontos ativos;
2. localizar os membros;
3. verificar seus estados de voz;
4. validar se ainda estão em call autorizada;
5. recuperar sessões válidas;
6. corrigir sessões inconsistentes;
7. evitar contabilização duplicada;
8. registrar recuperação nos logs.

Nunca depender apenas de Collections/Maps em memória.

---

# 11. ANTI-FRAUDE

O bot deve impedir:

* ponto fora da call;
* dois pontos simultâneos;
* contabilização fora da call;
* alteração de horas pelo próprio membro;
* abertura manual retroativa;
* alterações sem log;
* duplicação de segmentos;
* duas finalizações do mesmo ponto;
* manipulação por interação repetida;
* spam em botões/comandos.

Toda alteração administrativa de tempo deve gerar auditoria.

---

# 12. PAINEL DE PONTO

Criar painel fixo.

## CHOQUE - BGR

### Controle de Serviço

Botões:

`🟢 Iniciar Serviço`

`🔴 Finalizar Serviço`

`⏱ Minhas Horas`

`📋 Histórico`

As respostas pessoais devem ser ephemeral sempre que fizer sentido.

---

# 13. STATUS DO MEMBRO

`/ponto status`

Exemplo:

```text
🟢 EM SERVIÇO

Entrada: 20:31
Tempo válido: 01h42
Call atual: Patrulhamento 01
Sessão: #10832
```

---

# 14. MEMBROS EM SERVIÇO

Criar:

`/servico ativos`

Exibir:

```text
CHOQUE - BGR
EFETIVO EM SERVIÇO

01 • João
Soldado
Patrulhamento 01
01h32

02 • Pedro
Cabo
Operação
47min

Total em serviço: 2
```

Também permitir um painel automático em canal configurado.

Quando atualizar:

edite a mensagem existente.

Não envie uma nova mensagem toda vez.

---

# 15. HORAS

Criar:

`/horas hoje`

`/horas semana`

`/horas mes`

`/horas total`

`/horas membro`

`/horas ranking`

Permitir períodos administrativos personalizados.

---

# 16. RANKING

Exemplo:

```text
RANKING SEMANAL — CHOQUE BGR

🥇 João — 19h42
🥈 Lucas — 17h13
🥉 Pedro — 15h59
4. Carlos — 12h21
```

Ranking deve utilizar exclusivamente horas válidas.

---

# 17. META SEMANAL

Criar meta configurável.

Exemplo:

```text
META SEMANAL = 6 HORAS
```

Relatório:

```text
🟢 João — 8h31
🟢 Pedro — 7h10
🟡 Lucas — 5h20
🔴 Carlos — 2h15
```

Não punir ninguém automaticamente.

A decisão continua sendo do comando.

---

# 18. SISTEMA DE MEMBROS

Criar ou adaptar o cadastro existente.

Campos sugeridos:

* Discord ID;
* nick Discord;
* nick MTA;
* ID/personagem;
* patente;
* unidade;
* status;
* ingresso;
* horas;
* cursos;
* observações administrativas;
* última atividade.

Status:

* Ativo
* Afastado
* Reserva
* Suspenso
* Desligado

---

# 19. PERFIL

Criar:

`/membro perfil @usuario`

Exemplo:

```text
JOÃO SILVA

Patente: Cabo
Status: Ativo
Ingresso: 10/07/2026

Tempo total: 74h21
Semana: 08h43
Mês: 31h18

Cursos:
• Formação
• Choque
• Patrulhamento

Último serviço:
20/08/2026
```

---

# 20. HIERARQUIA

Não deixar patente hardcoded dentro dos comandos.

Criar sistema configurável.

Possível estrutura:

```text
rank.id
rank.name
rank.level
rank.discordRoleId
rank.permissions
```

Promoções devem atualizar banco e cargos corretamente.

---

# 21. PROMOÇÃO E REBAIXAMENTO

Criar:

`/promover`

`/rebaixar`

Registrar:

* membro;
* patente anterior;
* nova patente;
* responsável;
* motivo;
* data.

Nunca apagar histórico.

---

# 22. PUNIÇÕES

Criar:

`/punicao aplicar`

`/punicao consultar`

`/punicao revogar`

Tipos configuráveis:

* orientação;
* advertência;
* suspensão;
* afastamento;
* desligamento.

Registrar sempre:

* autor;
* alvo;
* motivo;
* evidência opcional;
* data;
* duração;
* status.

Revogar uma punição NÃO significa apagar o registro.

---

# 23. AFASTAMENTO

Criar:

`/ausencia solicitar`

Membro informa:

* início;
* término;
* motivo.

Enviar para aprovação administrativa.

Botões:

`Aprovar`

`Negar`

Membros afastados devem ser ignorados nos relatórios de meta durante o período aprovado.

---

# 24. TREINAMENTOS

Criar sistema de cursos.

Exemplo:

* Formação;
* Choque;
* Patrulhamento;
* Operações;
* Instrutor;
* outros configuráveis.

Registrar:

* curso;
* instrutor;
* participantes;
* data;
* aprovado/reprovado;
* observação.

---

# 25. EVENTOS E OPERAÇÕES

Criar:

`/evento criar`

Tipos:

* patrulhamento;
* treinamento;
* operação;
* reunião;
* formação.

Possibilitar controle de presença.

Não misturar presença de evento com horas de serviço obrigatoriamente.

---

# 26. LOGS DE AUDITORIA

Criar um serviço central de auditoria.

Registrar:

* abertura de ponto;
* fechamento;
* saída automática;
* recuperação após restart;
* alteração de horas;
* promoção;
* rebaixamento;
* punição;
* afastamento;
* alteração de configuração;
* exclusão/desligamento;
* erros importantes.

Modelo:

```text
AÇÃO
Usuário:
Responsável:
Antes:
Depois:
Motivo:
Data:
ID:
```

Toda ação administrativa relevante deve ser rastreável.

---

# 27. RBAC / PERMISSÕES

Não validar permissões de forma aleatória dentro de cada comando.

Criar sistema central.

Exemplo:

```text
MEMBRO
GRADUADO
INSTRUTOR
COMANDO
ADMINISTRADOR
```

Cada ação possui uma permissão.

Exemplo:

```text
shift.view.self
shift.view.all
shift.edit
member.edit
member.promote
punishment.create
training.manage
settings.manage
```

Mapear essas permissões aos cargos Discord configurados.

---

# 28. BANCO

Analise primeiro o banco atual.

Não faça migração simplesmente por preferência pessoal.

Porém dados críticos não devem depender de arquivos JSON.

Estrutura conceitual:

```text
members
ranks
shifts
shift_segments
voice_events
promotions
punishments
absences
trainings
training_attendance
events
audit_logs
guild_settings
```

Utilize transactions onde houver risco de inconsistência.

Criar restrição lógica/banco impedindo mais de um ponto ativo por membro.

---

# 29. PERFORMANCE

Evite:

* intervalos de 1 segundo;
* consulta constante ao banco;
* atualização de embed a cada segundo;
* listeners duplicados;
* loops globais frequentes;
* busca completa de histórico sem paginação;
* cache sem limite.

Utilize eventos + timestamps.

Faça queries adequadas.

Crie índices para campos usados frequentemente.

Exemplos:

```text
member_id
discord_id
guild_id
shift_status
started_at
created_at
```

---

# 30. SEGURANÇA

Verifique imediatamente o repositório por:

* Discord token;
* senhas;
* URLs privadas;
* chaves;
* secrets;
* credenciais antigas.

Mover secrets para variáveis de ambiente.

Criar `.env.example`.

Nunca colocar valores reais nele.

Aplicar princípio do menor privilégio.

Não solicitar `Administrator` se não for necessário.

---

# 31. CONFIGURAÇÃO

Canais, cargos e regras precisam ser configuráveis.

Exemplo:

```text
callsPermitidas
cargoMembro
cargoComando
cargoAdmin
cargoEmServico
canalLogs
canalPonto
canalOperacoes
canalAdministrativo
metaSemanal
gracePeriod
timezone
```

Evitar IDs espalhados pelo projeto.

---

# 32. TIMEZONE

Internamente prefira timestamps UTC.

Apresentação:

`America/Sao_Paulo`

Não salvar horário formatado como fonte principal do dado.

Salvar timestamps reais.

---

# 33. INTEGRAÇÃO FUTURA COM MTA

Deixe a arquitetura pronta para futuramente termos:

```text
MTA
 ↓
API
 ↓
Backend/Bot
 ↓
Discord
```

Possibilidades futuras:

* vincular Discord ao personagem;
* validar jogador;
* consultar patente;
* conferir facção;
* confirmar que está online;
* validar serviço dentro do MTA;
* sincronizar hierarquia;
* registrar operações;
* cruzar tempo Discord × MTA.

Não implemente isso agora caso prejudique as prioridades principais.

Mas evite criar arquitetura que torne essa integração difícil depois.

---

# 34. SCREENSHOTS DO SISTEMA ANTIGO

Eu também enviarei screenshots do antigo sistema.

Quando recebê-los:

analise individualmente cada imagem.

Identifique:

* funcionalidades;
* informações exibidas;
* botões;
* estrutura;
* fluxo;
* permissões;
* experiência.

Compare com o projeto existente.

Não copie cegamente.

Utilize como referência para recriar e melhorar a experiência dentro da CHOQUE - BGR.

---

# 35. TESTES OBRIGATÓRIOS DO BATE PONTO

Validar pelo menos:

### Teste 1

Fora da call tenta iniciar.

Esperado:

`NEGADO`

### Teste 2

Dentro de call permitida inicia.

Esperado:

`PONTO ATIVO`

### Teste 3

Tenta abrir segundo ponto.

Esperado:

`NEGADO`

### Teste 4

Troca entre duas calls autorizadas.

Esperado:

`SESSÃO CONTINUA`

### Teste 5

Sai da call.

Esperado:

`GRACE PERIOD → FINALIZAÇÃO`

### Teste 6

Retorna durante tolerância.

Esperado:

`SESSÃO CONTINUA SEM DUPLICAR TEMPO`

### Teste 7

Bot reinicia.

Esperado:

`SESSÃO RECUPERADA`

### Teste 8

Dois eventos tentam finalizar simultaneamente.

Esperado:

`UMA ÚNICA FINALIZAÇÃO`

### Teste 9

Admin altera tempo.

Esperado:

`ALTERAÇÃO + AUDIT LOG`

### Teste 10

Membro perde cargo durante ponto.

Esperado:

aplicar regra definida e registrar evento.

---

# 36. PRIORIZAÇÃO

Não tente implementar tudo ao mesmo tempo.

## FASE 1 — QA

* compreender projeto;
* executar;
* encontrar bugs;
* corrigir arquitetura problemática;
* limpar código morto;
* corrigir segurança.

## FASE 2 — CORE CHOQUE

* identidade;
* configuração;
* permissões;
* banco;
* membros.

## FASE 3 — PONTO

* ponto por call;
* segmentos;
* saída automática;
* tolerância;
* recuperação após restart;
* consulta;
* painel;
* logs.

## FASE 4 — GESTÃO

* ranking;
* meta;
* hierarquia;
* promoção;
* rebaixamento;
* afastamento;
* punições.

## FASE 5 — CORPORAÇÃO

* treinamentos;
* operações;
* presença;
* eventos.

## FASE 6 — FUTURO

* dashboard;
* API;
* integração MTA;
* analytics avançado.

Não avance deixando erros críticos para trás.

---

# 37. FORMA DE TRABALHO

Você está autorizado a alterar o código do repositório.

Não fique apenas explicando o que deveria ser feito.

Faça as alterações.

Fluxo esperado:

```text
ANALISAR
↓
EXECUTAR
↓
ENCONTRAR PROBLEMAS
↓
CORRIGIR
↓
REFATORAR
↓
IMPLEMENTAR
↓
TESTAR
↓
REVISAR
```

Preserve funcionalidades existentes que forem úteis.

Antes de remover algo, confirme pelo código se realmente está obsoleto.

---

# 38. NÃO FAÇA

Não:

* peça novamente o repositório;
* gere apenas pseudocódigo;
* diga "você pode implementar";
* entregue apenas uma arquitetura conceitual;
* troque apenas a identidade;
* reescreva tudo sem necessidade;
* apague dados existentes;
* remova funções úteis;
* introduza dependências sem motivo;
* faça alterações administrativas sem audit log;
* use timers constantes para calcular horas;
* deixe secrets no repositório;
* ignore erros de build;
* considere uma função pronta sem testar.

---

# 39. RELATÓRIO DA EXECUÇÃO

Durante o desenvolvimento mantenha uma lista do que foi encontrado e realizado.

Ao final apresente:

### Diagnóstico

Problemas encontrados originalmente.

### Correções

Bugs e problemas corrigidos.

### Refatorações

Arquivos/módulos reorganizados.

### Funcionalidades

O que foi implementado.

### Banco

Mudanças de schema/migrations.

### Sistema de ponto

Como ficou o fluxo completo.

### Segurança

Problemas encontrados e proteções adicionadas.

### Testes

Quais cenários foram realmente testados.

### Arquivos alterados

Lista dos principais arquivos.

### Pendências

O que ainda falta.

### Próximos passos

Somente melhorias posteriores, sem confundir com funcionalidades supostamente concluídas.

---

# REGRA PRINCIPAL

Você já possui o repositório.

Portanto, não produza apenas recomendações.

**Inspecione e trabalhe diretamente no projeto.**

A primeira entrega importante deverá ser um bot estável da **CHOQUE - BGR** com um sistema confiável de bate ponto baseado na presença real nas calls autorizadas.

Depois evolua os módulos administrativos sem comprometer o funcionamento do core.
