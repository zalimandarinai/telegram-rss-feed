from flask import Flask, Response
from telethon import TelegramClient
from feedgen.feed import FeedGenerator
import os
import asyncio
from telethon.sessions import StringSession

app = Flask(__name__)

# Telegram API credentials
api_id = 29183291  # Provided API ID
api_hash = '8a7bceeb297d0d36307326a9305b6cd1'  # Provided API Hash
string_session = '1BJWap1wBuxvIEZuYKdqntabibZ6egpHUNqvj025vuzmZLfaplPB258r_aect3-CvCjXY82fEkSuMH6XMvVM4nIgYalxIbSv8VptQNHxdfOYmP7-9dMZX99Hah961cggDWsnjEqWBKwlPZKRv1jD_92AFHMacKwZ2TrONeQoOAzSa7yny8tWfsp6hbAY-Ula4miRa_Of3UhStkXXNbdXo1zNLSQqjd_zwJQBCRSqwT0AldJVJUPuzY9KzyfbsyXaXkwHI6cQZX2Q0J1POSNGWh8geLB0mlfJ0qXxDaDykv-hNJDYZiuX0AQQoDZWohpRUcm7oeDP0-bLy3W4mM7tFHkYdOUY8QRo='  # Your generated String Session

client = TelegramClient(StringSession(string_session), api_id, api_hash)

async def create_rss():
    await client.start()  # No need for a phone number, using StringSession
    messages = await client.get_messages('Tsaplienko', limit=10)  # Replace 'Tsaplienko' with your channel username

    fg = FeedGenerator()
    fg.title('Tsaplienko Telegram Channel RSS Feed')
    fg.link(href=f'https://t.me/Tsaplienko')  # Update to your channel link
    fg.description('RSS feed from Tsaplienko Telegram Channel')

    for msg in messages:
        fe = fg.add_entry()
        fe.title(msg.message[:30] if msg.message else "No Title")
        fe.link(href=f'https://t.me/Tsaplienko/{msg.id}')  # Update to your channel link
        fe.description(msg.message or "No Content")
        fe.pubDate(msg.date)

    return fg.rss_str(pretty=True)

@app.route('/rss')
def rss_feed():
    rss_content = asyncio.run(create_rss())
    return Response(rss_content, mimetype='application/rss+xml')

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
