# BOOTSTRAP_PROMPT.md

# PROTOCOLO DE CONTINUIDADE DE SESSÃO

Você está assumindo um projeto que estava sendo desenvolvido por outra sessão do Codex.

Sua função NÃO é reiniciar o trabalho.

Sua função é assumir o estado atual e continuar exatamente de onde a sessão anterior parou, utilizando o menor contexto necessário.

---

## FASE 1 — CARREGAMENTO

Leia nesta ordem:

1. `PROJECT_STATE.md`
2. `SESSION_HANDOFF.md`

Não faça uma análise completa de todo o repositório neste momento.

Não procure conversas anteriores por padrão.

Não reconstrua decisões que já estejam documentadas.

---

## FASE 2 — ENTENDIMENTO

Extraia internamente:

- objetivo do projeto;
- tarefa atual;
- último passo concluído;
- alteração em andamento;
- próxima ação exata;
- arquivos envolvidos;
- bloqueios;
- testes relevantes;
- fila AGORA;
- fila DEPOIS.

Não transforme isso em um resumo longo para o usuário.

---

## FASE 3 — VALIDAÇÃO CONTRA O REPOSITÓRIO

Faça apenas as verificações mínimas necessárias.

Verifique:

```bash
git status
```

e, quando aplicável:

```bash
git branch --show-current
git log -1 --oneline
```

Confirme a existência e o estado dos arquivos mencionados no handoff.

Não faça varredura completa do projeto sem necessidade.

---

## FASE 4 — REGRA DE CONFLITO

Prioridade das fontes:

1. Estado real do código/repositório.
2. `SESSION_HANDOFF.md`.
3. `PROJECT_STATE.md`.
4. Contextos auxiliares/plugins.
5. Conversas históricas.

Se houver divergência, nunca sobrescreva silenciosamente o estado real do código para obedecer a um handoff desatualizado.

Corrija o handoff.

---

## FASE 5 — CONTINUAÇÃO

Se o estado estiver consistente:

**continue imediatamente da seção `PRÓXIMA AÇÃO EXATA` do `SESSION_HANDOFF.md`.**

Não:

- reinicie o projeto;
- refaça análise já concluída;
- repita explicações;
- redesenhe o plano inteiro;
- releia arquivos não relacionados;
- reabra toda a conversa anterior;
- altere a prioridade da fila sem motivo técnico.

---

# FILA DE TAREFAS

A hierarquia é:

```text
AGORA
↓
DEPOIS
↓
BACKLOG
```

Conclua a tarefa em `AGORA`.

Quando ela terminar:

1. execute/verifique os testes necessários;
2. registre seu resultado;
3. marque-a como concluída;
4. mova a primeira tarefa de `DEPOIS` para `AGORA`;
5. continue.

Não execute várias tarefas simultaneamente se elas dependerem umas das outras.

---

# PRESERVAÇÃO DE CONTEXTO

Evite carregar informações apenas "por garantia".

Antes de abrir arquivos adicionais, pergunte internamente:

> Preciso realmente desse arquivo para executar a próxima ação?

Se não, não carregue.

Prefira:

- funções específicas;
- trechos específicos;
- arquivos específicos;
- buscas pontuais.

Evite:

- diretórios inteiros;
- logs enormes;
- histórico completo;
- documentação não relacionada;
- conversas anteriores inteiras.

---

# PROTOCOLO DE MIGRAÇÃO

Durante a sessão, observe sinais de que continuar nela está ficando ineficiente.

Exemplos:

- contexto acumulado muito grande;
- muitas tarefas diferentes discutidas na mesma sessão;
- necessidade frequente de recuperar informações antigas;
- respostas começando a repetir análise;
- dificuldade de manter precisamente o estado atual;
- muitas alterações e resultados de ferramentas acumulados;
- grande quantidade de arquivos já analisados;
- tarefa principal mudou substancialmente;
- uma etapa importante terminou e outra grande etapa vai começar.

Não alegue conhecer um número exato de tokens restantes se essa informação não estiver disponível.

Use sinais de degradação e complexidade como heurística.

---

# QUANDO MIGRAR

Quando uma nova sessão for claramente mais eficiente:

1. finalize qualquer operação que não possa ficar em estado inconsistente;
2. execute validações mínimas necessárias;
3. atualize `PROJECT_STATE.md` somente se houve mudanças permanentes;
4. reescreva `SESSION_HANDOFF.md`;
5. registre a tarefa AGORA;
6. registre a PRÓXIMA AÇÃO EXATA;
7. registre arquivos parcialmente modificados;
8. registre testes;
9. registre problemas ainda abertos;
10. registre a fila DEPOIS;
11. pare em um ponto seguro de transferência.

O objetivo é permitir que a próxima sessão continue sem reler esta conversa.

---

# COMPACTAÇÃO

O handoff não deve ser uma transcrição.

Preserve:

- estado;
- decisões;
- resultados;
- referências;
- tarefas;
- código relevante;
- erros relevantes;
- próximos passos.

Descarte:

- conversa informal;
- raciocínio repetido;
- tentativas inúteis já descartadas;
- explicações que não alteram decisões;
- outputs gigantes que podem ser reproduzidos facilmente.

---

# REGRA DE OURO

> Transporte o ESTADO do trabalho, não o histórico da conversa.

---

# ATUALIZAÇÃO CONTÍNUA

Durante trabalhos longos, mantenha o `SESSION_HANDOFF.md` suficientemente atualizado para que uma interrupção inesperada não destrua a continuidade.

Informações críticas não devem existir somente no contexto da conversa.

---

# FINALIZAÇÃO DA SESSÃO

Antes de uma migração, o `SESSION_HANDOFF.md` precisa responder sem ambiguidade:

1. O que estamos construindo?
2. O que estamos fazendo agora?
3. O que já foi feito?
4. O que ainda falta nesta tarefa?
5. Qual arquivo está sendo alterado?
6. Qual é a próxima ação exata?
7. Existem alterações não commitadas?
8. Existem bugs ou bloqueios?
9. Quais testes passaram ou falharam?
10. O que vem imediatamente depois?

Se alguma dessas respostas necessária à continuação estiver faltando, complete o handoff antes da migração.
