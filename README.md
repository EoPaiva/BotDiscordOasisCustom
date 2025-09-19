# Bot de Gerenciamento Multifuncional OasisCustom

<p align="center">
  <img src="https://img.shields.io/badge/status-ativo-brightgreen" alt="Status do Projeto">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/discord.py-2.3.2-7289DA" alt="discord.py">
  <img src="https://img.shields.io/badge/licença-MIT-lightgrey" alt="Licença">
</p>

<p align="center">
  Uma solução de automação robusta e modular para servidores Discord, projetada para gerenciar membros, atividades e moderação de forma eficiente e profissional.
</p>

---

## 📜 Sobre o Projeto

Este bot foi desenvolvido para ser a espinha dorsal administrativa de comunidades complexas, como servidores de **Roleplay (RP)** ou **guilds de jogos**. Ele centraliza funcionalidades essenciais, substituindo múltiplos bots com uma solução modular, com gerenciamento via banco de dados e automação completa.

Cada módulo foi projetado para ser intuitivo, utilizando interações do Discord como **botões** e **formulários** para facilitar a experiência tanto para membros quanto para administradores.

---

---

### **🛠️ Tecnologias e Ferramentas Utilizadas**

Este projeto foi construído com foco em desempenho, modularidade e confiabilidade, utilizando as seguintes tecnologias:

<p align="left">
  <a href="https://skillicons.dev">
    <img src="https://skillicons.dev/icons?i=python,sqlite,git,discord,vscode" />
  </a>
</p>

* **Linguagem Principal: Python**
    * Todo o bot foi desenvolvido em Python, uma linguagem poderosa e versátil, ideal para projetos de automação e back-end.

* **Biblioteca Principal: `discord.py`**
    * Utilizamos a biblioteca `discord.py` para toda a interação com a API do Discord. Sua natureza assíncrona garante que o bot possa lidar com múltiplas ações simultaneamente sem travar, oferecendo uma experiência fluida para os usuários.

* **Banco de Dados: SQLite (via `aiosqlite`)**
    * Para persistência de dados (registros de farm, ausências, caixa, etc.), foi escolhido o SQLite.
    * **Por quê?** É um banco de dados leve, rápido e que não requer um servidor separado, sendo armazenado em um único arquivo (`.db`) junto com o bot.
    * A biblioteca `aiosqlite` foi usada para garantir que todas as operações de banco de dados sejam assíncronas, mantendo o bot responsivo.

* **Ferramentas de Desenvolvimento e Configuração**
    * **Git & GitHub:** Para controle de versão e gerenciamento do código-fonte.
    * **JSON:** Utilizado para os arquivos de configuração (`config.json`, etc.), permitindo uma personalização fácil de todos os IDs e parâmetros do bot sem precisar alterar o código Python.
    * **`.env`:** Para o armazenamento seguro de informações sensíveis, como o token do bot.

---

## ✨ Funcionalidades Principais

### 📝 Sistema de Registro com Aprovação

- **Auto-Role na Entrada**: Novos membros recebem um cargo temporário ao entrar.
- **Painel Interativo**: Um comando `/painel_registro` cria um painel com um botão para iniciar o registro.
- **Formulário Modal**: Coleta informações detalhadas do novo membro (Nome, ID, etc.).
- **Aprovação da Staff**: A staff pode aprovar ou negar o registro com um clique.
- **Automação Completa**: Após aprovação, o bot altera o apelido do membro e atribui os cargos finais.

### ✈️ Sistema de Ausência

- **Solicitação Formal**: Membros solicitam ausência informando o motivo e data de retorno.
- **Cargo Automático**: O membro recebe o cargo "Ausente".
- **Retorno Agendado**: O bot monitora o retorno e remove o cargo automaticamente.

### 🌾 Sistema de Tickets de Farm

- **Canais Privados**: Membros criam tickets individuais para registrar entregas.
- **Entrega com Provas**: Formulário para solicitar detalhes da entrega e envio de imagem como prova.
- **Aprovação da Staff**: Cada entrega é enviada para análise da staff.
- **Ranking Automático**: Um ranking das entregas aprovadas é mantido e atualizado automaticamente.

### 👮 Sistema de Gestão de RH

- **Painel Centralizado**: Um painel único para ações como "Desligamento", "Promoção" e "Rebaixamento".
- **Hierarquia Configurável**: Defina uma cadeia de cargos e prefixos no arquivo de configuração.
- **Automação de Ações**: Demissão, promoções e rebaixamentos são automáticos.
- **Logs Detalhados**: Registra todas as ações em um canal privado para a staff.

### 🆘 Sistema de Resgate

- **Pedido de Ajuda**: Membros podem solicitar ajuda de emergência.
- **Coleta de Informações**: Formulário para coletar dados de localização e problema, seguido de uma imagem.
- **Alerta @everyone**: Envia um alerta com todos os detalhes no canal de resgate.

---

## 🚀 Começando

### Pré-requisitos

- Python 3.10 ou superior
- Conta de Bot no [Portal de Desenvolvedores do Discord](https://discord.com/developers/docs/intro) com as Privileged Gateway Intents ativadas

### Guia de Instalação

1. Clone o repositório:

    git clone [URL_DO_SEU_REPOSITORIO]
    cd [NOME_DA_PASTA]

2. Crie um ambiente virtual (recomendado):

    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # Linux/macOS
    source venv/bin/activate

3. Instale as dependências:

    pip install -r requirements.txt

4. Configure o Token do Bot:

- Crie um arquivo chamado `.env` na pasta principal.
- Dentro dele, adicione a linha:

    TOKEN="SEU_TOKEN_AQUI"

5. Configure os IDs do Servidor:

- Abra o arquivo `config.json` e preencha os IDs dos canais, categorias e cargos.
- Abra o arquivo `ranking_config.json` (ele pode estar vazio, o bot irá gerenciá-lo).

6. Convide o Bot para o seu servidor com as permissões necessárias.

---

## ⚙️ Uso

### Iniciar o bot

Para iniciar o bot, execute o seguinte comando:

    python main.py

### Enviar os Painéis (Comandos de Admin)

Vá para os canais de texto correspondentes configurados no `config.json` e use os comandos para implantar os painéis de interação:

    /painel_registro
    /painel_ausencia
    /painel_farm
    /painel_rh
    /painel_resgate

### Gerenciar o Ranking de Farm (Comandos de Admin)

    /ranking_iniciar  # Inicia o ranking no canal configurado.
    /ranking_parar    # Desativa o ranking.

---






### **Histórico de Versões e Atualizações**

*Atualizações implementadas em 18-19 de Setembro de 2025.*

### ✨ Novas Funcionalidades

* **Sistema de Hierarquia Dinâmica**
    * Adicionado um novo módulo para exibir a estrutura hierárquica completa da equipe em um canal dedicado.
    * O painel é esteticamente formatado, mostrando cada cargo (com título e emoji customizados) e a lista de membros correspondente.
    * A hierarquia é atualizada automaticamente sempre que um membro é registrado, promovido, rebaixado ou demitido.
    * Comandos de admin disponíveis: `/hierarquia` para postar ou forçar uma atualização.

* **Sistema de Controle de Caixa**
    * Criado um novo módulo para registrar transações financeiras com provas.
    * Implementado um painel interativo com botões de "Depositar" e "Sacar" que exibe o saldo em tempo real.
    * A staff preenche um formulário com valor/motivo e anexa uma imagem como prova.
    * Todas as transações são salvas em banco de dados e um resumo é postado em um canal de logs.
    * Comandos disponíveis: `/painel_caixa` (admin), `/saldo` (staff).

* **Módulo de Comandos Utilitários**
    * Adicionado um novo conjunto de comandos gerais e de moderação, incluindo:
        * **Gerais**: `/ajuda`, `/sobre`, `/status`, `/version`, `/erro` (com formulário), `/enquete`.
        * **Moderação (Staff)**: `/limpar`, `/banir`, `/desbanir`, `/notificar`.
        * **Administrativo**: `/relatorio` (gera um resumo das atividades de Farm e Caixa).

### ⚙️ Melhorias e Alterações

* **Atualização Automática de Apelidos (Sistema de RH)**
    * O sistema de Promoção e Rebaixamento agora altera automaticamente o prefixo no apelido do membro para refletir seu novo cargo na hierarquia.
    * A configuração da hierarquia foi unificada em uma estrutura mais robusta no `config.json`.

* **Comando de Verificação de Apelidos (Sistema de RH)**
    * Adicionado o comando de administrador `/verificar_apelidos`.
    * Esta ferramenta varre todos os membros do servidor e corrige automaticamente qualquer apelido que não esteja alinhado com o cargo mais alto do membro na hierarquia.

* **Múltiplas Mensagens para Hierarquia**
    * O sistema de hierarquia foi otimizado para lidar com um grande número de membros. Se a lista de membros for muito longa para uma única mensagem, o bot agora a divide em várias mensagens para garantir que toda a equipe seja exibida.

### 🐛 Correções de Bugs

* **Corrigido Erro de 'Módulo não Encontrado' (`ModuleNotFoundError`)**: Resolvido um problema de importação que impedia os módulos (`Cogs`) de carregarem corretamente.
* **Corrigido Erro de 'Tamanho do Embed' (`Embed Size Exceeds Limit`)**: Resolvido o erro crítico que ocorria ao tentar exibir uma hierarquia com muitos membros.
* **Corrigido Erro de Codificação (`Charmap Codec Error`)**: Solucionado um problema de codificação de caracteres no `config.json` que impedia o bot de iniciar.
* **Corrigido Erro de 'Coluna não Encontrada' (`No Such Column`)**: Corrigido um problema de dessincronização entre o código e o banco de dados.
* **Corrigido Erro de Imagens Quebradas**: A lógica de anexo de imagens nos sistemas de Resgate e Caixa foi reescrita para usar arquivos permanentes em vez de links temporários do Discord, garantindo que as imagens nunca expirem.


## 📁 Estrutura do Projeto
```
.
├── 📄 .env                   # Guarda o token secreto do seu bot.
├── 📄 config.json             # O "painel de controle" principal, com todos os IDs e configurações.
├── 📄 database.py             # Gerencia o banco de dados (SQLite) para todos os sistemas.
├── 📄 main.py                 # O arquivo principal que você executa para iniciar o bot.
├── 📄 ranking_config.json     # Salva o ID da mensagem do ranking de farm para atualização automática.
├── 📄 requirements.txt       # Lista de bibliotecas que o bot precisa para funcionar.
└── 📁 cogs/                   # Pasta onde cada sistema do bot é organizado como um módulo.
    ├── 📄 absence_system.py       # Lógica para o sistema de ausência.
    ├── 📄 cash_control.py       # Lógica para o controle de caixa.
    ├── 📄 farm_system.py        # Lógica para os tickets e ranking de farm.
    ├── 📄 hierarchy_system.py     # Lógica para o painel de hierarquia dinâmico.
    ├── 📄 hr_system.py            # Lógica para demissão, promoção e verificação de apelidos.
    ├── 📄 registration_system.py  # Lógica para o registro e aprovação de novos membros.
    ├── 📄 rescue_system.py        # Lógica para o sistema de pedido de ajuda.
    └── 📄 utility_commands.py     # Contém todos os comandos gerais e de moderação (/ajuda, /limpar, etc).

    

