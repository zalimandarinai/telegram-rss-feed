import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from telethon import TelegramClient
from feedgen.feed import FeedGenerator

# Load API credentials exactly as in the original code
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    raise ValueError("API_ID or API_HASH is missing. Please check your environment variables.")

API_ID = int(API_ID)  # Convert to integer only after checking
client = TelegramClient('session', API_ID, API_HASH)

# Constants
CHANNEL_USERNAME = 'your_channel'
LOOKBACK_TIME = 2 * 60 * 60  # Last 2 hours
RSS_FILE = "docs/rss.xml"
LAST_POST_FILE = "docs/last_post.json"

async def fetch_latest_posts():
    """Fetch the latest posts from the Telegram channel."""
    async with client:
        now = datetime.utcnow()
        min_time = now - timedelta(seconds=LOOKBACK_TIME)
        
        try:
            with open(LAST_POST_FILE, "r") as file:
                last_post_data = json.load(file)
                last_post_id = last_post_data.get("id", 0)
        except (FileNotFoundError, json.JSONDecodeError):
            last_post_id = 0  # Default to zero if file not found or corrupted

        posts = []
        async for message in client.iter_messages(CHANNEL_USERNAME, min_id=last_post_id):
            if message.date < min_time:
                break  # Stop if the message is older than the lookback window
            
            if message.text and message.media:
                posts.append(message)

        return posts[::-1]  # Return in chronological order

async def generate_rss():
    """Generate an RSS feed from Telegram posts."""
    posts = await fetch_latest_posts()
    if not posts:
        logging.info("❌ No new posts — RSS will not be updated.")
        return

    fg = FeedGenerator()
    fg.title("Latest news")
    fg.link(href="https://www.mandarinai.lt/")
    fg.description("Naujienų kanalą pristato www.mandarinai.lt")
    fg.lastBuildDate(datetime.utcnow())

    last_post_id = 0
    for post in posts:
        fe = fg.add_entry()
        fe.title(post.text.split('\n')[0] if post.text else "No title")
        fe.description(post.text if post.text else "No description")
        fe.guid(str(post.id), permalink=False)
        fe.pubDate(post.date)

        if post.media:
            media_url = f"https://storage.googleapis.com/telegram-media-storage/{post.media.document.attributes[0].file_name}"
            fe.enclosure(media_url, length="None", type="video/mp4" if 'mp4' in media_url else "image/jpeg")

        last_post_id = max(last_post_id, post.id)

    fg.rss_file(RSS_FILE)

    with open(LAST_POST_FILE, "w") as file:
        json.dump({"id": last_post_id}, file)

    logging.info("✅ RSS successfully updated!")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(generate_rss())