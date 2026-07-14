# Com/speedtest.py
from telethon import events
import speedtest
import asyncio

__HELP__ = "!speedtest → Run an internet speed test and show ping, download, and upload speeds."
__CATEGORY__ = "Utilities"

def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!speedtest$"))
    async def speedtest_cmd(event):
        msg = await event.reply(
            "⏳ Running speed test... this may take a few seconds.")

        def run_test():
            st = speedtest.Speedtest()
            st.get_best_server()
            download = st.download()
            upload = st.upload()
            ping = st.results.ping
            return download, upload, ping

        try:
            loop = asyncio.get_event_loop()
            download, upload, ping = await loop.run_in_executor(None, run_test)

            download_mbps = round(download / 1_000_000, 2)
            upload_mbps = round(upload / 1_000_000, 2)

            await msg.edit(f"📶 **Speed Test Results:**\n"
                           f"• Ping: {ping} ms\n"
                           f"• Download: {download_mbps} Mbps\n"
                           f"• Upload: {upload_mbps} Mbps")
        except Exception as e:
            await msg.edit(f"❌ Speed test failed: {str(e)}")
