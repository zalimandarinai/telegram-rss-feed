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
FETCH_LIMIT = 5  # ✅ Only fetch the last 5 messages
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

    last_post = load_last_post()
    last_post_id = last_post.get("id", 0)
    logger.info(f"📌 Last processed post ID (from JSON): {last_post_id}")

    # ✅ Fetch only the last 5 messages
    messages = await client.get_messages('Tsaplienko', limit=FETCH_LIMIT)

    logger.info("🔍 Checking fetched messages:")
    for msg in messages:
        logger.info(f"ID: {msg.id}, Date: {msg.date}, Has Media: {bool(msg.media)}, Grouped ID: {msg.grouped_id}")

    valid_posts = []
    grouped_posts = {}

    # ✅ Process messages from NEWEST to OLDEST
    for msg in sorted(messages, key=lambda x: x.date, reverse=True):
        text = msg.message or getattr(msg, "caption", "").strip()

        # ✅ Handle grouped media posts correctly
        if msg.grouped_id:
            if msg.grouped_id not in grouped_posts:
                grouped_posts[msg.grouped_id] = {"text": text, "media": []}
            grouped_posts[msg.grouped_id]["media"].append(msg)
            logger.info(f"📸 Album detected: Grouped ID {msg.grouped_id}, Message ID: {msg.id}")
            continue  # ✅ Process the entire album later

        # ✅ Skip old posts
        if msg.id <= last_post_id:
            logger.info(f"⏩ Skipping old message {msg.id}")
            continue

        # ✅ Skip non-media messages
        if not msg.media:
            logger.info(f"⏩ Skipping text-only message {msg.id}")
            continue

        logger.info(f"✅ Adding to RSS: Message {msg.id} - Date: {msg.date}, Media: {bool(msg.media)}")
        valid_posts.append((msg, text))

    # ✅ Process grouped media albums (assign text from first in album)
    for group in grouped_posts.values():
        text = group["text"]
        for msg in group["media"]:
            logger.info(f"✅ Adding album message {msg.id} to RSS")
            valid_posts.append((msg, text))

    # ✅ Keep only the 5 newest media posts and sort RSS with newest first
    valid_posts = sorted(valid_posts[:MAX_POSTS], key=lambda x: x[0].date, reverse=True)
    logger.info(f"📝 Total posts selected for RSS: {len(valid_posts)}")

    if not valid_posts:
        logger.warning("⚠️ No valid media posts – RSS will not be updated.")
        return

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('News channel by https://www.mandarinai.lt')

    latest_post_id = last_post_id  # ✅ Track