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
FETCH_LIMIT = 15  # ✅ Fetch more to ensure latest media is included
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

    # ✅ Fetch latest 15 messages to avoid missing new media posts
    messages = await client.get_messages('Tsaplienko', limit=FETCH_LIMIT)

    valid_posts = []
    grouped_posts = {}

    # ✅ Process from NEWEST to OLDEST (Fix for delay issue)
    for msg in sorted(messages, key=lambda x: x.date, reverse=True):
        text = msg.message or getattr(msg, "caption", "").strip()

        # ✅ Handle grouped media posts correctly
        if msg.grouped_id:
            if msg.grouped_id not in grouped_posts:
                grouped_posts[msg.grouped_id] = {"text": text, "media": []}
            grouped_posts[msg.grouped_id]["media"].append(msg)
            continue  # ✅ Process the entire album later

        # ✅ Skip old posts
        if msg.id <= last_post_id:
            continue

        # ✅ Skip non-media messages
        if not msg.media:
            continue

        valid_posts.append((msg, text))

        # ✅ Stop at exactly 5 latest media posts
        if len(valid_posts) >= MAX_POSTS:
            break

    # ✅ Process grouped media albums (assign text from first in album)
    for group in grouped_posts.values():
        text = group["text"]
        for msg in group["media"]:
            valid_posts.append((msg, text))
        if len(valid_posts) >= MAX_POSTS:
            break

    # ✅ Only keep the 5 newest posts
    valid_posts = valid_posts[:MAX_POSTS]

    if not valid_posts:
        logger.warning("⚠️ No valid media posts – RSS will not be updated.")
        return

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('News channel by https://www.mandarinai.lt')

    latest_post_id = last_post_id  # ✅ Track latest processed post ID
    seen_media = set()

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

            # ✅ Upload if it doesn't exist
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