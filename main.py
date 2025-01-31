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

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Telegram API Credentials
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
MAX_POSTS = 5  # ✅ Užtikriname, kad RSS visada turės 5 įrašus su medija
MAX_MEDIA_SIZE = 15 * 1024 * 1024  # ✅ 15 MB ribojimas medijos failams

def load_last_post():
    """Užkrauna paskutinio įrašo ID"""
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    return {"id": 0}

def save_last_post(post_data):
    """Išsaugo paskutinio įrašo ID"""
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump(post_data, f)

def load_existing_rss():
    """Užkrauna esamus RSS įrašus ir užtikrina, kad išsaugoma ne mažiau kaip 5 įrašai."""
    if not os.path.exists(RSS_FILE):
        return []

    try:
        tree = ET.parse(RSS_FILE)
        root = tree.getroot()
        channel = root.find("channel")
        items = channel.findall("item") if channel else []
        return items[:MAX_POSTS]  # ✅ VISADA PALIEKAME BENT 5 ĮRAŠUS
    except Exception as e:
        logger.error(f"❌ Klaida skaitant RSS failą: {e}")
        return []

async def create_rss():
    await client.connect()
    last_post = load_last_post()

    # ✅ Nuskaitome **tik paskutinius 5 postus** (taupome resursus)
    messages = await client.get_messages('Tsaplienko', limit=5)

    # ✅ Filtruojame tik naujus pranešimus su medija
    new_messages = [msg for msg in messages if msg.id > last_post.get("id", 0) and msg.media]

    if not new_messages:
        logger.info("✅ Nėra naujų pranešimų su medija. Nutraukiame RSS atnaujinimą.")
        exit(0)

    # ✅ Užkrauname senus RSS įrašus ir prijungiame naujus
    existing_items = load_existing_rss()

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    # ✅ Užtikriname, kad RSS faile būtų bent 5 įrašai su medija
    all_posts = new_messages + existing_items  # 🔴 SUJUNGIAME NAUJUS IR SENUS POSTUS
    all_posts = all_posts[:MAX_POSTS]  # 🔴 NUPJAUNAME PERTEKLIŲ, BET VISADA IŠLAIKOME 5

    seen_media = set()  # ✅ Sekame jau apdorotus medijos failus, kad išvengtume dublių

    for msg in reversed(all_posts):
        fe = fg.add_entry()

        title_text = msg.message[:30] if msg.message else "No Title"
        description_text = msg.message if msg.message else "No Content"
        fe.title(title_text)
        fe.description(description_text)
        fe.pubDate(msg.date)

        # ✅ Jei postas turi mediją, atsisiunčiame ir įkeliame į Google Cloud Storage
        if msg.media:
            try:
                media_path = await msg.download_media(file="./")
                if media_path and os.path.getsize(media_path) <= MAX_MEDIA_SIZE:
                    blob_name = os.path.basename(media_path)
                    blob = bucket.blob(blob_name)

                    # ✅ Praleidžiame įkėlimą, jei failas jau egzistuoja
                    if not blob.exists():
                        blob.upload_from_filename(media_path)
                        blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'
                        logger.info(f"✅ Įkeltas {blob_name} į Google Cloud Storage")
                    else:
                        logger.info(f"🔄 Skipped upload, {blob_name} already exists")

                    if blob_name not in seen_media:
                        seen_media.add(blob_name)
                        fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                                     type='image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4')

                    os.remove(media_path)  # ✅ Išvalome failą po įkėlimo
                else:
                    logger.info(f"❌ Skipping large media file: {media_path}")
                    os.remove(media_path)
            except Exception as e:
                logger.error(f"❌ Error handling media: {e}")

    # ✅ Išsaugome paskutinio įrašo ID
    save_last_post({"id": new_messages[0].id})

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas sėkmingai!")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
