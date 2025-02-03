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
from email.utils import formatdate, parsedate_to_datetime

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
        items = channel.findall("item") if channel else []
        existing_posts = []
        for item in items:
            title = item.find("title").text if item.find("title") is not None else ""
            description = item.find("description").text if item.find("description") is not None else ""
            media_url = item.find("enclosure").attrib["url"] if item.find("enclosure") is not None else ""
            pub_date = parsedate_to_datetime(item.find("pubDate").text) if item.find("pubDate") is not None else None
            existing_posts.append((title, description, media_url, pub_date))
        return existing_posts
    except (ET.ParseError, FileNotFoundError) as e:
        logger.error(f"❌ RSS failas sugadintas arba nerastas, kuriamas naujas: {e}")
        return []

async def create_rss():
    await client.connect()
    last_post = load_last_post()
    messages = await client.get_messages('Tsaplienko', limit=5)
    
    grouped_texts = {}
    valid_posts = []

    for msg in reversed(messages):
        title = msg.message.strip() if msg.message else ""
        description = msg.caption.strip() if hasattr(msg, "caption") and msg.caption else ""
        media_files = {"mp4": None, "jpeg": None}
        
        if not (title or description):
            logger.warning(f"⚠️ PRALAIDŽIAMAS POSTAS {msg.id}: msg.message={msg.message}, msg.caption={msg.caption}")
            continue

        if not msg.photo and not msg.video and not msg.document:
            logger.warning(f"⚠️ PRALAIDŽIAMAS POSTAS {msg.id}: nėra media. msg.media={msg.media}")
            continue

        try:
            if msg.photo or msg.video or msg.document:
                media_path = await msg.download_media(file="./")
                if media_path and os.path.getsize(media_path) <= MAX_MEDIA_SIZE:
                    blob_name = os.path.basename(media_path)
                    blob = bucket.blob(blob_name)
                    try:
                        blob.reload()
                        exists = blob.exists()
                    except:
                        exists = False
                    if not exists:
                        if media_path.endswith(".mp4"):
                            media_files["mp4"] = media_path
                        elif media_path.endswith(('.jpg', '.jpeg')):
                            media_files["jpeg"] = media_path
        except Exception as e:
            logger.error(f"❌ Klaida apdorojant media: {e}")
            continue

        selected_media = media_files["mp4"] or media_files["jpeg"]
        if not selected_media:
            logger.warning(f"⚠️ PRALAIDŽIAMAS POSTAS {msg.id}: nėra tinkamo media failo")
            continue

        pub_date = formatdate(timeval=msg.date.timestamp(), usegmt=True) if msg.date else ""
        valid_posts.append((title, description, selected_media, pub_date))

    existing_items = load_existing_rss()
    valid_posts.extend([item for item in existing_items if (item[2], item[3]) not in [(post[2], post[3]) for post in valid_posts]])
    valid_posts = sorted(valid_posts, key=lambda x: parsedate_to_datetime(x[3]) if x[3] else None, reverse=True)[:MAX_POSTS]
    
    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')
    
    for title, description, media_url, pub_date in valid_posts:
        fe = fg.add_entry()
        fe.title(title[:30] if title else "No Title")
        fe.description(description if description else title)
        fe.pubDate(pub_date)
        if media_url:
            fe.enclosure(url=media_url, type='video/mp4' if media_url.endswith('.mp4') else 'image/jpeg')
        else:
            logger.warning(f"⚠️ PRALAIDŽIAMAS POSTAS be media: {title} ({pub_date})")
    
    if valid_posts:
        save_last_post({"id": valid_posts[0][0]})
    
    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas sėkmingai!")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
