from __future__ import annotations

import argparse
import asyncio
import sys

import discord

from choque.bot import ChoqueBot
from choque.config import AppConfig
from choque.logging_config import configure_logging


async def run_check(config: AppConfig) -> int:
    bot = ChoqueBot(config, check_mode=True)
    try:
        await bot.setup_hook()
        migration = await bot.services.database.fetchone(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        )
        commands = list(bot.tree.walk_commands())
        persistent_views = len(bot.persistent_views)
        print("CHECK_OK")
        print(f"database={config.database_path.resolve()}")
        print(f"migration={migration['version']}")
        print(f"guild_id={bot.guild_id or 'not_configured'}")
        print(f"cogs={len(bot.cogs)}")
        print(f"commands={len(commands)}")
        print(f"persistent_views={persistent_views}")
        return 0
    finally:
        await bot.close()


async def run_bot(config: AppConfig) -> int:
    if not config.token:
        print(
            "ERRO: defina DISCORD_TOKEN com um token novo. "
            "O token encontrado no histórico deve ser considerado comprometido.",
            file=sys.stderr,
        )
        return 2
    bot = ChoqueBot(config)
    try:
        async with bot:
            await bot.start(config.token)
    except discord.PrivilegedIntentsRequired:
        print(
            "ERRO: habilite Server Members Intent em Discord Developer Portal > "
            "Bot > Privileged Gateway Intents.",
            file=sys.stderr,
        )
        return 3
    except discord.LoginFailure:
        print("ERRO: DISCORD_TOKEN inválido ou revogado.", file=sys.stderr)
        return 4
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CHOQUE - BGR Discord Bot")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Valida banco, migrations, cogs, comandos e views sem conectar ao Discord.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AppConfig.load()
    configure_logging(config.log_level)
    try:
        return asyncio.run(run_check(config) if args.check else run_bot(config))
    except KeyboardInterrupt:
        print("Encerramento solicitado; recursos fechados com segurança.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
