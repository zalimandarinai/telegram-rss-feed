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
MAX_MEDIA_SIZE = 15 * 1024 * 1024

def load_last_post():
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    return {"id": 0}

def save_last_post(post_data):
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump(post_data, f)

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

async def create_rss():
    await client.connect()
    last_post = load_last_post()
    messages = await client.get_messages('Tsaplienko', limit=5)
    
    grouped_texts = {}
    valid_posts = []

    for msg in reversed(messages):
        text = msg.message or getattr(msg, "caption", None) or "No Content"
        media_files = []
        
        if hasattr(msg.media, "grouped_id") and msg.grouped_id:
            if msg.grouped_id not in grouped_texts:
                grouped_texts[msg.grouped_id] = text
            else:
                text = grouped_texts[msg.grouped_id]
        
        if not msg.media and text == "No Content":
            logger.warning(f"⚠️ Praleidžiamas postas {msg.id}, nes neturi nei teksto, nei media")
            continue

        media_info = {"mp4": None, "jpeg": None, "text": text}
        
        if msg.media:
            try:
                media_path = await msg.download_media(file="./")
                if media_path and os.path.getsize(media_path) <= MAX_MEDIA_SIZE:
                    if media_path.endswith(".mp4"):
                        media_info["mp4"] = media_path
                    elif media_path.endswith(('.jpg', '.jpeg')):
                        media_info["jpeg"] = media_path
            except Exception as e:
                logger.error(f"❌ Klaida apdorojant media: {e}")
                continue

        if not media_info["mp4"] and not media_info["jpeg"]:
            continue  # ✅ Jei nėra media failų, ignoruojame įrašą

        # ✅ Jei yra MP4 ir JPEG, naudojame MP4, bet pridedame title/description iš JPEG
        if media_info["mp4"] and media_info["jpeg"] and text == "No Content":
            text = media_info["text"]

        valid_posts.append((msg, text, media_info["mp4"] or media_info["jpeg"]))

        if len(valid_posts) >= MAX_POSTS:
            break

    existing_items = load_existing_rss()
    for item in existing_items:
        if len(valid_posts) < MAX_POSTS and all(item.find("enclosure").attrib["url"] != f"https://storage.googleapis.com/{bucket_name}/{os.path.basename(post[2])}" for post in valid_posts):
            valid_posts.append((None, item.find("title").text, item.find("enclosure").attrib["url"]))
    
    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')
    
    seen_media = set()

    for msg, text, media_path in valid_posts:
        fe = fg.add_entry()
        fe.title(text[:30] if text else "No Title")
        fe.description(text if text else "No Content")
        fe.pubDate(msg.date if msg else "")
        
        blob_name = os.path.basename(media_path)
        blob = bucket.blob(blob_name)
        
        fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                     type='video/mp4' if media_path.endswith('.mp4') else 'image/jpeg')
    
    save_last_post({"id": valid_posts[0][0].id if valid_posts[0][0] else last_post["id"]})
    
    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas sėkmingai!")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())

