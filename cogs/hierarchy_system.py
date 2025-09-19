# cogs/hierarchy_system.py
import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime
import asyncio

# --- Carregar Configurações ---
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

HIERARQUIA = config.get('HIERARQUIA', [])
HIERARCHY_BULLET_EMOJI = config.get('HIERARCHY_BULLET_EMOJI', '•')
HIERARCHY_CHANNEL_ID = config.get('HIERARCHY_CHANNEL_ID')

# --- Cog Principal ---
class HierarchySystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._hierarchy_lock = asyncio.Lock() # Para evitar atualizações simultâneas

    async def post_hierarchy(self, channel: discord.TextChannel):
        """Função que limpa o canal e posta a hierarquia em várias mensagens separadas."""
        async with self._hierarchy_lock: # Garante que apenas uma atualização rode por vez
            if not channel:
                print("HIERARQUIA: Canal de hierarquia não encontrado.")
                return

            try:
                # Limpa as mensagens anteriores do bot no canal
                await channel.purge(limit=100, check=lambda m: m.author == self.bot.user)
                
                guild = channel.guild
                await guild.chunk(cache=True)

                # Itera na ordem inversa para mostrar do maior para o menor cargo
                for rank_info in reversed(HIERARQUIA):
                    role_id = int(rank_info.get("role_id"))
                    display_name = rank_info.get("display_name", "Cargo Desconhecido")
                    
                    role = guild.get_role(role_id)
                    
                    if not role:
                        print(f"HIERARQUIA: Cargo com ID {role_id} não encontrado.")
                        continue

                    # Cria um embed separado para cada cargo
                    embed = discord.Embed(
                        title=display_name,
                        color=role.color if role.color.value != 0 else 0x2b2d31
                    )
                    
                    members_with_role = sorted(role.members, key=lambda m: m.display_name)
                    
                    if not members_with_role:
                        embed.description = f"{HIERARCHY_BULLET_EMOJI} *Vago*"
                    else:
                        # Lógica para dividir a lista de membros se ela for maior que o limite da descrição
                        member_list_parts = []
                        current_part = ""
                        for member in members_with_role:
                            mention = f"{HIERARCHY_BULLET_EMOJI} {member.mention}\n"
                            if len(current_part) + len(mention) > 4096:
                                member_list_parts.append(current_part)
                                current_part = ""
                            current_part += mention
                        member_list_parts.append(current_part)
                        
                        # Envia a primeira parte na descrição do embed principal
                        embed.description = member_list_parts[0]
                        await channel.send(embed=embed)

                        # Se houver mais partes, envia em embeds separados sem título
                        if len(member_list_parts) > 1:
                            for part in member_list_parts[1:]:
                                continuation_embed = discord.Embed(description=part, color=embed.color)
                                await channel.send(embed=continuation_embed)
                    
                    # Envia um separador visual
                    await channel.send("━━━━━━━━━━━━━━━━━━")
                    await asyncio.sleep(1) # Pequeno delay para não sobrecarregar a API

                print("HIERARQUIA: Mensagens de hierarquia postadas com sucesso.")

            except discord.Forbidden:
                print(f"HIERARQUIA: ERRO - Permissão negada para limpar ou enviar mensagens no canal {channel.name}.")
            except Exception as e:
                print(f"HIERARQUIA: Erro inesperado ao postar: {e}")

    @commands.Cog.listener("on_hierarchy_update")
    async def on_hierarchy_update(self, guild: discord.Guild):
        channel = guild.get_channel(HIERARCHY_CHANNEL_ID)
        if channel:
            await self.post_hierarchy(channel)

    @app_commands.command(name="hierarquia", description="Limpa o canal e posta a lista hierárquica atualizada.")
    @app_commands.checks.has_permissions(administrator=True)
    async def hierarchy_command(self, interaction: discord.Interaction):
        # Usamos o canal da interação para postar
        channel = interaction.channel
        await interaction.response.send_message(f"✅ A hierarquia será postada em {channel.mention}. Isso pode levar um momento...", ephemeral=True)
        await self.post_hierarchy(channel)

async def setup(bot: commands.Bot):
    await bot.add_cog(HierarchySystem(bot))