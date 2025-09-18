# cogs/farm_system.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import database
from datetime import datetime
import asyncio
import re

# --- Carregar Configurações ---
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

GUILD_ID = config.get('GUILD_ID')
STAFF_ROLE_ID = config.get('STAFF_ROLE_ID')
FARM_TICKET_CATEGORY_ID = config.get('FARM_TICKET_CATEGORY_ID')
FARM_APPROVAL_CHANNEL_ID = config.get('FARM_APPROVAL_CHANNEL_ID')

# --- Classes de Views e Modals (sem alterações) ---
class FarmApprovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    async def handle_approval(self, interaction: discord.Interaction, new_status: str):
        if not STAFF_ROLE_ID or not str(STAFF_ROLE_ID).isdigit():
            await interaction.response.send_message("❌ Erro de config: STAFF_ROLE_ID inválido.", ephemeral=True)
            return
        staff_role = interaction.guild.get_role(int(STAFF_ROLE_ID))
        if not staff_role or (staff_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            original_embed = interaction.message.embeds[0]
            footer_text = original_embed.footer.text
            match = re.search(r"ID da Entrega: (\d+)", footer_text)
            if not match:
                await interaction.followup.send("❌ Erro Interno: ID da entrega não encontrado.", ephemeral=True)
                return
            delivery_id = int(match.group(1))
            await database.update_delivery_status(delivery_id, new_status)
            delivery_info = await database.get_delivery_info(delivery_id)
            if delivery_info and delivery_info["private_message_id"] and delivery_info["user_id"]:
                ticket_info = await database.get_user_ticket(delivery_info["user_id"])
                if ticket_info:
                    ticket_channel = await interaction.guild.fetch_channel(ticket_info[0])
                    private_message = await ticket_channel.fetch_message(delivery_info["private_message_id"])
                    old_embed = private_message.embeds[0]
                    if new_status == 'aprovado':
                        new_private_embed = discord.Embed(title="✅ Sua Entrega foi APROVADA!", color=discord.Color.green())
                    else:
                        new_private_embed = discord.Embed(title="❌ Sua Entrega foi NEGADA.", color=discord.Color.red(), description="Contate um staff para mais detalhes.")
                    new_private_embed.set_image(url=old_embed.image.url if old_embed.image else None)
                    await private_message.edit(embed=new_private_embed)
            if new_status == 'aprovado':
                original_embed.title = "✅ Entrega Aprovada!"
                original_embed.color = discord.Color.green()
                original_embed.set_footer(text=f"Aprovado por {interaction.user.display_name}")
            else:
                original_embed.title = "❌ Entrega Negada!"
                original_embed.color = discord.Color.red()
                original_embed.set_footer(text=f"Negado por {interaction.user.display_name}")
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(embed=original_embed, view=self)
        except Exception as e:
            print(f"ERRO AO PROCESSAR APROVAÇÃO: {e}")
            await interaction.followup.send(f"⚠️ **Erro inesperado:**\n```\n{e}\n```", ephemeral=True)
    @discord.ui.button(label="Aceitar", style=discord.ButtonStyle.success, custom_id="accept_delivery")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_approval(interaction, "aprovado")
    @discord.ui.button(label="Negar", style=discord.ButtonStyle.danger, custom_id="deny_delivery")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_approval(interaction, "negado")

class FarmDeliveryModal(discord.ui.Modal, title="Registrar Entrega de Farm - Etapa 1/2"):
    item_name = discord.ui.TextInput(label="Nome do Item", placeholder="Ex: Ouro, Madeira...", required=True)
    item_quantity = discord.ui.TextInput(label="Quantidade", placeholder="Ex: 1500", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            quantity = int(self.item_quantity.value)
            if quantity <= 0: raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ A quantidade deve ser um número positivo.", ephemeral=True)
            return
        await interaction.response.send_message("✅ Dados recebidos. **Agora, envie a imagem da sua entrega.**", ephemeral=True)
        try:
            message = await interaction.client.wait_for("message", timeout=120.0, check=lambda m: m.author == interaction.user and m.channel == interaction.channel and m.attachments)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Tempo esgotado. Inicie o processo novamente.", ephemeral=True)
            return
        image_url = message.attachments[0].url
        delivery_id = await database.add_farm_delivery(interaction.user.id, self.item_name.value, quantity, image_url)
        private_embed = discord.Embed(title="✅ Entrega Enviada para Análise!", color=discord.Color.yellow(), description="Sua entrega aguarda aprovação da staff.")
        private_embed.set_image(url=image_url)
        private_message = await interaction.channel.send(embed=private_embed)
        await database.set_private_message_id(delivery_id, private_message.id)
        try:
            approval_channel = await interaction.guild.fetch_channel(FARM_APPROVAL_CHANNEL_ID)
            public_embed = discord.Embed(title="⏳ Nova Entrega Pendente", color=discord.Color.orange(), timestamp=datetime.now())
            public_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            public_embed.add_field(name="Item", value=self.item_name.value, inline=True)
            public_embed.add_field(name="Quantidade", value=f"**{quantity:,}**".replace(",", "."), inline=True)
            public_embed.set_image(url=image_url)
            public_embed.set_footer(text=f"ID da Entrega: {delivery_id}")
            await approval_channel.send(embed=public_embed, view=FarmApprovalView())
        except (discord.NotFound, ValueError):
            await interaction.followup.send("⚠️ Erro de Config: Canal de aprovação não encontrado.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("⚠️ Erro de Permissão: Não consigo enviar no canal de aprovação.", ephemeral=True)
        try:
            await message.delete()
        except discord.Forbidden:
            pass

class FarmTicketActionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Entregar Farm", style=discord.ButtonStyle.success, custom_id="deliver_farm", emoji="📦")
    async def deliver_farm_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FarmDeliveryModal())
    @discord.ui.button(label="Minhas Entregas", style=discord.ButtonStyle.secondary, custom_id="my_deliveries", emoji="📋")
    async def my_deliveries_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_deliveries = await database.get_user_deliveries(interaction.user.id)
        embed = discord.Embed(title=f"📋 Suas Últimas 10 Entregas", color=discord.Color.blurple())
        if not user_deliveries:
            embed.description = "Você ainda não registrou nenhuma entrega."
        else:
            description = ""
            status_emoji = {"aprovado": "✅", "negado": "❌", "pendente": "⏳"}
            for item, quantity, image_url, status, ts in user_deliveries:
                dt_object = datetime.fromisoformat(ts)
                image_link = f"[Ver Imagem]({image_url})" if image_url else "Sem imagem"
                description += f"{status_emoji.get(status, '')} **{item}**: `{quantity:,}` - {image_link} - <t:{int(dt_object.timestamp())}:R>\n".replace(",", ".")
            embed.description = description
        await interaction.followup.send(embed=embed, ephemeral=True)
    @discord.ui.button(label="Fechar Ticket", style=discord.ButtonStyle.danger, custom_id="close_farm_ticket", emoji="🔒")
    async def close_ticket_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Este canal será excluído em 5 segundos...", ephemeral=True)
        await database.delete_farm_ticket(interaction.user.id)
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket de farm fechado por {interaction.user.name}")

class FarmTicketOpenerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Abrir Ticket de Farm", style=discord.ButtonStyle.success, custom_id="open_farm_ticket", emoji="🌾")
    async def open_ticket_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        existing_ticket = await database.get_user_ticket(interaction.user.id)
        if existing_ticket:
            channel_id = existing_ticket[0]
            channel = interaction.guild.get_channel(channel_id)
            if channel:
                await interaction.followup.send(f"❌ Você já tem um ticket aberto em {channel.mention}!", ephemeral=True)
            else:
                await database.delete_farm_ticket(interaction.user.id)
                await interaction.followup.send("⚠️ Seu ticket antigo não foi encontrado. Clique novamente.", ephemeral=True)
            return
        guild = interaction.guild
        try:
            category = await guild.fetch_channel(FARM_TICKET_CATEGORY_ID)
            if not isinstance(category, discord.CategoryChannel):
                await interaction.followup.send("🚨 Erro de config: `FARM_TICKET_CATEGORY_ID` não é uma categoria.", ephemeral=True)
                return
        except (discord.NotFound, ValueError, TypeError):
            await interaction.followup.send("🚨 Erro de config: Categoria de farm não encontrada.", ephemeral=True)
            return
        try:
            staff_role = guild.get_role(int(STAFF_ROLE_ID))
            if not staff_role: raise ValueError("Cargo não encontrado")
        except (ValueError, TypeError):
            await interaction.followup.send("🚨 Erro de config: Cargo da staff não encontrado.", ephemeral=True)
            return
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
            staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }
        channel_name = f"🌾-farm-{interaction.user.name}"
        try:
            ticket_channel = await category.create_text_channel(name=channel_name, overwrites=overwrites)
            await database.create_farm_ticket(interaction.user.id, ticket_channel.id)
        except Exception as e:
            await interaction.followup.send(f"🚨 Ocorreu um erro ao criar seu ticket: {e}", ephemeral=True)
            return
        embed = discord.Embed(title=f"Bem-vindo ao seu Ticket de Farm, {interaction.user.display_name}!", description="Use os botões abaixo para gerenciar suas entregas.", color=0x8fbc8f)
        await ticket_channel.send(content=interaction.user.mention, embed=embed, view=FarmTicketActionsView())
        await interaction.followup.send(f"✅ Seu ticket de farm foi criado em {ticket_channel.mention}!", ephemeral=True)

# --- Cog Principal ---
class FarmSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_ranking_loop.start() # Inicia a tarefa em segundo plano

    def cog_unload(self):
        self.update_ranking_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(FarmTicketOpenerView())
        self.bot.add_view(FarmTicketActionsView())
        self.bot.add_view(FarmApprovalView())
        await database.init_db()
        print("Cog 'FarmSystem' carregado e Views registradas.")

    # --- NOVA TAREFA DE ATUALIZAÇÃO AUTOMÁTICA ---
    @tasks.loop(minutes=10)
    async def update_ranking_loop(self):
        print("RANKING LOOP: Verificando se há ranking para atualizar...")
        try:
            with open('ranking_config.json', 'r') as f:
                data = json.load(f)
            channel_id = data.get('ranking_channel_id')
            message_id = data.get('ranking_message_id')

            if not channel_id or not message_id:
                print("RANKING LOOP: Nenhuma mensagem de ranking configurada.")
                return

            channel = await self.bot.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
            
            # A mesma lógica de criação de embed do comando de ranking
            ranking_data = await database.get_farm_ranking()
            embed = self.build_ranking_embed(ranking_data)
            
            await message.edit(embed=embed)
            print(f"RANKING LOOP: Ranking atualizado na mensagem {message_id}")

        except FileNotFoundError:
            print("RANKING LOOP: Arquivo ranking_config.json não encontrado.")
        except (discord.NotFound, discord.Forbidden):
            print("RANKING LOOP: Mensagem ou canal do ranking não encontrado. Parando atualizações.")
            # Limpa a configuração para evitar erros repetidos
            with open('ranking_config.json', 'w') as f:
                json.dump({"ranking_channel_id": None, "ranking_message_id": None}, f)
        except Exception as e:
            print(f"RANKING LOOP: Erro inesperado: {e}")

    @update_ranking_loop.before_loop
    async def before_update_ranking(self):
        await self.bot.wait_until_ready()

    # Função auxiliar para construir o embed do ranking
    def build_ranking_embed(self, ranking_data):
        embed = discord.Embed(title="🏆 Ranking Geral de Farm - Top 10 (Aprovados)", color=discord.Color.gold(), timestamp=datetime.now())
        if not ranking_data:
            embed.description = "Nenhuma entrega aprovada foi registrada ainda para gerar um ranking."
        else:
            description_lines = []
            # Precisamos buscar os membros de forma síncrona dentro do que pudermos
            guild = self.bot.get_guild(int(GUILD_ID))
            for i, (user_id, total) in enumerate(ranking_data):
                user = guild.get_member(user_id) # Tenta pegar do cache primeiro
                user_mention = user.mention if user else f"Usuário (ID: {user_id})"
                medal = {0: "🥇", 1: "🥈", 2: "🥉"}.get(i, f"**#{i+1}**")
                description_lines.append(f"{medal} {user_mention} - `{total:,}` itens entregues".replace(",", "."))
            embed.description = "\n".join(description_lines)
        return embed

    @app_commands.command(name="painel_farm", description="Envia o painel para abrir tickets de farm.")
    @app_commands.checks.has_permissions(administrator=True)
    async def painel_farm(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Sistema de Registro de Farm", description="Para manter o servidor organizado e garantir a privacidade de suas entregas, clique no botão abaixo para abrir seu canal de farm pessoal.", color=discord.Color.dark_green())
        embed.set_footer(text="Todas as suas entregas serão feitas em um canal privado entre você e a staff.")
        await interaction.channel.send(embed=embed, view=FarmTicketOpenerView())
        await interaction.response.send_message("Painel de farm enviado!", ephemeral=True)
    
    # --- COMANDOS DE RANKING ATUALIZADOS ---
    @app_commands.command(name="ranking_iniciar", description="Cria e ativa a atualização automática do ranking neste canal.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ranking_iniciar(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        with open('ranking_config.json', 'r') as f:
            data = json.load(f)
        if data.get("message_id"):
            await interaction.followup.send("❌ Um ranking automático já está ativo em outro canal. Use `/ranking_parar` primeiro.", ephemeral=True)
            return
            
        ranking_data = await database.get_farm_ranking()
        embed = self.build_ranking_embed(ranking_data)
        
        message = await interaction.channel.send(embed=embed)
        
        # Salva a informação no arquivo de configuração
        with open('ranking_config.json', 'w') as f:
            json.dump({"ranking_channel_id": message.channel.id, "ranking_message_id": message.id}, f)
            
        await interaction.followup.send(f"✅ Ranking iniciado! Esta mensagem será atualizada a cada 10 minutos.", ephemeral=True)

    @app_commands.command(name="ranking_parar", description="Para a atualização automática do ranking.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ranking_parar(self, interaction: discord.Interaction):
        with open('ranking_config.json', 'w') as f:
            json.dump({"ranking_channel_id": None, "ranking_message_id": None}, f)
        await interaction.response.send_message("✅ Atualização automática do ranking foi parada.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(FarmSystem(bot))