import asyncio
import os
import json
import logging
import datetime
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

# ✅ GOOGLE CLOUD STORAGE PRISIJUNGIMAS
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
MAX_POSTS = 5  # ✅ Tik naujausi 5 postai
TIME_WINDOW = datetime.timedelta(hours=2)  # ✅ Tik postai iš paskutinių 2 valandų

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

# ✅ FUNKCIJA: RSS generacija
async def create_rss():
    await client.connect()
    last_post = load_last_post()

    now = datetime.datetime.now(datetime.UTC)  # ✅ Užtikrinta, kad `now` yra offset-aware
    min_time = now - TIME_WINDOW
    messages = await client.get_messages('Tsaplienko', limit=20)

    valid_posts = []
    grouped_posts = {}

    for msg in reversed(messages):
        msg_time = msg.date  # ✅ `msg.date` jau yra offset-aware

        if msg_time < min_time:
            continue

        text = msg.message or getattr(msg, "caption", None) or "No Content"
        if text == "No Content" or not msg.media:
            continue

        group_id = getattr(msg, "grouped_id", None)
        if group_id:
            if group_id not in grouped_posts:
                grouped_posts[group_id] = {"text": text, "media": []}
            grouped_posts[group_id]["media"].append(msg)
        else:
            grouped_posts[msg.id] = {"text": text, "media": [msg]}

    valid_posts = list(grouped_posts.values())[:MAX_POSTS]

    if not valid_posts:
        logger.info("🚨 Nėra naujų postų per pastarąsias 2 valandas – RSS neatsinaujins.")
        return

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')
    fg.lastBuildDate(now)  # ✅ Užtikrinta, kad RSS turi offset-aware laiką

    seen_guids = set()

    for post in valid_posts:
        text = post["text"]
        media_files = post["media"]

        first_msg = media_files[0]
        fe = fg.add_entry()
        fe.title(text[:80])  # ✅ Užtikriname, kad pavadinimas yra
        fe.description(text)  # ✅ Užtikriname, kad aprašymas yra
        fe.pubDate(first_msg.date)  # ✅ Užtikrinta, kad data yra offset-aware
        fe.guid(str(first_msg.id), permalink=False)

        if first_msg.id in seen_guids:
            continue
        seen_guids.add(first_msg.id)

        for media in media_files:
            try:
                media_path = await media.download_media(file="./")
                if os.path.getsize(media_path) > 15 * 1024 * 1024:
                    os.remove(media_path)
                    continue

                blob_name = os.path.basename(media_path)
                blob = bucket.blob(blob_name)
                if not blob.exists():
                    blob.upload_from_filename(media_path)
                    blob.make_public()

                fe.enclosure(url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                             length=str(os.path.getsize(media_path)),  # ✅ Užtikrinta, kad enclosure turi `length`
                             type='image/jpeg' if media_path.endswith(('.jpg', '.jpeg')) else 'video/mp4')
                os.remove(media_path)
            except Exception as e:
                logger.error(f"❌ Klaida apdorojant media: {e}")

    save_last_post({"id": valid_posts[0]["media"][0].id})

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas su tik naujausiais postais!")

# ✅ PAGRINDINIS PROCESO PALEIDIMAS
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())