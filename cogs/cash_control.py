# cogs/cash_control.py
import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime
import asyncio
import io
import database

# --- Carregar Configurações ---
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

LOG_CHANNEL_ID = config.get('CASH_CONTROL_LOG_CHANNEL_ID')
STAFF_ROLE_ID = config.get('STAFF_ROLE_ID')

# --- Formulário para Entrada/Saída ---
class TransactionModal(discord.ui.Modal):
    def __init__(self, transaction_type: str, bot: commands.Bot):
        self.transaction_type = transaction_type
        self.bot = bot
        title = "Registrar Depósito no Caixa" if transaction_type == 'entrada' else "Registrar Saque do Caixa"
        super().__init__(title=title)

    valor = discord.ui.TextInput(label="Valor (use . para centavos)", placeholder="Ex: 50.75", required=True)
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, placeholder="Ex: Pagamento de combo", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = float(self.valor.value.replace(',', '.'))
            if amount <= 0: raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ O valor deve ser um número positivo. Use '.' para centavos.", ephemeral=True)
            return

        await interaction.response.send_message("✅ Informações recebidas. **Agora, por favor, envie a imagem/print de prova.**", ephemeral=True)

        try:
            message = await self.bot.wait_for("message", timeout=180.0, check=lambda m: m.author == interaction.user and m.channel == interaction.channel and m.attachments)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Tempo esgotado. Por favor, inicie a transação novamente.", ephemeral=True)
            return

        # --- LÓGICA DE IMAGEM CORRIGIDA ---
        try:
            log_channel = await interaction.guild.fetch_channel(LOG_CHANNEL_ID)
        except (discord.NotFound, ValueError):
            await interaction.followup.send(f"🚨 **Erro de Configuração**: O canal de logs do caixa não foi encontrado.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send(f"🚨 **Erro de Permissão**: Não consigo ver o canal de logs do caixa.", ephemeral=True)
            return

        attachment = message.attachments[0]
        image_data = await attachment.read()
        # Prepara o arquivo para ser enviado
        image_file = discord.File(io.BytesIO(image_data), filename=f"prova_{interaction.id}_{attachment.filename}")

        saldo_inicial = await database.get_current_balance()
        if self.transaction_type == 'entrada':
            saldo_final = saldo_inicial + amount
            titulo_resumo = "✅ Entrada Registrada no Caixa"
            cor = discord.Color.green()
        else:
            saldo_final = saldo_inicial - amount
            titulo_resumo = "❌ Saída Registrada do Caixa"
            cor = discord.Color.red()
        
        # Cria o embed e aponta para o anexo
        embed = discord.Embed(title=titulo_resumo, color=cor, timestamp=datetime.now())
        embed.set_author(name=f"Registrado por: {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Saldo Anterior", value=f"R$ {saldo_inicial:,.2f}".replace(",", "."), inline=True)
        embed.add_field(name=f"{self.transaction_type.capitalize()}", value=f"R$ {amount:,.2f}".replace(",", "."), inline=True)
        embed.add_field(name="Saldo Final", value=f"R$ {saldo_final:,.2f}".replace(",", "."), inline=True)
        embed.add_field(name="Motivo", value=self.motivo.value, inline=False)
        embed.set_image(url=f"attachment://{image_file.filename}")

        # Envia o embed E o arquivo da imagem na mesma mensagem para obter o link permanente
        final_log_message = await log_channel.send(embed=embed, file=image_file)
        permanent_image_url = final_log_message.attachments[0].url

        # Salva a transação no DB com o link permanente
        await database.add_cash_transaction(self.transaction_type, amount, self.motivo.value, permanent_image_url, saldo_inicial, saldo_final, interaction.user.id)
        
        await interaction.followup.send("✅ Transação registrada com sucesso!", ephemeral=True)
        try:
            await message.delete()
        except discord.Forbidden:
            pass

# --- Painel de Caixa ---
class CashControlPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def check_permissions(self, interaction: discord.Interaction):
        staff_role = interaction.guild.get_role(int(STAFF_ROLE_ID))
        if staff_role and staff_role in interaction.user.roles or interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("❌ Apenas membros da Staff podem registrar transações.", ephemeral=True)
        return False

    @discord.ui.button(label="Depositar", style=discord.ButtonStyle.success, custom_id="cash_deposit", emoji="💰")
    async def deposit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_permissions(interaction): return
        await interaction.response.send_modal(TransactionModal(transaction_type='entrada', bot=self.bot))

    @discord.ui.button(label="Sacar", style=discord.ButtonStyle.danger, custom_id="cash_withdraw", emoji="💸")
    async def withdraw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_permissions(interaction): return
        await interaction.response.send_modal(TransactionModal(transaction_type='saida', bot=self.bot))

# --- Cog Principal ---
class CashControl(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(CashControlPanelView(bot=self.bot))

    @app_commands.command(name="painel_caixa", description="Envia ou atualiza o painel de controle de caixa.")
    @app_commands.checks.has_permissions(administrator=True)
    async def painel_caixa(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        saldo_atual = await database.get_current_balance()
        
        embed = discord.Embed(
            title="💰 Controle de Caixa",
            description=(
                "Utilize os botões abaixo para registrar as movimentações financeiras do seu caixa.\n\n"
                "Registre tanto as entradas, como os depósitos de valores, quanto as saídas, como os saques realizados. "
                "Este controle é essencial para monitorar o fluxo de recursos e manter o saldo atualizado em tempo real."
            ),
            color=discord.Color.gold()
        )
        
        saldo_texto = (
            "Acompanhe o saldo disponível no seu caixa a qualquer momento. Este valor será ajustado automaticamente conforme você registrar entradas e saídas.\n\n"
            f"**R$ {saldo_atual:,.2f}**".replace(",", ".")
        )
        embed.add_field(name="Saldo Atual", value=saldo_texto, inline=False)
        
        view = CashControlPanelView(bot=self.bot)

        history = interaction.channel.history(limit=100)
        async for msg in history:
            if msg.author == self.bot.user and msg.embeds and msg.embeds[0].title == "💰 Controle de Caixa":
                await msg.edit(embed=embed, view=view)
                await interaction.followup.send("✅ Painel de caixa atualizado com o novo layout e saldo!", ephemeral=True)
                return
        
        await interaction.channel.send(embed=embed, view=view)
        await interaction.followup.send("✅ Painel de caixa com novo layout enviado!", ephemeral=True)


    @app_commands.command(name="saldo", description="Verifica o saldo atual do caixa.")
    @app_commands.checks.has_permissions(administrator=True)
    async def caixa_saldo(self, interaction: discord.Interaction):
        saldo_atual = await database.get_current_balance()
        await interaction.response.send_message(f"💰 O saldo atual do caixa é: **R$ {saldo_atual:.2f}**", ephemeral=True)

async def setup(bot: commands.Bot):
    await database.init_db()
    await bot.add_cog(CashControl(bot))