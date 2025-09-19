# cogs/utility_commands.py
import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime
import database

# --- Carregar Configurações ---
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

BUG_REPORT_CHANNEL_ID = config.get('BUG_REPORT_CHANNEL_ID')
_VERSION = "1.0.0" # Versão do Bot

class BugReportModal(discord.ui.Modal, title="Relatório de Erro"):
    command_name = discord.ui.TextInput(label="Comando com Erro", placeholder="Ex: /farm_entregar", required=True)
    description = discord.ui.TextInput(label="Descrição do Erro", style=discord.TextStyle.paragraph, placeholder="Descreva o que aconteceu, o que você esperava e o que ocorreu.", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        # --- LÓGICA DE CANAL ATUALIZADA ---
        try:
            report_channel = await interaction.guild.fetch_channel(BUG_REPORT_CHANNEL_ID)
        except (discord.NotFound, ValueError):
            return await interaction.response.send_message(f"❌ **Erro de Configuração**: O canal para relatórios de bug (`{BUG_REPORT_CHANNEL_ID}`) não foi encontrado. Verifique o ID no `config.json`.", ephemeral=True)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ **Erro de Permissão**: Não consigo 'ver' o canal de relatórios de bug. Verifique minhas permissões para ele.", ephemeral=True)
        except Exception as e:
            return await interaction.response.send_message(f"❌ Erro inesperado ao buscar canal: {e}", ephemeral=True)

        embed = discord.Embed(title="🐞 Novo Relatório de Erro", color=discord.Color.orange(), timestamp=datetime.now())
        embed.set_author(name=f"Enviado por: {interaction.user.display_name}", icon_url=interaction.user.display_avatar)
        embed.add_field(name="Comando", value=self.command_name.value, inline=False)
        embed.add_field(name="Descrição do Problema", value=self.description.value, inline=False)
        
        await report_channel.send(embed=embed)
        await interaction.response.send_message("✅ Seu relatório de erro foi enviado com sucesso. Obrigado!", ephemeral=True)


class UtilityCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ajuda", description="Exibe uma lista de comandos e suas funções.")
    async def ajuda(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📚 Central de Ajuda do Bot", description="Aqui estão os principais comandos e como usá-los.", color=discord.Color.blurple())
        embed.add_field(name="Sistemas Interativos (Painéis)", value="A maioria das funções do bot é iniciada por um **painel** enviado por um administrador. Procure pelos canais de registro, farm, ausência, etc., para interagir com os botões.", inline=False)
        embed.add_field(name="Comandos Utilitários", value="`/ajuda`, `/sobre`, `/status`, `/version`, `/erro`, `/enquete`", inline=False)
        embed.add_field(name="Comandos de Moderação (Staff)", value="`/limpar`, `/banir`, `/desbanir`, `/notificar`, `/relatorio`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="sobre", description="Exibe informações sobre o bot.")
    async def sobre(self, interaction: discord.Interaction):
        embed = discord.Embed(title=f"Sobre o {self.bot.user.name}", description="Eu sou um bot multifuncional de gerenciamento para o servidor, projetado para automatizar tarefas e organizar sistemas complexos.", color=discord.Color.green())
        embed.add_field(name="Versão", value=_VERSION)
        embed.add_field(name="Criador", value="OasisCustom")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="status", description="Mostra o status e a latência do bot.")
    async def status(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"✅ Estou online! Latência: `{latency}ms`.", ephemeral=True)

    @app_commands.command(name="version", description="Mostra a versão atual do bot.")
    async def version(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"Versão atual do bot: `{_VERSION}`", ephemeral=True)

    @app_commands.command(name="erro", description="Relata um erro ou problema técnico para a staff.")
    async def erro(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BugReportModal())

    @app_commands.command(name="enquete", description="Cria uma enquete simples de Sim/Não.")
    @app_commands.describe(pergunta="A pergunta para a enquete.")
    async def enquete(self, interaction: discord.Interaction, pergunta: str):
        embed = discord.Embed(title="📊 Nova Enquete", description=f"**{pergunta}**", color=discord.Color.blue())
        embed.set_footer(text=f"Enquete criada por {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        await message.add_reaction("👍")
        await message.add_reaction("👎")

    # --- Comandos de Moderação ---
    @app_commands.command(name="limpar", description="Apaga uma quantidade de mensagens do chat.")
    @app_commands.describe(quantidade="O número de mensagens a serem apagadas (2-100).")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def limpar(self, interaction: discord.Interaction, quantidade: int):
        if 2 <= quantidade <= 100:
            deleted = await interaction.channel.purge(limit=quantidade)
            await interaction.response.send_message(f"✅ {len(deleted)} mensagens foram apagadas.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Por favor, insira um número entre 2 e 100.", ephemeral=True)

    @app_commands.command(name="banir", description="Bane um membro do servidor.")
    @app_commands.describe(membro="O membro a ser banido.", motivo="O motivo do banimento.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def banir(self, interaction: discord.Interaction, membro: discord.Member, motivo: str):
        if membro == interaction.user:
            return await interaction.response.send_message("❌ Você não pode se banir.", ephemeral=True)
        await membro.ban(reason=motivo)
        await interaction.response.send_message(f"✅ {membro.display_name} foi banido. Motivo: {motivo}")

    @app_commands.command(name="desbanir", description="Desbane um usuário pelo seu ID.")
    @app_commands.describe(user_id="O ID do usuário a ser desbanido.", motivo="O motivo do desbanimento.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def desbanir(self, interaction: discord.Interaction, user_id: str, motivo: str):
        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=motivo)
            await interaction.response.send_message(f"✅ {user.name} foi desbanido.")
        except (ValueError, discord.NotFound):
            await interaction.response.send_message(f"❌ Usuário com ID `{user_id}` não encontrado ou inválido.", ephemeral=True)

    @app_commands.command(name="notificar", description="Envia uma mensagem mencionando um cargo.")
    @app_commands.describe(mensagem="A mensagem a ser enviada.", cargo="O cargo a ser mencionado.")
    @app_commands.checks.has_permissions(mention_everyone=True)
    async def notificar(self, interaction: discord.Interaction, mensagem: str, cargo: discord.Role):
        await interaction.response.send_message(f"Notificação enviada!", ephemeral=True)
        await interaction.channel.send(f"{cargo.mention}\n\n{mensagem}")
        
    @app_commands.command(name="relatorio", description="Gera um relatório de atividades do bot.")
    @app_commands.checks.has_permissions(administrator=True)
    async def relatorio(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        farm_stats = await database.get_farm_report_stats()
        cash_stats = await database.get_cash_control_report_stats()
        current_balance = await database.get_current_balance()

        embed = discord.Embed(title="📊 Relatório de Atividades do Servidor", color=0x2b2d31, timestamp=datetime.now())
        
        farm_value = (f"**Total de Entregas Aprovadas:** {farm_stats['total_deliveries'] if farm_stats else 0}\n"
                      f"**Farmers Únicos:** {farm_stats['unique_farmers'] if farm_stats else 0}")
        embed.add_field(name="🌾 Sistema de Farm", value=farm_value, inline=False)

        cash_value = (f"**Total de Entradas:** R$ {cash_stats['total_in'] or 0:.2f}\n"
                      f"**Total de Saídas:** R$ {cash_stats['total_out'] or 0:.2f}\n"
                      f"**Total de Transações:** {cash_stats['total_transactions'] if cash_stats else 0}\n"
                      f"**Saldo Atual:** R$ {current_balance:.2f}")
        embed.add_field(name="💰 Controle de Caixa", value=cash_value, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(UtilityCommands(bot))