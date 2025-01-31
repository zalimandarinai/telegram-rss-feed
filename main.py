import asyncio
import os
import json
import logging
import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from feedgen.feed import FeedGenerator

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
RSS_FILE = "docs/rss.xml"
MAX_POSTS = 5  # ✅ RSS must contain exactly 5 valid posts
CHANNEL = "Tsaplienko"  # Replace with your Telegram channel username
FETCH_LIMIT = 10  # ✅ Fetch only 10 messages per request

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

# ✅ Fetch Messages
async def fetch_latest_posts():
    await client.connect()

    last_post_id = load_last_post()
    today = datetime.datetime.utcnow().date()
    valid_posts = []  # ✅ Store only posts with media & description

    # ✅ Fetch exactly 10 messages (no extra API calls)
    messages = await client.get_messages(CHANNEL, limit=FETCH_LIMIT)
    logger.info(f"📌 Checked {len(messages)} messages")

    for msg in messages:
        if msg.date.date() != today or msg.id <= last_post_id:
            continue  # ✅ Ignore old messages

        text = msg.message or getattr(msg, "caption", None)  # ✅ Must have text
        has_media = msg.media is not None  # ✅ Must have media

        if text and has_media:
            valid_posts.append(msg)

        if len(valid_posts) >= MAX_POSTS:
            break  # ✅ STOP once we have 5 valid posts

    if valid_posts:
        save_last_post(valid_posts[0].id)

    logger.info(f"✅ Found {len(valid_posts)} valid posts.")
    return valid_posts

# ✅ Generate RSS
async def generate_rss(posts):
    if not posts:
        logger.error("❌ No valid posts available!")
        return

    fg = FeedGenerator()
    fg.title("Latest news")
    fg.link(href="https://www.mandarinai.lt/")
    fg.description("Naujienų kanalą pristato www.mandarinai.lt")
    fg.lastBuildDate(datetime.datetime.utcnow())

    for msg in posts:
        fe = fg.add_entry()
        text = msg.message or getattr(msg, "caption", "No Content")
        fe.title(text[:30])
        fe.description(text)
        fe.pubDate(msg.date)

    # ✅ Save RSS File
    os.makedirs("docs", exist_ok=True)
    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info(f"✅ RSS updated with {len(posts)} posts.")

# ✅ Main Function
async def main():
    latest_posts = await fetch_latest_posts()

    if latest_posts:
        await generate_rss(latest_posts)
    else:
        logger.warning("❌ No valid posts found—RSS not updated.")

if __name__ == "__main__":
    asyncio.run(main())  # ✅ Executes properly