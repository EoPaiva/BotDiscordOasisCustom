# main.py
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio
import json

load_dotenv()
TOKEN = os.getenv("TOKEN")

# Habilita todas as intents necessárias para os sistemas funcionarem
intents = discord.Intents.default()
intents.members = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}!')
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        guild_id = config.get('GUILD_ID')
        if guild_id:
            guild = discord.Object(id=guild_id)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"Sincronizados {len(synced)} comandos para o servidor {guild_id}.")
    except Exception as e:
        print(f"Falha ao sincronizar comandos: {e}")

async def load_cogs():
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                print(f"Carregado com sucesso: {filename}")
            except Exception as e:
                print(f"--- FALHA AO CARREGAR: {filename} ---")
                print(f"ERRO: {e}\n")

async def main():
    if not TOKEN:
        print("ERRO: O TOKEN do bot não foi encontrado no arquivo '.env'.")
        return
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())