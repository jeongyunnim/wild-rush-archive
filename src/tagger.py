"""LLM-based hierarchical tag extraction using MiniMax Token Plan API."""

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
Given a Discord message, extract hierarchical topic tags that represent the message's subject.
Rules:
- Output ONLY valid JSON: {"tags": ["Tag1", "Tag1/SubTag"]}
- Tags should be in Korean or English mixed
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
- Song recommendations → include "선곡" tag"""


def build_tag_messages(content: str, author: str, channel: str) -> list[dict[str, str]]:
    """Build message list for chat completion."""
    user_content = f"""Channel: {channel}
Author: {author}
Message: {content}
Extract tags:"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


async def extract_tags_for_message(
    client: httpx.AsyncClient,
    content: str,
    author: str,
    channel: str,
) -> list[str]:
    """Extract tags for a single message via MiniMax API."""
    if not content or not content.strip():
        return []

    try:
        response = await client.post(
            f"{MINIMAX_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {MINIMAX_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MINIMAX_MODEL,
                "messages": build_tag_messages(content, author, channel),
                "temperature": 0.1,
                "max_tokens": 256,
                "reasoning": False,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        raw_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Find JSON object in the response
        json_match = re.search(r'\{[^{}]*\}', raw_text)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                return parsed.get("tags", [])
            except json.JSONDecodeError:
                pass

        # Try whole text
        try:
            parsed = json.loads(raw_text.strip())
            return parsed.get("tags", [])
        except json.JSONDecodeError:
            pass

        return []

    except Exception as e:
        log.warning(f"Tag extraction failed for message: {e}")
        return []


async def tag_messages(messages: list[dict[str, Any]], channel_name: str) -> dict[str, list[str]]:
    """Tag all messages sequentially, returns {message_id: [tags]} dict."""
    if not messages:
        return {}

    tag_results: dict[str, list[str]] = {}

    async with httpx.AsyncClient() as client:
        for i, msg in enumerate(messages):
            content = msg.get("content", "")
            author = msg.get("author_name", "unknown")
            msg_id = msg.get("id", f"unknown_{i}")

            tags = await extract_tags_for_message(client, content, author, channel_name)
            tag_results[msg_id] = tags

            log.info(f"  [{i+1}/{len(messages)}] Tags for {msg_id}: {tags}")

            # Rate limit delay between calls
            if i < len(messages) - 1:
                await asyncio.sleep(RATE_LIMIT_DELAY)

    return tag_results