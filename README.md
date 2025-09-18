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

## 📁 Estrutura do Projeto
```md
.
├── cogs/
│ ├── absence_system.py
│ ├── farm_system.py
│ ├── hr_system.py
│ └── registration_system.py
├── .env
├── config.json
├── database.py
├── main.py
├── ranking_config.json
└── requirements.txt


<p align="center">Desenvolvido com ❤️</p>
