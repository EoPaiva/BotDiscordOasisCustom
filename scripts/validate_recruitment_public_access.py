from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.channel_names import format_channel_name  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from scripts.configure_recruitment_candidate_access import (  # noqa: E402
    COMMUNITY_CATEGORY_ID,
    PRIVATE_REVIEW_ID,
    PUBLIC_STATUS_ID,
)
from scripts.configure_recruitment_workflow import (  # noqa: E402
    READ_MESSAGE_HISTORY,
    RECRUITMENT_APPROVED_ID,
    RECRUITMENT_PANEL_ID,
    RECRUITMENT_REJECTED_ID,
    RECRUITMENT_REQUIREMENTS_ID,
    SEND_MESSAGES,
    VIEW_CHANNEL,
    DiscordRest,
)


def _overwrite(channel: dict, target_id: int) -> dict | None:
    return next(
        (
            item
            for item in channel.get("permission_overwrites", [])
            if int(item.get("id", 0)) == target_id and int(item.get("type", -1)) == 0
        ),
        None,
    )


def _message_contains_protocol(message: dict, protocol: str) -> bool:
    haystack = [str(message.get("content") or "")]
    for embed in message.get("embeds", []):
        haystack.extend(
            [str(embed.get("title") or ""), str(embed.get("description") or "")]
        )
        haystack.extend(str(field.get("value") or "") for field in embed.get("fields", []))
    return protocol in "\n".join(haystack)


async def run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default="AL-00005")
    args = parser.parse_args()
    protocol = args.protocol.strip().upper()
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    guild_id = int(config.default_guild_id)
    api = DiscordRest(config.token)
    try:
        channels = await api.request("GET", f"/guilds/{guild_id}/channels")
        by_id = {int(channel["id"]): channel for channel in channels}
        public_ids = (
            RECRUITMENT_REQUIREMENTS_ID,
            RECRUITMENT_PANEL_ID,
            PUBLIC_STATUS_ID,
            RECRUITMENT_APPROVED_ID,
            RECRUITMENT_REJECTED_ID,
        )
        failures: list[str] = []
        for channel_id in public_ids:
            channel = by_id.get(channel_id)
            if not channel:
                failures.append(f"public_channel_missing:{channel_id}")
                continue
            everyone = _overwrite(channel, guild_id)
            allow = int(everyone.get("allow", 0)) if everyone else 0
            deny = int(everyone.get("deny", 0)) if everyone else 0
            if allow & (VIEW_CHANNEL | READ_MESSAGE_HISTORY) != (
                VIEW_CHANNEL | READ_MESSAGE_HISTORY
            ):
                failures.append(f"public_view_missing:{channel_id}")
            if not deny & SEND_MESSAGES:
                failures.append(f"public_send_not_denied:{channel_id}")

        review = by_id.get(PRIVATE_REVIEW_ID)
        review_everyone = _overwrite(review, guild_id) if review else None
        if not review_everyone or not int(review_everyone.get("deny", 0)) & VIEW_CHANNEL:
            failures.append("private_review_visible")

        tag_name = format_channel_name("Setar tag", "🏷️")
        tag = next(
            (
                channel
                for channel in channels
                if int(channel.get("parent_id") or 0) == COMMUNITY_CATEGORY_ID
                and str(channel.get("name")) == tag_name
                and int(channel.get("type", -1)) == 0
            ),
            None,
        )
        tag_everyone = _overwrite(tag, guild_id) if tag else None
        if not tag or not tag_everyone or not int(tag_everyone.get("deny", 0)) & VIEW_CHANNEL:
            failures.append("tag_channel_not_private")

        for channel_id, label in (
            (PUBLIC_STATUS_ID, "public_status"),
            (RECRUITMENT_APPROVED_ID, "approved_result"),
        ):
            messages = await api.request("GET", f"/channels/{channel_id}/messages?limit=50")
            match = next(
                (message for message in messages if _message_contains_protocol(message, protocol)),
                None,
            )
            if not match:
                failures.append(f"{label}_protocol_missing")
            elif not str(match.get("content") or "").startswith("<@"):
                failures.append(f"{label}_candidate_mention_missing")

        print(
            "RECRUITMENT_PUBLIC_ACCESS_LIVE_PASS"
            if not failures
            else "RECRUITMENT_PUBLIC_ACCESS_LIVE_INVALID"
        )
        print(f"public_channels={len(public_ids)} tag_channel={bool(tag)} protocol={protocol}")
        if failures:
            print(f"failures={failures}")
        return 0 if not failures else 1
    finally:
        await api.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
