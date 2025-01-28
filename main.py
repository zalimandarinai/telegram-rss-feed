import os
import asyncio
import logging
import mimetypes
import tempfile

from telethon import TelegramClient
from telethon.sessions import StringSession
from feedgen.feed import FeedGenerator
from google.cloud import storage

# Logging for easier debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === 1) Load environment variables (no hardcoded credentials) ===
try:
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    string_session = os.environ["TELEGRAM_STRING_SESSION"]
except KeyError as e:
    raise RuntimeError(f"Missing environment variable: {e}")

# Telegram channel or username you want to pull from
channel_username = os.environ.get("TELEGRAM_CHANNEL", "Tsaplienko")

# Google Cloud bucket name
bucket_name = os.environ.get("GCS_BUCKET_NAME", "telegram-media-storage")

# === 2) Initialize Telethon and Google Cloud Storage ===
client = TelegramClient(StringSession(string_session), api_id, api_hash)
storage_client = storage.Client()
bucket = storage_client.bucket(bucket_name)

async def generate_rss():
    """Fetch Telegram messages, build RSS, upload to GCS, then exit."""
    # Start Telegram client
    await client.start()

    # Fetch the latest N messages from channel (adjust limit as desired)
    messages = await client.get_messages(channel_username, limit=5)
    logger.info(f"Fetched {len(messages)} messages from {channel_username}.")

    # Create RSS feed
    fg = FeedGenerator()
    fg.title("Latest news")
    fg.link(href="https://www.mandarinai.lt/")
    fg.description("Naujienų kanalą pristato www.mandarinai.lt")

    # Iterate over messages (reversed so oldest is first in feed)
    for msg in reversed(messages):
        fe = fg.add_entry()
        fe.title(msg.message[:30] if msg.message else "No Title")
        fe.description(msg.message or "No Content")
        fe.pubDate(msg.date)

        # Handle media
        if msg.media:
            try:
                with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                    media_path = await msg.download_media(file=tmp_file.name)
                if media_path:
                    blob_name = os.path.basename(media_path)
                    blob = bucket.blob(blob_name)
                    blob.upload_from_filename(media_path)

                    # Try to guess content type
                    mime_type, _ = mimetypes.guess_type(media_path)
                    blob.content_type = mime_type or "application/octet-stream"

                    media_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
                    fe.enclosure(url=media_url, type=mime_type or "application/octet-stream")

                    # Remove local file
                    os.remove(media_path)
            except Exception as e:
                logger.error(f"Error handling media: {e}")

    # Convert feed to XML
    rss_bytes = fg.rss_str(pretty=True)

    # Save locally as rss.xml (for optional commit to GitHub Pages)
    with open("rss.xml", "wb") as f:
        f.write(rss_bytes)

    # Upload rss.xml to GCS
    rss_blob = bucket.blob("rss.xml")
    rss_blob.upload_from_string(rss_bytes, content_type="application/rss+xml")
    logger.info("RSS feed uploaded to GCS successfully!")

    # Disconnect Telegram
    await client.disconnect()

async def main():
    await generate_rss()

if __name__ == "__main__":
    asyncio.run(main())
