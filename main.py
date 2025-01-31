import asyncio
import os
import json
import logging
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession

# ✅ Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Telegram API Credentials
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
string_session = os.getenv("TELEGRAM_STRING_SESSION")

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# ✅ Constants
LAST_POST_FILE = "docs/last_post.json"
MAX_POSTS = 5  # RSS must contain exactly 5 valid posts
CHANNEL = "Tsaplienko"  # Replace with your channel username

# ✅ Load Last Processed Post ID
def load_last_post():
    if os.path.exists(LAST_POST_FILE):
        try:
            with open(LAST_POST_FILE, "r") as f:
                data = json.load(f)
                return data.get("id", 0)
        except json.JSONDecodeError:
            return 0
    return 0

# ✅ Save Last Processed Post ID
def save_last_post(post_id):
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump({"id": post_id}, f)

# ✅ Fetch only latest posts that have both media and description
async def fetch_latest_posts():
    await client.connect()

    last_post_id = load_last_post()
    today = datetime.utcnow().date()

    valid_posts = []  # Store only valid posts (media + description)
    fetched_messages = 0  # Track the number of checked messages

    while len(valid_posts) < MAX_POSTS:
        # ✅ Fetch next batch of 10 messages (avoids excessive requests)
        messages = await client.get_messages(CHANNEL, limit=10, offset_id=last_post_id)

        if not messages:
            logger.info("❌ No more messages found.")
            break

        fetched_messages += len(messages)

        for msg in messages:
            # ✅ Ensure post is from today and has not been processed
            if msg.date.date() != today or msg.id <= last_post_id:
                continue

            text = msg.message or getattr(msg, "caption", None)  # Description (must exist)
            has_media = msg.media is not None  # Media (must exist)

            if text and has_media:
                valid_posts.append(msg)

            # ✅ Stop when 5 valid posts are found
            if len(valid_posts) >= MAX_POSTS:
                break

        # ✅ Update last processed post ID
        last_post_id = messages[0].id if messages else last_post_id

    if valid_posts:
        save_last_post(valid_posts[0].id)

    logger.info(f"✅ Checked {fetched_messages} messages, found {len(valid_posts)} valid posts.")
    return valid_posts

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    latest_posts = loop.run_until_complete(fetch_latest_posts())

    if latest_posts:
        logger.info(f"✅ Found {len(latest_posts)} valid posts with media and description.")
    else:
        logger.info("❌ No valid posts available.")