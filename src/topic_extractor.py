"""LLM-based topic extraction for channel-level grouping."""

import json
import logging
import asyncio
from typing import Any

import httpx

from .config import MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL, RATE_LIMIT_DELAY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a topic extractor for a Korean band community Discord archive.
Given all messages in a channel, group them into coherent topics.

Output format — ONLY valid JSON, no markdown or extra text:
{
  "topics": [
    {
      "name": "토픽 제목 (10자 이내)",
      "summary": "토픽 요약 (2문장 이내)",
      "decision": "결정사항이 있으면 작성. 없으면 null",
      "message_ids": ["msg_id_1", "msg_id_2"],
      "importance": "high" | "medium" | "low"
    }
  ],
  "key_decisions": ["전체 채널 핵심 결정 1", "핵심 결정 2"],
  "important_links": [{"url": "https://...", "title": "링크 제목"}]
}

Rules:
- 최대 10개 토픽으로 그룹핑
- 단순 리액션(👍, ㅋㅋ, ㅇㅇ 등) / 인사 메시지는 제외
- 결정사항은 "확정", "결정", "선정", "완료" 등 확실한 결론만
- importance 기준:
  - high: 공연, 선곡, 합주 일정, 비용 관련
  - medium: 논의, 제안, 질문
  - low: 잡담, 단순 공유
- 같은 주제의 메시지는 하나의 토픽으로 묶기
- message_ids는 실제 전달받은 ID만 사용
- important_links는 메시지에 포함된 URL만 추출 (중복 제거)"""


def _build_messages_content(messages: list[dict], channel_name: str) -> str:
    """Build user content from messages."""
    lines = [f"Channel: #{channel_name}", f"Total messages: {len(messages)}", ""]

    for msg in messages:
        content = msg.get("content", "").strip()
        if not content:
            continue
        lines.append(f"[ID:{msg['id']}] [{msg.get('author_name', '?')}] {content[:400]}")

    lines.append("")
    lines.append("Group these messages into topics. Respond with valid JSON only.")
    return "\n".join(lines)


def _parse_response(raw_text: str) -> dict[str, Any]:
    """Parse JSON from LLM response."""
    if not raw_text or not raw_text.strip():
        return {"topics": [], "key_decisions": [], "important_links": []}

    # Try direct parse
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object
    start = raw_text.find('{')
    if start == -1:
        log.warning("No JSON object found in response")
        return {"topics": [], "key_decisions": [], "important_links": []}

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(raw_text)):
        ch = raw_text[i]

        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw_text[start:i+1])
                except json.JSONDecodeError:
                    break

    log.warning(f"Failed to parse topic extraction response: {raw_text[:200]}")
    return {"topics": [], "key_decisions": [], "important_links": []}


async def extract_topics(
    messages: list[dict],
    channel_name: str,
    max_messages: int = 200,
) -> dict[str, Any]:
    """Extract topics from channel messages.

    Returns:
        {
            "topics": [...],
            "key_decisions": [...],
            "important_links": [...]
        }
    """
    if not messages:
        return {"topics": [], "key_decisions": [], "important_links": []}

    # Filter meaningful messages and limit
    meaningful = [
        m for m in messages
        if (m.get("content") or "").strip() and len((m.get("content") or "").strip()) > 2
    ]

    # Take most recent if over limit
    if len(meaningful) > max_messages:
        meaningful = meaningful[-max_messages:]
        log.info(f"  Truncated to {max_messages} most recent messages")

    if not meaningful:
        return {"topics": [], "key_decisions": [], "important_links": []}

    log.info(f"Extracting topics from #{channel_name} ({len(meaningful)} messages)...")

    try:
        async with httpx.AsyncClient() as client:
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
                        {"role": "user", "content": _build_messages_content(meaningful, channel_name)},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 4096,
                },
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()

            raw_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            result = _parse_response(raw_text)

            log.info(f"  → {len(result.get('topics', []))} topics, {len(result.get('key_decisions', []))} decisions")
            return result

    except Exception as e:
        log.error(f"Topic extraction failed for #{channel_name}: {e}")
        return {"topics": [], "key_decisions": [], "important_links": []}


async def extract_all_channel_topics(
    channels_data: dict[str, Any],
    existing_summaries: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Extract topics for all channels.

    Returns:
        {
            "channel_id": {
                "topics": [...],
                "key_decisions": [...],
                "important_links": [...]
            }
        }
    """
    if existing_summaries is None:
        existing_summaries = {}

    results = {}

    for cid, channel in channels_data.items():
        channel_name = channel.get("name", cid)
        messages = channel.get("messages", [])

        # Include thread messages too
        for thread in channel.get("threads", []):
            messages.extend(thread.get("messages", []))

        if not messages:
            log.info(f"Skipping #{channel_name}: no messages")
            continue

        # Check cache validity (by message count)
        existing = existing_summaries.get(cid, {})
        if existing.get("_msg_count") == len(messages) and existing.get("topics"):
            log.info(f"Using cached topics for #{channel_name}")
            results[cid] = existing
            continue

        result = await extract_topics(messages, channel_name)
        result["_msg_count"] = len(messages)
        results[cid] = result

        await asyncio.sleep(RATE_LIMIT_DELAY)

    return results
