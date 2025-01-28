from telethon import TelegramClient, events
from feedgen.feed import FeedGenerator
import os
from telethon.sessions import StringSession
import logging
from google.cloud import storage

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Telegram API credentials
api_id = 29183291  # Replace with your Telegram API ID
api_hash = '8a7bceeb297d0d36307326a9305b6cd1'  # Replace with your Telegram API Hash
string_session = '1BJWap1wBu2IkVJST3delXpcMTToK14EVXqWRTikMhzzd00RVBv_DHeV9iixc42aRtm2bZEneOEZjNbRulywh5UQ1DZJXb9aDAdGdL5-t_JXe1kWGOJptdBfGpJEkyFoVLndvP0iiBIMfgeg84ALPK4hL-EhFvEzswF6ECfVWv1lbdsPzTWDkb9dx67JMGiC-ryqO93GmQZQnlEx6UzCZ1M5r9oYPDGEPyvfjRvlzSBDRVw9DfJ1L-hVIcQIVIhMnldOK3Rq4XhtRsa3O1GHUD4u_dogAPQppyWvvN0IIYSLqTTseygrFwxjnZceIamCLW3C5BULIYIeOa9gHoyrYiRC0eZd2D1I='  # Replace with your session string

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# Load Google Cloud credentials
credentials_path = r"C:\Users\ernbog\Desktop\makecom-projektas-af582cb15eab.json"  # Path to your JSON credentials
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
storage_client = storage.Client()

# Specify your Google Cloud bucket name
bucket_name = "telegram-media-storage"
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
            blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'

            media_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
            fe.enclosure(url=media_url, type='image/jpeg' if media_url.endswith('.jpg') else 'video/mp4')

            # Clean up local media file
            os.remove(media_path)

    rss_feed = fg.rss_str(pretty=True)

    # Upload RSS feed to Google Cloud
    rss_blob = bucket.blob("rss.xml")
    rss_blob.upload_from_string(rss_feed, content_type="application/rss+xml")
    logger.info("RSS feed updated successfully!")

# Event listener for new messages
@client.on(events.NewMessage(chats="Tsaplienko"))  # Replace with your channel's username
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
