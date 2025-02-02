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
FETCH_LIMIT = 10  # ✅ Fetch only the last 10 Telegram posts to ensure freshness
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

# ✅ FUNCTION: Load existing RSS items
def load_existing_rss():
    if not os.path.exists(RSS_FILE):
        return []

    try:
        tree = ET.parse(RSS_FILE)
        root = tree.getroot()
        channel = root.find("channel")
        return channel.findall("item") if channel else []
    except Exception as e:
        logger.error(f"❌ RSS file is corrupted. Creating a new one: {e}")
        return []

# ✅ FUNCTION: Generate RSS
async def create_rss():
    await client.connect()

    last_post = load_last_post()
    last_post_id = last_post.get("id", 0)
    last_media_files = set(last_post.get("media", []))

    # ✅ Fetch only the last 10 messages to ensure freshness
    messages = await client.get_messages('Tsaplienko', limit=FETCH_LIMIT)

    valid_posts = []
    grouped_texts = {}  # ✅ Stores text for album posts
    seen_media = set()  # ✅ Track already added media to avoid duplicates

    for msg in reversed(messages):  # ✅ Process from oldest to newest
        text = msg.message or getattr(msg, "caption", "").strip()

        # ✅ Assign album text from first grouped post
        if hasattr(msg.media, "grouped_id") and msg.grouped_id:
            if msg.grouped_id not in grouped_texts:
                grouped_texts[msg.grouped_id] = text
            else:
                text = grouped_texts[msg.grouped_id]

        # ✅ Skip posts without media
        if not msg.media:
            logger.warning(f"⚠️ Skipping message {msg.id} (No media)")
            continue

        # ✅ Prevent "No Title" / "No Content" posts
        if not text:
            text = "📷 Media Post"

        valid_posts.append((msg, text))

        # ✅ Stop after collecting 5 valid posts
        if len(valid_posts) >= MAX_POSTS:
            break

    # ✅ Ensure exactly 5 posts in RSS (sorted by post date, latest first)
    valid_posts = sorted(valid_posts, key=lambda x: x[0].date, reverse=True)[:MAX_POSTS]

    if not valid_posts:
        logger.warning("⚠️ No valid media posts – RSS will not be updated.")
        return

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('News channel by www.mandarinai.lt')

    latest_post_id = 0  # ✅ Track latest processed post ID

    for msg, text in valid_posts:
        latest_post_id = max(latest_post_id, msg.id)

        media_path = await msg.download_media(file="./")
        if media_path:
            file_size = os.path.getsize(media_path)
            if file_size > MAX_MEDIA_SIZE:
                os.remove(media_path)
                continue

            blob_name = os.path.basename(media_path)
            blob = bucket.blob(blob_name)

            # ✅ Avoid duplicate media
            if blob_name in seen_media:
                os.remove(media_path)
                continue
            seen_media.add(blob_name)

            # ✅ Upload to Google Cloud if not exists
            if not blob.exists():
                blob.upload_from_filename(media_path)
                logger.info(f"✅ Uploaded {blob_name} to Google Cloud Storage")

            # ✅ Create RSS entry
            fe = fg.add_entry()
            fe.title(text[:30] if text else "No Title")
            fe.description(text if text else "No Content")
            fe.pubDate(msg.date.replace(tzinfo=timezone.utc))

            # ✅ Determine media type for enclosure
            media_type = "image/jpeg" if blob_name.endswith((".jpg", ".jpeg")) else "video/mp4"
            fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                         length=str(file_size), type=media_type)

        # ✅ Remove downloaded media file
        if media_path:
            os.remove(media_path)

    # ✅ Save last processed post ID & media
    save_last_post({"id": latest_post_id, "media": list(seen_media)})

    # ✅ Write updated RSS file
    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS updated successfully!")

# ✅ MAIN PROCESS EXECUTION
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())