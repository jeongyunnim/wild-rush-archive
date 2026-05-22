"""Jinja2 HTML renderer for Discord archive."""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import TEMPLATE_DIR, OUTPUT_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def get_renderer():
    """Create Jinja2 environment."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["datetime"] = lambda s: datetime.fromisoformat(s).strftime("%Y-%m-%d %H:%M") if s else ""
    env.filters["shortdate"] = lambda s: datetime.fromisoformat(s).strftime("%m/%d") if s else ""
    return env


def render_site():
    """Main render function. Reads guild_data.json and renders all HTML pages."""
    env = get_renderer()

    # Load data
    data_path = Path(OUTPUT_DIR) / "guild_data.json"
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    guild = data["guild"]
    categories = data["categories"]
    channels = data["channels"]
    tags = data.get("tags", {})

    # Base output dir = project_root/docs/ (for GitHub Pages serving from root)
    base_out = Path(OUTPUT_DIR).parent / "docs"
    index_out = base_out / "index.html"
    channels_out = base_out / "channels"
    threads_out = base_out / "threads"

    channels_out.mkdir(parents=True, exist_ok=True)
    threads_out.mkdir(parents=True, exist_ok=True)
    tags_out = base_out / "tags"
    tags_out.mkdir(parents=True, exist_ok=True)

    base_path = "/wild-rush-archive"

    # --- Render index.html ---
    index_template = env.get_template("index.html")
    index_html = index_template.render(
        guild=guild,
        categories=categories,
        channels=channels,
        base_path=base_path,
        rendered_at=datetime.utcnow().isoformat(),
    )
    with open(index_out, "w", encoding="utf-8") as f:
        f.write(index_html)
    log.info(f"Rendered: {index_out}")

    # --- Render channel pages ---
    for cid, channel in channels.items():
        ch_template = env.get_template("channel.html")
        ch_html = ch_template.render(
            guild=guild,
            channel=channel,
            categories=categories,
            tags=tags,
            base_path=base_path,
            rendered_at=datetime.utcnow().isoformat(),
        )
        ch_path = channels_out / cid / "index.html"
        ch_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ch_path, "w", encoding="utf-8") as f:
            f.write(ch_html)
        log.info(f"Rendered: {ch_path}")

        # --- Render thread pages ---
        for thread in channel.get("threads", []):
            th_template = env.get_template("thread.html")
            th_html = th_template.render(
                guild=guild,
                channel=channel,
                thread=thread,
                categories=categories,
                tags=tags,
                base_path=base_path,
                rendered_at=datetime.utcnow().isoformat(),
            )
            th_path = threads_out / thread["id"] / "index.html"
            th_path.parent.mkdir(parents=True, exist_ok=True)
            with open(th_path, "w", encoding="utf-8") as f:
                f.write(th_html)
            log.info(f"Rendered: {th_path}")

    # --- Render tag index & detail pages ---
    all_tags: dict[str, list[tuple]] = {}
    for cid, ch_tags in tags.items():
        for src_type, msg_tags in ch_tags.items():
            for msg_id, tag_list in msg_tags.items():
                for tag in tag_list:
                    if tag not in all_tags:
                        all_tags[tag] = []
                    all_tags[tag].append((cid if src_type == "channel" else None, msg_id, src_type))

    # Tag index page
    env.filters["tag_count"] = lambda t: len(all_tags.get(t, []))
    tag_index_template = env.get_template("tag_index.html")
    tag_index_html = tag_index_template.render(
        guild=guild,
        categories=categories,
        all_tags=sorted(all_tags.keys()),
        base_path=base_path,
        rendered_at=datetime.utcnow().isoformat(),
    )
    with open(tags_out / "index.html", "w", encoding="utf-8") as f:
        f.write(tag_index_html)
    log.info(f"Rendered tag index: {tags_out / 'index.html'}")

    # Per-tag detail pages
    tag_detail_template = env.get_template("tag_detail.html")
    for tag, occurrences in all_tags.items():
        tag_html = tag_detail_template.render(
            guild=guild,
            tag=tag,
            occurrences=occurrences,
            channels=channels,
            base_path=base_path,
            rendered_at=datetime.utcnow().isoformat(),
        )
        tag_path = tags_out / tag / "index.html"
        tag_path.parent.mkdir(parents=True, exist_ok=True)
        with open(tag_path, "w", encoding="utf-8") as f:
            f.write(tag_html)
        log.info(f"Rendered tag: {tag_path}")

    log.info("All pages rendered successfully")


if __name__ == "__main__":
    render_site()