import os
import json
import asyncio
import datetime
from telethon import TelegramClient
from google.cloud import storage
from feedgen.feed import FeedGenerator

# Configurations
API_ID = 'YOUR_API_ID'
API_HASH = 'YOUR_API_HASH'
CHANNEL = 'YOUR_CHANNEL'  # Example: 't.me/channel_name'
BUCKET_NAME = 'telegram-media-storage'
RSS_FILE = 'docs/rss.xml'
LAST_POST_FILE = 'docs/last_post.json'
LOOKBACK_TIME = 7200  # 2 hours in seconds

# Initialize Telegram Client
client = TelegramClient('session', API_ID, API_HASH)

# Initialize Google Cloud Storage
storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)


async def fetch_latest_posts():
    """Fetches the latest Telegram posts within the last LOOKBACK_TIME"""
    async with client:
        now = datetime.datetime.now(datetime.UTC)
        min_time = now - datetime.timedelta(seconds=LOOKBACK_TIME)
        
        # Get last processed post ID
        try:
            with open(LAST_POST_FILE, 'r') as f:
                last_post_data = json.load(f)
                last_post_id = last_post_data.get("id", 0)
        except (FileNotFoundError, json.JSONDecodeError):
            last_post_id = 0

        # Fetch posts
        posts = []
        async for message in client.iter_messages(CHANNEL, min_id=last_post_id):
            if message.date < min_time:
                break  # Ignore very old messages

            if message.text and message.media:
                posts.append(message)

        return posts


async def upload_media_to_gcs(message):
    """Uploads media from a Telegram message to Google Cloud Storage"""
    if not message.media:
        return None

    media_path = await message.download_media()
    if not media_path:
        return None

    file_name = os.path.basename(media_path)
    blob = bucket.blob(file_name)

    # Upload file
    try:
        blob.upload_from_filename(media_path)
        os.remove(media_path)  # Cleanup local file after upload
        return f"https://storage.googleapis.com/{BUCKET_NAME}/{file_name}"
    except Exception as e:
        print(f"ERROR: Failed to upload {file_name} - {str(e)}")
        return None


async def generate_rss(posts):
    """Generates an RSS feed with the latest posts that include media"""
    fg = FeedGenerator()
    fg.title("Latest news")
    fg.link(href="https://www.mandarinai.lt/")
    fg.description("Naujienų kanalą pristato www.mandarinai.lt")
    fg.generator("python-feedgen")
    fg.lastBuildDate(datetime.datetime.utcnow())

    latest_post_id = 0

    for message in posts:
        media_url = await upload_media_to_gcs(message)

        if not media_url:
            continue  # Skip post if media is missing

        fe = fg.add_entry()
        fe.title(message.text.split('\n')[0])  # First line as title
        fe.description(message.text)
        fe.guid(str(message.id), isPermaLink=False)
        fe.pubDate(message.date)

        if media_url:
            if media_url.endswith(".mp4"):
                fe.enclosure(media_url, length="None", type="video/mp4")
            elif media_url.endswith(".jpg") or media_url.endswith(".jpeg"):
                fe.enclosure(media_url, length="None", type="image/jpeg")

        latest_post_id = max(latest_post_id, message.id)

    # Write RSS file only if there are valid posts
    if latest_post_id > 0:
        fg.rss_file(RSS_FILE)

        # Update last post ID
        with open(LAST_POST_FILE, 'w') as f:
            json.dump({"id": latest_post_id}, f)

        print("✅ RSS successfully updated!")
    else:
        print("❌ No valid posts with media found. RSS not updated.")


async def main():
    posts = await fetch_latest_posts()
    if posts:
        await generate_rss(posts)
    else:
        print("❌ No new posts found.")

if __name__ == "__main__":
    asyncio.run(main())