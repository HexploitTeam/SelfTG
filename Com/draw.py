# Com/draw.py
import os
import aiohttp
from telethon import events
from io import BytesIO

__HELP__ = (
    "!draw <prompt> → Generate an image from a text prompt using Stable Diffusion.\n"
    "Example: !draw a cat wearing a hat\n"
    "Requires HF_API_TOKEN set in Secrets (get one at huggingface.co/settings/tokens)."
)
__CATEGORY__ = "Utilities"

API_TOKEN = os.getenv("HF_API_TOKEN")
if not API_TOKEN:
    print("[DRAW] HF_API_TOKEN not set. The command will show an error.")

# Model to use (can be changed)
MODEL = "runwayml/stable-diffusion-v1-5"

async def generate_image(prompt):
    """Send a prompt to Hugging Face and return image bytes."""
    if not API_TOKEN:
        return None, "HF_API_TOKEN not set. Please add it to Secrets."

    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    payload = {"inputs": prompt}
    url = f"https://api-inference.huggingface.co/models/{MODEL}"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 200:
                return await resp.read(), None
            elif resp.status == 503:
                # Model is loading – wait and retry (up to 3 times)
                for _ in range(3):
                    await asyncio.sleep(2)
                    async with session.post(url, headers=headers, json=payload) as retry_resp:
                        if retry_resp.status == 200:
                            return await retry_resp.read(), None
                return None, "Model loading took too long. Try again in a moment."
            else:
                error_text = await resp.text()
                return None, f"API error ({resp.status}): {error_text[:200]}"

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!draw\s+(.+)$"))
    async def draw_cmd(event):
        try:
            prompt = event.pattern_match.group(1).strip()
            if not prompt:
                await event.edit("❌ Please provide a prompt.\nExample: `!draw a cat wearing a hat`")
                return

            await event.edit(f"🎨 Generating image for: `{prompt}` ... (may take 15‑30s)")

            # Generate
            img_bytes, error = await generate_image(prompt)
            if error:
                await event.edit(f"❌ {error}")
                return

            # Send as photo
            bio = BytesIO(img_bytes)
            bio.name = "generated.png"
            await client.send_file(
                event.chat_id,
                bio,
                caption=f"🖼️ Generated from: {prompt}",
                reply_to=event.id
            )
            await event.delete()

        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")