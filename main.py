import asyncio
from telethon import TelegramClient
import os
import json
from feedgen.feed import FeedGenerator
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Telegram API Credentials
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH"))
string_session = os.getenv("TELEGRAM_STRING_SESSION")

client = TelegramClient("session_name", api_id, api_hash)

LAST_POST_FILE = "docs/last_post.json"

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

async def create_rss():
    await client.connect()
    last_post = load_last_post()

    # Fetch the latest 5 messages
    messages = await client.get_messages('Tsaplienko', limit=5)

    # Filter only new messages with media
    new_messages = [msg for msg in messages if msg.id > last_post.get("id", 0) and msg.media]
    
    if not new_messages:
        logger.info("No new Telegram posts with media. Exiting early.")
        exit(1)  # Stop script to save GitHub minutes

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    for msg in reversed(new_messages):  # Process older messages first
        fe = fg.add_entry()
        fe.title("Media Post")  # Generic title since text is ignored
        fe.pubDate(msg.date)

        if msg.media:
            try:
                # Download media
                media_path = await msg.download_media(file="./")
                if media_path and os.path.getsize(media_path) <= 15 * 1024 * 1024:  # ≤15MB
                    blob_name = os.path.basename(media_path)
                    fe.enclosure(url=f"https://storage.googleapis.com/telegram-media-storage/{blob_name}", 
                                 type='image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4')

                    os.remove(media_path)  # Cleanup
                else:
                    logger.info(f"Skipping large media file: {media_path}")
                    os.remove(media_path)
            except Exception as e:
                logger.error(f"Error handling media: {e}")

    # Save the latest processed message ID
    save_last_post({"id": new_messages[0].id})

    with open("docs/rss.xml", "wb") as f:
        f.write(fg.rss_str(pretty=True))

    return "RSS Updated"

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
