"""!tts: text to speech with gTTS, sent as a voice note or an audio file."""
import asyncio
import os
import shlex
import tempfile
from telethon import events
import Com.core.tgsend as tgsend
from gtts import gTTS
from gtts.tts import gTTSError

__HELP__ = (
    "!tts [options] <text> (or reply) → Convert text to speech.\n"
    "Options:\n"
    "  --lang <code>     Language code (e.g., en, fa, fr, de, es) – default: en\n"
    "  --tld <domain>    Accent/domain (e.g., com, co.uk, ca, com.au) – default: com\n"
    "  --voice-note      Send as a voice message (Telegram voice note) instead of audio file.\n"
    "Examples:\n"
    "  !tts --lang fa سلام\n"
    "  !tts --lang en --tld co.uk 'Hello from the UK'\n"
    "  !tts (reply to a message) – uses that text with default settings."
)
__CATEGORY__ = "Utilities"

TTS_FOLDER = "mode/tts"
os.makedirs(TTS_FOLDER, exist_ok=True)

#------------------------------
#Helpers
#------------------------------

def _render_tts(text, lang, tld):
    """Blocking: build the MP3 with gTTS and return the temp path."""
    tts = gTTS(text=text, lang=lang, tld=tld, slow=False)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
        path = tmp.name
        tts.save(path)
    return path


def parse_args(args):
    options = {'lang': 'en', 'tld': 'com', 'voice_note': False}
    text_parts = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith('--'):
            if arg == '--lang':
                if i + 1 >= len(args):
                    raise ValueError("Missing value for --lang")
                options['lang'] = args[i+1]
                i += 2
            elif arg == '--tld':
                if i + 1 >= len(args):
                    raise ValueError("Missing value for --tld")
                options['tld'] = args[i+1]
                i += 2
            elif arg == '--voice-note':
                options['voice_note'] = True
                i += 1
            else:
                raise ValueError(f"Unknown option: {arg}")
        else:
            text_parts.append(arg)
            i += 1
    return options, ' '.join(text_parts)

#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r'^!tts(?:\s+(.*))?$'))
    async def tts_cmd(event):
        try:
            arg_str = event.pattern_match.group(1)
            text = None
            options = {'lang': 'en', 'tld': 'com', 'voice_note': False}

            if not arg_str and not event.is_reply:
                await event.edit("📖 **TTS Help**\n" + __HELP__)
                return

            if arg_str:
                args = shlex.split(arg_str)
                options, text = parse_args(args)

            if not text and event.is_reply:
                reply = await event.get_reply_message()
                text = reply.text or reply.raw_text
            if not text:
                await event.edit("❌ No text to convert. Provide text or reply to a message.")
                return

            lang = options['lang']
            tld = options['tld']

            await event.edit(f"🔊 Generating TTS (lang: {lang}, tld: {tld})...")

            # gTTS.save() is synchronous and does a network round trip, so it
            # runs in a worker thread with a timeout: previously it blocked the
            # whole event loop (every other handler) for the length of the call
            # and had no timeout at all if Google stalled.
            try:
                tmp_path = await asyncio.wait_for(
                    asyncio.to_thread(_render_tts, text, lang, tld), timeout=45
                )
            except asyncio.TimeoutError:
                await event.edit("❌ TTS timed out (free Google endpoint is slow right now).")
                return
            except gTTSError as e:
                await event.edit(f"❌ TTS error: {e} (the free endpoint may be rate limiting)")
                return
            except Exception as e:
                await event.edit(f"❌ Error: {e}")
                return

            if options['voice_note']:
                try:
                    await client.send_file(await tgsend.peer(event),
                        tmp_path,
                        voice_note=True,
                        reply_to=event.id if event.is_reply else None
                    )
                except Exception as e:
                    await event.edit(f"❌ Failed to send voice note: {e}")
                    os.remove(tmp_path)
                    return
            else:
                try:
                    await client.send_file(await tgsend.peer(event),
                        tmp_path,
                        caption=f"🔊 TTS ({lang})",
                        reply_to=event.id if event.is_reply else None
                    )
                except Exception as e:
                    await event.edit(f"❌ Failed to send audio: {e}")
                    os.remove(tmp_path)
                    return

            os.remove(tmp_path)
            await event.delete()

        except ValueError as e:
            await event.edit(f"❌ {e}")
        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")