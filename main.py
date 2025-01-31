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
MAX_POSTS = 5
MAX_MEDIA_SIZE = 15 * 1024 * 1024  # ✅ Maksimalus medijos dydis - 15MB

# ✅ FUNKCIJA: Paskutinio posto ID įkėlimas
def load_last_post():
    if os.path.exists(LAST_POST_FILE):
        try:
            with open(LAST_POST_FILE, "r") as f:
                data = json.load(f)
                return data if "id" in data else {"id": 0}
        except json.JSONDecodeError:
            logger.error("❌ Klaida nuskaitant paskutinį postą, pradėsiu nuo naujausių!")
            return {"id": 0}
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
        return channel.findall("item") if channel is not None else []
    except ET.ParseError:
        logger.error("❌ RSS failas sugadintas, kuriamas naujas.")
        return []

# ✅ FUNKCIJA: RSS generacija
async def create_rss():
    await client.connect()
    last_post = load_last_post()

    # ✅ Gauname 100 naujausių postų (kad nieko nepraleistume)
    messages = await client.get_messages('Tsaplienko', limit=100)

    grouped_posts = {}
    valid_posts = []

    for msg in reversed(messages):
        text = msg.message or getattr(msg, "caption", None) or "No Content"

        # ✅ Jei tai albumas (`grouped_id`), grupuojame postus
        if hasattr(msg.media, "grouped_id") and msg.grouped_id:
            if msg.grouped_id not in grouped_posts:
                grouped_posts[msg.grouped_id] = {"text": text, "media": []}
            grouped_posts[msg.grouped_id]["media"].append(msg)
        else:
            valid_posts.append({"msg": msg, "text": text, "media": [msg]})

        if len(valid_posts) >= MAX_POSTS:
            break

    # ✅ Pridedame albumus
    for album in grouped_posts.values():
        valid_posts.append({"msg": album["media"][0], "text": album["text"], "media": album["media"]})
        if len(valid_posts) >= MAX_POSTS:
            break

    # ✅ Užtikriname, kad RSS faile visada būtų 5 įrašai
    existing_items = load_existing_rss()
    needed_posts = MAX_POSTS - len(valid_posts)
    if needed_posts > 0:
        valid_posts.extend(existing_items[:needed_posts])

    # ✅ Generuojame naują RSS
    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    seen_posts = set()

    for post in valid_posts:
        msg = post["msg"]
        text = post["text"]
        media_files = post["media"]

        if msg.id in seen_posts:
            continue
        seen_posts.add(msg.id)

        fe = fg.add_entry()
        fe.title(text[:30] if text else "No Title")
        fe.description(text if text else "No Content")
        fe.pubDate(msg.date)

        # ✅ Apdorojame visus albumo media failus
        for media_msg in media_files:
            try:
                media_path = await media_msg.download_media(file="./")
                if media_path and os.path.getsize(media_path) <= MAX_MEDIA_SIZE:
                    blob_name = os.path.basename(media_path)
                    blob = bucket.blob(blob_name)

                    if not blob.exists():
                        blob.upload_from_filename(media_path)
                        blob.content_type = 'image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4'

                    fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                                 type="image/jpeg" if media_path.endswith(".jpg") else "video/mp4")

                    os.remove(media_path)
            except Exception as e:
                logger.error(f"❌ Klaida apdorojant media: {e}")

    save_last_post({"id": valid_posts[0]["msg"].id})

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas sėkmingai!")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
