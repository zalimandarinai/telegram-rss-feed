import os
import asyncio
import time
from telethon import TelegramClient
from feedgen.feed import FeedGenerator
from telethon.sessions import StringSession

# Telegram API credentials
api_id = 29183291  # Replace with your actual API ID
api_hash = '8a7bceeb297d0d36307326a9305b6cd1'  # Replace with your actual API Hash
string_session = '1BJWap1wBuz3ak_NtApiKl74VO_Ta8yRY_iCLmZCHOB0MpeScP...'  # Replace with your new session string

client = TelegramClient(StringSession(string_session), api_id, api_hash)

async def create_rss():
    cache_file = "docs/rss.xml"  # Save RSS file inside the "docs" folder for GitHub Pages
    cache_lifetime = 3600  # Update every hour

    # Check if RSS file exists and is recent
    if os.path.exists(cache_file) and time.time() - os.path.getmtime(cache_file) < cache_lifetime:
        print("Using cached RSS feed.")
        return

    # Connect to Telegram
    if not client.is_connected():
        await client.connect()

    # Fetch the latest messages from the Telegram channel
    messages = await client.get_messages('Tsaplienko', limit=5)  # Replace 'Tsaplienko' with your channel name

    if not messages:
        print("❌ ERROR: No messages retrieved. Check your channel name.")
        return

    print(f"✅ Fetched {len(messages)} messages.")

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

        # If the message has media, include it in the RSS feed
        if msg.media:
            media_url = await client.download_media(msg, file=bytes)  # Use Telegram's direct URL
            fe.enclosure(url=media_url, type='image/jpeg' if media_url.endswith('.jpg') else 'video/mp4')

    # Save the RSS feed to the "docs" folder
    rss_content = fg.rss_str(pretty=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write(rss_content)

    print("✅ RSS feed updated successfully!")

if __name__ == "__main__":
    asyncio.run(create_rss())
