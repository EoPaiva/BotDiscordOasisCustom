# ADR 009 — Analista de recrutamento somente leitura

Status: aceito em 2026-08-22.

## Contexto

O recrutamento precisa reduzir o trabalho de leitura sem transferir autoridade administrativa a um
modelo. Respostas de candidatos podem conter prompt injection e o provider pode falhar, variar ou
retornar conteúdo fora do contrato.

## Decisão

- `RecruitmentAnalysisProvider` recebe somente perguntas, respostas, rubrica, contexto autorizado,
  checks determinísticos e, na análise final, avaliação da entrevista. Não recebe Discord IDs,
  credenciais, cookies, dados de outros candidatos ou ferramentas.
- O provider é OpenAI-compatible e selecionado por ambiente; `disabled` é o default seguro. NVIDIA
  NIM pode ser usado pela mesma interface sem acoplar domínio ou UI ao fornecedor.
- Envio da candidatura e decisão humana não dependem do provider. Jobs persistidos possuem retry
  limitado, backoff, cache por hash e histórico imutável.
- Rubrica, contexto, prompt, provider e modelo são versionados. Publicar nova rubrica/contexto marca
  análises anteriores como `OUTDATED`; nunca as sobrescreve.
- O backend recalcula a pontuação ponderada, aplica as faixas publicadas, valida evidências e schema,
  rejeita campos desconhecidos/HTML ativo e pode forçar `REVIEW` diante de sinais de integridade.
  Esses sinais continuam não punitivos.
- O relatório fica em área administrativa separada e fechada por padrão. A recomendação, feedback,
  divergência e decisão humana são registros distintos. Não existe ranking de candidatos.

## Consequências

Um provider real exige segredo e autorização de produção. Sem isso, o módulo permanece configurado,
testável e inativo, sem inventar uma análise. A disponibilidade da IA nunca reduz a disponibilidade
do recrutamento.
