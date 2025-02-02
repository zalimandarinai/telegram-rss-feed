import asyncio
import os
import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
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
MAX_POSTS = 5  
TIME_THRESHOLD = 65  
MAX_MEDIA_SIZE = 15 * 1024 * 1024  

# ✅ FUNCTION: Load last saved post data
def load_last_post():
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    return {"id": 0, "media": []}

# ✅ FUNCTION: Save last post data
def save_last_post(post_data):
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump(post_data, f)

# ✅ FUNCTION: Load existing RSS data
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

# ✅ FUNCTION: Main RSS Generation Process
async def create_rss():
    await client.connect()

    last_post = load_last_post()
    last_post_id = last_post.get("id", 0)
    last_media_files = set(last_post.get("media", []))

    utc_now = datetime.now(timezone.utc)

    messages = await client.get_messages('Tsaplienko', limit=50)
    valid_messages = []

    for msg in messages:
        msg_date = msg.date.replace(tzinfo=timezone.utc)
        text = msg.message or getattr(msg, "caption", "").strip()  # ✅ Always a valid string

        # ✅ Ignore messages that are too old or already processed
        if msg.id <= last_post_id or msg_date < utc_now - timedelta(minutes=TIME_THRESHOLD):
            continue
        
        # ✅ Skip messages that don’t have BOTH media and valid text
        if not msg.media or not text:
            logger.warning(f"⚠️ Skipping message {msg.id} (No valid text or media)")
            continue

        valid_messages.append(msg)

    existing_items = load_existing_rss()

    # ✅ Ensure 5 latest posts are saved
    for item in existing_items:
        if len(valid_messages) >= MAX_POSTS:
            break
        valid_messages.append(item)

    valid_messages = valid_messages[:MAX_POSTS]

    if not valid_messages:
        logger.warning("⚠️ No new entries – RSS file will not be updated.")
        return

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('News channel by www.mandarinai.lt')

    seen_media = set()
    added_entries = 0

    for msg in valid_messages:
        media_path = await msg.download_media(file="./")
        if media_path:
            file_size = os.path.getsize(media_path)
            if file_size > MAX_MEDIA_SIZE:
                os.remove(media_path)
                continue

            blob_name = os.path.basename(media_path)
            blob = bucket.blob(blob_name)

            if blob_name in last_media_files:
                os.remove(media_path)
                continue

            if not blob.exists():
                blob.upload_from_filename(media_path)
                logger.info(f"✅ Uploaded {blob_name} to {bucket_name}")

            seen_media.add(blob_name)

            fe = fg.add_entry()
            fe.title(text[:30])  # ✅ Always valid text
            fe.description(text)
            fe.pubDate(msg.date.replace(tzinfo=timezone.utc))

            # ✅ Correct media format
            if blob_name.endswith(".jpg") or blob_name.endswith(".jpeg"):
                media_type = "image/jpeg"
            elif blob_name.endswith(".mp4"):
                media_type = "video/mp4"
            else:
                logger.warning(f"⚠️ Unsupported file format {blob_name}, skipping.")
                continue

            fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}", length=str(file_size), type=media_type)

            added_entries += 1

        if media_path:
            os.remove(media_path)

    if added_entries == 0:
        logger.warning("⚠️ No valid media found – RSS will not be updated.")
        return

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    save_last_post({"id": valid_messages[0].id, "media": list(seen_media)})

# ✅ MAIN PROCESS EXECUTION
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())