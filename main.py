import asyncio
import os
import json
import logging
import xml.etree.ElementTree as ET
import datetime
import email.utils
from feedgen.feed import FeedGenerator
from google.cloud import storage
from google.oauth2 import service_account
from telethon import TelegramClient
from telethon.sessions import StringSession

# ========================================================
# APSAUGA NUO SLAPTŲ DUOMENŲ ATSKLEIDIMO
# ========================================================
def block_sensitive_data(output):
    sensitive_keywords = ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_STRING_SESSION", "GCP_SERVICE_ACCOUNT_JSON"]
    for keyword in sensitive_keywords:
        if keyword in output:
            raise Exception("❌ Bandymas išvesti slaptus duomenis!")
    return output

# Perrašome `print()` funkciją, kad tikrintų jautrius duomenis
original_print = print
def safe_print(*args, **kwargs):
    output = " ".join(map(str, args))
    block_sensitive_data(output)
    original_print(*args, **kwargs)

print = safe_print  # Pakeičiame `print()` su saugia versija

# ========================================================
# LOGŲ KONFIGŪRACIJA
# ========================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================================================
# TELEGRAM PRISIJUNGIMO DUOMENYS
# ========================================================
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
string_session = os.getenv("TELEGRAM_STRING_SESSION")
client = TelegramClient(StringSession(string_session), api_id, api_hash)

# ========================================================
# GOOGLE CLOUD STORAGE KONFIGŪRACIJA
# ========================================================
credentials_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
if not credentials_json:
    raise Exception("❌ Google Cloud kredencialai nerasti!")
credentials_dict = json.loads(credentials_json)
credentials = service_account.Credentials.from_service_account_info(credentials_dict)
storage_client = storage.Client(credentials=credentials)
bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# ========================================================
# NUOLATINIAI KONSTANTAI
# ========================================================
LAST_POST_FILE = "docs/last_post.json"
RSS_FILE = "docs/rss.xml"
MAX_POSTS = 7
MAX_MEDIA_SIZE = 15 * 1024 * 1024

# ========================================================
# FUNKCIJA: Įkelti paskutinio įrašo ID iš failo
# ========================================================
def load_last_post():
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    return {"id": 0}

# ========================================================
# FUNKCIJA: Įrašyti paskutinio įrašo ID į failą
# ========================================================
def save_last_post(post_data):
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump(post_data, f)

# ========================================================
# FUNKCIJA: Nuskaityti esamo RSS failo įrašus
# ========================================================
def load_existing_rss():
    if not os.path.exists(RSS_FILE):
        return []
    try:
        tree = ET.parse(RSS_FILE)
        root = tree.getroot()
        channel = root.find("channel")
        return channel.findall("item") if channel is not None else []
    except Exception as e:
        logger.error(f"❌ RSS failas sugadintas, kuriamas naujas: {e}")
        return []

# ========================================================
# FUNKCIJA: Konvertuoti datą į datetime objektą
# ========================================================
def get_datetime(date_val):
    if isinstance(date_val, datetime.datetime):
        return date_val
    try:
        return email.utils.parsedate_to_datetime(date_val)
    except Exception:
        return datetime.datetime.min

# ========================================================
# FUNKCIJA: Generuoti naują RSS srautą
# ========================================================
async def create_rss():
    await client.connect()
    last_post = load_last_post()
    messages = await client.get_messages('Tsaplienko', limit=14)
    grouped_texts = {}
    valid_posts = []

    for msg in messages:
        text = msg.message or getattr(msg, "caption", None)
        if not text or not msg.media:
            continue

        if hasattr(msg.media, "grouped_id") and msg.media.grouped_id:
            text = grouped_texts.setdefault(msg.media.grouped_id, text)

        valid_posts.append((msg, text))

    if not valid_posts:
        return

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    for msg, text in valid_posts:
        fe = fg.add_entry()
        fe.title(text[:30] if text else "No Title")
        fe.link(href=f"https://www.mandarinai.lt/post/{msg.id}")
        fe.description(text if text else "No Content")
        fe.pubDate(msg.date)

    save_last_post({"id": valid_posts[0][0].id})
    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas sėkmingai!")

# ========================================================
# PAGRINDINIS PROGRAMOS PALEIDIMAS
# Paleidžiame asinkroninį pagrindinį ciklą, kuris generuoja RSS srautą.
# ========================================================
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
