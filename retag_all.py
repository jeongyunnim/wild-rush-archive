"""Re-tag all existing messages in guild_data.json that don't have tags yet."""
import asyncio
import json
import os
import logging

from src.tagger import tag_messages
from src.config import OUTPUT_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


async def retag_all():
    data_path = os.path.join(OUTPUT_DIR, "guild_data.json")
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    tags = data.get("tags", {})
    all_messages_by_channel = {}  # channel_id -> list of (msg_id, content, source_type)
    all_messages = []  # flat list for batch processing

    # Collect all messages from channels
    for cid, ch in data.get("channels", {}).items():
        ch_tags = tags.get(cid, {})
        ch_msgs = ch.get("messages", [])
        for msg in ch_msgs:
            msg_id = msg["id"]
            existing = ch_tags.get("channel", {}).get(msg_id, [])
            if not existing and msg.get("content", "").strip():
                all_messages.append({
                    "id": msg_id,
                    "content": msg["content"],
                    "author_name": msg.get("author_name", "unknown"),
                    "_ch_id": cid,
                    "_source": "channel",
                })

    # Collect all messages from threads
    for cid, ch in data.get("channels", {}).items():
        ch_tags = tags.get(cid, {})
        for thread in ch.get("threads", []):
            tid = thread["id"]
            th_tags = tags.get(tid, {})
            for msg in thread.get("messages", []):
                msg_id = msg["id"]
                existing = th_tags.get("thread", {}).get(msg_id, [])
                if not existing and msg.get("content", "").strip():
                    all_messages.append({
                        "id": msg_id,
                        "content": msg["content"],
                        "author_name": msg.get("author_name", "unknown"),
                        "_ch_id": cid,
                        "_thread_id": tid,
                        "_source": "thread",
                    })

    log.info(f"Found {len(all_messages)} untagged messages total")

    if not all_messages:
        log.info("Nothing to tag — all messages already have tags")
        return

    # Batch tag all messages
    all_results = await tag_messages(all_messages, "전체", batch_size=50)

    log.info(f"Got tags for {len(all_results)} messages")

    # Merge results into tags
    for msg in all_messages:
        msg_id = msg["id"]
        if msg_id in all_results:
            tag_list = all_results[msg_id]
            if msg["_source"] == "channel":
                cid = msg["_ch_id"]
                if cid not in tags:
                    tags[cid] = {"channel": {}, "thread": {}}
                if "channel" not in tags[cid]:
                    tags[cid]["channel"] = {}
                tags[cid]["channel"][msg_id] = tag_list
            else:
                tid = msg["_thread_id"]
                if tid not in tags:
                    tags[tid] = {"channel": {}, "thread": {}}
                if "thread" not in tags[tid]:
                    tags[tid]["thread"] = {}
                tags[tid]["thread"][msg_id] = tag_list

    data["tags"] = tags

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log.info(f"Saved updated {data_path}")

    # Print summary
    tagged_count = sum(1 for v in all_results.values() if v)
    log.info(f"SUMMARY: {tagged_count} messages tagged out of {len(all_messages)} total")


if __name__ == "__main__":
    asyncio.run(retag_all())