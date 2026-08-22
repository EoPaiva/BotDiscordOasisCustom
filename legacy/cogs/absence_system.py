# cogs/absence_system.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
from datetime import datetime
import database

# --- Carregar Configurações ---
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

GUILD_ID = config.get('GUILD_ID')
ABSENT_ROLE_ID = config.get('ABSENT_ROLE_ID')
ABSENCE_LOGS_CHANNEL_ID = config.get('ABSENCE_LOGS_CHANNEL_ID')
ABSENCE_RETURN_CHANNEL_ID = config.get('ABSENCE_RETURN_CHANNEL_ID')

# --- Formulário de Ausência ---
class AbsenceModal(discord.ui.Modal, title="Solicitação de Ausência"):
    motivo = discord.ui.TextInput(
        label="Motivo da sua ausência",
        style=discord.TextStyle.paragraph,
        placeholder="Ex: Viagem em família, problemas pessoais, etc.",
        required=True
    )
    data_retorno = discord.ui.TextInput(
        label="Data de Retorno (formato DD/MM/AAAA)",
        placeholder="Ex: 25/12/2025",
        required=True,
        min_length=10,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            return_date_obj = datetime.strptime(self.data_retorno.value, '%d/%m/%Y')
            return_date_str_db = return_date_obj.strftime('%Y-%m-%d')
        except ValueError:
            await interaction.followup.send("❌ Formato de data inválido. Por favor, use **DD/MM/AAAA**.", ephemeral=True)
            return

        guild = interaction.guild
        absent_role = guild.get_role(ABSENT_ROLE_ID)
        
        # --- VERIFICAÇÃO MELHORADA DO CANAL DE LOGS ---
        try:
            logs_channel = await guild.fetch_channel(ABSENCE_LOGS_CHANNEL_ID)
        except (discord.NotFound, ValueError):
            # Adiciona o cargo e o registro no DB, mas avisa o admin sobre o erro no log
            await interaction.followup.send(
                "✅ Sua ausência foi registrada, mas **houve um erro ao enviar para o canal de logs.**\n"
                "Por favor, avise um administrador para verificar o `ABSENCE_LOGS_CHANNEL_ID` no `config.json`.", 
                ephemeral=True
            )
            logs_channel = None # Define como None para o resto do código funcionar
        except discord.Forbidden:
            await interaction.followup.send(
                "✅ Sua ausência foi registrada, mas **não tenho permissão para ver ou enviar mensagens no canal de logs.**\n"
                "Por favor, avise um administrador.",
                ephemeral=True
            )
            logs_channel = None

        if not absent_role:
            await interaction.followup.send("🚨 Erro de configuração: Cargo 'Ausente' não encontrado.", ephemeral=True)
            return

        try:
            await interaction.user.add_roles(absent_role, reason=f"Ausência solicitada: {self.motivo.value}")
            await database.add_absence(interaction.user.id, self.motivo.value, return_date_str_db)
        except Exception as e:
            await interaction.followup.send(f"⚠️ Ocorreu um erro ao processar sua solicitação: {e}", ephemeral=True)
            # Se falhar aqui, não envia o log
            return

        if logs_channel:
            embed = discord.Embed(
                title="📝 Nova Solicitação de Ausência",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            embed.add_field(name="Motivo", value=self.motivo.value, inline=False)
            embed.add_field(name="Data de Retorno", value=self.data_retorno.value, inline=False)
            await logs_channel.send(embed=embed)
        
        # A mensagem de sucesso só é enviada se não houve erro no log
        if logs_channel:
            await interaction.followup.send("✅ Sua ausência foi registrada com sucesso!", ephemeral=True)

# --- Painel de Ausência ---
class AbsencePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Solicitar Ausência", style=discord.ButtonStyle.primary, custom_id="request_absence_button", emoji="📝")
    async def request_absence_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AbsenceModal())


# --- Cog do Sistema de Ausência ---
class AbsenceSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(AbsencePanelView())
        self.check_absences.start()

    def cog_unload(self):
        self.check_absences.cancel()

    @tasks.loop(hours=24)
    async def check_absences(self):
        print("Verificando ausências expiradas...")
        expired_absences = await database.get_expired_absences()
        
        if not GUILD_ID:
            print("ERRO: GUILD_ID não definido no config.json. A verificação de ausências foi pulada.")
            return
            
        guild = self.bot.get_guild(int(GUILD_ID))
        if not guild:
            print(f"ERRO: Servidor com ID {GUILD_ID} não encontrado.")
            return

        return_channel = guild.get_channel(ABSENCE_RETURN_CHANNEL_ID)
        absent_role = guild.get_role(ABSENT_ROLE_ID)

        if not return_channel or not absent_role:
            print("ERRO: Canal de retorno ou cargo de ausente não configurado corretamente.")
            return

        for absence_id, user_id in expired_absences:
            member = guild.get_member(user_id)
            if member:
                try:
                    await member.remove_roles(absent_role, reason="Fim do período de ausência")
                    await return_channel.send(f"✅ O membro {member.mention} retornou de sua ausência e não está mais listado como ausente.")
                    await database.deactivate_absence(absence_id)
                except Exception as e:
                    print(f"Falha ao processar retorno de {member.name}: {e}")
            else:
                await database.deactivate_absence(absence_id)
    
    @check_absences.before_loop
    async def before_check_absences(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="painel_ausencia", description="Envia o painel de solicitação de ausência.")
    @app_commands.checks.has_permissions(administrator=True)
    async def painel_ausencia(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="OasisCustom • Sistema de Ausência",
            description="Se você irá se ausentar das atividades, solicite sua ausência clicando no botão abaixo:",
            color=0x2b2d31
        )
        embed.add_field(
            name="📝 Instruções",
            value=(
                "🔹 Informe o motivo da ausência.\n"
                "🔹 Especifique a data estimada de retorno.\n"
                "🔹 A equipe será notificada automaticamente."
            ),
            inline=False
        )
        embed.add_field(
            name="❗ Importante",
            value=(
                "🔸 Ao enviar, você receberá o cargo **Ausente**.\n"
                "🔸 Sua ausência será registrada no canal de logs."
            ),
            inline=False
        )

        await interaction.channel.send("## Solicitação de Ausência", embed=embed, view=AbsencePanelView())
        await interaction.response.send_message("Painel de ausência enviado!", ephemeral=True)


async def setup(bot: commands.Bot):
    await database.init_db()
    await bot.add_cog(AbsenceSystem(bot))