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

# Load credentials from GitHub Secrets
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
string_session = os.getenv("TELEGRAM_STRING_SESSION")

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# Google Cloud Storage setup
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
storage_client = storage.Client()
bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# Global asyncio event loop
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

async def create_rss():
    if not client.is_connected():
        await client.connect()

    try:
        messages = await client.get_messages('Tsaplienko', limit=1)  # Fetch latest message
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        return None

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    if messages:
        msg = messages[0]
        fe = fg.add_entry()
        fe.title(msg.message[:30] if msg.message else "No Title")
        fe.description(msg.message or "No Content")
        fe.pubDate(msg.date)

        if msg.media:
            try:
                media_path = await msg.download_media(file="./")
                if media_path:
                    blob_name = os.path.basename(media_path)
                    blob = bucket.blob(blob_name)
                    blob.upload_from_filename(media_path)
                    blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'

                    media_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
                    fe.enclosure(url=media_url, type='image/jpeg' if media_url.endswith('.jpg') else 'video/mp4')

                    os.remove(media_path)  # Cleanup local file
            except Exception as e:
                logger.error(f"Error handling media: {e}")

    rss_feed = fg.rss_str(pretty=True)

    # Ensure docs/ folder exists
    os.makedirs("docs", exist_ok=True)
    with open("docs/rss.xml", "wb") as f:
        f.write(rss_feed)

    return rss_feed

@app.route('/rss')
def rss_feed():
    try:
        rss_content = loop.run_until_complete(create_rss())
        if not rss_content:
            return Response("No messages found", status=500)
    except Exception as e:
        logger.error(f"Error generating RSS feed: {e}")
        return Response(f"Error: {str(e)}", status=500)

    return Response(rss_content, mimetype='application/rss+xml')

if __name__ == "__main__":
    loop.run_until_complete(create_rss())  # Run RSS feed update once
