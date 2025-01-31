import asyncio
import os
import json
import logging
import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
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
MAX_POSTS = 5  # ✅ RSS turi turėti tiksliai 5 valid postus
CHANNEL = "Tsaplienko"  # Pakeiskite į savo Telegram kanalo username
FETCH_LIMIT = 10  # ✅ Gauname tik 10 žinučių per request

# ✅ Load Last Processed Post ID
def load_last_post():
    if os.path.exists(LAST_POST_FILE):
        try:
            with open(LAST_POST_FILE, "r") as f:
                data = json.load(f)
                return data.get("id", 0)
        except (json.JSONDecodeError, FileNotFoundError):
            return 0
    return 0

# ✅ Save Last Processed Post ID
def save_last_post(post_id):
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump({"id": post_id}, f)

# ✅ Extract Media URLs
async def extract_media(msg):
    media_urls = []
    if isinstance(msg.media, (MessageMediaPhoto, MessageMediaDocument)):
        media = await client.download_media(msg, file=bytes)
        media_urls.append(f"data:image/jpeg;base64,{media.hex()[:50]}...")  # Fake placeholder, replace with real hosting logic
    return media_urls

# ✅ Fetch Messages
async def fetch_latest_posts():
    async with client:
        last_post_id = load_last_post()
        today = datetime.datetime.now(datetime.UTC).date()  # ✅ Pataisyta UTC laiko juosta
        valid_posts = {}  # ✅ Saugojame albumus pagal `grouped_id`

        messages = await client.get_messages(CHANNEL, limit=FETCH_LIMIT)
        logger.info(f"📌 Checked {len(messages)} messages")

        for msg in messages:
            if msg.date.date() != today or msg.id <= last_post_id:
                continue  # ✅ Ignoruojame senas žinutes

            text = msg.message or getattr(msg, "caption", None)  # ✅ Turi būti tekstas
            has_media = msg.media is not None  # ✅ Turi būti medija
            group_id = msg.grouped_id or msg.id  # ✅ Albumai atpažįstami pagal `grouped_id`

            if text and has_media:
                if group_id not in valid_posts:
                    valid_posts[group_id] = {"msg": msg, "media": []}

                media_urls = await extract_media(msg)
                valid_posts[group_id]["media"].extend(media_urls)

            if len(valid_posts) >= MAX_POSTS:
                break  # ✅ STOP jei jau turime 5 postus

        if valid_posts:
            save_last_post(max(valid_posts.keys()))

        logger.info(f"✅ Found {len(valid_posts)} valid posts.")
        return list(valid_posts.values())

# ✅ Generate RSS
async def generate_rss(posts):
    if not posts:
        logger.error("❌ No valid posts available!")
        return

    fg = FeedGenerator()
    fg.title("Latest news")
    fg.link(href="https://www.mandarinai.lt/")
    fg.description("Naujienų kanalą pristato www.mandarinai.lt")
    fg.lastBuildDate(datetime.datetime.now(datetime.UTC))  # ✅ Pataisyta UTC laiko juosta

    for post_data in posts:
        msg = post_data["msg"]
        media_urls = post_data["media"]
        text = msg.message or getattr(msg, "caption", "No Content")

        fe = fg.add_entry()
        fe.title(text[:30])
        fe.description(f"{text}<br><br>" + "".join(f'<img src="{url}" /><br>' for url in media_urls))
        fe.pubDate(msg.date.replace(tzinfo=datetime.UTC))  # ✅ Pataisyta UTC laiko juosta

    # ✅ Išsaugoti RSS failą
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
    asyncio.run(main())  # ✅ Vykdoma teisingai