import os
import asyncio
import logging
import mimetypes
import tempfile
from telethon import TelegramClient
from telethon.sessions import StringSession
from feedgen.feed import FeedGenerator
from google.cloud import storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load required info from environment
api_id = int(os.environ["TELEGRAM_API_ID"])
api_hash = os.environ["TELEGRAM_API_HASH"]
string_session = os.environ["TELEGRAM_STRING_SESSION"]
channel_username = os.environ.get("TELEGRAM_CHANNEL", "Tsaplienko")  # default to "Tsaplienko"
bucket_name = os.environ.get("GCS_BUCKET_NAME", "telegram-media-storage")

client = TelegramClient(StringSession(string_session), api_id, api_hash)
storage_client = storage.Client()
bucket = storage_client.bucket(bucket_name)

async def generate_rss():
    # 1) Connect
    await client.start()

    # 2) Fetch the latest 5 messages
    messages = await client.get_messages(channel_username, limit=5)

    # 3) Build an RSS feed
    fg = FeedGenerator()
    fg.title("Latest news")
    fg.link(href="https://www.mandarinai.lt/")
    fg.description("Naujienų kanalą pristato www.mandarinai.lt")

    for msg in reversed(messages):
        fe = fg.add_entry()
        fe.title(msg.message[:30] if msg.message else "No Title")
        fe.description(msg.message or "No Content")
        fe.pubDate(msg.date)

        # Media
        if msg.media:
            try:
                with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                    media_path = await msg.download_media(file=tmp_file.name)
                if media_path:
                    blob_name = os.path.basename(media_path)
                    blob = bucket.blob(blob_name)
                    blob.upload_from_filename(media_path)
                    
                    # Guess the file type
                    mime_type, _ = mimetypes.guess_type(media_path)
                    blob.content_type = mime_type or "application/octet-stream"

                    media_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
                    fe.enclosure(url=media_url, type=mime_type or "application/octet-stream")
                    
                    os.remove(media_path)
            except Exception as e:
                logger.error(f"Error handling media: {e}")

    # 4) Convert feed to XML
    rss_xml = fg.rss_str(pretty=True)

    # 5) Save to local file
    with open("rss.xml", "wb") as f:
        f.write(rss_xml)

    # 6) Upload the feed to Google Cloud Storage (optional)
    rss_blob = bucket.blob("rss.xml")
    rss_blob.upload_from_string(rss_xml, content_type="application/rss+xml")

    # Disconnect
    await client.disconnect()

async def main():
    await generate_rss()

if __name__ == "__main__":
    asyncio.run(main())
