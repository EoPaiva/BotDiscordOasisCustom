# cogs/registration_system.py
import discord
from discord.ext import commands
from discord import app_commands
import json
import database

# --- Carregar Configurações ---
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

GUILD_ID = config.get('GUILD_ID')
UNREGISTERED_ROLE_ID = config.get('UNREGISTERED_ROLE_ID')
REGISTERED_ROLE_ID_1 = config.get('REGISTERED_ROLE_ID_1')
REGISTERED_ROLE_ID_2 = config.get('REGISTERED_ROLE_ID_2')
REGISTRATION_LOGS_CHANNEL_ID = config.get('REGISTRATION_LOGS_CHANNEL_ID')
REGISTRATION_APPROVAL_CHANNEL_ID = config.get('REGISTRATION_APPROVAL_CHANNEL_ID')
HIERARQUIA = config.get('HIERARQUIA', [])
PRIMEIRO_PREFIXO = HIERARQUIA[0]["prefix"] if HIERARQUIA else "[MEMBRO]"

class ApprovalView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.success, custom_id="approve_button")
    async def approve_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        original_embed = interaction.message.embeds[0]
        target_user_id = int(original_embed.author.name.split('(')[-1].strip(')'))
        nome_val = next((f.value for f in original_embed.fields if f.name == "📋 Nome"), None)
        id_val = next((f.value for f in original_embed.fields if f.name == "🆔 ID"), None)

        if not nome_val or not id_val:
            await interaction.followup.send("Erro ao extrair dados.", ephemeral=True)
            return

        guild = interaction.guild
        member = guild.get_member(target_user_id)
        if not member:
            await interaction.followup.send("Membro não encontrado.", ephemeral=True)
            return
            
        unregistered_role = guild.get_role(int(UNREGISTERED_ROLE_ID))
        registered_role_1 = guild.get_role(int(REGISTERED_ROLE_ID_1))
        registered_role_2 = guild.get_role(int(REGISTERED_ROLE_ID_2))

        try:
            novo_nick = f"{PRIMEIRO_PREFIXO} {nome_val} | {id_val}"
            await member.edit(nick=novo_nick)
            if unregistered_role: await member.remove_roles(unregistered_role, reason=f"Aprovado por {interaction.user.name}")
            if registered_role_1: await member.add_roles(registered_role_1, reason=f"Aprovado por {interaction.user.name}")
            if registered_role_2: await member.add_roles(registered_role_2, reason=f"Aprovado por {interaction.user.name}")
        except discord.Forbidden:
            await interaction.followup.send(f"Falha ao editar {member.mention}.", ephemeral=True)
            return

        logs_channel = guild.get_channel(REGISTRATION_LOGS_CHANNEL_ID)
        if logs_channel:
            await logs_channel.send(embed=original_embed)

        new_embed = original_embed
        new_embed.title = "✅ Registro Aprovado"
        new_embed.color = discord.Color.green()
        new_embed.set_footer(text=f"Aprovado por {interaction.user.name}")
        
        for item in self.children: item.disabled = True
        await interaction.message.edit(embed=new_embed, view=self)

        self.bot.dispatch("hierarchy_update", guild)

        try:
            await member.send("🎉 Seu registro foi **aprovado**!")
        except discord.Forbidden:
            pass

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger, custom_id="reject_button")
    async def reject_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ... (código existente, sem alterações)
        pass

class RegistrationModal(discord.ui.Modal, title="Formulário de Registro"):
    nome = discord.ui.TextInput(label="Nome", placeholder="Ex: Paiva", required=True)
    id_jogador = discord.ui.TextInput(label="ID", placeholder="Ex: 10", required=True)
    telefone = discord.ui.TextInput(label="Telefone", placeholder="Ex: 123-321", required=True)
    recrutador = discord.ui.TextInput(label="Recrutador", placeholder="Ex: Paiva", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        approval_channel = guild.get_channel(REGISTRATION_APPROVAL_CHANNEL_ID)

        if not approval_channel:
            await interaction.followup.send("🚨 Erro de config: Canal de aprovação não encontrado.", ephemeral=True)
            return
            
        embed = discord.Embed(title="⏳ Registro Pendente", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
        embed.set_author(name=f"{interaction.user.name} ({interaction.user.id})", icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="📋 Nome", value=self.nome.value, inline=False)
        embed.add_field(name="🆔 ID", value=self.id_jogador.value, inline=False)
        embed.add_field(name="📞 Telefone", value=self.telefone.value, inline=False)
        embed.add_field(name="🧑‍💼 Recrutador", value=self.recrutador.value, inline=False)
        
        await approval_channel.send(embed=embed, view=ApprovalView(bot=interaction.client))
        await interaction.followup.send("✅ Sua solicitação foi enviada para análise.", ephemeral=True)

class RegistrationPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Registrar", style=discord.ButtonStyle.success, custom_id="register_button")
    async def register_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        unregistered_role = interaction.guild.get_role(int(UNREGISTERED_ROLE_ID))
        if unregistered_role and unregistered_role not in interaction.user.roles:
            await interaction.response.send_message("❌ Você já está registrado.", ephemeral=True)
            return
        await interaction.response.send_modal(RegistrationModal())

class RegistrationSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(RegistrationPanelView())
        self.bot.add_view(ApprovalView(bot=self.bot))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if str(member.guild.id) != str(GUILD_ID):
            return
        unregistered_role = member.guild.get_role(int(UNREGISTERED_ROLE_ID))
        if unregistered_role:
            try:
                await member.add_roles(unregistered_role, reason="Novo membro")
            except discord.Forbidden:
                print(f"Falha ao atribuir cargo para {member.name}.")
    
    @app_commands.command(name="painel_registro", description="Envia o painel de registro de funcionários.")
    @app_commands.checks.has_permissions(administrator=True)
    async def painel_registro(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Oásis Custom - Sistema de Registro", description="Inicie seu registro para fazer parte da nossa equipe.", color=0x2b2d31)
        embed.add_field(name="⚠️ Atenção", value="🔹 Apenas membros não registrados podem se registrar.\n🔹 Após o registro, a equipe verificará suas informações.", inline=False)
        embed.set_footer(text="Oásis Custom • Sistema de Registro")
        await interaction.channel.send("## Registro de funcionários\nClique no botão abaixo para começar.", embed=embed, view=RegistrationPanelView())
        await interaction.response.send_message("Painel enviado!", ephemeral=True)

# ESSA FUNÇÃO ESTAVA FALTANDO
async def setup(bot: commands.Bot):
    await bot.add_cog(RegistrationSystem(bot))