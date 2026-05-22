"""Discord message crawler with LLM-based incremental tagging."""

import asyncio
import json
import os
import logging
from datetime import datetime
from typing import Any

import discord
from discord import Thread

from .config import BOT_TOKEN, GUILD_ID, CHANNEL_IDS, OUTPUT_DIR, MESSAGE_BATCH_SIZE, MAX_MESSAGES_PER_THREAD, RATE_LIMIT_DELAY

from .tagger import tag_messages
from .summarizer import summarize_all_threads

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


def load_existing_data() -> dict[str, Any]:
    """Load existing guild_data.json if present."""
    out_path = os.path.join(OUTPUT_DIR, "guild_data.json")
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_existing_message_ids(channel_data: dict[str, Any]) -> set[str]:
    """Collect all existing message IDs from channel data."""
    ids = set()
    for ch in channel_data.values():
        for msg in ch.get("messages", []):
            ids.add(msg["id"])
        for thread in ch.get("threads", []):
            for msg in thread.get("messages", []):
                ids.add(msg["id"])
    return ids


async def fetch_messages_since(
    channel_or_thread,
    since_id: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch messages from a channel or thread, optionally since a given message ID."""
    messages = []
    oldest_id = None

    log.info(f"Fetching messages from: {channel_or_thread.name} (ID: {channel_or_thread.id})")

    try:
        while True:
            if len(messages) >= MAX_MESSAGES_PER_THREAD:
                log.warning(f"Cap reached for {channel_or_thread.name}, truncating at {MAX_MESSAGES_PER_THREAD}")
                break

            query = channel_or_thread.history(limit=MESSAGE_BATCH_SIZE, oldest_first=True)
            if oldest_id:
                query = channel_or_thread.history(limit=MESSAGE_BATCH_SIZE, oldest_first=True, after=discord.Object(oldest_id))
            elif since_id:
                query = channel_or_thread.history(limit=MESSAGE_BATCH_SIZE, oldest_first=True, after=discord.Object(since_id))

            batch = []
            async for msg in query:
                batch.append(serialize_message(msg))
                oldest_id = msg.id

            if not batch:
                break

            messages.extend(batch)
            await asyncio.sleep(RATE_LIMIT_DELAY)

            log.info(f"  Fetched {len(messages)} messages so far from {channel_or_thread.name}")

    except Exception as e:
        log.error(f"Error fetching {channel_or_thread.name}: {e}")

    log.info(f"Total fetched: {len(messages)} messages from {channel_or_thread.name}")
    return messages


async def crawl_guild(intents: discord.Intents) -> dict[str, Any]:
    """Incremental crawl: only fetch new messages since last crawl."""
    # Load existing data
    existing = load_existing_data()
    existing_channel_ids = {ch["id"]: ch for ch in existing.get("channels", {}).values()}
    existing_msg_ids = get_existing_message_ids(existing.get("channels", {}))
    existing_tags = existing.get("tags", {})
    existing_summaries = existing.get("thread_summaries", {})

    log.info(f"Loaded {len(existing_msg_ids)} existing messages from previous crawl")

    client = discord.Client(intents=intents)
    await client.login(BOT_TOKEN)
    guild = await client.fetch_guild(int(GUILD_ID))
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

        # Preserve existing channel data as base
        prev = existing_channel_ids.get(str(ch.id), {})
        channel_data[str(ch.id)] = {
            "id": str(ch.id),
            "name": ch.name,
            "category": ch.category.name if ch.category else "없음",
            "category_id": str(ch.category.id) if ch.category else None,
            "topic": ch.topic or "",
            "type": str(ch.type),
            "threads": list(prev.get("threads", [])),  # Preserve existing threads
            "messages": list(prev.get("messages", [])),  # Preserve existing messages
        }

    log.info(f"Found {len(all_channels)} channels to crawl")

    # Track which channels/threads got new messages
    new_tag_sources: dict[str, dict[str, list[str]]] = {}  # channel_id -> {channel/thread: {msg_id: tags}}

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

        # Fetch new messages from the channel itself (if not a forum)
        if not isinstance(channel, discord.ForumChannel):
            prev_msgs = channel_data[cid]["messages"]
            since_id = prev_msgs[-1]["id"] if prev_msgs else None

            new_msgs = await fetch_messages_since(channel, since_id=since_id)

            if new_msgs:
                log.info(f"  → {len(new_msgs)} NEW messages in '{channel.name}' (since_id: {since_id})")
                channel_data[cid]["messages"].extend(new_msgs)

                # Tag only new messages
                log.info(f"Extracting tags for {len(new_msgs)} NEW messages in '{channel.name}'...")
                new_tags = await tag_messages(new_msgs, channel.name)
                new_tag_sources[cid] = {"channel": new_tags}
            else:
                log.info(f"  → No new messages in '{channel.name}'")
                new_tag_sources[cid] = {"channel": {}}

        # Process threads
        for thread in threads:
            tid = str(thread.id)

            # Find existing thread or create new
            existing_thread = next((t for t in channel_data[cid]["threads"] if t["id"] == tid), None)
            prev_thread_msgs = existing_thread["messages"] if existing_thread else []
            since_id = prev_thread_msgs[-1]["id"] if prev_thread_msgs else None

            new_thread_msgs = await fetch_messages_since(thread, since_id=since_id)

            if new_thread_msgs:
                log.info(f"  → {len(new_thread_msgs)} NEW messages in thread '{thread.name}'")

                thread_info = {
                    "id": tid,
                    "name": thread.name,
                    "owner_id": str(thread.owner_id) if thread.owner_id else None,
                    "message_count": thread.message_count if hasattr(thread, 'message_count') else len(new_thread_msgs),
                    "created_at": thread.created_at.isoformat(),
                    "archived": thread.archived,
                    "messages": list(prev_thread_msgs) + new_thread_msgs,
                }

                # Tag only new messages
                log.info(f"Extracting tags for {len(new_thread_msgs)} NEW messages in thread '{thread.name}'...")
                new_tags = await tag_messages(new_thread_msgs, f"{channel.name}/{thread.name}")
                new_tag_sources[tid] = {"thread": new_tags}

                # Update or append thread
                if existing_thread:
                    for i, t in enumerate(channel_data[cid]["threads"]):
                        if t["id"] == tid:
                            channel_data[cid]["threads"][i] = thread_info
                            break
                else:
                    channel_data[cid]["threads"].append(thread_info)
            else:
                log.info(f"  → No new messages in thread '{thread.name}'")
                # Preserve existing tags entry if no new messages
                if tid not in new_tag_sources:
                    new_tag_sources[tid] = {"thread": {}}

            await asyncio.sleep(RATE_LIMIT_DELAY)

    await client.close()

    # Categorize channels
    categories = {}
    for cid, ch_data in channel_data.items():
        cat_name = ch_data["category"]
        if cat_name not in categories:
            categories[cat_name] = []
        categories[cat_name].append(ch_data)

    # Merge new tags with existing tags
    merged_tags = dict(existing_tags)
    for key, source_tags in new_tag_sources.items():
        if key not in merged_tags:
            merged_tags[key] = {}
        for source, tags in source_tags.items():
            if tags:
                merged_tags[key][source] = tags

    # Summarize all threads
    log.info(f"Summarizing {len([t for ch in channel_data.values() for t in ch.get('threads', [])])} threads...")
    thread_summaries = await summarize_all_threads(channel_data, existing_summaries)

    result = {
        "guild": {
            "id": str(guild.id),
            "name": guild.name,
            "description": guild.description or "",
            "icon_url": guild.icon.url if guild.icon else None,
        },
        "categories": categories,
        "channels": channel_data,
        "tags": merged_tags,
        "thread_summaries": thread_summaries,
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