from flask import Flask, Response
from telethon import TelegramClient
from feedgen.feed import FeedGenerator
import os
import asyncio

app = Flask(__name__)

# Telegram API credentials from environment variables
api_id = int(os.environ['API_ID'])
api_hash = os.environ['API_HASH']
channel_username = 'Tsaplienko'  # Replace with the Telegram channel username

client = TelegramClient('session_name', api_id, api_hash)

async def create_rss():
    await client.start()
    messages = await client.get_messages(channel_username, limit=10)
    
    fg = FeedGenerator()
    fg.title('Tsaplienko Telegram Channel RSS Feed')
    fg.link(href=f'https://t.me/{channel_username}')
    fg.description('RSS feed from Tsaplienko Telegram Channel')
    
    for msg in messages:
        fe = fg.add_entry()
        fe.title(msg.message[:30] if msg.message else "No Title")
        fe.link(href=f'https://t.me/{channel_username}/{msg.id}')
        fe.description(msg.message or "No Content")
        fe.pubDate(msg.date)
    
    return fg.rss_str(pretty=True)

@app.route('/rss')
def rss_feed():
    rss_content = asyncio.run(create_rss())
    return Response(rss_content, mimetype='application/rss+xml')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
