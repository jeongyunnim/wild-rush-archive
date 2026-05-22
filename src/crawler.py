import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any

import discord
from discord import Thread
from discord.http import Route

from .config import BOT_TOKEN, GUILD_ID, CHANNEL_IDS, OUTPUT_DIR, MESSAGE_BATCH_SIZE, MAX_MESSAGES_PER_THREAD, RATE_LIMIT_DELAY

from .tagger import tag_messages
from .summarizer import summarize_all_threads
from .channel_summarizer import generate_all_summaries

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def clean_message(msg: discord.Message) -> dict[str, Any]:
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
            if r.count > 1
        ],
    }


async def fetch_messages_from_thread(
    thread: discord.Thread,
    since_id: int | None = None,
) -> list[dict[str, Any]]:
    messages = []
    async for msg in thread.history(
        limit=MAX_MESSAGES_PER_THREAD,
        after=discord.Object(id=since_id) if since_id else None,
    ):
        if msg.author.bot and msg.author.id == thread.owner_id:
            continue
        messages.append(clean_message(msg))
    return messages


async def fetch_channel_threads(client: discord.Client, channel_id: int) -> list[discord.Thread]:
    threads: list[discord.Thread] = []
    try:
        ch = client.get_channel(channel_id)
        if not ch:
            log.warning(f"Channel {channel_id} not found via get_channel")
            return threads
        bot = client._connection
        for thread in ch.threads:
            threads.append(thread)
        route = Route("GET", "/channels/{channel_id}/threads/archived/public", channel_id=channel_id)
        resp = await bot.http.request(route)
        if resp:
            for tdata in resp.get("threads", []):
                if any(t.id == int(tdata["id"]) for t in threads):
                    continue
                thread = Thread(state=bot, data=tdata)
                threads.append(thread)
    except Exception as e:
        log.warning(f"Error fetching threads for channel {channel_id}: {e}")
    return threads


def _load_existing() -> dict[str, Any]:
    path = os.path.join(OUTPUT_DIR, "guild_data.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


async def crawl_guild(intents: discord.Intents) -> dict[str, Any]:
    result = {}
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log.info(f"on_ready fired! Bot user: {client.user}")
        try:
            if not GUILD_ID:
                log.error("DISCORD_GUILD_ID is not set")
                await client.close()
                return

            guild = client.get_guild(int(GUILD_ID))
            if not guild:
                log.error(f"Guild {GUILD_ID} not found — bot may not be in the guild. Bot guilds: {[g.id for g in client.guilds]}")
                await client.close()
                return

            log.info(f"Guild: {guild.name} (ID: {guild.id})")
            log.info(f"Guild categories: {len(guild.categories)}")
            for cat in guild.categories:
                text_count = sum(1 for ch in cat.channels if ch.type in (discord.ChannelType.text, discord.ChannelType.news))
                log.info(f"  Category '{cat.name}': {text_count} text channels, {len(cat.channels)} total channels")
                for ch in cat.channels:
                    log.info(f"    Channel '{ch.name}' type={ch.type}")

            existing = _load_existing()
            existing_msg_ids = existing.get("msg_ids", {})
            existing_tags = existing.get("tags", {})
            existing_summaries = existing.get("thread_summaries", {})
            log.info(f"Loaded {len(existing_msg_ids)} existing messages from previous crawl")

            channel_data: dict[str, Any] = {}
            new_tag_sources: dict[str, dict] = {}
            processed_threads: set[int] = set()

            for channel_id, ch_info in existing.get("channels", {}).items():
                channel_data[channel_id] = ch_info

            for category in guild.categories:
                for ch in category.channels:
                    if ch.type not in (discord.ChannelType.text, discord.ChannelType.news):
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
                        log.info(f"  -> {len(new_msgs)} NEW messages in '{ch.name}'")
                        new_tags = await tag_messages(new_msgs, ch.name)
                        new_tag_sources[str(ch.id)] = {"channel": new_tags}
                    else:
                        log.info(f"  -> No new messages in '{ch.name}'")
                        new_tag_sources[str(ch.id)] = existing_tags.get(str(ch.id), {"channel": {}})

                    if str(ch.id) not in channel_data:
                        channel_data[str(ch.id)] = {
                            "id": str(ch.id),
                            "name": ch.name,
                            "category": ch.category.name if ch.category else "etc",
                            "messages": [],
                            "threads": [],
                        }
                    channel_data[str(ch.id)]["messages"] = fetched_messages

                    all_threads = await fetch_channel_threads(client, ch.id)
                    log.info(f"  -> Found {len(all_threads)} total threads (active={len(ch.threads)}, archived={max(0, len(all_threads)-len(ch.threads))})")

                    for thread in all_threads:
                        if thread.id in processed_threads:
                            continue
                        processed_threads.add(thread.id)
                        tid = str(thread.id)

                        existing_thread = next(
                            (t for t in channel_data[str(ch.id)]["threads"] if t["id"] == tid),
                            None,
                        )
                        prev_msgs = existing_thread["messages"] if existing_thread else []
                        since_id = int(prev_msgs[-1]["id"]) if prev_msgs else None

                        thread_messages = await fetch_messages_from_thread(thread, since_id=since_id)
                        log.info(f"  -> Thread '{thread.name}': {len(thread_messages)} messages")

                        thread_info = {
                            "id": tid,
                            "name": thread.name,
                            "owner_id": str(thread.owner_id) if thread.owner_id else None,
                            "message_count": getattr(thread, "message_count", len(thread_messages)) or len(thread_messages),
                            "created_at": thread.created_at.isoformat(),
                            "archived": getattr(thread, "archived", False),
                            "messages": thread_messages,
                        }

                        if existing_thread:
                            for i, t in enumerate(channel_data[str(ch.id)]["threads"]):
                                if t["id"] == tid:
                                    channel_data[str(ch.id)]["threads"][i] = thread_info
                                    break
                        else:
                            channel_data[str(ch.id)]["threads"].append(thread_info)

                        new_tag_sources.setdefault(tid, {"thread": {}})
                        await asyncio.sleep(RATE_LIMIT_DELAY)

            await client.close()

            categories: dict[str, list] = {}
            for cid, ch_data in channel_data.items():
                cat_name = ch_data.get("category", "etc")
                if cat_name not in categories:
                    categories[cat_name] = []
                categories[cat_name].append(ch_data)

            merged_tags = dict(existing_tags)
            for key, source_tags in new_tag_sources.items():
                if key not in merged_tags:
                    merged_tags[key] = {}
                for source, tags in source_tags.items():
                    if tags:
                        merged_tags[key].setdefault(source, {}).update(tags)

            log.info("Tagging all thread messages...")
            for cid, ch_data in channel_data.items():
                for thread in ch_data.get("threads", []):
                    tid = thread["id"]
                    msgs = thread.get("messages", [])
                    if not msgs:
                        continue
                    existing_thread_tags = merged_tags.get(tid, {}).get("thread", {})
                    untagged = [m for m in msgs if str(m["id"]) not in existing_thread_tags]
                    if untagged:
                        log.info(f"Tagging {len(untagged)} untagged messages in thread '{thread['name']}'...")
                        thread_name = f"{ch_data['name']}/{thread['name']}"
                        new_tags = await tag_messages(untagged, thread_name)
                        merged_tags.setdefault(tid, {"channel": {}, "thread": {}})
                        merged_tags[tid].setdefault("thread", {}).update(new_tags)
                        await asyncio.sleep(RATE_LIMIT_DELAY)

            thread_count = len([t for ch in channel_data.values() for t in ch.get("threads", [])])
            log.info(f"Summarizing {thread_count} threads...")
            thread_summaries = await summarize_all_threads(channel_data, existing_summaries)

            msg_ids: dict[str, list[str]] = {}
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

            # Generate channel-level topic summaries
            log.info("Generating channel summaries...")
            existing_channel_summaries = existing.get("channel_summaries", {})
            result["channel_summaries"] = existing_channel_summaries
            await generate_all_summaries(result)

            os.makedirs(OUTPUT_DIR, exist_ok=True)
            out_path = os.path.join(OUTPUT_DIR, "guild_data.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            log.info(f"Saved to {out_path}")

        except Exception as e:
            log.exception(f"FATAL in on_ready: {e}")
            await client.close()
            raise

    await client.start(BOT_TOKEN)
    return result


def run_crawler():
    intents = discord.Intents(
        messages=True,
        guild_messages=True,
        message_content=True,
        guilds=True,
    )
    return asyncio.run(crawl_guild(intents))


if __name__ == "__main__":
    run_crawler()