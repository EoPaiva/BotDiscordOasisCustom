# cogs/rescue_system.py
import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime
import asyncio

# --- Carregar Configurações ---
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

RESCUE_ALERT_CHANNEL_ID = config.get('RESCUE_ALERT_CHANNEL_ID')

# --- Formulário de Pedido de Ajuda ---
class RescueModal(discord.ui.Modal, title="Pedido de Ajuda"):
    location_details = discord.ui.TextInput(
        label="Onde você está e qual o problema?",
        style=discord.TextStyle.paragraph,
        placeholder="Descreva com o máximo de detalhes sua localização, pontos de referência e o que aconteceu.",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Informações recebidas. **Agora, por favor, envie uma print da sua localização (mapa ou /gps).**", ephemeral=True)

        try:
            # Espera por 2 minutos (120 segundos) pela imagem
            message = await interaction.client.wait_for(
                "message",
                timeout=120.0,
                check=lambda m: m.author == interaction.user and m.channel == interaction.channel and m.attachments
            )
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Tempo esgotado. Por favor, inicie o pedido de ajuda novamente.", ephemeral=True)
            return

        image_url = message.attachments[0].url
        alert_channel = interaction.guild.get_channel(RESCUE_ALERT_CHANNEL_ID)

        if not alert_channel:
            await interaction.followup.send("🚨 Erro de configuração: O canal de resgate não foi encontrado. Avise um administrador.", ephemeral=True)
            return

        # Cria o embed de alerta
        embed = discord.Embed(
            title="🚨 Pedido de Resgate Urgente!",
            description=f"O membro {interaction.user.mention} precisa de ajuda.",
            color=discord.Color.red(),
            timestamp=datetime.now()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="📍 Localização e Detalhes", value=self.location_details.value, inline=False)
        embed.set_image(url=image_url)
        embed.set_footer(text="A equipe de resgate mais próxima deve se manifestar.")

        try:
            # Envia a mensagem no canal de alerta marcando @everyone
            await alert_channel.send(
                content="@everyone",
                embed=embed,
                allowed_mentions=discord.AllowedMentions.all() # Permite que o @everyone funcione
            )
            await interaction.followup.send("✅ Seu pedido de ajuda foi enviado com sucesso!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("🚨 Erro de permissão: Não consigo enviar mensagens no canal de resgate. Avise um administrador.", ephemeral=True)
        
        # Apaga a mensagem com a imagem para manter o canal limpo
        try:
            await message.delete()
        except discord.Forbidden:
            pass

# --- Painel de Pedido de Ajuda ---
class RescuePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Pedir Ajuda", style=discord.ButtonStyle.danger, custom_id="request_rescue_button", emoji="🆘")
    async def request_rescue_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RescueModal())

# --- Cog Principal ---
class RescueSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(RescuePanelView())

    @app_commands.command(name="painel_resgate", description="Envia o painel para pedir ajuda.")
    @app_commands.checks.has_permissions(administrator=True)
    async def painel_resgate(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Central de Resgate",
            description="Se você precisa de ajuda imediata, está preso ou em uma situação de emergência, clique no botão abaixo para notificar a equipe de resgate.",
            color=0x2b2d31
        )
        await interaction.channel.send(embed=embed, view=RescuePanelView())
        await interaction.response.send_message("Painel de resgate enviado!", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(RescueSystem(bot))