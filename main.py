import asyncio
import os
import json
import logging
import xml.etree.ElementTree as ET
from feedgen.feed import FeedGenerator
from google.cloud import storage
from google.oauth2 import service_account
from telethon import TelegramClient
from telethon.sessions import StringSession

# ✅ LOGŲ KONFIGŪRACIJA
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ TELEGRAM PRISIJUNGIMO DUOMENYS (gaunami iš aplinkos kintamųjų)
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
MAX_POSTS = 5  # RSS faile visada turi būti 5 paskutiniai postai
MAX_MEDIA_SIZE = 15 * 1024 * 1024  # Maksimalus medijos dydis – 15MB

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

# ✅ FUNKCIJA: Esamo RSS failo duomenų įkėlimas
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

# ✅ FUNKCIJA: RSS generacija
async def create_rss():
    await client.connect()
    last_post = load_last_post()
    
    # Gauname tik 5 paskutinių žinučių pagal datą (naujausi pirmiau)
    messages = await client.get_messages('Tsaplienko', limit=5)

    # Albumų tekstų sekimas – jei postai priklauso vienam albumui, visi naudoja tą patį tekstą
    grouped_texts = {}

    valid_posts = []  # Saugosime tik postus, kurie turi tiek tekstą, tiek medijos failą

    for msg in messages:
        # Patikriname, ar postas turi tekstą (message arba caption)
        text = msg.message or getattr(msg, "caption", None)
        if not text:
            logger.warning(f"⚠️ Praleidžiamas postas {msg.id}, nes neturi teksto (title/description)")
            continue

        # Patikriname, ar postas turi medijos failą
        if not msg.media:
            logger.warning(f"⚠️ Praleidžiamas postas {msg.id}, nes neturi medijos failo")
            continue

        # Jei postas priklauso albumui, užtikriname, kad visi naudotų tą patį tekstą
        if hasattr(msg.media, "grouped_id") and msg.media.grouped_id:
            if msg.media.grouped_id not in grouped_texts:
                grouped_texts[msg.media.grouped_id] = text
            else:
                text = grouped_texts[msg.media.grouped_id]

        valid_posts.append((msg, text))

    # Jei naujų validių postų nerasta, RSS faile išlaikome senus įrašus
    if not valid_posts:
        logger.info("Naujų validių postų nerasta, RSS liks nepakitęs.")
        return

    # Jei validų postų yra mažiau nei 5, papildomai pridedame senesnius įrašus iš esamo RSS
    if len(valid_posts) < MAX_POSTS:
        existing_items = load_existing_rss()
        additional_needed = MAX_POSTS - len(valid_posts)
        for item in existing_items[:additional_needed]:
            # Sukuriame „fake“ post objektą – pritaikyti pagal duomenų formatą
            fake_msg = type("FakeMsg", (object,), {})()
            fake_msg.id = item.find("guid").text if item.find("guid") is not None else 0
            fake_msg.date = item.find("pubDate").text if item.find("pubDate") is not None else ""
            fake_text = item.find("description").text if item.find("description") is not None else ""
            valid_posts.append((fake_msg, fake_text))
            if len(valid_posts) >= MAX_POSTS:
                break

    # Generuojame naują RSS
    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    seen_media = set()  # Saugosime jau panaudotus medijos failus, kad nebūtų dublikatų

    for msg, text in valid_posts:
        fe = fg.add_entry()
        fe.title(text[:30] if text else "No Title")
        fe.description(text if text else "No Content")
        fe.pubDate(msg.date)

        # Apdorojame medijos failą
        try:
            media_path = await msg.download_media(file="./")
            if not media_path:
                logger.warning(f"⚠️ Nepavyko parsisiųsti medijos iš post {msg.id}")
                continue

            # Jei medijos failų yra daugiau (albumas), pasirinkite mp4, jei yra
            if isinstance(media_path, list):
                mp4_files = [p for p in media_path if p.endswith('.mp4')]
                if mp4_files:
                    media_path = mp4_files[0]
                else:
                    media_path = media_path[0]

            # Tikriname medijos failo dydį
            if os.path.getsize(media_path) > MAX_MEDIA_SIZE:
                logger.info(f"❌ Didelis failas – {media_path}, praleidžiamas")
                os.remove(media_path)
                continue

            blob_name = os.path.basename(media_path)
            blob = bucket.blob(blob_name)

            # Jei failas dar neįkeltas – įkeliame į Google Cloud Storage
            if not blob.exists():
                blob.upload_from_filename(media_path)
                content_type = 'video/mp4' if media_path.endswith('.mp4') else 'image/jpeg'
                blob.content_type = content_type
                logger.info(f"✅ Įkėlėme {blob_name} į Google Cloud Storage")
            else:
                logger.info(f"🔄 {blob_name} jau egzistuoja Google Cloud Storage")

            # Pridedame į RSS, jei dar nebuvo panaudotas
            if blob_name not in seen_media:
                seen_media.add(blob_name)
                content_type = 'video/mp4' if media_path.endswith('.mp4') else 'image/jpeg'
                fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                             type=content_type)

            os.remove(media_path)  # Ištriname failą iš vietinės sistemos po įkėlimo
        except Exception as e:
            logger.error(f"❌ Klaida apdorojant mediją iš post {msg.id}: {e}")

    # Išsaugome paskutinio (naujausio) posto ID
    save_last_post({"id": valid_posts[0][0].id})

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas sėkmingai!")

# Pagrindinis proceso paleidimas
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
