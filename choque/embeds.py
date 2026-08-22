from __future__ import annotations

import discord

from .config import Branding


def branded_embed(
    branding: Branding,
    *,
    title: str,
    description: str | None = None,
    color: int | discord.Color | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color or branding.embed_color,
        timestamp=discord.utils.utcnow(),
    )
    if branding.logo_url:
        embed.set_thumbnail(url=branding.logo_url)
    embed.set_footer(text=branding.footer)
    return embed
