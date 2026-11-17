from telethon import events
import asyncio
import os
import json

__HELP__ = (
    "!countdown <number><s/m/h> <reason> → Start a countdown in this chat\n"
    "!countdown stop → Stop the countdown running in this chat")
__CATEGORY__ = "Utilities"

os.makedirs("mods", exist_ok=True)
CD_FILE = "mods/cd.json"

active_countdowns = {}  # chat_id: {"remaining": seconds, "reason": str, "msg": Message, "task": Task}


def setup(client, my_id):

    def format_hms(seconds: int) -> str:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    async def save_cd():
        data = {}
        for chat_id, info in active_countdowns.items():
            data[str(chat_id)] = {
                "remaining": info["remaining"],
                "reason": info["reason"]
            }
        with open(CD_FILE, "w") as f:
            json.dump(data, f)

    async def load_cd():
        if not os.path.exists(CD_FILE):
            return {}
        try:
            with open(CD_FILE, "r") as f:
                return json.load(f)
        except:
            return {}

    async def run_countdown(chat_id: int, total_seconds: int, reason: str,
                            msg):
        active_countdowns[chat_id] = {
            "remaining": total_seconds,
            "reason": reason,
            "msg": msg,
            "task": asyncio.current_task()
        }
        remaining = total_seconds
        try:
            while remaining > 0:
                display = format_hms(remaining)
                try:
                    await msg.edit(f"⏳ Countdown: {display}")
                except:
                    pass
                active_countdowns[chat_id]["remaining"] = remaining
                await save_cd()
                await asyncio.sleep(1)
                remaining -= 1
            try:
                await msg.edit(f"✅ Countdown finished! Reason: {reason}")
            except:
                pass
        except asyncio.CancelledError:
            try:
                await msg.edit("❌ Countdown stopped!")
            except:
                pass
        finally:
            active_countdowns.pop(chat_id, None)
            await save_cd()

    async def resume_cds():
        data = await load_cd()
        for chat_id_str, info in data.items():
            chat_id = int(chat_id_str)
            remaining = info.get("remaining", 0)
            reason = info.get("reason", "")
            msg = await client.send_message(
                chat_id, f"⏳ Countdown resumed: {format_hms(remaining)}")
            asyncio.create_task(run_countdown(chat_id, remaining, reason, msg))

    asyncio.create_task(resume_cds())

    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!countdown\s+(\d+)([smh])\s+(.+)$"))
    async def countdown(event):
        chat_id = event.chat_id
        if chat_id in active_countdowns:
            await event.reply(
                "❌ A countdown is already running in this chat! Stop it first with !countdown stop."
            )
            return

        number = int(event.pattern_match.group(1))
        unit = event.pattern_match.group(2).lower()
        reason = event.pattern_match.group(3)

        if unit == "s":
            total_seconds = number
        elif unit == "m":
            total_seconds = number * 60
        elif unit == "h":
            total_seconds = number * 3600
        else:
            await event.reply("❌ Invalid unit! Use s, m, or h.")
            return

        msg = await event.reply(f"⏳ Countdown: {format_hms(total_seconds)}")
        asyncio.create_task(run_countdown(chat_id, total_seconds, reason, msg))
        await event.delete()

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!countdown stop$"))
    async def stop(event):
        chat_id = event.chat_id
        info = active_countdowns.get(chat_id)
        if info:
            task = info.get("task")
            msg = info.get("msg")

            # Try to edit the countdown message if it still exists
            if msg:
                try:
                    await msg.edit("❌ Countdown stopping...")
                except Exception:
                    # Message was deleted – ignore
                    pass

            # Cancel the task
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            active_countdowns.pop(chat_id, None)
            await save_cd()
            await event.delete()
        else:
            await event.edit(
                "❌ No countdown is currently running in this chat!")