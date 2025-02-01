import asyncio
import os
import json
import logging
import xml.etree.ElementTree as ET
import datetime
from feedgen.feed import FeedGenerator
from google.cloud import storage
from google.oauth2 import service_account
from telethon import TelegramClient
from telethon.sessions import StringSession

# ✅ LOG CONFIGURATION
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ TELEGRAM AUTHENTICATION
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
string_session = os.getenv("TELEGRAM_STRING_SESSION")

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# ✅ GOOGLE CLOUD STORAGE AUTH
credentials_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
if not credentials_json:
    raise Exception("❌ Google Cloud credentials missing!")

credentials_dict = json.loads(credentials_json)
credentials = service_account.Credentials.from_service_account_info(credentials_dict)
storage_client = storage.Client(credentials=credentials)
bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# ✅ CONSTANTS
LAST_POST_FILE = "docs/last_post.json"
RSS_FILE = "docs/rss.xml"
MAX_POSTS = 5
MAX_MEDIA_SIZE = 15 * 1024 * 1024  # ✅ Ignore files > 15 MB
LOOKBACK_TIME = 2 * 60 * 60  # ✅ Check posts from the last 2 hours

# ✅ LOAD LAST PROCESSED POST ID
def load_last_post():
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    return {"id": 0}

# ✅ SAVE LAST PROCESSED POST ID
def save_last_post(post_data):
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump(post_data, f)

# ✅ LOAD EXISTING RSS DATA
def load_existing_rss():
    if not os.path.exists(RSS_FILE):
        return []

    try:
        tree = ET.parse(RSS_FILE)
        root = tree.getroot()
        channel = root.find("channel")
        return channel.findall("item") if channel else []
    except Exception as e:
        logger.error(f"❌ Corrupt RSS file, creating a new one: {e}")
        return []

# ✅ RSS GENERATION FUNCTION
async def create_rss():
    await client.connect()
    last_post = load_last_post()
    
    # ✅ FIX: Ensure `min_time` is timezone-aware
    min_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=LOOKBACK_TIME)

    messages = await client.get_messages('Tsaplienko', limit=10, wait_time=2)
    
    grouped_texts = {}
    valid_posts = []

    for msg in reversed(messages):
        if msg.date < min_time:  # ✅ FIX: Both are now timezone-aware
            continue

        text = msg.message or getattr(msg, "caption", None) or "No Content"

        if hasattr(msg, "grouped_id") and msg.grouped_id:
            if msg.grouped_id not in grouped_texts:
                grouped_texts[msg.grouped_id] = text
            else:
                text = grouped_texts[msg.grouped_id]

        if text == "No Content" and not msg.media:
            logger.warning(f"⚠️ Skipping post {msg.id}, no text or media")
            continue

        valid_posts.append((msg, text))

        if len(valid_posts) >= MAX_POSTS:
            break

    # ✅ ENSURE WE ALWAYS HAVE 5 ITEMS
    existing_items = load_existing_rss()
    if len(valid_posts) < MAX_POSTS:
        remaining_posts = [msg for msg in existing_items if msg not in valid_posts]
        valid_posts.extend(remaining_posts[:MAX_POSTS - len(valid_posts)])

    # ✅ GENERATE NEW RSS
    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')
    fg.lastBuildDate(datetime.datetime.now(datetime.UTC))

    seen_media = set()

    for msg, text in valid_posts:
        fe = fg.add_entry()
        fe.title(text[:80])  # ✅ Increased length to 80 characters
        fe.description(text)
        fe.pubDate(msg.date.replace(tzinfo=datetime.UTC))
        fe.guid(str(msg.id), permalink=False)

        if msg.media:
            try:
                media_path = await msg.download_media(file="./")

                # ✅ IGNORE FILES > 15 MB
                if os.path.getsize(media_path) > MAX_MEDIA_SIZE:
                    logger.info(f"🚨 File too large: {media_path}, skipping")
                    os.remove(media_path)
                    continue  # Skip this file

                blob_name = os.path.basename(media_path)
                blob = bucket.blob(blob_name)

                # ✅ FIX: ENSURE MEDIA EXISTS BEFORE PROCESSING
                try:
                    blob.reload()  # Force load blob metadata
                except Exception as e:
                    logger.error(f"❌ Failed to load blob {blob_name}: {e}")
                    continue

                if not blob.exists():  # Check again after reload()
                    blob.upload_from_filename(media_path)
                    blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'
                    blob.make_public()
                    logger.info(f"✅ Uploaded {blob_name} to Google Cloud Storage")

                if blob_name not in seen_media:
                    seen_media.add(blob_name)
                    fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                                 type='image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4')

                os.remove(media_path)
            except Exception as e:
                logger.error(f"❌ Error processing media: {e}")

    save_last_post({"id": valid_posts[0][0].id if valid_posts else last_post["id"]})

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS successfully updated!")

# ✅ RUN SCRIPT
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())