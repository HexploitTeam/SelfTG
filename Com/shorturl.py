# Com/shorturl.py
from telethon import events
import aiohttp
import os
import json

__HELP__ = "!shorturl [tinyurl/bitly] <link> or reply → Shorten a URL using TinyURL or Bitly"
__CATEGORY__ = "Utilities"
BITLY_TOKEN = os.getenv("BITLY_TOKEN")  # set your Bitly token in env
LOG_FILE = "mode/shorturl/shorturl_log.json"
os.makedirs("mode", exist_ok=True)


def setup(client, my_id):

    def log_url(original, short, service):
        data = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except:
                    data = []
        data.append({"original": original, "short": short, "service": service})
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    async def tinyurl_shorten(url):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    f"http://tinyurl.com/api-create.php?url={url}") as resp:
                if resp.status != 200:
                    return None
                return await resp.text()

    async def bitly_shorten(url):
        if not BITLY_TOKEN:
            return None
        headers = {
            "Authorization": f"Bearer {BITLY_TOKEN}",
            "Content-Type": "application/json"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api-ssl.bitly.com/v4/shorten",
                                    headers=headers,
                                    json={"long_url": url}) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("link")

    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!shorturl(?:\s+(\w+))?(?:\s+(.+))?"))
    async def shorturl(event):
        try:
            service = "tinyurl"
            url = event.pattern_match.group(2)
            arg1 = event.pattern_match.group(1)

            # Check if first argument is a service name
            if arg1 and arg1.lower() in ["tinyurl", "bitly"]:
                service = arg1.lower()
            elif arg1 and not url:
                url = arg1

            # If no URL in command, check reply
            if not url and event.is_reply:
                reply_msg = await event.get_reply_message()
                url = reply_msg.text or reply_msg.message or ""

            if not url:
                await event.reply(
                    "❌ Provide a URL or reply to a message containing one.")
                return

            if not url.startswith("http"):
                url = "http://" + url

            # Shorten
            if service == "bitly":
                short_link = await bitly_shorten(url)
                if not short_link:
                    await event.reply(
                        "❌ Failed to shorten using Bitly. Check token or URL.")
                    return
            else:
                short_link = await tinyurl_shorten(url)
                if not short_link:
                    await event.reply("❌ Failed to shorten using TinyURL.")
                    return

            # Reply with shortened URL
            await event.reply(
                f"🔗 Shortened URL ({service.title()}):\n{short_link}")

            # Log it
            log_url(url, short_link, service)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
