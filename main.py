import os
import asyncio
import time
from telethon import TelegramClient
from feedgen.feed import FeedGenerator
from telethon.sessions import StringSession

# Telegram API credentials
api_id = 29183291
api_hash = '8a7bceeb297d0d36307326a9305b6cd1'
string_session = 'YOUR_STRING_SESSION'

client = TelegramClient(StringSession(string_session), api_id, api_hash)

async def create_rss():
    cache_file = "rss.xml"
    cache_lifetime = 3600  # 1 hour

    # Check if RSS feed exists and is recent (avoid too many Telegram API calls)
    if os.path.exists(cache_file) and time.time() - os.path.getmtime(cache_file) < cache_lifetime:
        print("Using cached RSS feed.")
        return

    if not client.is_connected():
        await client.connect()

    message = await client.get_messages('Tsaplienko', limit=1)

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    if message:
        msg = message[0]
        fe = fg.add_entry()
        fe.title(msg.message[:30] if msg.message else "No Title")
        fe.description(msg.message or "No Content")
        fe.pubDate(msg.date)

        if msg.media:
            media_url = await client.download_media(msg, file=bytes)  # Use Telegram Direct URL
            fe.enclosure(url=media_url, type='image/jpeg' if media_url.endswith('.jpg') else 'video/mp4')

    rss_content = fg.rss_str(pretty=True)
    with open("rss.xml", "w") as f:
        f.write(rss_content)

    print("Updated RSS feed.")

if __name__ == "__main__":
    asyncio.run(create_rss())
