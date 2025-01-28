import os
import asyncio
import time
from telethon import TelegramClient
from feedgen.feed import FeedGenerator
from telethon.sessions import StringSession

# Telegram API credentials (Use your own values)
api_id = 29183291
api_hash = '8a7bceeb297d0d36307326a9305b6cd1'
string_session = 'YOUR_STRING_SESSION'  # Replace with your actual session string

client = TelegramClient(StringSession(string_session), api_id, api_hash)

async def create_rss():
    cache_file = "docs/rss.xml"  # Save inside the "docs" folder
    cache_lifetime = 3600  # Update every 1 hour

    # Check if RSS file exists and is fresh
    if os.path.exists(cache_file) and time.time() - os.path.getmtime(cache_file) < cache_lifetime:
        print("Using cached RSS feed.")
        return

    # Connect to Telegram
    if not client.is_connected():
        await client.connect()

    # Fetch the latest messages from the Telegram channel
    messages = await client.get_messages('Tsaplienko', limit=5)  # Get last 5 messages

    # Create RSS feed
    fg = FeedGenerator()
    fg.title('Telegram News')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Latest updates from Telegram')

    for msg in messages:
        fe = fg.add_entry()
        fe.title(msg.message[:30] if msg.message else "No Title")
        fe.description(msg.message or "No Content")
        fe.pubDate(msg.date)

        # If media is present, add it to the feed
        if msg.media:
            media_url = await client.download_media(msg, file=bytes)  # Use Telegram's direct URL
            fe.enclosure(url=media_url, type='image/jpeg' if media_url.endswith('.jpg') else 'video/mp4')

    # Save RSS feed to the "docs" folder
    rss_content = fg.rss_str(pretty=True)
    w
