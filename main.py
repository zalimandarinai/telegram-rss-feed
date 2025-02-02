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
FETCH_LIMIT = 5  # ✅ Fetch only the last 5 Telegram messages
MAX_MEDIA_SIZE = 15 * 1024 * 1024  # ✅ Max media file size 15MB

# ✅ FUNCTION: Fetch Last 5 Telegram Messages
async def fetch_last_5_messages():
    await client.connect()

    # ✅ Fetch the last 5 messages from the Telegram channel
    messages = await client.get_messages('Tsaplienko', limit=FETCH_LIMIT)

    collected_posts = []
    grouped_texts = {}  # ✅ Store text for album posts

    for msg in reversed(messages):  # ✅ Process from oldest to newest
        text = msg.message or getattr(msg, "caption", "").strip()

        # ✅ Assign album text from the first grouped post
        if hasattr(msg.media, "grouped_id") and msg.grouped_id:
            if msg.grouped_id not in grouped_texts:
                grouped_texts[msg.grouped_id] = text
            else:
                text = grouped_texts[msg.grouped_id]

        # ✅ Collect only messages with media
        if msg.media:
            collected_posts.append({
                "id": msg.id,
                "date": msg.date.replace(tzinfo=timezone.utc),
                "text": text if text else "📷 Media Post",
                "media": "Yes" if msg.media else "No"
            })

    # ✅ Sort messages by date (newest first)
    collected_posts = sorted(collected_posts, key=lambda x: x["date"], reverse=True)

    return collected_posts

# ✅ MAIN PROCESS EXECUTION
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    fetched_data = loop.run_until_complete(fetch_last_5_messages())

    # ✅ Display collected data
    for post in fetched_data:
        print(f"🆕 Post ID: {post['id']}")
        print(f"📅 Date: {post['date']}")
        print(f"📝 Text: {post['text']}")
        print(f"🖼️ Media: {post['media']}")
        print("-" * 40)