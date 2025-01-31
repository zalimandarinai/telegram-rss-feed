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
MAX_POSTS = 5  # ✅ RSS visada turės bent 5 postus
MAX_MEDIA_SIZE = 15 * 1024 * 1024  # ✅ 15 MB ribojimas medijos failams

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
    """Užkrauna esamus RSS įrašus ir užtikrina, kad RSS visada turės bent 5 įrašus"""
    if not os.path.exists(RSS_FILE):
        return []

    try:
        tree = ET.parse(RSS_FILE)
        root = tree.getroot()
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else []
        return items[:MAX_POSTS]  # ✅ VISADA PALIEKAME BENT 5 ĮRAŠUS
    except Exception as e:
        logger.error(f"❌ Klaida skaitant RSS failą: {e}")
        return []

async def create_rss():
    await client.connect()
    last_post = load_last_post()

    # ✅ Tikriname paskutinius 5 postus
    messages = await client.get_messages('Tsaplienko', limit=5)
    new_messages = [msg for msg in messages if msg.id > last_post.get("id", 0) and msg.media]

    if not new_messages:
        logger.info("✅ Nėra naujų postų su medija – nutraukiame procesą.")
        exit(0)  # ✅ Taupome „GitHub Actions“ resursus

    logger.info(f"🆕 Rasti {len(new_messages)} nauji postai su medija!")

    # ✅ Užkrauname senus RSS įrašus
    existing_items = load_existing_rss()

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    # ✅ Užtikriname, kad RSS faile būtų bent 5 įrašai su medija
    all_posts = new_messages + existing_items
    all_posts = all_posts[:MAX_POSTS]

    for msg in reversed(all_posts):
        fe = fg.add_entry()

        # ✅ Patikriname, ar tai `Telethon` objektas ar `XML Element`
        if isinstance(msg, ET.Element):
            fe.title(msg.find("title").text if msg.find("title") is not None else "No Title")
            fe.description(msg.find("description").text if msg.find("description") is not None else "No Content")
            fe.pubDate(msg.find("pubDate").text if msg.find("pubDate") is not None else "")
        else:
            # ✅ Dabar naudojame `msg.caption`, jei `msg.message` neegzistuoja
            title_text = (msg.message or msg.caption or "No Title")[:30]
            description_text = msg.message or msg.caption or "No Content"

            fe.title(title_text)
            fe.description(description_text)
            fe.pubDate(msg.date)

            # ✅ Jei yra keli paveikslėliai, pridedame visus
            if msg.media:
                if hasattr(msg.media, "grouped_id"):
                    media_messages = await client.get_messages('Tsaplienko', min_id=msg.id - 5, max_id=msg.id + 5)
                    for media_msg in media_messages:
                        if media_msg.media and media_msg.grouped_id == msg.grouped_id:
                            media_path = await media_msg.download_media(file="./")
                            if media_path and os.path.getsize(media_path) <= MAX_MEDIA_SIZE:
                                blob_name = os.path.basename(media_path)
                                blob = bucket.blob(blob_name)

                                if not blob.exists():
                                    blob.upload_from_filename(media_path)
                                    blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'
                                    logger.info(f"✅ Įkeltas {blob_name} į Google Cloud Storage")

                                fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                                             type='image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4')

                                os.remove(media_path)
                else:
                    media_path = await msg.download_media(file="./")
                    if media_path and os.path.getsize(media_path) <= MAX_MEDIA_SIZE:
                        blob_name = os.path.basename(media_path)
                        blob = bucket.blob(blob_name)

                        if not blob.exists():
                            blob.upload_from_filename(media_path)
                            blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'
                            logger.info(f"✅ Įkeltas {blob_name} į Google Cloud Storage")

                        fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                                     type='image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4')

                        os.remove(media_path)

    save_last_post(new_messages[0].id)

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas sėkmingai!")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
