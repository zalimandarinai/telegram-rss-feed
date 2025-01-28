from flask import Flask, Response
from telethon import TelegramClient
from feedgen.feed import FeedGenerator
import os
import asyncio
from telethon.sessions import StringSession
import logging
from waitress import serve
from google.cloud import storage

# Set up logging to help diagnose issues
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Telegram API credentials
api_id = 29183291  # Your Telegram API ID
api_hash = '8a7bceeb297d0d36307326a9305b6cd1'  # Your Telegram API Hash
string_session = '1BJWap1wBu2IkVJST3delXpcMTToK14EVXqWRTikMhzzd00RVBv_DHeV9iixc42aRtm2bZEneOEZjNbRulywh5UQ1DZJXb9aDAdGdL5-t_JXe1kWGOJptdBfGpJEkyFoVLndvP0iiBIMfgeg84ALPK4hL-EhFvEzswF6ECfVWv1lbdsPzTWDkb9dx67JMGiC-ryqO93GmQZQnlEx6UzCZ1M5r9oYPDGEPyvfjRvlzSBDRVw9DfJ1L-hVIcQIVIhMnldOK3Rq4XhtRsa3O1GHUD4u_dogAPQppyWvvN0IIYSLqTTseygrFwxjnZceIamCLW3C5BULIYIeOa9gHoyrYiRC0eZd2D1I='  # Your Telegram session string

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# Load Google Cloud credentials
credentials_path = r"C:\Users\ernbog\Desktop\makecom-projektas-af582cb15eab.json"  # Path to your Google Cloud JSON credentials
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
storage_client = storage.Client()

# Create a global event loop
loop = asyncio.get_event_loop()

# Specify your Google Cloud bucket name
bucket_name = "telegram-media-storage"  # Your Google Cloud Storage bucket name
bucket = storage_client.bucket(bucket_name)

async def create_rss():
    # Ensure the client is connected before proceeding
    if not client.is_connected():
        await client.connect()

    try:
        message = await client.get_messages('Tsaplienko', limit=1)  # Fetch only the latest message
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        return None

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

        # Handle media (photo or video)
        if msg.media:
            try:
                media_path = await msg.download_media(file="./")
                if media_path:
                    logger.info(f"Downloaded media to {media_path}")

                    # Upload media to Google Cloud Storage
                    blob_name = os.path.basename(media_path)
                    blob = bucket.blob(blob_name)
                    blob.upload_from_filename(media_path)
                    blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'
                    logger.info(f"Uploaded media to Google Cloud Storage: {blob_name}")

                    # Get the public URL of the uploaded media
                    media_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
                    logger.info(f"Media URL: {media_url}")

                    # Add media URL to RSS feed
                    fe.enclosure(url=media_url, type='image/jpeg' if media_url.endswith('.jpg') else 'video/mp4')

                    # Optionally delete the local file to save space
                    os.remove(media_path)
                    logger.info(f"Deleted local media file: {media_path}")

            except Exception as e:
                logger.error(f"Error handling media: {e}")

    return fg.rss_str(pretty=True)

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
    port = int(os.getenv("PORT", 10000))
    serve(app, host="0.0.0.0", port=port)
