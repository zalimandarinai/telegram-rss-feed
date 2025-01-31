import asyncio
import os
import json
import logging
import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from feedgen.feed import FeedGenerator

# ✅ Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Telegram API Credentials (Loaded from GitHub Secrets)
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
string_session = os.getenv("TELEGRAM_STRING_SESSION")

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# ✅ Constants
LAST_POST_FILE = "docs/last_post.json"
RSS_FILE = "docs/rss.xml"
MAX_POSTS = 5  # The RSS feed must contain exactly 5 valid posts
CHANNEL = "Tsaplienko"  # Replace with your Telegram channel username
FETCH_LIMIT = 10  # ✅ Fetch only 10 messages per API request

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

# ✅ Fetch messages with delay and error handling
async def fetch_messages_with_delay(channel, limit=FETCH_LIMIT, delay=1.5):
    try:
        logger.info(f"📌 Fetching {limit} messages at {datetime.datetime.utcnow()}...")
        messages = await client.get_messages(channel, limit=limit)
        await asyncio.sleep(delay)  # Prevents hitting Telegram's rate limit
        return messages
    except FloodWaitError as e:
        logger.warning(f"🚨 Telegram API rate limit hit. Waiting {e.seconds} seconds...")
        await asyncio.sleep(e.seconds + 1)  # Wait and retry
        return await client.get_messages(channel, limit=limit)  # Retry after waiting

# ✅ Fetch latest posts, ensuring they have both media and description
async def fetch_latest_posts():
    await client.connect()

    last_post_id = load_last_post()
    today = datetime.datetime.utcnow().date()
    valid_posts = []  # Store only valid posts (media + description)
    fetched_messages = 0  # Track number of checked messages

    while len(valid_posts) < MAX_POSTS:
        messages = await fetch_messages_with_delay(CHANNEL, limit=FETCH_LIMIT)

        if not messages:
            logger.info("❌ No more messages found.")
            break

        fetched_messages += len(messages)

        for msg in messages:
            if msg.date.date() != today or msg.id <= last_post_id:
                continue  # Ignore old posts

            text = msg.message or getattr(msg, "caption", None)  # Must have description
            has_media = msg.media is not None  # Must have media

            if text and has_media:
                valid_posts.append(msg)

            if len(valid_posts) >= MAX_POSTS:
                break  # Stop when we have enough valid posts

        last_post_id = messages[0].id if messages else last_post_id

    if valid_posts:
        save_last_post(valid_posts[0].id)

    logger.info(f"✅ Checked {fetched_messages} messages, found {len(valid_posts)} valid posts.")
    return valid_posts

# ✅ Generate RSS in an Async Function
async def generate_rss(posts):
    if not posts:
        logger.error("❌ No valid posts available to generate RSS!")
        return

    fg = FeedGenerator()
    fg.title("Latest news")
    fg.link(href="https://www.mandarinai.lt/")
    fg.description("Naujienų kanalą pristato www.mandarinai.lt")
    fg.lastBuildDate(datetime.datetime.utcnow())

    seen_media = set()  # ✅ Prevents duplicate media links

    for msg in posts:
        fe = fg.add_entry()
        text = msg.message or getattr(msg, "caption", "No Content")
        fe.title(text[:30])  # ✅ Trim title for readability
        fe.description(text)
        fe.pubDate(msg.date)

        # ✅ Process media correctly
        if msg.media:
            media_path = await msg.download_media(file="./")  # ✅ Must be inside async function
            if media_path and os.path.exists(media_path):
                media_url = f"https://storage.googleapis.com/telegram-media-storage/{os.path.basename(media_path)}"

                if media_url not in seen_media:  # ✅ Prevent duplicate links
                    fe.enclosure(url=media_url, type="image/jpeg" if media_path.endswith(".jpg") else "video/mp4")
                    seen_media.add(media_url)

                os.remove(media_path)  # ✅ Clean up local files after processing

    # ✅ Save RSS to File
    os.makedirs("docs", exist_ok=True)
    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info(f"✅ RSS feed successfully updated with {len(posts)} posts.")

# ✅ Main Execution Flow
async def main():
    latest_posts = await fetch_latest_posts()

    if latest_posts:
        await generate_rss(latest_posts)
    else:
        logger.warning("❌ No valid posts found—RSS will not be updated.")

if __name__ == "__main__":
    asyncio.run(main())  # ✅ Properly executes async functions