"""LLM-based hierarchical tag extraction using MiniMax Token Plan API — batch mode."""

import os
import json
import logging
import asyncio
import re
from typing import Any

import httpx

from .config import MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL, RATE_LIMIT_DELAY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a message tagger for a Korean band community Discord archive.
Given a list of Discord messages, extract hierarchical topic tags for each message.
Rules:
- Output ONLY valid JSON: {"results": [{"id": "msg_id", "tags": ["Tag1", "Tag1/SubTag"]}, ...]}
- Maximum 4 tags per message
- Hierarchical tags use "/" (e.g., "선곡/수지", "공연/대관")
- Tag categories: 선곡, 공연, 합주, 팀, 회비, 공지, 추천, 투표, 일정, 장소, 역할, 기타, 노래
- Sub-tags under 선곡: 수지, 인호, 성현
- Sub-tags under 공연: 대관, 일정, 계약금
- Sub-tags under 합주: 일정, 장소, 영상
- Sub-tags under 팀: 역할분담
- Sub-tags under 회비: 비용, 관리
- Sub-tags under 공지: 투표, 일정
- Messages with only emojis, single-word reactions, or pure agreement (e.g., "맞아요", "ㅋㅋㅋ", "🫡") → tags: []
- URLs → always include a resource/link tag like "자원/유튜브" or "자원/링크"
- Questions → include "질문" tag
- Poll/voting → include "투표" tag
- Announcements → include "공지" tag
- Song recommendations → include "선곡" tag
- Keep the order of messages as provided"""


def build_batch_content(messages: list[dict[str, Any]], channel: str) -> str:
    """Build user content for batch tagging."""
    lines = []
    for i, msg in enumerate(messages):
        lines.append(f"[{i}] ID: {msg.get('id', 'unknown')}")
        lines.append(f"    Author: {msg.get('author_name', 'unknown')}")
        lines.append(f"    Content: {msg.get('content', '')[:300]}")
        lines.append("")

    return f"Channel: {channel}\n" + "\n".join(lines) + "\nExtract tags for each message above. Respond with valid JSON only."


def _find_json_object(text: str) -> str | None:
    """Find the first balanced JSON object in text. Returns the object string or None."""
    start = text.find('{')
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape:
            escape = False
            continue

        if ch == '\\':
            escape = True
            continue

        if ch == '"' and not escape:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


def parse_batch_response(raw_text: str) -> dict[str, list[str]]:
    """Parse batch API response, returns {msg_id: [tags]}."""
    if not raw_text or not raw_text.strip():
        return {}

    obj = _find_json_object(raw_text)
    if obj is None:
        log.warning("Batch parse failed: no JSON object found")
        return {}

    try:
        parsed = json.loads(obj)
        results = parsed.get("results", [])
        return {item["id"]: item.get("tags", []) for item in results if item.get("id")}
    except (json.JSONDecodeError, KeyError) as e:
        log.warning(f"Batch parse failed: {e}")
        return {}


async def extract_tags_batch(
    client: httpx.AsyncClient,
    messages: list[dict[str, Any]],
    channel: str,
) -> dict[str, list[str]]:
    """Extract tags for a batch of messages in a single API call."""
    if not messages:
        return {}

    try:
        response = await client.post(
            f"{MINIMAX_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {MINIMAX_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MINIMAX_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_batch_content(messages, channel)},
                ],
                "temperature": 0.1,
                "max_tokens": 2048,
                "reasoning": False,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()

        raw_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        result = parse_batch_response(raw_text)

        log.info(f"  Batch [{len(messages)} msgs] → {len(result)} tagged")
        return result

    except Exception as e:
        log.warning(f"Batch tag extraction failed: {e}")
        return {}


async def tag_messages(
    messages: list[dict[str, Any]],
    channel_name: str,
    batch_size: int = 50,
) -> dict[str, list[str]]:
    """Tag all messages in batches, returns {message_id: [tags]} dict."""
    if not messages:
        return {}

    tag_results: dict[str, list[str]] = {}
    total = len(messages)

    # Filter out empty content messages
    valid_messages = [m for m in messages if m.get("content", "").strip()]

    async with httpx.AsyncClient() as client:
        for start in range(0, len(valid_messages), batch_size):
            batch = valid_messages[start:start + batch_size]
            batch_num = start // batch_size + 1
            log.info(f"  Processing batch {batch_num} ({len(batch)} msgs)...")

            results = await extract_tags_batch(client, batch, channel_name)
            tag_results.update(results)

            # Rate limit delay between batches
            if start + batch_size < len(valid_messages):
                await asyncio.sleep(RATE_LIMIT_DELAY)

    return tag_results