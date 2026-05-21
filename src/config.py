"""Configuration for Discord archive crawler."""

import os

# Discord Bot Token (set via GitHub Actions secret)
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# Discord Server (Guild) ID
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")

# Channel IDs to crawl (empty list = all accessible public channels)
# Format: ["123456789", "987654321"]
CHANNEL_IDS: list[str] = []

# Paths
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")

# Discord API settings
MESSAGE_BATCH_SIZE = 100  # Messages per fetch batch
MAX_MESSAGES_PER_THREAD = 1000  # Cap to avoid huge pages
RATE_LIMIT_DELAY = 0.5  # Seconds between API calls to avoid rate limit