# Corte reversível de Recrutamento e Cursos — DC1 para DC2

## Estado desta entrega

O corte está implementado e validado apenas no código local. Ele não executa deploy, não exclui
canais e não altera a Discloud por conta própria. O modo padrão do script é somente leitura.

## Garantias

- DC2 precisa apontar explicitamente para o DC1 como fonte de identidade.
- Todos os canais e painéis obrigatórios do DC2 precisam existir e responder.
- O catálogo ativo do DC2 não pode ser menor que o catálogo ativo da origem.
- Candidaturas, campanhas, cursos ou treinamentos ainda ativos no DC1 bloqueiam a operação.
- O script nunca envia `DELETE` para a API do Discord.
- Antes da primeira alteração é criado snapshot do layout e backup consistente do SQLite.
- Um lock durável coloca a origem em somente leitura durante o corte, inclusive após reinício.
- O corte final grava origem, destino e flag na mesma transação e valida novamente o vínculo.
- Falha recuperável restaura nomes, overwrites e configurações anteriores.
- Depois do corte, histórico e identidade do DC1 permanecem preservados; novas operações de
  Recrutamento, Robô Analista, Cursos e Treinamentos são aceitas somente no DC2.
- A sincronização aprovada DC2 para o cadastro canônico do DC1 continua autorizada.

## Dry-run obrigatório

```powershell
.\.venv\Scripts\python.exe scripts\archive_rec_source_layout.py
```

O comando deve terminar com `DC2_SOURCE_ARCHIVE_PREFLIGHT_PASS` e `DRY_RUN_ONLY`. O caminho do
snapshot é exibido, mas fica dentro de `data/`, que não é versionada.

## Aplicação

A aplicação exige autorização explícita do proprietário e a confirmação literal apresentada pelo
dry-run. Não executar apenas porque testes locais passaram.

## Restauração

A restauração exige o snapshot original, confirmação literal própria e confere se servidor de
origem, DC2 e todos os IDs de canais ainda correspondem ao ambiente atual. Um snapshot que aponta
para outro servidor é recusado antes de qualquer alteração.

## Gates executados antes do checkpoint

- suíte completa Python;
- Ruff nos arquivos envolvidos;
- `compileall`;
- `main.py --check`;
- `git diff --check`;
- varredura de segredos;
- revisão de RBAC, interrupção, rollback e fronteira canônica DC1/DC2.

Deploy na Discloud e aplicação no Discord continuam fora deste checkpoint.
