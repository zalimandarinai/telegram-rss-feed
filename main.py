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
api_id = 29183291  # Replace with your Telegram API ID
api_hash = '8a7bceeb297d0d36307326a9305b6cd1'  # Replace with your Telegram API Hash
string_session = '1BJWap1wBu4OMUn0rmXj8rIgX31eZKc1AUgx0NKN9kIHzHg8RAzvLjcx8TnR18ORikTOtqwC2oc1wMCsORasoEsjtF5KunmZaeRDrJjJDIA47CpOOihYZCzUC50yj9bXP5t7Sqxate4VTCR7oAz_SkftL7GvndjYfxbz9emGTbwTjM-4OpicD0GfpoyKi9IFjg9l4wA0L2OoXjIdwFlVPeh6b3ZgUjzpaev8QLk26b6FpuJeyX2XDMAUnmyu9wK55HO0mdvQBR9DAR9OTDhKw9hQ-kexoZVGuELLVTFETw8gyF64AhcgNHBP_l7OUEqU_7G38FTsI7QElTeBIGCWEwzpAPSTkMqQ='  # Replace with the valid session string

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# Load Google Cloud credentials
credentials_path = "/etc/secrets/makecom-projektas-8a72ca1be499.json"  # Your Google Cloud JSON credentials path
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
storage_client = storage.Client()

# Create a global event loop
loop = asyncio.get_event_loop()

# Specify your Google Cloud bucket name
bucket_name = "telegram-media-storage"
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
