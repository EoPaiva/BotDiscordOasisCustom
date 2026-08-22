# Validação do ponto por tempo mínimo em patrulha

Status: **CONCLUÍDO E VALIDADO EM 2026-08-22**.

Evidência: migration v14, `choque/shift_validation.py`, integração em `choque/shifts.py`,
configuração visual em `cogs/config_ui.py`, confirmação/revisão em `cogs/shift_commands.py`,
cenários em `tests/test_minimum_patrol.py` e validação real por
`scripts/validate_live_minimum_patrol.py`.

## Objetivo

Uma sessão somente contabiliza horas quando acumular o tempo mínimo configurado em calls que
efetivamente contam como patrulha. O padrão inicial será:

```text
minimum_patrol_minutes = 15
```

O membro pode iniciar o serviço normalmente. A validação acontece durante o acompanhamento e no
encerramento, sem contadores por segundo.

## Regra de validade

```text
patrol_duration = soma dos segmentos que contam como patrulha
```

- `patrol_duration >= minimum_patrol_minutes`: sessão válida.
- `patrol_duration < minimum_patrol_minutes`: sessão invalidada.

Tempo bruto de sessão nunca substitui o tempo válido de patrulha. Intervalos fora da call e grace
period não contam.

## Persistência

Sessões curtas nunca devem ser apagadas. O banco deve preservar:

- membro e identificador da sessão;
- início e encerramento;
- duração bruta;
- duração válida em patrulha;
- calls e segmentos utilizados;
- status final;
- motivo e origem do encerramento;
- mínimo exigido no momento da sessão;
- instante em que o requisito foi atingido, quando aplicável;
- origem de eventual validação manual.

Estado inválido sugerido: `INVALIDATED`, com motivo estruturado
`MINIMUM_PATROL_TIME_NOT_REACHED`. A modelagem deve se integrar aos estados atuais sem reescrever
segmentos históricos.

## Contabilização

Uma sessão invalidada deve aparecer no histórico, mas contribuir com zero para:

- horas totais;
- horas diárias, semanais e mensais;
- ranking;
- meta semanal;
- relatórios de horas válidas.

Relatórios administrativos podem separar quantidades de sessões válidas e invalidadas. Várias
invalidações devem ser preservadas, mas nunca gerar punição automática.

## Configuração de calls

Autorização de serviço e contagem para o mínimo são conceitos independentes. Cada call precisa
possuir, no mínimo:

```text
service_allowed
counts_toward_patrol_minimum
```

Uma call de espera ou treinamento pode manter o ponto aberto e não acumular patrulha. Trocas entre
duas calls que contam como patrulha acumulam tempo sem reiniciar o progresso.

O valor do segmento deve registrar a classificação aplicável no momento da passagem para preservar
o resultado histórico mesmo se a configuração da call mudar depois.

## Configuração administrativa

O painel de Controle de Serviço deve permitir alterar o mínimo em uma faixa segura de 5 a 120
minutos. O valor 15 deve existir somente como default centralizado, nunca espalhado pelo projeto.

O painel de calls deve exibir e alterar separadamente:

- permite serviço;
- conta para validação mínima.

## Experiência do membro

Ao iniciar, a resposta ephemeral informa o mínimo e que uma saída antecipada invalida a sessão.

O status pessoal deve mostrar, sob demanda e em eventos relevantes:

```text
Validação: 11m / 15m
```

ou:

```text
Validação: requisito mínimo atingido
```

Não atualizar mensagens a cada segundo. Calcular por timestamps quando houver consulta, troca de
call, encerramento ou outro evento relevante.

## Saída antecipada

Se o membro tentar finalizar antes do mínimo, exibir confirmação com:

- tempo válido atual;
- mínimo exigido;
- aviso de que a sessão será invalidada;
- `Finalizar mesmo assim`;
- `Continuar em serviço`.

Somente a confirmação encerra manualmente a sessão curta. Saída por expiração do grace encerra
automaticamente e invalida quando o mínimo não tiver sido atingido.

## Recuperação após restart

O progresso vem dos segmentos persistidos. Se o bot reiniciar aos dez minutos e o membro continuar
em call válida, os dez minutos anteriores permanecem e os próximos cinco podem completar o mínimo.
Períodos ambíguos continuam seguindo as regras de recuperação e revisão já existentes.

## Override administrativo

O Comando pode revisar uma invalidação excepcionalmente. O painel deve mostrar duração bruta,
patrulha válida, mínimo, status e motivo.

`VALIDAR MANUALMENTE` deve exigir:

- motivo;
- confirmação;
- responsável;
- auditoria;
- `validation_source = ADMIN_OVERRIDE`.

O sistema não pode fingir que a regra automática foi cumprida. Ajustes de tempo continuam
append-only.

## Testes obrigatórios

1. `14m59s` de patrulha resulta em `INVALIDATED`.
2. `15m00s` exatos resulta em sessão válida.
3. `20m` em call de patrulha resulta em sessão válida.
4. `10m` em Patrulha 01 + `5m` em Patrulha 02 resulta em sessão válida.
5. `10m` em patrulha + `20m` em treinamento resulta em sessão invalidada.
6. `14m30s` + queda de `40s` + retorno por `30s` resulta em `15m` válidos; a queda não conta.
7. Encerramento automático com `8m` resulta em sessão invalidada.
8. Restart aos `10m` e mais `5m` válidos após recuperação resulta em sessão válida.

Também devem ser cobertos:

- confirmação antes de finalizar uma sessão curta;
- exclusão dos totais, ranking, metas e relatórios;
- histórico preservado;
- alteração segura do mínimo;
- alteração da classificação das calls sem mudar sessões antigas;
- override administrativo auditado;
- concorrência entre encerramento manual, grace e restart.

## Critério de conclusão

A pendência só pode ser marcada como concluída quando:

- o mínimo estiver centralizado e configurável;
- calls autorizadas e calls de patrulha forem conceitos separados;
- segmentos preservarem a classificação histórica;
- sessões curtas forem invalidadas sem exclusão;
- consultas e relatórios ignorarem invalidadas nos totais;
- o aviso e a confirmação de saída antecipada estiverem ativos;
- recuperação após restart preservar o progresso;
- override exigir motivo, confirmação e auditoria;
- não existir punição automática;
- todos os cenários obrigatórios passarem localmente e no servidor de QA.
