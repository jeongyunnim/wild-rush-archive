"""Discord message crawler with LLM-based incremental tagging."""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any

import discord
from discord import Thread

from .config import BOT_TOKEN, GUILD_ID, CHANNEL_IDS, OUTPUT_DIR, MESSAGE_BATCH_SIZE, MAX_MESSAGES_PER_THREAD, RATE_LIMIT_DELAY

from .tagger import tag_messages
from .summarizer import summarize_all_threads

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def clean_message(msg: discord.Message) -> dict[str, Any]:
    """Convert a discord.Message to a clean dict."""
    return {
        "id": str(msg.id),
        "author_id": str(msg.author.id),
        "author_name": str(msg.author.display_name),
        "author_avatar": (
            str(msg.author.display_avatar.url)
            if msg.author.display_avatar and not msg.author.display_avatar.is_static()
            else None
        ),
        "content": msg.content,
        "timestamp": msg.created_at.isoformat(),
        "attachments": [
            {"url": a.url, "filename": a.filename, "is_image": a.is_image}
            for a in msg.attachments
        ],
        "reactions": [
            {"emoji": str(r.emoji), "count": r.count}
            for r in msg.reactions
            if r.count > 1  # skip single reactions
        ],
    }


async def fetch_messages_from_thread(
    thread: discord.Thread,
    since_id: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch messages from a thread, optionally after since_id."""
    messages = []
    last_id = None

    async for msg in thread.history(limit=MAX_MESSAGES_PER_THREAD, after=discord.Object(id=since_id) if since_id else None):
        if msg.author.bot and msg.author.id == thread.owner_id:
            continue  # skip auto-setup messages
        messages.append(clean_message(msg))
        last_id = msg.id

    return messages  # oldest first


async def fetch_channel_threads(client: discord.Client, channel_id: int) -> list[discord.Thread]:
    """Fetch all active + public archived threads for a channel."""
    threads = []

    try:
        ch = client.get_channel(channel_id)
        if not ch:
            return threads

        # Fetch archive info for forum channels (type=15) or channels with threads
        # For each channel, also check public archived threads
        # We'll use the REST API endpoint for archived public threads
        # via the bot's HTTP session
        bot = client._connection

        # Active threads (joined threads in channel)
        for thread in ch.threads:
            threads.append(thread)

        # Fetch public archived threads via API
        resp = await bot.http.get(f"channels/{channel_id}/threads/archived/public")
        if resp:
            for tdata in resp.get("threads", []):
                # Check if we already have this thread
                if any(t.id == int(tdata["id"]) for t in threads):
                    continue
                # Create a minimal Thread object from dict data
                thread = client.get_channel(int(tdata["id"]))
                if thread is None:
                    # Try to get from cache or create from data
                    from discord import Thread as DiscordThread
                    thread = DiscordThread(state=bot, data=tdata)
                threads.append(thread)
    except Exception as e:
        log.warning(f"Error fetching threads for channel {channel_id}: {e}")

    return threads


async def crawl_guild(intents: discord.Intents) -> dict[str, Any]:
    """Main crawl function."""
    result = {}

    class FakeMessage:
        """Minimal message object for REST-only threads."""
        def __init__(self, data, thread, http):
            self.id = int(data["id"])
            self.channel = thread
            self.author = type("U", (), {"id": int(data.get("author", {}).get("id", 0)), "display_name": data.get("author", {}).get("username", "unknown"), "display_avatar": type("A", (), {"url": None, "is_static": lambda: True})()})()
            self.content = data.get("content", "")
            self.created_at = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            self.attachments = []
            self.reactions = []

    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log.info(f"Logged in as {client.user}")
        guild = client.get_guild(int(GUILD_ID))
        if not guild:
            log.error(f"Guild {GUILD_ID} not found")
            await client.close()
            return

        log.info(f"Guild: {guild.name} (ID: {guild.id})")

        existing = _load_existing()
        existing_msg_ids = existing.get("msg_ids", {})
        existing_tags = existing.get("tags", {})
        existing_summaries = existing.get("thread_summaries", {})

        log.info(f"Loaded {len(existing_msg_ids)} existing messages from previous crawl")

        channel_data = {}
        new_tag_sources = {}
        all_new_messages = {}  # channel_id -> list of new messages
        processed_threads = set()

        for channel_id, ch_info in existing.get("channels", {}).items():
            channel_data[channel_id] = ch_info

        for category in guild.categories:
            for ch in category.channels:
                if ch.type != discord.ChannelType.text and ch.type != discord.ChannelType.news:
                    continue
                if CHANNEL_IDS and str(ch.id) not in CHANNEL_IDS:
                    continue

                log.info(f"Channel '{ch.name}': {len(ch.threads)} active threads")
                log.info(f"Fetching messages from: {ch.name} (ID: {ch.id})")

                fetched_messages = []
                async for msg in ch.history(limit=MESSAGE_BATCH_SIZE, after=discord.Object(id="0")):
                    fetched_messages.append(clean_message(msg))

                if fetched_messages:
                    log.info(f"Total fetched: {len(fetched_messages)} messages from {ch.name}")
                else:
                    log.info(f"No messages in {ch.name}")

                existing_msgs = existing_msg_ids.get(str(ch.id), [])
                new_msgs = [m for m in fetched_messages if m["id"] not in existing_msgs]

                if new_msgs:
                    log.info(f"  → {len(new_msgs)} NEW messages in '{ch.name}'")

                    # Tag new messages
                    log.info(f"Extracting tags for {len(new_msgs)} NEW messages in '{ch.name}'...")
                    new_tags = await tag_messages(new_msgs, ch.name)
                    new_tag_sources[str(ch.id)] = {"channel": new_tags}

                    # Store new messages
                    if str(ch.id) not in all_new_messages:
                        all_new_messages[str(ch.id)] = []

                    channel_data[str(ch.id)] = {
                        "id": str(ch.id),
                        "name": ch.name,
                        "category": ch.category.name if ch.category else "기타",
                        "messages": fetched_messages,
                        "threads": channel_data.get(str(ch.id), {}).get("threads", []),
                    }
                else:
                    log.info(f"  → No new messages in '{ch.name}'")
                    existing_entry = existing.get("channels", {}).get(str(ch.id), {})
                    channel_data[str(ch.id)] = existing_entry
                    new_tag_sources[str(ch.id)] = existing_tags.get(str(ch.id), {"channel": {}})

                # Fetch all threads (active + archived public)
                all_threads = await fetch_channel_threads(client, ch.id)
                log.info(f"  → Found {len(all_threads)} total threads")

                for thread in all_threads:
                    if thread.id in processed_threads:
                        continue
                    processed_threads.add(thread.id)

                    tid = str(thread.id)
                    existing_thread = next(
                        (t for t in channel_data[str(ch.id)]["threads"] if t["id"] == tid),
                        None,
                    )
                    prev_thread_msgs = existing_thread["messages"] if existing_thread else []
                    since_id = int(prev_thread_msgs[-1]["id"]) if prev_thread_msgs else None

                    thread_messages = await fetch_messages_from_thread(thread, since_id=since_id)

                    if thread_messages:
                        log.info(f"  → {len(thread_messages)} TOTAL messages in thread '{thread.name}'")
                    else:
                        log.info(f"  → No messages in thread '{thread.name}'")

                    # Update thread data
                    thread_info = {
                        "id": tid,
                        "name": thread.name,
                        "owner_id": str(thread.owner_id) if thread.owner_id else None,
                        "message_count": thread.message_count if hasattr(thread, 'message_count') and thread.message_count else len(thread_messages),
                        "created_at": thread.created_at.isoformat(),
                        "archived": getattr(thread, 'archived', False),
                        "messages": thread_messages,
                    }

                    if existing_thread:
                        for i, t in enumerate(channel_data[str(ch.id)]["threads"]):
                            if t["id"] == tid:
                                channel_data[str(ch.id)]["threads"][i] = thread_info
                                break
                    else:
                        channel_data[str(ch.id)]["threads"].append(thread_info)

                    new_tag_sources[tid] = {"thread": {}}

                    await asyncio.sleep(RATE_LIMIT_DELAY)

        await client.close()

        # Categorize channels
        categories = {}
        for cid, ch_data in channel_data.items():
            cat_name = ch_data.get("category", "기타")
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
                    if source not in merged_tags[key]:
                        merged_tags[key][source] = {}
                    merged_tags[key][source].update(tags)

        # Tag ALL messages in threads (for initial tagging of old messages)
        log.info("Tagging all thread messages...")
        for cid, ch_data in channel_data.items():
            for thread in ch_data.get("threads", []):
                tid = thread["id"]
                msgs = thread.get("messages", [])
                if msgs:
                    existing_thread_tags = merged_tags.get(tid, {}).get("thread", {})
                    untagged = [m for m in msgs if str(m["id"]) not in existing_thread_tags]
                    if untagged:
                        log.info(f"Tagging {len(untagged)} untagged messages in thread '{thread['name']}'...")
                        thread_name = f"{ch_data['name']}/{thread['name']}"
                        new_tags = await tag_messages(untagged, thread_name)
                        if tid not in merged_tags:
                            merged_tags[tid] = {"channel": {}, "thread": {}}
                        if "thread" not in merged_tags[tid]:
                            merged_tags[tid]["thread"] = {}
                        merged_tags[tid]["thread"].update(new_tags)
                        await asyncio.sleep(RATE_LIMIT_DELAY)

        # Summarize all threads
        log.info(f"Summarizing {len([t for ch in channel_data.values() for t in ch.get('threads', [])])} threads...")
        thread_summaries = await summarize_all_threads(channel_data, existing_summaries)

        # Build msg_ids index
        msg_ids = {}
        for cid, ch_data in channel_data.items():
            for msg in ch_data.get("messages", []):
                msg_ids.setdefault(cid, []).append(msg["id"])
            for thread in ch_data.get("threads", []):
                for msg in thread.get("messages", []):
                    msg_ids.setdefault(cid, []).append(msg["id"])

        result = {
            "guild": {
                "id": str(guild.id),
                "name": guild.name,
                "description": guild.description or "",
                "icon_url": guild.icon.url if guild.icon else None,
            },
            "categories": categories,
            "channels": channel_data,
            "msg_ids": msg_ids,
            "tags": merged_tags,
            "thread_summaries": thread_summaries,
            "crawled_at": datetime.utcnow().isoformat() + "Z",
        }

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out_path = os.path.join(OUTPUT_DIR, "guild_data.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        log.info(f"Saved to {out_path}")

        return result


def _load_existing() -> dict[str, Any]:
    """Load existing guild_data.json if present."""
    path = os.path.join(OUTPUT_DIR, "guild_data.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


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