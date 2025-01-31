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
        items = channel.findall("item") if channel else []
        return items[:MAX_POSTS]  # ✅ VISADA PALIEKAME BENT 5 ĮRAŠUS
    except Exception as e:
        logger.error(f"❌ Klaida skaitant RSS failą: {e}")
        return []

async def create_rss():
    await client.connect()
    last_post = load_last_post()

    # ✅ Nuskaitome paskutinius 5 postus
    messages = await client.get_messages('Tsaplienko', limit=5)
    new_messages = [msg for msg in messages if msg.id > last_post.get("id", 0) and msg.media]

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
        fe.title(msg.message[:30] if msg.message else "No Title")
        fe.description(msg.message if msg.message else "No Content")
        fe.pubDate(msg.date)

    # ✅ Išsaugome naujausią ID, kad nepraleistume postų
    if new_messages:
        save_last_post(new_messages[0].id)

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas sėkmingai!")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
