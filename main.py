import os
import asyncio
import logging
import mimetypes
import tempfile

from telethon import TelegramClient
from telethon.sessions import StringSession
from feedgen.feed import FeedGenerator
from google.cloud import storage

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 1) Load Telegram API credentials from environment variables
try:
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    string_session = os.environ["TELEGRAM_STRING_SESSION"]
except KeyError as e:
    raise RuntimeError(f"Missing required environment variable: {e}")

# 2) Initialize Telethon client
client = TelegramClient(StringSession(string_session), api_id, api_hash)

# 3) Load Google Cloud credentials
#    The google.cloud SDK will pick up the JSON file specified by GOOGLE_APPLICATION_CREDENTIALS.
storage_client = storage.Client()

# 4) Specify your Google Cloud bucket name (from env or default to "telegram-media-storage")
bucket_name = os.environ.get("GCS_BUCKET_NAME", "telegram-media-storage")
bucket = storage_client.bucket(bucket_name)

# 5) Which Telegram channel to fetch from. Replace or set via env var if needed.
channel_username = os.environ.get("TELEGRAM_CHANNEL", "Tsaplienko")

async def fetch_and_generate_feed():
    """Connect to Telegram, fetch latest messages, and generate an RSS feed."""
    # Ensure the client is connected
    await client.start()

    # Fetch the latest N messages (adjust limit as desired)
    messages = await client.get_messages(channel_username, limit=10)
    logger.info(f"Fetched {len(messages)} messages from {channel_username}.")

    # Build a new RSS feed
    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    # Iterate through messages (oldest to newest if you want them in that order)
    for msg in reversed(messages):
        fe = fg.add_entry()
        fe.title(msg.message[:30] if msg.message else "No Title")
        fe.description(msg.message or "No Content")
        fe.pubDate(msg.date)

        # Handle media (photos, videos, etc.)
        if msg.media:
            try:
                with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                    media_path = await msg.download_media(file=tmp_file.name)
                if media_path:
                    # Upload media to Google Cloud Storage
                    blob_name = os.path.basename(media_path)
                    blob = bucket.blob(blob_name)
                    blob.upload_from_filename(media_path)

                    # Detect MIME type
                    mime_type, _ = mimetypes.guess_type(media_path)
                    if not mime_type:
                        mime_type = 'application/octet-stream'
                    blob.content_type = mime_type

                    media_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
                    logger.info(f"Uploaded media to GCS: {media_url}")

                    # Add enclosure to feed
                    fe.enclosure(url=media_url, type=mime_type)

                    # Clean up local file
                    os.remove(media_path)
            except Exception as e:
                logger.error(f"Error handling media: {e}")

    # Generate RSS string
    rss_feed = fg.rss_str(pretty=True)

    # 6) Write the RSS to a local file (this file can be committed or published)
    with open("rss.xml", "wb") as f:
        f.write(rss_feed)
    logger.info("Saved local rss.xml")

    # 7) (Optional) Also store rss.xml in Google Cloud Storage
    rss_blob = bucket.blob("rss.xml")
    rss_blob.upload_from_string(rss_feed, content_type="application/rss+xml")
    logger.info("RSS feed uploaded to GCS successfully!")

async def main():
    await fetch_and_generate_feed()
    # Disconnect after finishing
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
