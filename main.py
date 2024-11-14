from flask import Flask, Response
from telethon import TelegramClient
from feedgen.feed import FeedGenerator
import os
import asyncio
from telethon.sessions import StringSession
import logging
from waitress import serve
from google.cloud import storage
import threading

# Set up logging to help diagnose issues
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Telegram API credentials
api_id = 29183291
api_hash = '8a7bceeb297d0d36307326a9305b6cd1'
string_session = '1BJWap1wBu7NUCDPv4i2I2ClI_ilTvfiNJXz2uEIFG1qdDiRM6rsoXjsaSzrqLiHotj3T898WUvh0CZBwkSqlrnXz9IjlULk_6sUaFOFkZXd3Kb_LL-SfI6V_cSL-YC0mlzDoeXx9BaT8dVKWL4WmadnlFKvb_I4Cvlrrm_TiZgdZEXTrS84X-3H_rXb0wZBRRz6mO2swgz7eI6YNL0KsOqy9VdtZv2HbTlxwNoSji19VrjTY3RNnmq1nyR9wQ-zO5ICZPq3uZCcJ-JF7dSvvbAjWyIVsEWvK8OAFj4EQu1pqlrXRqyeWMfF2lMxz7GREdItGMF7EIChleFC4iNXKEfX8F3dPf-I='

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# Load Google Cloud credentials
credentials_path = "/etc/secrets/makecom-projektas-8a72ca1be499.json"
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
storage_client = storage.Client()

bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# Create a global event loop
loop = asyncio.get_event_loop()

@app.route('/rss')
def rss_feed():
    try:
        # Generate the RSS feed using the latest message info
        rss_content = loop.run_until_complete(generate_rss())
    except Exception as e:
        logger.error(f"Error generating RSS feed: {e}")
        return Response(f"Error: {str(e)}", status=500)
    return Response(rss_content, mimetype='application/rss+xml')

async def generate_rss():
    if not client.is_connected():
        await client.connect()

    try:
        message = await client.get_messages('Tsaplienko', limit=1)
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        raise

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

        # Check if media is available, and handle it asynchronously in the background
        if msg.media:
            threading.Thread(target=download_and_upload_media, args=(msg,)).start()

    return fg.rss_str(pretty=True)

def download_and_upload_media(msg):
    """Download media files and upload them to Google Cloud Storage."""
    media_urls = []
    try:
        media_path = loop.run_until_complete(msg.download_media(file="./"))
        if media_path:
            logger.info(f"Downloaded media to {media_path}")

            # Upload media to Google Cloud Storage
            blob_name = os.path.basename(media_path)
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(media_path)
            blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'
            logger.info(f"Uploaded media to Google Cloud Storage: {blob_name}")

            # Construct media URL and store it for later use
            media_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
            media_urls.append(media_url)
            logger.info(f"Media URL: {media_url}")

            # Optionally delete the local file to save space
            os.remove(media_path)
            logger.info(f"Deleted local media file: {media_path}")

    except Exception as e:
        logger.error(f"Error handling media: {e}")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    serve(app, host="0.0.0.0", port=port)
