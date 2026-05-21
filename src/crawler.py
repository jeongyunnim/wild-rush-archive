"""Discord message crawler using discord.py async API."""

import asyncio
import json
import os
import logging
from datetime import datetime
from typing import Any

import discord
from discord import Thread

from .config import BOT_TOKEN, GUILD_ID, CHANNEL_IDS, OUTPUT_DIR, MESSAGE_BATCH_SIZE, MAX_MESSAGES_PER_THREAD, RATE_LIMIT_DELAY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def serialize_message(msg: discord.Message) -> dict[str, Any]:
    """Convert discord.Message to serializable dict."""
    attachments = []
    for att in msg.attachments:
        attachments.append({
            "url": att.url,
            "filename": att.filename,
            "size": att.size,
        })

    embeds = []
    for emb in msg.embeds:
        embeds.append({"title": emb.title, "description": emb.description, "url": emb.url})

    reactions = []
    for reaction in msg.reactions:
        reactions.append({"emoji": str(reaction.emoji), "count": reaction.count})

    return {
        "id": str(msg.id),
        "author_id": str(msg.author.id),
        "author_name": msg.author.display_name,
        "author_avatar": str(msg.author.display_avatar) if hasattr(msg.author, 'display_avatar') else None,
        "author_roles": [],
        "content": msg.content,
        "timestamp": msg.created_at.isoformat(),
        "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
        "attachments": attachments,
        "embeds": embeds,
        "reactions": reactions,
        "thread_id": str(msg.thread.id) if msg.thread else None,
    }


async def fetch_messages_for_channel(channel: discord.TextChannel, thread: Thread | None = None) -> list[dict[str, Any]]:
    """Fetch all messages from a channel or thread."""
    target = thread if thread else channel
    messages = []
    oldest_id = None

    log.info(f"Fetching messages from: {target.name} (ID: {target.id})")

    try:
        while True:
            if len(messages) >= MAX_MESSAGES_PER_THREAD:
                log.warning(f"Cap reached for {target.name}, truncating at {MAX_MESSAGES_PER_THREAD}")
                break

            query = target.history(limit=MESSAGE_BATCH_SIZE, oldest_first=True)
            if oldest_id:
                query = target.history(limit=MESSAGE_BATCH_SIZE, oldest_first=True, after=discord.Object(oldest_id))

            batch = []
            async for msg in query:
                batch.append(serialize_message(msg))
                oldest_id = msg.id

            if not batch:
                break

            messages.extend(batch)
            await asyncio.sleep(RATE_LIMIT_DELAY)

            log.info(f"  Fetched {len(messages)} messages so far from {target.name}")

    except Exception as e:
        log.error(f"Error fetching {target.name}: {e}")

    log.info(f"Total fetched: {len(messages)} messages from {target.name}")
    return messages


async def crawl_guild(intents: discord.Intents) -> dict[str, Any]:
    """Main crawl function. Returns all guild data as dict."""
    client = discord.Client(intents=intents)

    await client.login(BOT_TOKEN)
    guild = await client.fetch_guild(int(int(GUILD_ID)))
    log.info(f"Guild: {guild.name} (ID: {guild.id})")

    all_channels = []
    channel_data = {}

    # Fetch all channels
    guild_channels = await guild.fetch_channels()
    for ch in guild_channels:
        if not isinstance(ch, (discord.TextChannel, discord.ForumChannel)):
            continue
        if CHANNEL_IDS and str(ch.id) not in CHANNEL_IDS:
            continue
        all_channels.append(ch)
        channel_data[str(ch.id)] = {
            "id": str(ch.id),
            "name": ch.name,
            "category": ch.category.name if ch.category else "없음",
            "category_id": str(ch.category.id) if ch.category else None,
            "topic": ch.topic or "",
            "type": str(ch.type),
            "threads": [],
            "messages": [],
        }

    log.info(f"Found {len(all_channels)} channels to crawl")

    # Process each channel
    for channel in all_channels:
        cid = str(channel.id)

        # Fetch public threads
        try:
            threads = [t for t in channel.threads if t.archived is False]
            log.info(f"Channel '{channel.name}': {len(threads)} active threads")
        except Exception as e:
            log.error(f"Error fetching threads for {channel.name}: {e}")
            threads = []

        # Fetch messages from the channel itself (if not a forum)
        if not isinstance(channel, discord.ForumChannel):
            msgs = await fetch_messages_for_channel(channel)
            channel_data[cid]["messages"] = msgs

        # Fetch each thread
        for thread in threads:
            thread_msgs = await fetch_messages_for_channel(channel, thread)
            thread_info = {
                "id": str(thread.id),
                "name": thread.name,
                "owner_id": str(thread.owner_id) if thread.owner_id else None,
                "message_count": thread.message_count if hasattr(thread, 'message_count') else len(thread_msgs),
                "created_at": thread.created_at.isoformat(),
                "archived": thread.archived,
                "messages": thread_msgs,
            }
            channel_data[cid]["threads"].append(thread_info)
            await asyncio.sleep(RATE_LIMIT_DELAY)

    await client.close()

    # Categorize channels
    categories = {}
    for cid, ch_data in channel_data.items():
        cat_name = ch_data["category"]
        if cat_name not in categories:
            categories[cat_name] = []
        categories[cat_name].append(ch_data)

    result = {
        "guild": {
            "id": str(guild.id),
            "name": guild.name,
            "description": guild.description or "",
            "icon_url": guild.icon.url if guild.icon else None,
        },
        "categories": categories,
        "channels": channel_data,
        "crawled_at": datetime.utcnow().isoformat() + "Z",
    }

    # Save to JSON
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "guild_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log.info(f"Saved to {out_path}")

    return result


def run_crawler():
    """Sync entry point."""
    intents = discord.Intents(
        messages=True,
        guild_messages=True,
        message_content=True,
        guilds=True,
    )
    return asyncio.run(crawl_guild(intents))


if __name__ == "__main__":
    run_crawler()