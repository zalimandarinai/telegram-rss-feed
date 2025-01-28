from telethon import TelegramClient, events
from feedgen.feed import FeedGenerator
import os
from telethon.sessions import StringSession
import logging
from google.cloud import storage

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 1) Load Telegram API credentials from environment variables
#    Fall back to default/testing values if desired, or raise an error if missing.
try:
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    string_session = os.environ["TELEGRAM_STRING_SESSION"]
except KeyError as e:
    raise RuntimeError(f"Missing required environment variable: {e}")

# 2) Initialize Telethon client
client = TelegramClient(StringSession(string_session), api_id, api_hash)

# 3) Load Google Cloud credentials
#    The google.cloud SDK automatically picks up the file set in GOOGLE_APPLICATION_CREDENTIALS.
#    Example: GOOGLE_APPLICATION_CREDENTIALS=/home/runner/work/repo/gcp_credentials.json
storage_client = storage.Client()

# 4) Specify your Google Cloud bucket name (or use a default if not set)
bucket_name = os.environ.get("GCS_BUCKET_NAME", "telegram-media-storage")
bucket = storage_client.bucket(bucket_name)

# Function to generate RSS feed
async def generate_rss(message):
    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    fe = fg.add_entry()
    fe.title(message.message[:30] if message.message else "No Title")
    fe.description(message.message or "No Content")
    fe.pubDate(message.date)

    # Handle media
    if message.media:
        media_path = await message.download_media(file="./")
        if media_path:
            blob_name = os.path.basename(media_path)
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(media_path)

            # Rudimentary MIME determination
            if media_path.endswith(('.jpg', '.jpeg')):
                blob.content_type = 'image/jpeg'
                enclosure_type = 'image/jpeg'
            elif media_path.endswith('.mp4'):
                blob.content_type = 'video/mp4'
                enclosure_type = 'video/mp4'
            else:
                # Fallback if more file types are involved
                blob.content_type = 'application/octet-stream'
                enclosure_type = 'application/octet-stream'

            media_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
            fe.enclosure(url=media_url, type=enclosure_type)

            # Clean up local media file
            os.remove(media_path)

    rss_feed = fg.rss_str(pretty=True)

    # Upload RSS feed to Google Cloud
    rss_blob = bucket.blob("rss.xml")
    rss_blob.upload_from_string(rss_feed, content_type="application/rss+xml")
    logger.info("RSS feed updated successfully!")

# Event listener for new messages
@client.on(events.NewMessage(chats="Tsaplienko"))  # Replace with your channel's username (or channel ID)
async def new_message_handler(event):
    logger.info(f"New message detected: {event.message.message}")
    await generate_rss(event.message)

# Start the client
async def main():
    await client.start()
    logger.info("Listening for new Telegram messages...")
    await client.run_until_disconnected()

# Run the event loop
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
