import os
import json
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from feedgen.feed import FeedGenerator
import logging
import xml.etree.ElementTree as ET
from google.cloud import storage
from google.oauth2 import service_account

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Telegram API prisijungimo duomenys
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
string_session = os.getenv("TELEGRAM_STRING_SESSION")

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# Google Cloud nustatymai
credentials_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
credentials_dict = json.loads(credentials_json)
credentials = service_account.Credentials.from_service_account_info(credentials_dict)

storage_client = storage.Client(credentials=credentials)
bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# Failai
LAST_POST_FILE = "docs/last_post.json"
RSS_FILE = "docs/rss.xml"
MAX_POSTS = 5
MAX_MEDIA_SIZE = 15 * 1024 * 1024  # 15MB limit per failą

def load_last_post():
    """Užkrauna paskutinio įrašo ID"""
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    return {"id": 0}

def save_last_post(post_id):
    """Išsaugo paskutinio įrašo ID"""
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump({"id": post_id}, f)
    logger.info(f"✅ Naujas `last_post.json`: {post_id}")

def load_existing_rss():
    """Užkrauna esamus RSS įrašus"""
    if not os.path.exists(RSS_FILE):
        return []

    try:
        tree = ET.parse(RSS_FILE)
        root = tree.getroot()
        channel = root.find("channel")
        items = channel.findall("item") if channel else []
        return items[:MAX_POSTS]
    except Exception as e:
        logger.error(f"❌ Klaida skaitant RSS failą: {e}")
        return []

async def create_rss():
    await client.connect()
    last_post = load_last_post()

    # Tikriname paskutinius 5 postus
    messages = await client.get_messages('Tsaplienko', limit=5)
    new_messages = [msg for msg in messages if msg.id > last_post.get("id", 0) and msg.media]

    if not new_messages:
        logger.info("✅ Nėra naujų postų su medija – nutraukiame procesą.")
        exit(0)

    logger.info(f"🆕 Rasti {len(new_messages)} nauji postai su medija!")

    # Užkrauname senus RSS įrašus
    existing_items = load_existing_rss()

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    all_posts = new_messages + existing_items
    all_posts = all_posts[:MAX_POSTS]

    processed_media = set()
    grouped_texts = {}

    valid_posts = []  # Laikinas sąrašas, kuriame filtruosime postus su tekstu ir medija

    for msg in reversed(all_posts):
        # Tikriname, ar tai albumas
        if hasattr(msg.media, "grouped_id") and msg.grouped_id:
            if msg.grouped_id not in grouped_texts:
                grouped_texts[msg.grouped_id] = msg.message or getattr(msg, "caption", None) or "No Content"
            text = grouped_texts[msg.grouped_id]
        else:
            text = msg.message or getattr(msg, "caption", None) or "No Content"

        # Praleidžiame postus be teksto
        if text == "No Content":
            logger.warning(f"⚠️ Praleidžiamas postas {msg.id}, nes neturi teksto")
            continue

        # Pridedame tik tuos, kurie turi tiek tekstą, tiek mediją
        valid_posts.append((msg, text))

    for msg, text in valid_posts:
        fe = fg.add_entry()

        title_text = text[:30] if text != "No Content" else "No Title"
        fe.title(title_text)
        fe.description(text)
        fe.pubDate(msg.date)

        # Tikriname, ar žinutėje yra medija
        if msg.media:
            try:
                media_path = await msg.download_media(file="./")
                if media_path and os.path.getsize(media_path) <= MAX_MEDIA_SIZE:
                    blob_name = os.path.basename(media_path)
                    blob = bucket.blob(blob_name)

                    if blob_name not in processed_media:
                        if not blob.exists():
                            blob.upload_from_filename(media_path)
                            blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'
                            logger.info(f"✅ Įkėlėme {blob_name} į Google Cloud Storage")

                        fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                                     type='image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4')

                        processed_media.add(blob_name)

                    os.remove(media_path)

            except Exception as e:
                logger.error(f"❌ Klaida apdorojant mediją: {e}")

    save_last_post(new_messages[0].id)

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas sėkmingai!")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
