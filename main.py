import asyncio
import os
import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from feedgen.feed import FeedGenerator
from google.cloud import storage
from google.oauth2 import service_account
from telethon import TelegramClient
from telethon.sessions import StringSession

# ✅ LOGŲ KONFIGŪRACIJA
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ TELEGRAM PRISIJUNGIMO DUOMENYS
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
string_session = os.getenv("TELEGRAM_STRING_SESSION")

client = TelegramClient(StringSession(string_session), api_id, api_hash)

# ✅ GOOGLE CLOUD STORAGE PRISIJUNGIMO DUOMENYS
credentials_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
credentials_dict = json.loads(credentials_json)
credentials = service_account.Credentials.from_service_account_info(credentials_dict)
storage_client = storage.Client(credentials=credentials)
bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# ✅ NUOLATINIAI KONSTANTAI
LAST_POST_FILE = "docs/last_post.json"
RSS_FILE = "docs/rss.xml"
MAX_POSTS = 5  # ✅ RSS faile visada bus 5 naujausi įrašai
TIME_THRESHOLD = 65  # ✅ Tikriname paskutines 65 minutes
MAX_MEDIA_SIZE = 15 * 1024 * 1024  

# ✅ FUNKCIJA: Paskutinio posto ID įkėlimas
def load_last_post():
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    return {"id": 0, "media": []}

# ✅ FUNKCIJA: Esamo RSS duomenų įkėlimas
def load_existing_rss():
    if not os.path.exists(RSS_FILE):
        return []
    
    try:
        tree = ET.parse(RSS_FILE)
        root = tree.getroot()
        channel = root.find("channel")
        return channel.findall("item") if channel else []
    except Exception as e:
        logger.error(f"❌ RSS failas sugadintas, kuriamas naujas: {e}")
        return []

# ✅ FUNKCIJA: Pagrindinis RSS generavimas
async def create_rss():
    await client.connect()

    last_post = load_last_post()
    last_post_id = last_post.get("id", 0)
    last_media_files = set(last_post.get("media", []))

    utc_now = datetime.now(timezone.utc)

    messages = await client.get_messages('Tsaplienko', limit=50)
    valid_messages = []

    for msg in messages:
        msg_date = msg.date.replace(tzinfo=timezone.utc)
        if msg.id <= last_post_id or msg_date < utc_now - timedelta(minutes=TIME_THRESHOLD):
            continue
        if not msg.media:
            continue
        valid_messages.append(msg)

    existing_items = load_existing_rss()

    # ✅ Išsaugome 5 naujausius postus
    for item in existing_items:
        if len(valid_messages) >= MAX_POSTS:
            break
        valid_messages.append(item)

    valid_messages = valid_messages[:MAX_POSTS]

    if not valid_messages:
        logger.warning("⚠️ Nėra naujų įrašų – RSS failas nebus atnaujintas.")
        exit(0)

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    seen_media = set()
    added_entries = 0

    for msg in valid_messages:
        media_path = await msg.download_media(file="./")
        if media_path:
            file_size = os.path.getsize(media_path)
            if file_size > MAX_MEDIA_SIZE:
                os.remove(media_path)
                continue

            blob_name = os.path.basename(media_path)
            blob = bucket.blob(blob_name)

            if blob_name in last_media_files:
                os.remove(media_path)
                continue

            if not blob.exists():
                blob.upload_from_filename(media_path)

            seen_media.add(blob_name)

            fe = fg.add_entry()
            fe.title(msg.message[:30] if msg.message else "No Title")
            fe.description(msg.message if msg.message else "No Content")
            fe.pubDate(msg.date.replace(tzinfo=timezone.utc))

            # ✅ Tinkamas media formatas
            if blob_name.endswith(".jpg") or blob_name.endswith(".jpeg"):
                media_type = "image/jpeg"
            elif blob_name.endswith(".mp4"):
                media_type = "video/mp4"
            else:
                logger.warning(f"⚠️ Nepalaikomas failo formatas {blob_name}, praleidžiama.")
                continue

            fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}", type=media_type)

            added_entries += 1

        if media_path:
            os.remove(media_path)

    if added_entries == 0:
        exit(0)

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    save_last_post({"id": valid_messages[0].id, "media": list(seen_media)})

# ✅ PAGRINDINIS PROCESO PALEIDIMAS
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())