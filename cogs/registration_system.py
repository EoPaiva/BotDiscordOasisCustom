# cogs/registration_system.py
import discord
from discord.ext import commands
from discord import app_commands
import json

# --- Carregar Configurações ---
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

GUILD_ID = config.get('GUILD_ID')
UNREGISTERED_ROLE_ID = config.get('UNREGISTERED_ROLE_ID')
REGISTERED_ROLE_ID_1 = config.get('REGISTERED_ROLE_ID_1')
REGISTERED_ROLE_ID_2 = config.get('REGISTERED_ROLE_ID_2')
REGISTRATION_LOGS_CHANNEL_ID = config.get('REGISTRATION_LOGS_CHANNEL_ID')
REGISTRATION_APPROVAL_CHANNEL_ID = config.get('REGISTRATION_APPROVAL_CHANNEL_ID')

# --- Nova View para Aprovação ---
class ApprovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.success, custom_id="approve_button")
    async def approve_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        original_embed = interaction.message.embeds[0]
        target_user_id = int(original_embed.author.name.split('(')[-1].strip(')'))
        
        nome_val = next((field.value for field in original_embed.fields if field.name == "📋 Nome"), None)
        id_val = next((field.value for field in original_embed.fields if field.name == "🆔 ID"), None)

        if not nome_val or not id_val:
            await interaction.followup.send("Erro ao extrair dados do registro.", ephemeral=True)
            return

        guild = interaction.guild
        member = guild.get_member(target_user_id)

        if not member:
            await interaction.followup.send("Membro não encontrado no servidor.", ephemeral=True)
            # Edita a mensagem original para mostrar que o usuário saiu
            new_embed = original_embed
            new_embed.title = "⚠️ Usuário saiu do Servidor"
            new_embed.color = discord.Color.greyple()
            new_embed.set_footer(text=f"Tentativa de aprovação por {interaction.user.name}")
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(embed=new_embed, view=self)
            return
            
        unregistered_role = guild.get_role(UNREGISTERED_ROLE_ID)
        registered_role_1 = guild.get_role(REGISTERED_ROLE_ID_1)
        registered_role_2 = guild.get_role(REGISTERED_ROLE_ID_2)

        try:
            novo_nick = f"[AJD] {nome_val} | {id_val}"
            await member.edit(nick=novo_nick)
            await member.remove_roles(unregistered_role, reason=f"Registro aprovado por {interaction.user.name}")
            await member.add_roles(registered_role_1, registered_role_2, reason=f"Registro aprovado por {interaction.user.name}")
        except discord.Forbidden:
            await interaction.followup.send(f"❌ FALHA: Não foi possível alterar o apelido/cargos de {member.mention}. Verifique se meu cargo está acima do dele e se tenho as permissões necessárias.", ephemeral=True)
            return

        logs_channel = guild.get_channel(REGISTRATION_LOGS_CHANNEL_ID)
        if logs_channel:
            await logs_channel.send(embed=original_embed)

        new_embed = original_embed
        new_embed.title = "✅ Registro Aprovado"
        new_embed.color = discord.Color.green()
        new_embed.set_footer(text=f"Aprovado por {interaction.user.name}")
        
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(embed=new_embed, view=self)

        try:
            await member.send("🎉 Seu registro no servidor Oásis Custom foi **aprovado**!")
        except discord.Forbidden:
            print(f"Não foi possível enviar DM para {member.name}.")

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger, custom_id="reject_button")
    async def reject_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        original_embed = interaction.message.embeds[0]
        target_user_id = int(original_embed.author.name.split('(')[-1].strip(')'))
        
        guild = interaction.guild
        member = guild.get_member(target_user_id)

        new_embed = original_embed
        new_embed.title = "❌ Registro Recusado"
        new_embed.color = discord.Color.red()
        new_embed.set_footer(text=f"Recusado por {interaction.user.name}")
        
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(embed=new_embed, view=self)

        if member:
            try:
                await member.send("Seu registro no servidor Oásis Custom foi **recusado**. Entre em contato com um administrador para mais detalhes.")
            except discord.Forbidden:
                print(f"Não foi possível enviar DM para {member.name}.")


# --- Formulário (Modal) ---
class RegistrationModal(discord.ui.Modal, title="Formulário de Registro"):
    nome = discord.ui.TextInput(label="Nome", placeholder="Ex: Paiva", required=True)
    id_jogador = discord.ui.TextInput(label="ID", placeholder="Ex: 10", required=True)
    telefone = discord.ui.TextInput(label="Telefone", placeholder="Ex: 123-321", required=True)
    recrutador = discord.ui.TextInput(label="Recrutador", placeholder="Ex: Paiva", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        guild = interaction.guild
        
        # --- MUDANÇA PRINCIPAL: Usando fetch_channel ---
        try:
            # Tenta buscar o canal diretamente da API do Discord, ignorando o cache
            approval_channel = await guild.fetch_channel(REGISTRATION_APPROVAL_CHANNEL_ID)
        except discord.NotFound:
            # O ID está errado ou o canal foi deletado
            await interaction.followup.send("🚨 Erro de configuração: O ID do canal de aprovação está incorreto ou o canal foi apagado.", ephemeral=True)
            return
        except discord.Forbidden:
            # O bot não tem permissão para VER o canal
            await interaction.followup.send("🚨 Erro de permissão: Não consigo 'ver' o canal de aprovação. Verifique minhas permissões para ele.", ephemeral=True)
            return
        except Exception as e:
            # Outros erros
            await interaction.followup.send(f"🚨 Ocorreu um erro inesperado ao buscar o canal: {e}", ephemeral=True)
            return
            
        embed = discord.Embed(
            title="⏳ Registro Pendente de Aprovação",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=f"{interaction.user.name} ({interaction.user.id})", icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="📋 Nome", value=self.nome.value, inline=False)
        embed.add_field(name="🆔 ID", value=self.id_jogador.value, inline=False)
        embed.add_field(name="📞 Telefone", value=self.telefone.value, inline=False)
        embed.add_field(name="🧑‍💼 Recrutador", value=self.recrutador.value, inline=False)
        
        await approval_channel.send(embed=embed, view=ApprovalView())

        await interaction.followup.send("✅ Sua solicitação de registro foi enviada para análise. Você será notificado quando for aprovada.", ephemeral=True)


# --- Painel com Botão ---
class RegistrationPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Registrar", style=discord.ButtonStyle.success, custom_id="register_button")
    async def register_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        unregistered_role = interaction.guild.get_role(UNREGISTERED_ROLE_ID)
        if unregistered_role not in interaction.user.roles:
            await interaction.response.send_message("❌ Você já está registrado em nosso sistema.", ephemeral=True)
            return
        
        await interaction.response.send_modal(RegistrationModal())


# --- Cog Principal ---
class RegistrationSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(RegistrationPanelView())
        self.bot.add_view(ApprovalView())

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if str(member.guild.id) != str(GUILD_ID):
            return
        unregistered_role = member.guild.get_role(UNREGISTERED_ROLE_ID)
        if unregistered_role:
            try:
                await member.add_roles(unregistered_role, reason="Novo membro")
            except discord.Forbidden:
                print(f"Falha ao atribuir cargo para {member.name}: Permissões insuficientes.")
        else:
            print(f"ERRO: Cargo de não-registrado (ID: {UNREGISTERED_ROLE_ID}) não encontrado.")

    @app_commands.command(name="painel_registro", description="Envia o painel de registro de funcionários.")
    @app_commands.checks.has_permissions(administrator=True)
    async def painel_registro(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Oásis Custom - Sistema de Registro de Funcionarios",
            description="Você está prestes a iniciar seu registro para fazer parte da nossa grade de funcionarios.",
            color=0x2b2d31
        )
        embed.add_field(name="⚠️ Atenção", value="🔹 Apenas membros ainda não registrados podem se registrar.\n🔹 Após o registro, a equipe verificará suas informações.", inline=False)
        embed.set_footer(text="Oásis Custom • Sistema de Registro • Atendimento Exclusivo")
        
        await interaction.channel.send("## Registro de funcionarios\nClique no botão abaixo para começar.", embed=embed, view=RegistrationPanelView())
        await interaction.response.send_message("Painel de registro enviado!", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(RegistrationSystem(bot))