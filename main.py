from flask import Flask, Response
from telethon import TelegramClient
from feedgen.feed import FeedGenerator
import os
import asyncio
from telethon.sessions import StringSession
import logging
from waitress import serve
from google.cloud import storage
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Load credentials from GitHub Secrets (set in GitHub Actions)
api_id = int(os.getenv("TELEGRAM_API_ID"))  # Telegram API ID
api_hash = os.getenv("TELEGRAM_API_HASH")   # Telegram API Hash
string_session = os.getenv("TELEGRAM_STRING_SESSION")  # Telegram Session String

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# Google Cloud Storage Setup
credentials_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
credentials_path = "/tmp/gcp_credentials.json"

# Write credentials file for Google Cloud Storage
with open(credentials_path, "w") as f:
    f.write(credentials_json)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
storage_client = storage.Client()

# Define Google Cloud Storage Bucket
bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# Store last processed message ID
LAST_MESSAGE_FILE = "last_message.json"

def get_last_message_id():
    """Retrieve the last processed Telegram message ID"""
    if os.path.exists(LAST_MESSAGE_FILE):
        with open(LAST_MESSAGE_FILE, "r") as f:
            return json.load(f).get("last_message_id", 0)
    return 0

def save_last_message_id(message_id):
    """Save the last processed Telegram message ID"""
    with open(LAST_MESSAGE_FILE, "w") as f:
        json.dump({"last_message_id": message_id}, f)

async def create_rss():
    """Fetch the latest message from Telegram and update the RSS feed"""
    if not client.is_connected():
        await client.connect()

    last_message_id = get_last_message_id()

    try:
        messages = await client.get_messages('Tsaplienko', limit=1)
        if not messages or messages[0].id == last_message_id:
            logger.info("No new messages found.")
            return None

        msg = messages[0]
        save_last_message_id(msg.id)  # Save latest message ID

    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        return None

    # Create RSS feed
    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    fe = fg.add_entry()
    fe.title(msg.message[:30] if msg.message else "No Title")
    fe.description(msg.message or "No Content")
    fe.pubDate(msg.date)

    # Handle media (photo/video)
    if msg.media:
        try:
            media_path = await msg.download_media(file="./")
            if media_path:
                logger.info(f"Downloaded media: {media_path}")

                # Upload to Google Cloud Storage
                blob_name = os.path.basename(media_path)
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(media_path)
                blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'
                logger.info(f"Uploaded media to Cloud Storage: {blob_name}")

                media_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
                logger.info(f"Media URL: {media_url}")

                fe.enclosure(url=media_url, type='image/jpeg' if media_url.endswith('.jpg') else 'video/mp4')

                os.remove(media_path)  # Cleanup local file
                logger.info(f"Deleted local file: {media_path}")

        except Exception as e:
            logger.error(f"Error handling media: {e}")

    return fg.rss_str(pretty=True)

@app.route('/rss')
def rss_feed():
    try:
        rss_content = asyncio.run(create_rss())
        if not rss_content:
            return Response("No new messages found", status=204)
    except Exception as e:
        logger.error(f"Error generating RSS feed: {e}")
        return Response(f"Error: {str(e)}", status=500)

    return Response(rss_content, mimetype='application/rss+xml')

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    serve(app, host="0.0.0.0", port=port)
