import asyncio
import os
import json
import time
import logging
import xml.etree.ElementTree as ET
import datetime
import email.utils
import requests
from feedgen.feed import FeedGenerator
from google.cloud import storage
from google.oauth2 import service_account
from telethon import TelegramClient
from telethon.sessions import StringSession

import translate_pipeline  # 3 pakopų vertimas + saugiklis

# ====================================================================
# LOGŲ KONFIGŪRACIJA
# ====================================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====================================================================
# TELEGRAM PRISIJUNGIMO DUOMENYS
# ====================================================================
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
string_session = os.getenv("TELEGRAM_STRING_SESSION")
client = TelegramClient(StringSession(string_session), api_id, api_hash)

# ====================================================================
# GOOGLE CLOUD STORAGE KONFIGŪRACIJA
# ====================================================================
credentials_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
if not credentials_json:
    raise Exception("❌ Google Cloud kredencialai nerasti!")
credentials_dict = json.loads(credentials_json)
credentials = service_account.Credentials.from_service_account_info(credentials_dict)
storage_client = storage.Client(credentials=credentials)
bucket_name = "telegram-media-storage"
bucket = storage_client.bucket(bucket_name)

# ====================================================================
# KONSTANTOS
# ====================================================================
LAST_POST_FILE = "docs/last_post.json"
RSS_FILE = "docs/rss.xml"
MAX_POSTS = 7
MAX_MEDIA_SIZE = 30 * 1024 * 1024

MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL")
SENT_FILE = "docs/sent_to_make.json"
LAST_SENT_FILE = "docs/last_sent.json"
SENT_HISTORY_LIMIT = 200

# Postinimo dažnio riba: ne dažniau kaip 1 postas per valandą
MIN_INTERVAL_SECONDS = 60 * 60

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")


# ====================================================================
# BŪSENOS FAILAI
# ====================================================================
def load_last_post():
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    return {"id": 0}


def save_last_post(post_data):
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump(post_data, f)


def load_sent_ids():
    if os.path.exists(SENT_FILE):
        try:
            with open(SENT_FILE, "r") as f:
                return list(json.load(f))
        except Exception as e:
            logger.error(f"❌ {SENT_FILE} sugadintas, kuriamas naujas: {e}")
    return []


def save_sent_ids(ids):
    os.makedirs("docs", exist_ok=True)
    with open(SENT_FILE, "w") as f:
        json.dump(ids[-SENT_HISTORY_LIMIT:], f)


def load_last_sent_ts():
    if os.path.exists(LAST_SENT_FILE):
        try:
            with open(LAST_SENT_FILE, "r") as f:
                return float(json.load(f).get("ts", 0))
        except Exception:
            return 0.0
    return 0.0


def save_last_sent_ts(ts):
    os.makedirs("docs", exist_ok=True)
    with open(LAST_SENT_FILE, "w") as f:
        json.dump({"ts": ts,
                   "utc": datetime.datetime.utcfromtimestamp(ts).isoformat()}, f)


# ====================================================================
# PRANEŠIMAS Į TELEGRAM (Saved Messages)
# ====================================================================
async def notify(text):
    logger.warning(text)
    try:
        await client.send_message("me", text)
    except Exception as e:
        logger.error(f"❌ Nepavyko išsiųsti pranešimo į Telegram: {e}")


# ====================================================================
# SIUNTIMAS Į MAKE
# ====================================================================
def send_to_make(payload):
    if not MAKE_WEBHOOK_URL:
        logger.warning("⚠️ MAKE_WEBHOOK_URL nenustatytas - webhook praleidžiamas")
        return False
    try:
        r = requests.post(MAKE_WEBHOOK_URL, json=payload, timeout=30)
        if 200 <= r.status_code < 300:
            logger.info(f"📨 Nusiųsta į Make: post {payload['id']}")
            return True
        logger.error(f"❌ Make webhook atmetė ({r.status_code}): {r.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"❌ Nepavyko pasiekti Make webhook: {e}")
        return False


# ====================================================================
# RSS PAGALBINĖS
# ====================================================================
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


def get_datetime(date_val):
    if isinstance(date_val, datetime.datetime):
        return date_val
    try:
        return email.utils.parsedate_to_datetime(date_val)
    except Exception:
        return datetime.datetime.min


# ====================================================================
# PAGRINDINĖ FUNKCIJA
# ====================================================================
async def create_rss():
    await client.connect()
    last_post = load_last_post()

    messages = await client.get_messages('Tsaplienko', limit=14)

    grouped_texts = {}
    valid_posts = []

    for msg in messages:
        text = msg.message or getattr(msg, "caption", None)
        if not text:
            logger.warning(f"⚠️ Praleidžiamas postas {msg.id}, nes neturi teksto")
            continue
        if not msg.media:
            logger.warning(f"⚠️ Praleidžiamas postas {msg.id}, nes neturi medijos failo")
            continue
        if hasattr(msg.media, "grouped_id") and msg.media.grouped_id:
            if msg.media.grouped_id not in grouped_texts:
                grouped_texts[msg.media.grouped_id] = text
            else:
                text = grouped_texts[msg.media.grouped_id]
        valid_posts.append((msg, text))

    if not valid_posts:
        logger.info("Naujų validių postų nerasta, RSS liks nepakitęs.")
        return

    if len(valid_posts) < MAX_POSTS:
        existing_items = load_existing_rss()
        additional_needed = MAX_POSTS - len(valid_posts)
        for item in existing_items[:additional_needed]:
            fake_msg = type("FakeMsg", (object,), {})()
            fake_msg.id = item.find("guid").text if item.find("guid") is not None else 0
            fake_msg.date = item.find("pubDate").text if item.find("pubDate") is not None else ""
            fake_text = item.find("description").text if item.find("description") is not None else ""
            valid_posts.append((fake_msg, fake_text))
            if len(valid_posts) >= MAX_POSTS:
                break

    valid_posts.sort(key=lambda x: get_datetime(x[0].date), reverse=True)

    fg = FeedGenerator()
    fg.title('Latest news')
    fg.link(href='https://www.mandarinai.lt/')
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')

    seen_media = set()
    sent_ids = load_sent_ids()
    queue = []

    for msg, text in valid_posts:
        fe = fg.add_entry()
        fe.title(text[:30] if text else "No Title")
        fe.link(href=f"https://www.mandarinai.lt/post/{msg.id}")
        fe.description(text if text else "No Content")
        fe.pubDate(msg.date)

        try:
            media_path = await msg.download_media(file="./")
            if not media_path:
                logger.warning(f"⚠️ Nepavyko parsisiųsti medijos iš post {msg.id}")
                continue

            if isinstance(media_path, list):
                mp4_files = [p for p in media_path if p.lower().endswith('.mp4')]
                media_path = mp4_files[0] if mp4_files else media_path[0]

            if os.path.getsize(media_path) > MAX_MEDIA_SIZE:
                logger.info(f"❌ Didelis failas - {media_path}, praleidžiamas")
                os.remove(media_path)
                continue

            video_extensions = ['.mp4', '.mov', '.mkv', '.avi', '.wmv', '.flv', '.webm']
            if media_path.lower().endswith(tuple(video_extensions)):
                content_type = 'video/mp4'
            else:
                content_type = 'image/jpeg'

            blob_name = os.path.basename(media_path)
            blob = bucket.blob(blob_name)

            if not blob.exists():
                blob.upload_from_filename(media_path)
                blob.content_type = content_type
                logger.info(f"✅ Įkėlėme {blob_name} į Google Cloud Storage")
            else:
                logger.info(f"🔄 {blob_name} jau egzistuoja Google Cloud Storage")

            media_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"

            if blob_name not in seen_media:
                seen_media.add(blob_name)
                fe.enclosure(url=media_url, type=content_type,
                             length=str(os.path.getsize(media_path)))

            post_id = str(msg.id)
            if content_type == 'video/mp4' and post_id not in sent_ids:
                queue.append({
                    "id": post_id,
                    "raw_text": text,
                    "video_url": media_url,
                    "link": f"https://www.mandarinai.lt/post/{msg.id}",
                    "pubdate": str(msg.date),
                    "_sort": get_datetime(msg.date),
                })

            os.remove(media_path)
        except Exception as e:
            logger.error(f"❌ Klaida apdorojant mediją iš post {msg.id}: {e}")

    save_last_post({"id": valid_posts[0][0].id})

    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas sėkmingai!")

    # ================================================================
    # POSTINIMAS: 1 video per paleidimą, ne dažniau kaip 1 kartą per valandą,
    # seniausias pirmas (FB tvarka lieka chronologinė).
    # ================================================================
    if not queue:
        logger.info("🎬 Naujų video nėra - nieko nesiunčiam.")
        return

    queue.sort(key=lambda v: v["_sort"])
    logger.info(f"🎬 Eilėje laukia {len(queue)} video.")

    now = time.time()
    elapsed = now - load_last_sent_ts()

    if elapsed < MIN_INTERVAL_SECONDS:
        wait_min = int((MIN_INTERVAL_SECONDS - elapsed) / 60)
        logger.info(f"⏳ Nuo paskutinio posto praėjo tik {int(elapsed/60)} min. "
                    f"Laukiam dar {wait_min} min. (riba: 1 postas/val.)")
        return

    video = queue[0]
    logger.info(f"🚀 Skelbiam video {video['id']} ({video['pubdate']})")

    lt_text, ok, report = translate_pipeline.translate(DEEPSEEK_API_KEY, video["raw_text"])

    if not ok:
        await notify(
            "⚠️ VERTIMAS NEPAVYKO\n\n"
            f"Postas: {video['link']}\n"
            f"Priežastis: {report}\n\n"
            "Video paskelbtas Facebook'e BE TEKSTO.\n"
            "Originalas:\n"
            f"{video['raw_text'][:500]}"
        )
    elif report and report != "ok":
        await notify(
            "🟡 Vertimas praėjo, bet su pastabomis\n\n"
            f"Postas: {video['link']}\n"
            f"Pastabos: {report}\n\n"
            "Vertimas:\n"
            f"{lt_text[:600]}"
        )

    payload = {
        "id": video["id"],
        "description": lt_text,
        "video_url": video["video_url"],
        "link": video["link"],
        "pubdate": video["pubdate"],
        "translation_ok": ok,
    }

    if send_to_make(payload):
        sent_ids.append(video["id"])
        save_sent_ids(sent_ids)
        save_last_sent_ts(now)
        logger.info(f"✅ Paskelbta. Eilėje liko {len(queue) - 1} video "
                    f"(kitas ne anksčiau kaip po 1 val.)")
    else:
        await notify(
            "🔴 Make webhook NEPASIEKIAMAS\n\n"
            f"Postas: {video['link']}\n"
            "Video NEPASKELBTAS. Bus bandoma dar kartą kito paleidimo metu."
        )


# ====================================================================
# PALEIDIMAS
# ====================================================================
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
