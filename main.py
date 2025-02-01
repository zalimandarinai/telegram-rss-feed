import os
import json
import datetime
from telethon.sync import TelegramClient
from google.cloud import storage
from feedgen.feed import FeedGenerator

# Load API credentials securely
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = "session"

# Configure Google Cloud Storage
BUCKET_NAME = "telegram-media-storage"

# Define constants
RSS_FILE = "docs/rss.xml"
LAST_POST_FILE = "docs/last_post.json"
LOOKBACK_TIME = 7200  # 2 hours in seconds

# Initialize Telegram client
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

def load_last_post_id():
    """Load the last processed post ID from file."""
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as file:
            data = json.load(file)
            return data.get("id", 0)
    return 0

def save_last_post_id(post_id):
    """Save the last processed post ID to file."""
    with open(LAST_POST_FILE, "w") as file:
        json.dump({"id": post_id}, file)

def upload_to_gcs(local_path, gcs_path):
    """Upload file to Google Cloud Storage."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(gcs_path)
    blob.upload_from_filename(local_path)
    return f"https://storage.googleapis.com/{BUCKET_NAME}/{gcs_path}"

def fetch_latest_posts():
    """Fetch the latest posts from Telegram."""
    last_post_id = load_last_post_id()
    new_posts = []

    with client:
        for message in client.iter_messages("your_telegram_channel", limit=20):
            if message.id <= last_post_id:
                break  # Stop processing old posts

            if message.date.timestamp() < datetime.datetime.utcnow().timestamp() - LOOKBACK_TIME:
                continue  # Ignore posts older than 2 hours

            if message.text and (message.photo or message.video or message.document):
                new_posts.append(message)

    return new_posts

def process_media(message):
    """Download and upload media files."""
    if message.photo:
        file_path = client.download_media(message.photo)
        return upload_to_gcs(file_path, os.path.basename(file_path))

    if message.video:
        file_path = client.download_media(message.video)
        return upload_to_gcs(file_path, os.path.basename(file_path))

    if message.document:
        file_path = client.download_media(message.document)
        return upload_to_gcs(file_path, os.path.basename(file_path))

    return None  # No media found

def generate_rss(posts):
    """Generate the RSS feed."""
    fg = FeedGenerator()
    fg.title("Latest news")
    fg.link(href="https://www.mandarinai.lt/")
    fg.description("Naujienų kanalą pristato www.mandarinai.lt")
    fg.generator("python-feedgen")
    fg.lastBuildDate(datetime.datetime.utcnow())

    for post in posts:
        fe = fg.add_entry()
        fe.title(post.text[:75] + "..." if len(post.text) > 75 else post.text)
        fe.description(post.text)
        fe.guid(str(post.id), permalink=False)
        fe.pubDate(post.date)

        media_url = process_media(post)
        if media_url:
            media_type = "image/jpeg" if media_url.endswith(".jpg") else "video/mp4"
            fe.enclosure(media_url, length="None", type=media_type)

    fg.rss_file(RSS_FILE)

def main():
    """Main execution function."""
    print("Fetching latest posts...")
    posts = fetch_latest_posts()

    if not posts:
        print("No new posts found, RSS will not be updated.")
        return

    print("Generating RSS feed...")
    generate_rss(posts)

    latest_post_id = max(post.id for post in posts)
    save_last_post_id(latest_post_id)
    print("RSS successfully updated!")

if __name__ == "__main__":
    main()