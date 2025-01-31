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
MAX_POSTS = 5  # ✅ RSS faile visada bus bent 5 paskutiniai postai su media ir tekstu
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
    
    # ✅ Gauname 20 paskutinių žinučių (didesnis skaičius, kad turėtume atsargą)
    messages = await client.get_messages('Tsaplienko', limit=20)

    # ✅ Albumų tekstų sekimas (kad visi albumo įrašai turėtų tą patį tekstą)
    grouped_texts = {}

    valid_posts = []  # ✅ Saugojami tik postai su media ir tekstu

    for msg in reversed(messages):  # ✅ Apdorojame postus nuo seniausio iki naujausio
        text = msg.message or getattr(msg, "caption", None) or "No Content"

        # ✅ Jei postas yra albumo dalis, tekstą imame iš pirmo įrašo
        if hasattr(msg.media, "grouped_id") and msg.grouped_id:
            if msg.grouped_id not in grouped_texts:
                grouped_texts[msg.grouped_id] = text
            else:
                text = grouped_texts[msg.grouped_id]

        # ✅ Jei nėra nei teksto, nei media – praleidžiame
        if text == "No Content" and not msg.media:
            logger.warning(f"⚠️ Praleidžiamas postas {msg.id}, nes neturi nei teksto, nei media")
            continue

        # ✅ Išsaugome validžius postus
        valid_posts.append((msg, text))

        # ✅ Sustojame, kai surenkame 5 postus
        if len(valid_posts) >= MAX_POSTS:
            break

    # ✅ Užtikriname, kad RSS faile visada būtų 5 įrašai
    existing_items = load_existing_rss()
    if len(valid_posts) < MAX_POSTS:
        remaining_posts = [msg for msg in existing_items if msg not in valid_posts]
        valid_posts.extend(remaining_posts[:MAX_POSTS - len(valid_posts)])

    # ✅ Generuojame naują RSS
    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    seen_media = set()  # ✅ Saugome jau naudotus media failus, kad nebūtų dublikatų

    for msg, text in valid_posts:
        fe = fg.add_entry()
        fe.title(text[:30] if text else "No Title")
        fe.description(text if text else "No Content")
        fe.pubDate(msg.date)

        # ✅ Apdorojame media failą
        if msg.media:
            try:
                media_path = await msg.download_media(file="./")
                if media_path and os.path.getsize(media_path) <= MAX_MEDIA_SIZE:
                    blob_name = os.path.basename(media_path)
                    blob = bucket.blob(blob_name)

                    # ✅ Jei failas dar neįkeltas – įkeliame
                    if not blob.exists():
                        blob.upload_from_filename(media_path)
                        blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'
                        logger.info(f"✅ Įkėlėme {blob_name} į Google Cloud Storage")
                    else:
                        logger.info(f"🔄 {blob_name} jau egzistuoja Google Cloud Storage")

                    # ✅ Pridėti prie RSS tik jei nėra dublikato
                    if blob_name not in seen_media:
                        seen_media.add(blob_name)
                        fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                                     type='image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4')

                    os.remove(media_path)  # ✅ Ištriname failą iš vietinės atminties
                else:
                    logger.info(f"❌ Didelis failas – {media_path}, praleidžiamas")
                    os.remove(media_path)
            except Exception as e:
                logger.error(f"❌ Klaida apdorojant media: {e}")

    # ✅ Išsaugome paskutinio posto ID
    save_last_post({"id": valid_posts[0][0].id})

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas sėkmingai!")

# ✅ PAGRINDINIS PROCESO PALEIDIMAS
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
