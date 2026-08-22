# cogs/hr_system.py
import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime

# --- Carregar Configurações ---
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

STAFF_ROLE_ID = config.get('STAFF_ROLE_ID')
HR_LOGS_CHANNEL_ID = config.get('HR_LOGS_CHANNEL_ID')
DISMISSAL_ALERT_CHANNEL_ID = config.get('DISMISSAL_ALERT_CHANNEL_ID')
PROMOTION_ALERT_CHANNEL_ID = config.get('PROMOTION_ALERT_CHANNEL_ID')
DEMOTION_ALERT_CHANNEL_ID = config.get('DEMOTION_ALERT_CHANNEL_ID')
HIERARQUIA = config.get('HIERARQUIA', [])

# --- Formulários (Modals) ---

class DismissalModal(discord.ui.Modal, title="Formulário de Desligamento"):
    membro_id = discord.ui.TextInput(label="ID do Membro a ser Desligado", required=True)
    motivo = discord.ui.TextInput(label="Motivo do Desligamento", style=discord.TextStyle.paragraph, required=True)
    provas = discord.ui.TextInput(label="Provas (Opcional, links)", style=discord.TextStyle.paragraph, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        logs_channel = guild.get_channel(HR_LOGS_CHANNEL_ID)
        alert_channel = guild.get_channel(DISMISSAL_ALERT_CHANNEL_ID)

        try:
            member_to_dismiss = await guild.fetch_member(int(self.membro_id.value))
        except (ValueError, discord.NotFound):
            await interaction.followup.send("❌ ID de membro inválido ou não encontrado.", ephemeral=True)
            return

        try:
            await member_to_dismiss.edit(nick=None, roles=[], reason=f"Desligado por {interaction.user.name}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Falha ao modificar o membro. Verifique as permissões do bot.", ephemeral=True)
            return

        if logs_channel:
            log_embed = discord.Embed(title="🚨 Desligamento (Log Staff)", color=discord.Color.dark_red(), timestamp=datetime.now())
            log_embed.set_author(name=f"Executado por: {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
            log_embed.add_field(name="Membro", value=f"{member_to_dismiss.mention} (`{member_to_dismiss.id}`)", inline=False)
            log_embed.add_field(name="Motivo", value=self.motivo.value, inline=False)
            if self.provas.value:
                log_embed.add_field(name="Provas", value=self.provas.value, inline=False)
            await logs_channel.send(embed=log_embed)
        
        if alert_channel:
            description_text = (
                f"**Nome:** {member_to_dismiss.mention}\n"
                f"**ID:** `{member_to_dismiss.id}`\n"
                f"**Motivo:** {self.motivo.value}\n"
                f"**Quem desligou:** {interaction.user.mention}"
            )
            alert_embed = discord.Embed(title="❌ Demissão de Membro", description=description_text, color=discord.Color.dark_red(), timestamp=datetime.now())
            if interaction.guild.icon:
                alert_embed.set_footer(icon_url=interaction.guild.icon.url)
            await alert_channel.send(embed=alert_embed)

        interaction.client.dispatch("hierarchy_update", interaction.guild)
        await interaction.followup.send(f"✅ O membro {member_to_dismiss.display_name} foi desligado com sucesso.", ephemeral=True)

class PromotionModal(discord.ui.Modal, title="Formulário de Promoção"):
    membro_id = discord.ui.TextInput(label="ID do Membro a ser Promovido", required=True)
    motivo = discord.ui.TextInput(label="Motivo da Promoção", placeholder="Ex: Mérito e Desempenho", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        alert_channel = guild.get_channel(PROMOTION_ALERT_CHANNEL_ID)

        try:
            member = await guild.fetch_member(int(self.membro_id.value))
        except (ValueError, discord.NotFound):
            await interaction.followup.send("❌ ID de membro inválido ou não encontrado.", ephemeral=True)
            return

        member_roles_ids = {role.id for role in member.roles}
        current_rank_index = -1
        for i in range(len(HIERARQUIA) - 1, -1, -1):
            if int(HIERARQUIA[i]["role_id"]) in member_roles_ids:
                current_rank_index = i
                break
        
        if current_rank_index >= len(HIERARQUIA) - 1:
            await interaction.followup.send(f"🏆 {member.display_name} já está no cargo mais alto!", ephemeral=True)
            return
        
        base_name = ""
        if member.nick:
            parts = member.nick.split(']', 1)
            if len(parts) > 1: base_name = parts[1].strip()
        if not base_name:
            base_name = member.global_name or member.name

        new_prefix = HIERARQUIA[current_rank_index + 1]["prefix"]
        new_nick = f"{new_prefix} {base_name}"
        
        current_role = guild.get_role(int(HIERARQUIA[current_rank_index]["role_id"])) if current_rank_index != -1 else None
        next_role = guild.get_role(int(HIERARQUIA[current_rank_index + 1]["role_id"]))
        
        try:
            await member.edit(nick=new_nick)
            if current_role: await member.remove_roles(current_role, reason="Promoção")
            await member.add_roles(next_role, reason="Promoção")
        except discord.Forbidden:
             await interaction.followup.send("❌ Falha ao editar apelido/cargos.", ephemeral=True)
             return
        
        if alert_channel:
            description_text = (
                f"**Nome:** {member.mention}\n"
                f"**Cargo Anterior:** {current_role.mention if current_role else 'Nenhum'}\n"
                f"**Cargo Novo:** {next_role.mention}\n"
                f"**Motivo:** {self.motivo.value}"
            )
            alert_embed = discord.Embed(title="📈 Promoção de Membro", description=description_text, color=discord.Color.green(), timestamp=datetime.now())
            if member.display_avatar:
                alert_embed.set_thumbnail(url=member.display_avatar.url)
            await alert_channel.send(embed=alert_embed)

        interaction.client.dispatch("hierarchy_update", interaction.guild)
        await interaction.followup.send(f"✅ {member.display_name} promovido para {next_role.name}!", ephemeral=True)

class DemotionModal(discord.ui.Modal, title="Formulário de Rebaixamento"):
    membro_id = discord.ui.TextInput(label="ID do Membro a ser Rebaixado", required=True)
    motivo = discord.ui.TextInput(label="Motivo do Rebaixamento", placeholder="Ex: Ajuste de quadro", required=True)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        alert_channel = guild.get_channel(DEMOTION_ALERT_CHANNEL_ID)

        try:
            member = await guild.fetch_member(int(self.membro_id.value))
        except (ValueError, discord.NotFound):
            await interaction.followup.send("❌ ID de membro inválido ou não encontrado.", ephemeral=True)
            return

        member_roles_ids = {role.id for role in member.roles}
        current_rank_index = -1
        for i in range(len(HIERARQUIA) - 1, -1, -1):
            if int(HIERARQUIA[i]["role_id"]) in member_roles_ids:
                current_rank_index = i
                break
        
        if current_rank_index <= 0:
            await interaction.followup.send(f"📉 O membro {member.display_name} já está no cargo mais baixo ou não tem cargo!", ephemeral=True)
            return

        base_name = ""
        if member.nick:
            parts = member.nick.split(']', 1)
            if len(parts) > 1: base_name = parts[1].strip()
        if not base_name:
            base_name = member.global_name or member.name
            
        new_prefix = HIERARQUIA[current_rank_index - 1]["prefix"]
        new_nick = f"{new_prefix} {base_name}"
        
        current_role = guild.get_role(int(HIERARQUIA[current_rank_index]["role_id"]))
        previous_role = guild.get_role(int(HIERARQUIA[current_rank_index - 1]["role_id"]))
        
        try:
            await member.edit(nick=new_nick)
            await member.remove_roles(current_role, reason="Rebaixamento")
            await member.add_roles(previous_role, reason="Rebaixamento")
        except discord.Forbidden:
             await interaction.followup.send("❌ Falha ao editar apelido/cargos.", ephemeral=True)
             return

        if alert_channel:
            description_text = (
                f"**Funcionário:** {member.mention}\n"
                f"**Cargo anterior:** {current_role.mention}\n"
                f"**Novo cargo:** {previous_role.mention}\n"
                f"**Motivo:** {self.motivo.value}"
            )
            alert_embed = discord.Embed(title="📉 Rebaixamento de Membro", description=description_text, color=discord.Color.orange(), timestamp=datetime.now())
            if member.display_avatar:
                alert_embed.set_thumbnail(url=member.display_avatar.url)
            await alert_channel.send(embed=alert_embed)

        interaction.client.dispatch("hierarchy_update", interaction.guild)
        await interaction.followup.send(f"✅ {member.display_name} rebaixado para {previous_role.name}!", ephemeral=True)


class HRPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    async def check_permissions(self, interaction: discord.Interaction):
        staff_role = interaction.guild.get_role(int(STAFF_ROLE_ID))
        if staff_role in interaction.user.roles or interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("❌ Apenas membros da Staff podem usar estas funções.", ephemeral=True)
        return False
    @discord.ui.button(label="Desligamento", style=discord.ButtonStyle.danger, custom_id="hr_dismiss", emoji="🔴")
    async def dismiss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_permissions(interaction): return
        await interaction.response.send_modal(DismissalModal())
    @discord.ui.button(label="Promoção", style=discord.ButtonStyle.success, custom_id="hr_promote", emoji="🟢")
    async def promote_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_permissions(interaction): return
        await interaction.response.send_modal(PromotionModal())
    @discord.ui.button(label="Rebaixamento", style=discord.ButtonStyle.primary, custom_id="hr_demote", emoji="🔵")
    async def demote_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_permissions(interaction): return
        await interaction.response.send_modal(DemotionModal())


class HRSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(HRPanelView())

    @app_commands.command(name="painel_rh", description="Envia o painel de gestão de RH.")
    @app_commands.checks.has_permissions(administrator=True)
    async def painel_rh(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Central de Gestão de Recursos Humanos",
            description=(
                "Este painel é o seu ponto central para a administração da nossa equipe. Ele foi projetado para otimizar o fluxo de trabalho e garantir uma gestão eficiente e transparente dos cargos e responsabilidades de cada colaborador.\n\n"
                "Utilize os botões abaixo para gerenciar os membros da equipe de forma segura e profissional."
            ),
            color=0x2b2d31
        )
        embed.add_field(name="🔴 Desligamento", value="Inicia o processo formal para desvincular um membro da equipe.", inline=False)
        embed.add_field(name="🟢 Promoção", value="Promove um membro para um novo cargo, reconhecendo seu mérito e desempenho.", inline=False)
        embed.add_field(name="🔵 Rebaixamento", value="Permite ajustar o cargo de um membro para uma posição inferior.", inline=False)
        await interaction.channel.send(embed=embed, view=HRPanelView())
        await interaction.response.send_message("Painel de RH atualizado enviado!", ephemeral=True)

    # --- NOVO COMANDO PARA VERIFICAR APELIDOS ---
    @app_commands.command(name="verificar_apelidos", description="Verifica e corrige os apelidos de todos os membros com cargo na hierarquia.")
    @app_commands.checks.has_permissions(administrator=True)
    async def verificar_apelidos(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        guild = interaction.guild
        updated_members = []
        checked_count = 0
        
        async for member in guild.fetch_members(limit=None):
            if member.bot:
                continue
            
            checked_count += 1
            member_roles_ids = {role.id for role in member.roles}
            
            correct_prefix = None
            
            for rank_info in reversed(HIERARQUIA):
                if int(rank_info["role_id"]) in member_roles_ids:
                    correct_prefix = rank_info["prefix"]
                    break
            
            if correct_prefix:
                current_nick = member.nick or member.global_name or member.name
                
                if current_nick.startswith(correct_prefix):
                    continue

                base_name = ""
                if member.nick:
                    # Tenta extrair o nome base de apelidos com e sem prefixo
                    if ']' in member.nick:
                        parts = member.nick.split(']', 1)
                        base_name = parts[1].strip() if len(parts) > 1 else member.nick
                    else:
                        base_name = member.nick
                
                if not base_name:
                    base_name = member.global_name or member.name

                new_nick = f"{correct_prefix} {base_name}"

                try:
                    await member.edit(nick=new_nick, reason="Correção automática de apelido")
                    updated_members.append(f"✅ {member.mention} → `{new_nick}`")
                except discord.Forbidden:
                    updated_members.append(f"❌ Falha ao atualizar {member.mention} (permissão).")
                except Exception as e:
                    updated_members.append(f"⚠️ Erro ao atualizar {member.mention}: {e}")

        embed = discord.Embed(
            title="✅ Verificação de Apelidos Concluída",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Membros Verificados", value=str(checked_count), inline=True)
        embed.add_field(name="Apelidos Corrigidos", value=str(len([m for m in updated_members if '✅' in m])), inline=True)
        
        if updated_members:
            report_text = "\n".join(updated_members[:20])
            if len(updated_members) > 20:
                report_text += f"\n... e mais {len(updated_members) - 20} outros."
            embed.add_field(name="Detalhes das Atualizações", value=report_text, inline=False)
        else:
            embed.description = "Nenhum apelido precisou ser corrigido. Tudo em ordem!"

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HRSystem(bot))