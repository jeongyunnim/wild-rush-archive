"""LLM-based channel summarizer for overview generation."""

import json
import logging
import asyncio
from datetime import datetime
from typing import Any

import httpx

from .config import MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL, RATE_LIMIT_DELAY
from .topic_extractor import extract_all_channel_topics

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _get_date_range(messages: list[dict]) -> tuple[str, str] | None:
    """Get min/max dates from messages."""
    if not messages:
        return None

    dates = []
    for m in messages:
        ts = m.get("timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                dates.append(dt)
            except (ValueError, TypeError):
                pass

    if not dates:
        return None

    min_dt = min(dates)
    max_dt = max(dates)
    return (min_dt.strftime("%Y-%m-%d"), max_dt.strftime("%Y-%m-%d"))


def _enrich_topics_with_dates(
    topics: list[dict],
    messages: list[dict],
) -> list[dict]:
    """Add date_range to each topic based on its message_ids."""
    msg_map = {m["id"]: m for m in messages if m.get("id")}

    for topic in topics:
        msg_ids = topic.get("message_ids", [])
        topic_msgs = [msg_map[mid] for mid in msg_ids if mid in msg_map]
        date_range = _get_date_range(topic_msgs)
        if date_range:
            topic["date_range"] = f"{date_range[0]} ~ {date_range[1]}"
        else:
            topic["date_range"] = None

    return topics


def _extract_links_from_messages(messages: list[dict]) -> list[dict]:
    """Extract URLs from message content and embeds."""
    import re
    url_pattern = re.compile(r'https?://[^\s<>\[\]()]+')

    links = {}
    for m in messages:
        content = m.get("content", "")
        for url in url_pattern.findall(content):
            # Clean trailing punctuation
            url = url.rstrip('.,;:!?)')
            if url not in links:
                links[url] = {"url": url, "title": url[:50] + "..." if len(url) > 50 else url}

        # Check embeds
        for embed in m.get("embeds", []):
            url = embed.get("url")
            title = embed.get("title") or embed.get("description")
            if url and url not in links:
                links[url] = {"url": url, "title": title or url[:50]}

    return list(links.values())


async def summarize_channels(
    channels_data: dict[str, Any],
    existing_summaries: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Generate channel summaries with topics.

    Returns:
        {
            "channel_id": {
                "name": "공지방",
                "description": "채널 설명 요약",
                "topics": [...],
                "key_decisions": [...],
                "important_links": [...],
                "message_count": 123,
                "date_range": "2026-04-04 ~ 2026-05-22",
                "_msg_count": 123
            }
        }
    """
    if existing_summaries is None:
        existing_summaries = {}

    # First, extract topics for all channels
    log.info("=== Phase 1: Extracting topics ===")
    topic_results = await extract_all_channel_topics(channels_data, existing_summaries)

    # Then enrich with metadata
    log.info("=== Phase 2: Building channel summaries ===")
    results = {}

    for cid, channel in channels_data.items():
        channel_name = channel.get("name", cid)
        messages = channel.get("messages", [])

        # Include thread messages
        for thread in channel.get("threads", []):
            messages.extend(thread.get("messages", []))

        topic_data = topic_results.get(cid, {})
        topics = topic_data.get("topics", [])

        # Enrich topics with date ranges
        topics = _enrich_topics_with_dates(topics, messages)

        # Sort topics by importance
        importance_order = {"high": 0, "medium": 1, "low": 2}
        topics.sort(key=lambda t: importance_order.get(t.get("importance", "low"), 2))

        # Extract links if not from LLM
        important_links = topic_data.get("important_links", [])
        if not important_links:
            important_links = _extract_links_from_messages(messages)[:10]

        # Get overall date range
        date_range = _get_date_range(messages)

        results[cid] = {
            "name": channel_name,
            "description": channel.get("topic", ""),
            "topics": topics,
            "key_decisions": topic_data.get("key_decisions", []),
            "important_links": important_links,
            "message_count": len(messages),
            "thread_count": len(channel.get("threads", [])),
            "date_range": f"{date_range[0]} ~ {date_range[1]}" if date_range else None,
            "_msg_count": len(messages),
        }

        log.info(f"  #{channel_name}: {len(topics)} topics, {len(results[cid]['key_decisions'])} decisions")

    return results


def aggregate_decisions(channel_summaries: dict[str, dict]) -> list[dict]:
    """Aggregate key decisions from all channels for homepage display.

    Returns list of decisions with source channel info, sorted by recency.
    """
    all_decisions = []

    for cid, summary in channel_summaries.items():
        channel_name = summary.get("name", cid)
        for decision in summary.get("key_decisions", []):
            all_decisions.append({
                "text": decision,
                "channel_id": cid,
                "channel_name": channel_name,
            })

        # Also extract decisions from high-importance topics
        for topic in summary.get("topics", []):
            if topic.get("importance") == "high" and topic.get("decision"):
                # Avoid duplicates
                if topic["decision"] not in [d["text"] for d in all_decisions]:
                    all_decisions.append({
                        "text": topic["decision"],
                        "channel_id": cid,
                        "channel_name": channel_name,
                        "topic": topic.get("name"),
                    })

    return all_decisions[:15]  # Limit for homepage


async def generate_all_summaries(
    guild_data: dict[str, Any],
) -> dict[str, Any]:
    """Main entry point: generate all channel summaries and aggregate.

    Modifies guild_data in place, adding:
        - channel_summaries: per-channel topic summaries
        - homepage_decisions: aggregated decisions for homepage
    """
    channels_data = guild_data.get("channels", {})
    existing = guild_data.get("channel_summaries", {})

    channel_summaries = await summarize_channels(channels_data, existing)
    homepage_decisions = aggregate_decisions(channel_summaries)

    guild_data["channel_summaries"] = channel_summaries
    guild_data["homepage_decisions"] = homepage_decisions

    log.info(f"Generated summaries for {len(channel_summaries)} channels")
    log.info(f"Aggregated {len(homepage_decisions)} decisions for homepage")

    return guild_data
