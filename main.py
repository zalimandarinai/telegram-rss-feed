from flask import Flask, Response
from telethon import TelegramClient
from feedgen.feed import FeedGenerator
import os
import asyncio
from telethon.sessions import StringSession
import logging
from waitress import serve
from google.cloud import storage

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Telegram API credentials
api_id = 29183291  # Replace with your API ID
api_hash = '8a7bceeb297d0d36307326a9305b6cd1'  # Replace with your API Hash
string_session = '1BJWap1wBuxkXG6GdvO3XxDAYnJXExG88btWa8PiAyCPQK5YfWj8xrnPqer9Te0cRJDIV-O06ZOTpCqSp6q7cV2fgin52J-GlXazhw-EuSpLkMp6_9P9p0DjpcMi21md9jQUDsiN0O_cXmExIKG-d-iWGesG-Sjy_rFpI1R-UaDiymDHbTINpHFtfnoN0KjuW7X0Hm3LiL0lV3zJk6wd5w_HO4un_CFI6c2FwYU6P66kDdK4n1LowUyuQh5_9f-uerGCGH7mzwWhGdobREcZY_fvIIBI7wcR0NvUpMG6KUSmTKnklNTm3EAs-MKmAvQRx3N5Kzn4xIp3FDWrYWLkfHeZ_Yqy2QyE='  # Replace with your updated session string

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# Google Cloud credentials
credentials_path = "/etc/secrets/makecom-projektas-8a72ca1be499.json"  # Ensure this file exists
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
storage_client = storage.Client()
bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# Async function to fetch Telegram messages and create RSS feed
async def create_rss():
    if not client.is_connected():
        await client.connect()
    
    try:
        messages = await client.get_messages('Tsaplienko', limit=5)
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        return None

    fg = FeedGenerator()
    fg.title('Latest Telegram News')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    for msg in messages:
        fe = fg.add_entry()
        fe.title(msg.message[:30] if msg.message else "No Title")
        fe.description(msg.message or "No Content")
        fe.pubDate(msg.date)

    rss_content = fg.rss_str(pretty=True)

    with open("docs/rss.xml", "wb") as f:
        f.write(rss_content)

    return rss_content

@app.route('/rss')
def rss_feed():
    try:
        rss_content = asyncio.run(create_rss())
    except Exception as e:
        logger.error(f"Error generating RSS feed: {e}")
        return Response(f"Error: {str(e)}", status=500)
    return Response(rss_content, mimetype='application/rss+xml')

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    serve(app, host="0.0.0.0", port=port)
