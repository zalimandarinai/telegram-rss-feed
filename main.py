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

# Nauji importai, reikalingi MIME tipams tvarkyti
import mimetypes
mimetypes.add_type('video/quicktime', '.mov')
mimetypes.add_type('video/mp4', '.mp4')

# ====================================================================
# LOGŲ KONFIGŪRACIJA:
# Nustatome pranešimų lygį ir sukuriame logger'į, kuris fiksuos vykdymo informaciją.
# ====================================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====================================================================
# TELEGRAM PRISIJUNGIMO DUOMENYS:
# Gauname reikiamus duomenis (api_id, api_hash ir string_session) iš aplinkos kintamųjų,
# kad galėtume prisijungti prie Telegram API.
# ====================================================================
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
string_session = os.getenv("TELEGRAM_STRING_SESSION")
client = TelegramClient(StringSession(string_session), api_id, api_hash)

# ====================================================================
# GOOGLE CLOUD STORAGE KONFIGŪRACIJA:
# Gauname Google Cloud saugyklos (Storage) kredencialus ir inicijuojame klientą,
# taip pat nustatome saugyklos pavadinimą.
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
# NUOLATINIAI KONSTANTAI:
# LAST_POST_FILE: Failas, kuriame saugomas paskutinio apdoroto įrašo ID.
# RSS_FILE: Failo kelias, kuriame bus išsaugotas sugeneruotas RSS srautas.
# MAX_POSTS: Maksimalus įrašų skaičius RSS faile (visada 5 paskutiniai postai).
# MAX_MEDIA_SIZE: Maksimalus leidžiamas medijos failo dydis (15 MB).
# ====================================================================
LAST_POST_FILE = "docs/last_post.json"
RSS_FILE = "docs/rss.xml"
MAX_POSTS = 7
MAX_MEDIA_SIZE = 15 * 1024 * 1024

# ====================================================================
# FUNKCIJA: Įkelti paskutinio įrašo ID iš failo.
# Jei failas neegzistuoja, grąžiname numatytąją reikšmę.
# ====================================================================
def load_last_post():
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    return {"id": 0}

# ====================================================================
# FUNKCIJA: Įrašyti paskutinio įrašo ID į failą.
# ====================================================================
def save_last_post(post_data):
    os.makedirs("docs", exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump(post_data, f)

# ====================================================================
# FUNKCIJA: Nuskaityti esamo RSS failo įrašus.
# Jei RSS failas neegzistuoja arba yra sugadintas, grąžiname tuščią sąrašą.
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

# ====================================================================
# FUNKCIJA: Konvertuoti datą į datetime objektą.
# Jei data jau yra datetime, grąžiname ją, o jei tai string – konvertuojame.
# ====================================================================
def get_datetime(date_val):
    if isinstance(date_val, datetime.datetime):
        return date_val
    try:
        # Konvertuojame RFC 822 formato datą į datetime objektą.
        return email.utils.parsedate_to_datetime(date_val)
    except Exception:
        return datetime.datetime.min

# ====================================================================
# FUNKCIJA: Generuoti naują RSS srautą.
# ====================================================================
async def create_rss():
    # Prisijungiame prie Telegram API.
    await client.connect()
    last_post = load_last_post()
    
    # Gauname paskutines 14 žinutes iš kanalo "Tsaplienko".
    messages = await client.get_messages('Tsaplienko', limit=14)

    # Kintamasis albumo pranešimų tekstams:
    # Jei žinutės priklauso vienam albumui, visoms bus naudojamas tas pats tekstas.
    grouped_texts = {}
    valid_posts = []  # Čia saugosime įrašus, kurie turi tiek tekstą, tiek medijos failą.

    # Iteruojame per gautas žinutes.
    for msg in messages:
        # Patikriname, ar žinutėje yra tekstas (message arba caption).
        text = msg.message or getattr(msg, "caption", None)
        if not text:
            logger.warning(f"⚠️ Praleidžiamas postas {msg.id}, nes neturi teksto (title/description)")
            continue

        # Tikriname, ar žinutėje yra medijos failas.
        if not msg.media:
            logger.warning(f"⚠️ Praleidžiamas postas {msg.id}, nes neturi medijos failo")
            continue

        # Jei žinutė priklauso albumui, užtikriname, kad visoms žinutėms būtų naudojamas vienodas tekstas.
        if hasattr(msg.media, "grouped_id") and msg.media.grouped_id:
            if msg.media.grouped_id not in grouped_texts:
                grouped_texts[msg.media.grouped_id] = text
            else:
                text = grouped_texts[msg.media.grouped_id]

        valid_posts.append((msg, text))

    # Jei naujų tinkamų įrašų nerasta – paliekame esamą RSS nepakitusią.
    if not valid_posts:
        logger.info("Naujų validių postų nerasta, RSS liks nepakitęs.")
        return

    # Jei validių įrašų yra mažiau nei MAX_POSTS, papildomai pridedame senesnius įrašus iš esamo RSS.
    if len(valid_posts) < MAX_POSTS:
        existing_items = load_existing_rss()
        additional_needed = MAX_POSTS - len(valid_posts)
        for item in existing_items[:additional_needed]:
            # Sukuriame "fake" pranešimą, kad atitikčiau duomenų struktūrą.
            fake_msg = type("FakeMsg", (object,), {})()
            fake_msg.id = item.find("guid").text if item.find("guid") is not None else 0
            fake_msg.date = item.find("pubDate").text if item.find("pubDate") is not None else ""
            fake_text = item.find("description").text if item.find("description") is not None else ""
            valid_posts.append((fake_msg, fake_text))
            if len(valid_posts) >= MAX_POSTS:
                break

    # Rūšiuojame įrašus pagal datą mažėjimo tvarka – naujausi postai bus viršuje.
    # Konvertuojame datas į datetime objektus, kad būtų galima atlikti teisingą rūšiavimą.
    valid_posts.sort(key=lambda x: get_datetime(x[0].date), reverse=True)

    # Pradedame generuoti naują RSS srautą su FeedGenerator.
    fg = FeedGenerator()
    fg.title('Latest news')                           # Kanalas: pavadinimas.
    fg.link(href='https://www.mandarinai.lt/')         # Kanalas: pagrindinė nuoroda.
    fg.description('Naujienų kanalą pristato www.mandarinai.lt')  # Kanalas: aprašymas.

    seen_media = set()  # Saugojame jau panaudotus medijos failų pavadinimus,
                        # kad jų nebūtų dubliuota RSS įraše.

    # Iteruojame per kiekvieną validų įrašą.
    for msg, text in valid_posts:
        fe = fg.add_entry()  # Pridedame naują įrašą į RSS srautą.
        fe.title(text[:30] if text else "No Title")  # Įrašo pavadinimas (pirmos 30 simbolių).
        fe.link(href=f"https://www.mandarinai.lt/post/{msg.id}")  # Pridedame individualią nuorodą į įrašą.
        fe.description(text if text else "No Content")  # Įrašo aprašymas (pilnas tekstas).
        fe.pubDate(msg.date)  # Įrašo paskelbimo data.

        # Apdorojame medijos failą iš žinutės.
        try:
            # Parsisiunčiame medijos failą į vietinę sistemą.
            media_path = await msg.download_media(file="./")
            if not media_path:
                logger.warning(f"⚠️ Nepavyko parsisiųsti medijos iš post {msg.id}")
                continue

            # Jei žinutėje yra daugiau nei vienas medijos failas (pvz., albumas),
            # pasirinkime mp4 failą, jei toks yra (naudojama .lower() tikrinimui).
            if isinstance(media_path, list):
                mp4_files = [p for p in media_path if p.lower().endswith('.mp4')]
                if mp4_files:
                    media_path = mp4_files[0]
                else:
                    media_path = media_path[0]

            # Patikriname, ar medijos failo dydis neviršija nustatytos ribos.
            if os.path.getsize(media_path) > MAX_MEDIA_SIZE:
                logger.info(f"❌ Didelis failas – {media_path}, praleidžiamas")
                os.remove(media_path)
                continue

            # Nustatome medijos failo MIME tipą naudojant mimetypes.
            content_type, _ = mimetypes.guess_type(media_path)
            if content_type is None:
                logger.warning(f"⚠️ Nepavyko nustatyti MIME tipo failui {media_path}, praleidžiamas")
                os.remove(media_path)
                continue

            # Nustatome medijos failo pavadinimą ir paruošiame failą įkėlimui į Google Cloud Storage.
            blob_name = os.path.basename(media_path)
            blob = bucket.blob(blob_name)

            # Jei failas dar nėra įkeltas į saugyklą, atliekame įkėlimą.
            if not blob.exists():
                blob.upload_from_filename(media_path)
                blob.content_type = content_type
                logger.info(f"✅ Įkėlėme {blob_name} į Google Cloud Storage")
            else:
                logger.info(f"🔄 {blob_name} jau egzistuoja Google Cloud Storage")

            # Pridedame medijos failą kaip RSS įrašo priedą (<enclosure> elementą).
            if blob_name not in seen_media:
                seen_media.add(blob_name)
                fe.enclosure(
                    url=f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                    type=content_type,
                    length=str(os.path.getsize(media_path))  # Nustatome failo dydį (baitu skaičius).
                )

            # Ištriname parsisiųstą medijos failą iš vietinės sistemos, kad neužsikrautų saugykla.
            os.remove(media_path)
        except Exception as e:
            logger.error(f"❌ Klaida apdorojant mediją iš post {msg.id}: {e}")

    # Išsaugome paskutinio įrašo ID, kad vėliau žinotume nuo kurio laiko ieškoti naujų žinučių.
    save_last_post({"id": valid_posts[0][0].id})

    # Įrašome sugeneruotą RSS srautą į failą, naudodami gražų formatavimą.
    with open(RSS_FILE, "wb") as f:
        f.write(fg.rss_str(pretty=True))

    logger.info("✅ RSS atnaujintas sėkmingai!")

# ====================================================================
# PAGRINDINIS PROGRAMOS PALEIDIMAS:
# Paleidžiame asinkroninį pagrindinį ciklą, kuris generuoja RSS srautą.
# ====================================================================
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_rss())
