+# PROMPT MESTRE — EXTENSÃO DO SISTEMA CHOQUE / BGR

## 1. CONTEXTO

Evoluir o sistema já existente da corporação **CHOQUE**, do servidor **BGR (MTA)**.

Este prompt deve ser tratado como uma **extensão do sistema atual**, e não como um projeto do zero.

### FUNCIONALIDADES QUE JÁ EXISTEM

Não recriar, substituir ou duplicar:

* **Central de Tags / Set**
* **Bate-ponto automático por presença em canais de patrulha**

Esses dois sistemas já foram implementados em etapas anteriores.

As novas funcionalidades devem **consumir e integrar-se aos dados existentes**.

Em especial:

* o novo sistema deve utilizar o histórico do bate-ponto já existente;
* não criar outro sistema de ponto;
* não criar outro sistema de identidade se já existir;
* não recriar a Central de Tags;
* aproveitar a autenticação, cargos, banco, auditoria e componentes já existentes.

Antes de alterar qualquer código, analisar a implementação atual para descobrir exatamente como esses sistemas funcionam.

---

# 2. OBJETIVO DESTA ETAPA

Implementar somente os módulos ainda necessários:

1. Sistema de viaturas;
2. Comandante automático;
3. Efetivo organizado por viatura;
4. Histórico de composição das viaturas;
5. Evolução do relatório de PTR;
6. Registro de perdas e irregularidades;
7. Sistema de progressão automática de Recruta até Cadete;
8. Sistema de promoções;
9. Sistema de rebaixamentos;
10. Sistema de mérito após Cadete;
11. Sistema de candidatura para Oficial;
12. Avaliação estruturada de candidatos;
13. Área exclusiva do responsável por upamento;
14. Relatórios de candidatura;
15. Criação automática dos canais necessários;
16. Auditoria e integração dos novos módulos;
17. Sincronização dos cargos envolvidos.

---

# 3. PRINCÍPIO DE INTEGRAÇÃO

O sistema já possui uma fonte de verdade para o bate-ponto.

Utilizar os dados existentes para calcular:

* tempo acumulado;
* tempo válido;
* histórico de patrulhas;
* experiência do membro.

Não desenvolver outro mecanismo de contagem de ponto.

A arquitetura deverá conectar:

```text
BATE-PONTO EXISTENTE
        ↓
HORAS ACUMULADAS
        ↓
PROGRESSÃO DE CARREIRA

BATE-PONTO EXISTENTE
        ↓
PRESENÇA EM PATRULHA
        ↓
VIATURA
        ↓
PTR / OCORRÊNCIAS

IDENTIDADE EXISTENTE
        ↓
CARREIRA
        ↓
MÉRITO
        ↓
CANDIDATURA A OFICIAL
        ↓
UPAMENTO
```

---

# 4. SISTEMA DE VIATURAS

Criar um sistema que interprete os membros presentes em uma mesma call de patrulha como uma unidade operacional.

Exemplo:

```text
PATRULHA ALFA

Sargento Carlos
Cabo João
Soldado Pedro
```

Resultado:

```text
VIATURA 01

Comandante: Sargento Carlos

Integrantes:
• Sargento Carlos
• Cabo João
• Soldado Pedro
```

A viatura deve ser criada automaticamente quando existir pelo menos um membro em uma call de patrulha.

---

# 5. RELAÇÃO ENTRE CALL E VIATURA

Uma call de patrulha representa a composição operacional atual da viatura.

Quando um membro:

### Entra na call

Adicionar à viatura.

### Sai da call

Remover da viatura.

### Troca para outra call de patrulha

Remover da viatura anterior e adicionar à nova.

### Sai completamente das patrulhas

Encerrar vínculo com a viatura.

O ponto já existente deve continuar funcionando conforme sua implementação atual.

O sistema de viaturas apenas deve consumir o estado da presença/patrulha.

---

# 6. IDENTIFICADOR DA VIATURA

Cada viatura deverá possuir identificador próprio.

Exemplo:

* Viatura 01
* Viatura 02
* Viatura 03

Não utilizar apenas o nome do canal como identidade interna.

Persistir:

* ID interno;
* número visual;
* patrulha;
* canal;
* status;
* comandante;
* integrantes;
* início;
* término;
* histórico.

O algoritmo de numeração deve evitar duplicidades e preservar histórico.

---

# 7. COMANDANTE AUTOMÁTICO

O sistema deve escolher automaticamente o comandante da viatura com base na hierarquia real do servidor.

Criar uma estrutura central de prioridade de cargos.

Exemplo conceitual:

```text
1º Tenente
2º Tenente
Aspirante
Cadete
Subtenente
1º Sargento
2º Sargento
3º Sargento
Cabo
Soldado
Recruta
```

A hierarquia real cadastrada no projeto deve prevalecer.

---

# 8. REGRAS DO COMANDANTE

Quando entrar um membro de patente superior:

* recalcular comandante.

Quando o comandante sair:

* recalcular comandante.

Quando houver alteração de cargo:

* recalcular comandante.

Quando houver empate hierárquico:

Utilizar uma regra secundária configurável, por exemplo:

1. maior patente;
2. maior tempo na patente;
3. maior tempo de corporação;
4. critério administrativo configurado.

Registrar qualquer alteração.

---

# 9. HISTÓRICO DA VIATURA

Registrar:

* criação;
* entrada de integrante;
* saída;
* comandante;
* troca de comandante;
* mudança de patrulha;
* encerramento.

Exemplo:

```text
20:10 — Viatura 01 criada
20:12 — João entrou
20:15 — Carlos assumiu como comandante
20:41 — Pedro saiu
21:00 — Viatura encerrada
```

O histórico nunca deve ser apagado quando a viatura terminar.

---

# 10. EFETIVO EM SERVIÇO

Criar/atualizar o painel existente de efetivo para apresentar as pessoas agrupadas por viatura.

Exemplo:

```text
EFETIVO EM SERVIÇO

VIATURA 01 — PATRULHA ALFA
Comandante: Sargento Carlos

• Sargento Carlos
• Cabo João
• Soldado Pedro

VIATURA 02 — PATRULHA BRAVO
Comandante: Cabo Marcos

• Cabo Marcos
• Soldado Lucas

SEM VIATURA
• Nenhum

TOTAL: 5
VIATURAS ATIVAS: 2
```

Atualizar a mensagem existente, evitando spam.

---

# 11. MEMBROS SEM VIATURA

Caso exista membro considerado em serviço, mas sem vínculo com uma viatura:

mostrar claramente:

**SEM VIATURA**

Nunca simplesmente ocultar o membro.

---

# 12. RELATÓRIO DE PTR

Evoluir o sistema de PTR já existente.

Não criar um segundo mecanismo se o projeto já possuir estrutura de relatório.

O PTR deverá utilizar os dados da viatura para preencher automaticamente:

* viatura;
* patrulha;
* comandante;
* integrantes;
* início;
* término;
* duração.

O usuário deverá complementar apenas as informações realmente necessárias.

---

# 13. REGISTRO DE OCORRÊNCIAS / PERDAS

Adicionar ao PTR uma área específica para registrar quem "perdeu", abandonou ou teve alguma irregularidade na patrulha.

Campos:

* ID Discord;
* nome;
* ID MTA;
* patente;
* viatura;
* data;
* horário;
* motivo;
* artigo;
* descrição;
* responsável;
* print;
* evidência;
* observação.

---

# 14. EXEMPLO DE OCORRÊNCIA

```text
MEMBRO REGISTRADO

Nome: João Silva
ID MTA: 183
Patente: Cabo
Viatura: 02

Motivo:
Abandono de PTR

Artigo:
Art. XX

Responsável:
Sargento Carlos

Evidência:
Print anexado
```

---

# 15. CATEGORIAS DE OCORRÊNCIA

Criar estrutura configurável.

Categorias iniciais:

* abandono de PTR;
* ausência;
* atraso;
* descumprimento de procedimento;
* conduta inadequada;
* erro operacional;
* perda de patrulha;
* outra ocorrência.

Não deixar esses valores espalhados pelo código.

---

# 16. ARTIGOS

Utilizar uma estrutura centralizada para artigos.

Cada artigo deverá possuir:

* código;
* título;
* descrição;
* categoria;
* gravidade;
* ativo/inativo.

O sistema de PTR deve permitir selecionar o artigo relacionado à ocorrência.

---

# 17. RELATÓRIO FINAL DE PTR

Ao finalizar o PTR, gerar uma consolidação automática.

Exemplo:

```text
RELATÓRIO DE PTR

Viatura: 01
Patrulha: Alfa
Comandante: Sargento Carlos

Início: 20:00
Término: 22:10
Duração: 02h10

Efetivo:
• Sargento Carlos
• Cabo João
• Soldado Pedro

Ocorrências: 2
Membros registrados: 1
Evidências: 2
```

---

# 18. PROGRESSÃO AUTOMÁTICA DE CARREIRA

Criar sistema de promoção automática baseado nas **horas de bate-ponto já existentes**.

O sistema será responsável somente pela evolução:

**RECRUTA → CADETE**

Ao alcançar Cadete:

**a progressão por horas termina.**

---

# 19. METAS

Utilizar inicialmente estas metas:

| Progressão                | Horas acumuladas |
| ------------------------- | ---------------: |
| Recruta → Soldado         |               4h |
| Soldado → Cabo            |               8h |
| Cabo → 3º Sargento        |              13h |
| 3º Sargento → 2º Sargento |              19h |
| 2º Sargento → 1º Sargento |              26h |
| 1º Sargento → Subtenente  |              33h |
| Subtenente → Cadete       |              40h |

As metas precisam ser configuráveis.

---

# 20. HORAS ACUMULADAS

As horas são cumulativas.

Exemplo:

```text
4h  → Soldado
8h  → Cabo
13h → 3º Sargento
19h → 2º Sargento
26h → 1º Sargento
33h → Subtenente
40h → Cadete
```

O contador não zera após promoção.

---

# 21. TEMPO MÍNIMO NA PATENTE

Para impedir que o membro seja promovido várias vezes em sequência apenas por ter acumulado horas rapidamente, aplicar permanência mínima.

Valores iniciais:

| Progressão                | Permanência mínima |
| ------------------------- | -----------------: |
| Recruta → Soldado         |                 0h |
| Soldado → Cabo            |                 2h |
| Cabo → 3º Sargento        |                 3h |
| 3º Sargento → 2º Sargento |                 4h |
| 2º Sargento → 1º Sargento |                 5h |
| 1º Sargento → Subtenente  |                 5h |
| Subtenente → Cadete       |                 6h |

Também configurável.

---

# 22. REGRAS PARA PROMOÇÃO AUTOMÁTICA

Antes de promover, verificar:

* horas mínimas;
* permanência mínima;
* identidade válida;
* cargo atual;
* ausência de inconsistência crítica;
* existência de promoção anterior;
* regras administrativas configuradas.

Não promover automaticamente se o estado do membro estiver inconsistente.

---

# 23. PROMOÇÃO AUTOMÁTICA

Quando os requisitos forem cumpridos:

1. atualizar o cargo no banco;
2. alterar o cargo do Discord;
3. registrar promoção;
4. registrar horas;
5. registrar data;
6. publicar;
7. auditar.

Exemplo:

```text
PROGRESSÃO AUTOMÁTICA

João Silva

Soldado → Cabo

Horas acumuladas: 08h14
Tempo na patente: 03h42
Requisitos: ✅

Promoção realizada automaticamente.
```

---

# 24. PROCESSAMENTO APÓS RESTART

Se o bot estiver offline quando o membro atingir uma meta:

ao retornar:

1. calcular situação atual;
2. verificar promoção elegível;
3. processar corretamente;
4. evitar duplicidades;
5. registrar normalmente.

Nunca depender de um evento único para efetivar a progressão.

---

# 25. CANAIS DE PROMOÇÃO

Criar caso não existam:

### `#promocoes`

Publicações de promoções concluídas.

### `#progressao-automatica`

Logs das promoções automáticas.

Evitar duplicação de canais existentes.

---

# 26. PROMOÇÕES MANUAIS

Criar estrutura administrativa para promoção por mérito.

Campos:

* membro;
* cargo anterior;
* cargo novo;
* motivo;
* responsável;
* data;
* evidência;
* observações.

Toda promoção manual deve gerar auditoria.

---

# 27. REBAIXAMENTOS

Criar estrutura administrativa para rebaixamentos.

Campos:

* membro;
* cargo anterior;
* cargo novo;
* motivo obrigatório;
* artigo;
* responsável;
* data;
* evidência;
* observações.

Nunca alterar cargo silenciosamente.

---

# 28. CANAL DE REBAIXAMENTO

Criar caso não exista:

### `#rebaixamentos`

Utilizar permissões apropriadas para limitar informações sensíveis.

---

# 29. MÉRITO APÓS CADETE

A partir de Cadete, não haverá promoção automática por horas.

Criar sistema de registro de mérito para subsidiar decisões.

Categorias:

### Mérito positivo

* liderança;
* desempenho;
* iniciativa;
* participação;
* comportamento exemplar;
* contribuição institucional.

### Mérito negativo

* falha;
* desempenho inadequado;
* comportamento;
* ocorrência relevante.

Cada registro possuirá:

* tipo;
* peso;
* motivo;
* responsável;
* data;
* evidência;
* observação.

O sistema nunca deverá transformar uma pontuação simples em promoção automática.

---

# 30. HISTÓRICO DE CARREIRA

A carreira do membro deve possuir timeline.

Exemplo:

```text
23/08 — Recruta → Soldado
24/08 — Soldado → Cabo
26/08 — Cabo → 3º Sargento
05/09 — Mérito positivo registrado
12/09 — Promoção por mérito
```

Registrar também rebaixamentos.

---

# 31. CANDIDATURA PARA OFICIAL

Criar um sistema de candidatura realizado exclusivamente pelo site.

No Discord deve existir apenas um canal de entrada/informação.

Criar caso não exista:

### `#candidatura-oficial`

Mensagem fixa:

> **CANDIDATURA PARA OFICIAL**
>
> O processo é realizado exclusivamente pelo site e consiste em uma avaliação completa de 30 perguntas.
>
> Serão avaliados liderança, disciplina, tomada de decisão, conhecimento operacional, comunicação, ética, maturidade e capacidade de comando.
>
> A candidatura não garante promoção.
>
> **[ CANDIDATAR-SE A OFICIAL ]**

---

# 32. REQUISITOS PARA CANDIDATURA

O candidato deve:

* possuir patente mínima de **Soldado**;
* possuir pelo menos **5 horas válidas de bate-ponto acumuladas**.

Usar o histórico do bate-ponto já existente.

Não implementar outro contador.

---

# 33. VALIDAÇÃO

Ao clicar:

1. autenticar;
2. recuperar identidade;
3. consultar patente;
4. consultar horas;
5. verificar candidatura existente;
6. liberar ou bloquear o processo.

Se não elegível:

mostrar exatamente o que falta.

Exemplo:

> Você ainda não está elegível.
>
> Requisitos:
> ✅ Patente mínima: Soldado
> ❌ Horas: 3h42 / 5h

---

# 34. FORMULÁRIO DE OFICIAL

O formulário deverá possuir:

# EXATAMENTE 30 PERGUNTAS

As perguntas devem ser profissionais e construídas para avaliar capacidade real de comando.

---

# 35. DIMENSÕES

As 30 perguntas deverão cobrir:

* liderança;
* tomada de decisão;
* disciplina;
* conhecimento operacional;
* comunicação;
* gestão de conflitos;
* ética;
* gestão de efetivo;
* comando;
* administração;
* maturidade;
* pressão;
* postura institucional;
* visão estratégica.

---

# 36. QUALIDADE DAS PERGUNTAS

Evitar perguntas genéricas.

Preferir cenários que exijam:

* decisão;
* justificativa;
* priorização;
* análise de consequências;
* entendimento de hierarquia;
* julgamento.

As perguntas devem conseguir diferenciar:

* liderança de autoritarismo;
* iniciativa de insubordinação;
* confiança de arrogância;
* disciplina de passividade.

---

# 37. TIPOS DE QUESTÃO

Misturar:

* cenários;
* respostas abertas;
* priorização;
* tomada de decisão;
* conflitos;
* dilemas éticos;
* comando;
* gestão.

Não transformar a avaliação em uma simples prova de múltipla escolha.

---

# 38. PONTUAÇÃO

Cada resposta deverá receber:

**nota de 1 a 10**

O sistema deverá gerar:

* nota por pergunta;
* nota por competência;
* média ponderada;
* nota geral.

Não depender exclusivamente de média aritmética.

---

# 39. PESOS

Os pesos das competências deverão ser configuráveis.

Exemplo inicial:

```text
Liderança: 15%
Tomada de decisão: 15%
Disciplina: 10%
Conhecimento operacional: 10%
Gestão de conflitos: 10%
Comunicação: 10%
Ética: 10%
Gestão de efetivo: 10%
Maturidade: 5%
Administração: 5%
```

---

# 40. RED FLAGS

Identificar respostas que indiquem:

* abuso de autoridade;
* favorecimento;
* insubordinação;
* conduta antiética;
* imprudência;
* omissão grave;
* incapacidade de comando.

Uma média alta não pode esconder um comportamento crítico.

---

# 41. CONSISTÊNCIA

Comparar respostas entre si.

Caso exista contradição:

* sinalizar;
* indicar perguntas relacionadas;
* explicar o motivo do alerta.

---

# 42. ANÁLISE DE PERFIL

Gerar perfil baseado na avaliação.

Possíveis perfis:

* operacional;
* comando;
* administrativo;
* liderança;
* gestão;
* instrutor;
* tático.

Um candidato pode possuir múltiplos perfis.

---

# 43. COMPATIBILIDADE HIERÁRQUICA

Avaliar qual nível de responsabilidade combina com o perfil do candidato.

A análise deve considerar:

* nota;
* competências;
* red flags;
* consistência;
* maturidade;
* histórico;
* experiência;
* desempenho.

Não recomendar automaticamente a maior patente.

---

# 44. HISTÓRICO DO CANDIDATO

Enviar ao avaliador:

* nome;
* Discord;
* ID MTA;
* patente;
* tempo de corporação;
* tempo na patente;
* horas;
* histórico de progressão;
* patrulhas;
* cursos;
* qualificações;
* mérito;
* promoções;
* rebaixamentos;
* informações administrativas pertinentes.

---

# 45. RELATÓRIO DE CANDIDATURA

Gerar automaticamente:

## Identificação

## Histórico

## Respostas

## Notas

## Competências

## Red flags

## Inconsistências

## Perfil

## Compatibilidade hierárquica

## Pontos fortes

## Pontos fracos

## Resumo executivo

## Recomendação

---

# 46. RESPONSÁVEL POR UPAMENTO

Utilizar o cargo existente:

**RESPONSÁVEL POR UPAMENTO**

Não criar novo cargo.

Criar no site área exclusiva para esses usuários.

---

# 47. PAINEL DO AVALIADOR

Mostrar:

```text
CANDIDATURAS

Novas: X
Em análise: X
Entrevista: X
Aprovadas: X
Aprovadas com condições: X
Reprovadas: X
```

Filtros:

* status;
* patente;
* nota;
* recomendação;
* período.

---

# 48. ANÁLISE HUMANA

A avaliação automática será apenas apoio.

O avaliador poderá:

* aprovar;
* aprovar com condições;
* solicitar entrevista;
* reprovar;
* devolver para análise.

A decisão final será sempre humana.

---

# 49. ENTREVISTA

Permitir colocar a candidatura em:

`ENTREVISTA NECESSÁRIA`

Registrar:

* entrevistador;
* data;
* resultado;
* observações.

---

# 50. APROVAÇÃO COM CONDIÇÕES

Permitir definir:

* condição;
* prazo;
* responsável;
* observação.

---

# 51. REPROVAÇÃO

Exigir justificativa.

Criar período configurável para uma nova candidatura.

Valor inicial:

**30 dias**

---

# 52. VERSIONAMENTO

O formulário deve possuir versão.

Cada candidatura guarda:

* versão do questionário;
* perguntas;
* pesos;
* critérios;
* resultado.

Alterações posteriores não devem alterar avaliações históricas.

---

# 53. ÁREA DO CANDIDATO

O candidato poderá consultar:

* candidatura;
* status;
* etapa;
* resultado final quando liberado.

Nunca mostrar informações internas confidenciais.

---

# 54. CANAIS NECESSÁRIOS

Verificar primeiro os canais existentes.

Criar somente o que estiver faltando.

Canais esperados:

```text
#efetivo-em-servico
#registro-de-ptr
#ocorrencias-de-ptr
#promocoes
#rebaixamentos
#progressao-automatica
#candidatura-oficial
#upamentos
#logs-sistema
```

Se já houver canal equivalente, reutilizar.

---

# 55. GERENCIAMENTO DOS CANAIS

Implementar uma lógica de descoberta e criação.

O sistema deverá:

1. procurar canal existente;
2. validar;
3. criar caso necessário;
4. aplicar permissões;
5. persistir ID;
6. evitar duplicidade.

A referência principal deve ser um identificador lógico/ID, não apenas o nome.

---

# 56. AUDITORIA

Registrar todas as ações relevantes.

Exemplos:

```text
VEHICLE_CREATED
VEHICLE_MEMBER_ADDED
VEHICLE_MEMBER_REMOVED
COMMANDER_CHANGED
PTR_CREATED
PTR_UPDATED
OCCURRENCE_CREATED
PROMOTION_CREATED
DEMOTION_CREATED
MERIT_CREATED
CANDIDACY_CREATED
CANDIDACY_EVALUATED
CANDIDACY_APPROVED
CANDIDACY_REJECTED
CANDIDACY_INTERVIEW
```

Cada evento deverá armazenar:

* usuário;
* data;
* entidade;
* ação;
* estado anterior;
* estado novo;
* observação.

---

# 57. IDEMPOTÊNCIA

As ações críticas devem suportar:

* clique duplo;
* retry;
* eventos duplicados;
* restart;
* processamento concorrente.

Não duplicar:

* viaturas;
* integrantes;
* promoção;
* rebaixamento;
* PTR;
* candidatura;
* decisão.

---

# 58. SINCRONIZAÇÃO DE CARGOS

Sempre que uma promoção ou rebaixamento for efetivado:

1. alterar banco;
2. atualizar cargo no Discord;
3. remover cargo anterior conforme configuração;
4. registrar auditoria;
5. publicar;
6. verificar se a alteração realmente ocorreu.

Se houver divergência entre banco e Discord:

* detectar;
* registrar;
* corrigir quando seguro.

---

# 59. SEGURANÇA

Todas as ações administrativas deverão ser verificadas no backend.

Validar:

* usuário;
* servidor;
* identidade;
* cargo;
* permissão;
* recurso;
* estado;
* ação.

Nunca confiar somente no frontend.

---

# 60. CONFIGURAÇÕES

Tornar configuráveis:

* canais;
* cargos;
* hierarquia;
* metas de horas;
* permanência mínima;
* artigos;
* ocorrências;
* pesos da avaliação;
* regras de elegibilidade;
* período para nova candidatura;
* permissões;
* canais de publicação.

Não espalhar configurações importantes pelo código.

---

# 61. DASHBOARD DE CARREIRA

Criar uma visão da evolução do membro.

Exemplo:

```text
CARREIRA

✓ Soldado — 4h
✓ Cabo — 8h
✓ 3º Sargento — 13h
✓ 2º Sargento — 19h
✓ 1º Sargento — 26h
✓ Subtenente — 33h
✓ Cadete — 40h

━━━━━━━━━━━━━━

PRÓXIMA EVOLUÇÃO
Baseada em mérito

CANDIDATURA PARA OFICIAL
✅ Elegível
```

Essa área deve utilizar dados reais já existentes.

---

# 62. TESTES OBRIGATÓRIOS

## Viaturas

* criação;
* entrada;
* saída;
* troca de patrulha;
* comandante;
* substituição;
* encerramento;
* múltiplos membros.

## PTR

* relatório;
* composição automática;
* ocorrência;
* artigo;
* evidência;
* encerramento.

## Progressão

* 4h;
* 8h;
* 13h;
* 19h;
* 26h;
* 33h;
* 40h;
* permanência;
* restart;
* duplicidade;
* cargo divergente.

## Promoções/Rebaixamentos

* manual;
* automático;
* auditoria;
* sincronização.

## Mérito

* criação;
* consulta;
* histórico.

## Oficial

* elegibilidade;
* 30 perguntas;
* notas;
* pesos;
* red flags;
* consistência;
* perfil;
* recomendação;
* aprovação;
* reprovação;
* entrevista.

## Infraestrutura

* criação de canais;
* permissões;
* restart;
* recuperação de estado.

---

# 63. CRITÉRIO DE CONCLUSÃO

Considerar a implementação concluída somente quando:

* o sistema de viaturas estiver integrado ao bate-ponto já existente;
* membros forem agrupados automaticamente;
* comandante for definido corretamente;
* efetivo for atualizado;
* PTR estiver integrado às viaturas;
* perdas/ocorrências puderem ser registradas;
* progressão de Recruta até Cadete estiver funcionando;
* promoção manual funcionar;
* rebaixamento funcionar;
* mérito existir a partir de Cadete;
* candidatura exigir Soldado + 5h;
* existirem exatamente 30 perguntas;
* respostas forem avaliadas de 1 a 10;
* relatório de avaliação for gerado;
* responsável por upamento puder analisar;
* canais necessários forem criados;
* cargos forem sincronizados;
* auditoria estiver funcionando;
* duplicidades forem impedidas;
* restart não corromper o estado;
* testes principais passarem.

---

# 64. INSTRUÇÃO FINAL AO DESENVOLVEDOR

Antes de implementar:

1. analisar o projeto atual;
2. localizar o sistema de bate-ponto já existente;
3. localizar a Central de Tags já existente;
4. localizar identidade e cargos;
5. localizar PTR existente;
6. localizar promoções existentes;
7. localizar sistema de upamento existente;
8. identificar o que pode ser reutilizado;
9. identificar o que realmente precisa ser criado;
10. implementar somente as funcionalidades deste prompt.

### NÃO FAZER

* não recriar bate-ponto;
* não recriar Central de Tags;
* não criar identidade paralela;
* não duplicar sistema de PTR existente;
* não criar cargos administrativos duplicados;
* não espalhar lógica pelo código;
* não confiar apenas no frontend;
* não considerar compilação como conclusão.

O objetivo desta etapa é evoluir o sistema existente para uma plataforma integrada de:

**VIATURA → OPERAÇÃO → PTR → CARREIRA → MÉRITO → OFICIALATO**

mantendo intactos os sistemas que já foram implementados anteriormente.
