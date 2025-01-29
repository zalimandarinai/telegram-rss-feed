from flask import Flask, Response
from telethon import TelegramClient
from feedgen.feed import FeedGenerator
import os
import asyncio
import json
import logging
from telethon.sessions import StringSession
from waitress import serve
from google.cloud import storage

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Retrieve credentials from GitHub Secrets
api_id = int(os.getenv("TELEGRAM_API_ID", 0))  # Default to 0 if missing
api_hash = os.getenv("TELEGRAM_API_HASH")
string_session = os.getenv("TELEGRAM_STRING_SESSION")
gcp_credentials = os.getenv("GCP_SERVICE_ACCOUNT_JSON")

# Ensure required secrets exist
if not all([api_id, api_hash, string_session, gcp_credentials]):
    raise ValueError("❌ Missing one or more required environment variables!")

# Write GCP credentials to a JSON file for Google Cloud SDK
gcp_credentials_path = "gcp_credentials.json"
with open(gcp_credentials_path, "w") as f:
    f.write(gcp_credentials)

# Set Google Cloud authentication
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = gcp_credentials_path
storage_client = storage.Client()

# Google Cloud Storage configuration
bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# Telegram client
client = TelegramClient(StringSession(string_session), api_id, api_hash)

# File to track last processed post
LAST_POST_FILE = "docs/last_post.json"

# Ensure event loop is available
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

def load_last_post():
    """Load last processed Telegram post ID."""
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_last_post(post_data):
    """Save last processed Telegram post ID."""
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump(post_data, f)

async def create_rss():
    """Fetch latest Telegram message and generate an RSS feed if there's new content."""
    if not client.is_connected():
        await client.connect()

    try:
        messages = await client.get_messages('Tsaplienko', limit=1)  # Fetch latest post
    except Exception as e:
        logger.error(f"❌ Error fetching messages: {e}")
        return None

    if not messages:
        logger.info("✅ No new messages found.")
        return None

    msg = messages[0]
    last_post = load_last_post()

    # Skip processing if the latest post has already been handled
    if last_post.get("id") == msg.id:
        logger.info("🔄 No new Telegram posts. Skipping update.")
        return None

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    fe = fg.add_entry()
    fe.title(msg.message[:30] if msg.message else "No Title")
    fe.description(msg.message or "No Content")
    fe.pubDate(msg.date)

    # Handle media attachments
    if msg.media:
        try:
            media_path = await msg.download_media(file="./")
            if media_path:
                blob_name = os.path.basename(media_path)
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(media_path)
                blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'

                media_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
                fe.enclosure(url=media_url, type='image/jpeg' if media_url.endswith('.jpg') else 'video/mp4')

                os.remove(media_path)  # Cleanup local file
        except Exception as e:
            logger.error(f"❌ Error handling media: {e}")

    rss_feed = fg.rss_str(pretty=True)

    # Save new post ID and RSS feed
    save_last_post({"id": msg.id})
    with open("docs/rss.xml", "wb") as f:
        f.write(rss_feed)

    return rss_feed

@app.route('/rss')
def rss_feed():
    """Serve the RSS feed via HTTP."""
    try:
        rss_content = loop.run_until_complete(create_rss())
        if not rss_content:
            return Response("No new messages found", status=204)
    except Exception as e:
        logger.error(f"❌ Error generating RSS feed: {e}")
        return Response(f"Error: {str(e)}", status=500)

    return Response(rss_content, mimetype='application/rss+xml')

if __name__ == "__main__":
    loop.run_until_complete(create_rss())  # Run RSS feed update only when needed
