import asyncio
import os
import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from feedgen.feed import FeedGenerator
from google.cloud import storage
from google.oauth2 import service_account
from telethon import TelegramClient
from telethon.sessions import StringSession

# ✅ LOG CONFIGURATION
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ TELEGRAM LOGIN DETAILS
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
string_session = os.getenv("TELEGRAM_STRING_SESSION")

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# ✅ GOOGLE CLOUD STORAGE LOGIN DETAILS
credentials_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
credentials_dict = json.loads(credentials_json)
credentials = service_account.Credentials.from_service_account_info(credentials_dict)
storage_client = storage.Client(credentials=credentials)
bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# ✅ CONSTANTS
LAST_POST_FILE = "docs/last_post.json"
RSS_FILE = "docs/rss.xml"
MAX_POSTS = 5  # ✅ Always keep exactly 5 latest posts in RSS
FETCH_LIMIT = 10  # ✅ Fetch last 10 messages for better selection
MAX_MEDIA_SIZE = 15 * 1024 * 1024  # ✅ Max media file size 15MB

# ✅ FUNCTION: Load last saved post data
def load_last_post():
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    return {"id": 0, "media": []}

# ✅ FUNCTION: Save last processed post ID and media files
def save_last_post(post_data):
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump(post_data, f)

# ✅ FUNCTION: Generate RSS
async def create_rss():
    await client.connect()

    try:
        last_post = load_last_post()
        last_post_id = last_post.get("id", 0)
        logger.info(f"📌 Last processed post ID (from JSON): {last_post_id}")

        # ✅ Fetch last 10 messages
        messages = await client.get_messages('Tsaplienko', limit=FETCH_LIMIT)

        if not messages:
            logger.warning("⚠️ No messages retrieved from Telegram.")
            return

        logger.info("🔍 Checking fetched messages:")
        for msg in messages:
            logger.info(f"ID: {msg.id}, Date: {msg.date}, Has Media: {bool(msg.media)}, Grouped ID: {msg.grouped_id}")

        valid_posts = []
        grouped_posts = {}

        # ✅ Process messages from OLDEST to NEWEST
        for msg in sorted(messages, key=lambda x: x.date):
            text = msg.message or getattr(msg, "caption", None) or "Untitled Post"

            # ✅ Handle grouped media posts correctly
            if msg.grouped_id:
                grouped_posts.setdefault(msg.grouped_id, {"text": text, "media": []})
                grouped_posts[msg.grouped_id]["media"].append(msg)
                continue

            # ✅ Skip old posts
            if msg.id <= last_post_id:
                continue

            # ✅ Skip non-media messages
            if not msg.media:
                continue

            valid_posts.append((msg, text))

        # ✅ Process grouped media albums
        for group in grouped_posts.values():
            text = group["text"]
            for msg in group["media"]:
                valid_posts.append((msg, text))

        # ✅ Keep only the 5 newest media posts and sort RSS with newest first
        valid_posts = sorted(valid_posts[:MAX_POSTS], key=lambda x: x[0].date, reverse=True)

        if not valid_posts:
            logger.warning("⚠️ No valid media posts – RSS will not be updated.")
            return

        fg = FeedGenerator()
        fg.title('Latest news')
        fg.link(href='https://www.mandarinai.lt/')
        fg.description('News channel by https://www.mandarinai.lt')

        latest_post_id = last_post_id
        seen_media = set()

        async def process_media(msg, text):
            nonlocal latest_post_id
            latest_post_id = max(latest_post_id, msg.id)

            media_path = await msg.download_media(file="./")

            if not media_path:
                return None

            file_size = os.path.getsize(media_path)
            if file_size > MAX_MEDIA_SIZE:
                os.remove(media_path)
                return None

            blob_name = os.path.basename(media_path)
            blob = bucket.blob(blob_name)

            if blob_name in seen_media:
                os.remove(media_path)
                return None
            seen_media.add(blob_name)

            try:
                if not blob.exists():
                    blob.upload_from_filename(media_path)
            except Exception as e:
                os.remove(media_path)
                return None

            os.remove(media_path)

            fe = fg.add_entry()
            fe.title(text[:30])  # ✅ Ensure the title is properly set
            fe.description(text)  # ✅ Ensure the description is properly set
            fe.pubDate(msg.date.replace(tzinfo=timezone.utc))

            media_type = "image/jpeg" if blob_name.endswith((".jpg", ".jpeg")) else "video/mp4"
            fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                         length=str(file_size), type=media_type)
            return fe

        tasks = [process_media(msg, text) for msg, text in valid_posts]
        await asyncio.gather(*tasks)

        save_last_post({"id": latest_post_id, "media": list(seen_media)})

        with open(RSS_FILE, "wb") as f:
            f.write(fg.rss_str(pretty=True))

        logger.info("✅ RSS updated successfully!")

    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(create_rss())
