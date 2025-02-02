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
if not credentials_json:
    raise Exception("❌ Google Cloud kredencialai nerasti!")

credentials_dict = json.loads(credentials_json)
credentials = service_account.Credentials.from_service_account_info(credentials_dict)
storage_client = storage.Client(credentials=credentials)
bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# ✅ NUOLATINIAI KONSTANTAI
LAST_POST_FILE = "docs/last_post.json"
RSS_FILE = "docs/rss.xml"
LAST_UPDATE_FILE = "docs/last_update.json"
MAX_POSTS = 20  
TIME_THRESHOLD = 30  # ✅ Tikriname tik paskutinių 30 minučių postus
MAX_MEDIA_SIZE = 15 * 1024 * 1024  # ✅ Maksimalus medijos dydis - 15MB

# ✅ FUNKCIJA: Paskutinio posto ID įkėlimas
def load_last_post():
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    return {"id": 0}

# ✅ FUNKCIJA: Paskutinio posto ID įrašymas
def save_last_post(post_data):
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump(post_data, f)

# ✅ FUNKCIJA: Pagrindinis RSS generavimas
async def create_rss():
    await client.connect()

    last_post = load_last_post()
    last_post_id = last_post.get("id", 0)

    # ✅ Užtikriname, kad `utc_now` yra offset-aware
    utc_now = datetime.now(timezone.utc)

    # ✅ Gauname naujausius Telegram postus
    messages = await client.get_messages('Tsaplienko', limit=50)

    valid_messages = []
    for msg in messages:
        msg_date = msg.date.replace(tzinfo=timezone.utc)  # ✅ Užtikriname, kad `msg.date` yra offset-aware
        if msg.id > last_post_id and msg_date >= utc_now - timedelta(minutes=TIME_THRESHOLD) and msg.media:
            valid_messages.append(msg)

    if not valid_messages:
        logger.warning("⚠️ Nėra naujų Telegram postų su medija per paskutines 30 min.")
        exit(0)

    logger.info(f"✅ Rasta {len(valid_messages)} naujų postų su medija.")

    # ✅ RSS generavimas
    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    seen_media = set()
    added_entries = 0

    for msg in valid_messages:
        media_path = None
        blob_name = None

        try:
            media_path = await msg.download_media(file="./")
            if media_path:
                file_size = os.path.getsize(media_path)
                if file_size > MAX_MEDIA_SIZE:
                    logger.warning(f"⚠️ Failas {media_path} per didelis ({file_size} B), praleidžiamas.")
                    os.remove(media_path)
                    continue  # ❌ NEĮTRAUKTI Į RSS

                blob_name = os.path.basename(media_path)
                blob = bucket.blob(blob_name)

                if not blob.exists():
                    blob.upload_from_filename(media_path)
                    logger.info(f"✅ Įkeltas {blob_name} į Google Cloud Storage")

                seen_media.add(blob_name)

                # ✅ Tik dabar pridedame įrašą į RSS
                fe = fg.add_entry()
                fe.title(msg.message[:30] if msg.message else "No Title")
                fe.description(msg.message if msg.message else "No Content")
                fe.pubDate(msg.date.replace(tzinfo=timezone.utc))  # ✅ Užtikriname, kad `pubDate` yra UTC
                fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}", type='image/jpeg')

                added_entries += 1
                logger.info(f"📌 Į RSS įtrauktas postas su media: {blob_name}")

            if media_path:
                os.remove(media_path)  # ✅ Ištriname laikiną failą
        except Exception as e:
            logger.error(f"❌ Klaida apdorojant media: {e}")
            if media_path:
                os.remove(media_path)  # ✅ Ištriname failą, jei nepavyko apdoroti

    # ✅ Jei nebuvo nė vieno sėkmingo įrašo su medija, nestatome RSS failo
    if added_entries == 0:
        logger.warning("⚠️ Visi postai buvo atmesti – RSS nebus atnaujintas.")
        exit(0)

    # ✅ Išsaugome naują RSS failą
    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    save_last_post({"id": valid_messages[0].id})
    logger.info("✅ RSS failas sėkmingai atnaujintas!")

# ✅ PAGRINDINIS PROCESO PALEIDIMAS
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())