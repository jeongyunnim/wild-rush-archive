"""LLM-based thread summarizer using MiniMax Token Plan API."""

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

SYSTEM_PROMPT = """You are a thread summarizer for a Korean band community Discord archive.
Given all messages in a Discord thread, produce a structured summary in Korean.

Output format — ONLY valid JSON, no extra text:
{
  "decision": "결정 사항이나 투표 결과를 한 줄 요약. 없으면 null",
  "discussion": [
    {
      "topic": "논의 주제",
      "points": ["포인트1", "포인트2"],
      "speakers": ["发言자1", "发言자2"]
    }
  ],
  "links": [
    {"url": "https://...", "description": "링크 설명"}
  ]
}

Rules:
- discussion은 최대 5개 topic으로 요약
- points는 각 topic당 2~4개
- links는 URL이 있는 메시지만 추출, 중복 제거
- discussion이 없으면 빈 배열
- decision이 없으면 null
- purely emoji/react messages are ignored for speaker attribution
- Keep it concise — this is an archive summary, not a transcript"""


async def summarize_thread(
    client: httpx.AsyncClient,
    messages: list[dict[str, Any]],
    thread_name: str,
) -> dict[str, Any]:
    """Summarize a thread's messages. Returns {decision, discussion, links}."""
    if not messages:
        return {"decision": None, "discussion": [], "links": []}

    # Filter meaningful messages
    meaningful = [
        m for m in messages
        if (m.get("content") or "").strip() and len((m.get("content") or "").strip()) > 2
    ]
    if not meaningful:
        return {"decision": None, "discussion": [], "links": []}

    content_parts = []
    for m in meaningful:
        content_parts.append(f"[{m.get('author_name', 'unknown')}]: {m.get('content', '')[:500]}")

    user_content = (
        f"Thread name: {thread_name}\n"
        + f"Total messages: {len(messages)}\n\n"
        + "\n---\n".join(content_parts)
        + "\n\nProvide a structured summary in Korean as specified in the system prompt."
    )

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
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.3,
                "max_tokens": 2048,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        raw_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Parse JSON from response
        return _parse_summary(raw_text)

    except Exception as e:
        log.warning(f"Thread summarization failed for '{thread_name}': {e}")
        return {"decision": None, "discussion": [], "links": []}


def _parse_summary(raw_text: str) -> dict[str, Any]:
    """Parse JSON summary from LLM response."""
    if not raw_text or not raw_text.strip():
        return {"decision": None, "discussion": [], "links": []}

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        # Try to extract JSON object
        json_match = re.search(r'\{[\s\S]*\}', raw_text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

    log.warning(f"Could not parse summary JSON: {raw_text[:100]}")
    return {"decision": None, "discussion": [], "links": []}


async def summarize_all_threads(
    channels_data: dict[str, Any],
    existing_summaries: dict[str, dict],
    batch_size: int = 3,
) -> dict[str, dict]:
    """Summarize all threads across channels. Returns {thread_id: summary}."""
    results = {}

    async with httpx.AsyncClient() as client:
        for cid, ch in channels_data.items():
            for thread in ch.get("threads", []):
                tid = thread["id"]
                msgs = thread.get("messages", [])

                # Check if already summarized and still current
                existing = existing_summaries.get(tid, {})
                prev_count = existing.get("_msg_count", 0)
                if prev_count == len(msgs) and existing.get("decision") is not None:
                    results[tid] = existing
                    log.info(f"Thread '{thread['name']}': using cached summary ({len(msgs)} msgs)")
                    continue

                if not msgs:
                    continue

                log.info(f"Summarizing thread '{thread['name']}' ({len(msgs)} msgs)...")
                summary = await summarize_thread(client, msgs, thread["name"])
                summary["_msg_count"] = len(msgs)
                results[tid] = summary
                log.info(f"  → decision: {summary.get('decision')}, {len(summary.get('discussion', []))} topics")

                await asyncio.sleep(RATE_LIMIT_DELAY)

    return results