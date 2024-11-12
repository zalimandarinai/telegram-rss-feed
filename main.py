from flask import Flask, Response
from telethon import TelegramClient
from feedgen.feed import FeedGenerator
import os
import asyncio

app = Flask(__name__)

# Telegram API credentials from environment variables
api_id = 29183291  # Provided API ID
api_hash = '8a7bceeb297d0d36307326a9305b6cd1'  # Provided API Hash
phone_number = '+37065662110'  # Provided Telegram phone number

client = TelegramClient('session_name', api_id, api_hash)

async def create_rss():
    await client.start(phone=phone_number)  # Start the client with the phone number
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
