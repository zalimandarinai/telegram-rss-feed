from flask import Flask, Response
from telethon import TelegramClient
from feedgen.feed import FeedGenerator
import os
import asyncio
from telethon.sessions import StringSession
import logging
from waitress import serve
from google.cloud import storage  # New Import for Google Cloud Storage
import json

# Set up logging to help diagnose issues
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Telegram API credentials
api_id = 29183291  # Provided API ID
api_hash = '8a7bceeb297d0d36307326a9305b6cd1'  # Provided API Hash
string_session = '1BJWap1wBu7NUCDPv4i2I2ClI_ilTvfiNJXz2uEIFG1qdDiRM6rsoXjsaSzrqLiHotj3T898WUvh0CZBwkSqlrnXz9IjlULk_6sUaFOFkZXd3Kb_LL-SfI6V_cSL-YC0mlzDoeXx9BaT8dVKWL4WmadnlFKvb_I4Cvlrrm_TiZgdZEXTrS84X-3H_rXb0wZBRRz6mO2swgz7eI6YNL0KsOqy9VdtZv2HbTlxwNoSji19VrjTY3RNnmq1nyR9wQ-zO5ICZPq3uZCcJ-JF7dSvvbAjWyIVsEWvK8OAFj4EQu1pqlrXRqyeWMfF2lMxz7GREdItGMF7EIChleFC4iNXKEfX8F3dPf-I='  # Your generated String Session

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# Load Google Cloud credentials
credentials_path = "/etc/secrets/makecom-projektas-8a72ca1be499.json"  # Path to your JSON credentials file
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
storage_client = storage.Client()

# Create a global event loop
loop = asyncio.get_event_loop()

# Specify your bucket name here
bucket_name = "telegram-media-storage"  # Updated bucket name to match the screenshot
bucket = storage_client.bucket(bucket_name)

async def create_rss():
    # Ensure the client is connected before proceeding
    if not client.is_connected():
        await client.connect()
    
    try:
        messages = await client.get_messages('Tsaplienko', limit=10)  # Replace 'Tsaplienko' with your channel username
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        raise

    fg = FeedGenerator()
    fg.title('Tsaplienko Telegram Channel RSS Feed')
    fg.link(href=f'https://t.me/Tsaplienko')  # Update to your channel link
    fg.description('RSS feed from Tsaplienko Telegram Channel')

    for msg in messages:
        fe = fg.add_entry()
        fe.title(msg.message[:30] if msg.message else "No Title")
        fe.link(href=f'https://t.me/Tsaplienko/{msg.id}')  # Update to your channel link
        fe.description(msg.message or "No Content")
        fe.pubDate(msg.date)

        # Check if the message has media (photo or video)
        if msg.media:
            try:
                # Download media to a temporary file
                media_path = await msg.download_media()
                logger.info(f"Downloaded media to {media_path}")

                # Upload media to Google Cloud Storage
                blob_name = os.path.basename(media_path)
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(media_path)
                blob.content_type = 'image/jpeg' if hasattr(msg, 'photo') else 'video/mp4'
                logger.info(f"Uploaded media to Google Cloud Storage: {blob_name}")

                # Get the public URL of the uploaded media
                media_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
                logger.info(f"Media URL: {media_url}")

                # Add media as an enclosure
                if hasattr(msg, 'photo') and msg.photo:
                    fe.enclosure(url=media_url, type='image/jpeg')
                elif hasattr(msg, 'video') and msg.video:
                    fe.enclosure(url=media_url, type='video/mp4')

                # Optionally delete the local file to save space
                os.remove(media_path)
                logger.info(f"Deleted local media file: {media_path}")

            except Exception as e:
                logger.error(f"Error handling media: {e}")

    return fg.rss_str(pretty=True)

@app.route('/rss')
def rss_feed():
    try:
        # Use the global event loop to handle the async function properly
        rss_content = loop.run_until_complete(create_rss())
    except Exception as e:
        logger.error(f"Error generating RSS feed: {e}")
        return Response(f"Error: {str(e)}", status=500)
    return Response(rss_content, mimetype='application/rss+xml')

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    serve(app, host="0.0.0.0", port=port)
