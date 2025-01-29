import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
import os
import json
from feedgen.feed import FeedGenerator
import logging
import xml.etree.ElementTree as ET
from google.cloud import storage
from google.oauth2 import service_account

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Telegram API Credentials
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
string_session = os.getenv("TELEGRAM_STRING_SESSION")

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# ✅ Fix: Explicitly load Google Cloud credentials
credentials_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
if not credentials_json:
    raise Exception("❌ Google Cloud credentials are missing!")

credentials_dict = json.loads(credentials_json)
credentials = service_account.Credentials.from_service_account_info(credentials_dict)

storage_client = storage.Client(credentials=credentials)
bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# Constants
LAST_POST_FILE = "docs/last_post.json"
RSS_FILE = "docs/rss.xml"
MAX_POSTS = 5  # ✅ Keeps exactly the last 5 media posts
MAX_MEDIA_SIZE = 15 * 1024 * 1024  # ✅ 15MB limit per file

def load_last_post():
    """Load the last processed post ID from a file."""
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    return {"id": 0}

def save_last_post(post_data):
    """Save the last processed post ID to a file."""
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump(post_data, f)

def load_existing_rss():
    """Load existing RSS feed and return as a list of entries."""
    if not os.path.exists(RSS_FILE):
        return []

    try:
        tree = ET.parse(RSS_FILE)
        root = tree.getroot()
        channel = root.find("channel")
        return channel.findall("item") if channel else []
    except Exception as e:
        logger.error(f"Error reading RSS file: {e}")
        return []

async def create_rss():
    await client.connect()
    last_post = load_last_post()

    # Fetch the latest 5 messages
    messages = await client.get_messages('Tsaplienko', limit=5)

    # Filter only new messages with media
    new_messages = [msg for msg in messages if msg.id > last_post.get("id", 0) and msg.media]

    if not new_messages:
        logger.info("No new Telegram posts with media. Exiting early.")
        exit(0)  # ✅ Prevents unnecessary GitHub Actions minutes usage

    # Load existing RSS entries
    existing_items = load_existing_rss()

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    # Keep only the latest 5 posts (new + existing)
    all_posts = new_messages + existing_items[:MAX_POSTS - len(new_messages)]

    seen_media = set()  # ✅ Track processed media to avoid duplicates

    for msg in reversed(new_messages):  # Process older messages first
        fe = fg.add_entry()

        # ✅ Use the first 30 characters of the message as the title, or a fallback
        title_text = msg.message[:30] if msg.message else "No Title"
        description_text = msg.message if msg.message else "No Content"

        fe.title(title_text)  # ✅ Correct title from Telegram message
        fe.description(description_text)  # ✅ Correct description from Telegram message
        fe.pubDate(msg.date)

        if msg.media:
            try:
                # Download media
                media_path = await msg.download_media(file="./")
                if media_path and os.path.getsize(media_path) <= MAX_MEDIA_SIZE:  # ✅ Ensures media is ≤15MB
                    blob_name = os.path.basename(media_path)
                    blob = bucket.blob(blob_name)

                    # ✅ Skip upload if media file already exists in Google Cloud Storage
                    if not blob.exists():
                        blob.upload_from_filename(media_path)
                        blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'
                        logger.info(f"Uploaded {blob_name} to Google Cloud Storage")
                    else:
                        logger.info(f"Skipping upload, {blob_name} already exists")

                    # ✅ Avoid duplicate media in RSS
                    if blob_name not in seen_media:
                        seen_media.add(blob_name)
                        fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                                     type='image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4')

                    os.remove(media_path)  # ✅ Cleanup local media after processing
                else:
                    logger.info(f"Skipping large media file: {media_path}")
                    os.remove(media_path)
            except Exception as e:
                logger.error(f"Error handling media: {e}")

    # Save the latest processed message ID
    save_last_post({"id": new_messages[0].id})

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    return "RSS Updated"

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
