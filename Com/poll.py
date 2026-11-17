# Com/poll.py
import shlex
from telethon import events
from telethon.tl.functions.messages import SendMessageRequest
from telethon.tl.types import Poll, PollAnswer

__HELP__ = (
    '!poll [flags] "Question" "Option1" "Option2" ...\n'
    'Flags:\n'
    '  -m          Multiple choice (native only)\n'
    '  -p          Public voters (native only)\n'
    '  -q          Quiz mode (native only)\n'
    '  -a <index>  Correct answer index (native only)\n'
    '  -s "text"   Solution explanation (native only)\n'
    'Example: !poll "Fav color?" "Red" "Blue" "Green"\n'
    'If your Telethon version doesn\'t support native polls, a text poll is created.\n'
    'Reply to a message to link the poll to it.'
)
__CATEGORY__ = "Utilities"

def parse_flags(args):
    flags = {'multiple_choice': False, 'public_voters': False, 'quiz': False, 'correct_answer': None, 'solution': ''}
    i = 0
    remaining = []
    while i < len(args):
        arg = args[i]
        if arg.startswith('-'):
            if arg == '-m':
                flags['multiple_choice'] = True
                i += 1
            elif arg == '-p':
                flags['public_voters'] = True
                i += 1
            elif arg == '-q':
                flags['quiz'] = True
                i += 1
            elif arg == '-a':
                if i + 1 >= len(args):
                    raise ValueError("Missing index for -a")
                try:
                    flags['correct_answer'] = int(args[i+1]) - 1
                except ValueError:
                    raise ValueError("Index must be a number")
                i += 2
            elif arg == '-s':
                if i + 1 >= len(args):
                    raise ValueError("Missing solution text for -s")
                flags['solution'] = args[i+1]
                i += 2
            else:
                raise ValueError(f"Unknown flag: {arg}")
        else:
            remaining.append(arg)
            i += 1
    return flags, remaining

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r'^!poll(?:\s+(.*))?$'))
    async def poll_cmd(event):
        try:
            input_text = event.pattern_match.group(1)
            if not input_text:
                await event.edit("📖 **Poll Help**\n" + __HELP__)
                return

            args = shlex.split(input_text)
            flags, remaining = parse_flags(args)

            if len(remaining) < 3:
                await event.edit("❌ Need a question and at least 2 options.\n" + __HELP__)
                return
            if len(remaining) > 11:
                await event.edit("❌ Maximum 10 options allowed.")
                return

            question = remaining[0]
            options = remaining[1:]

            if flags['quiz']:
                if flags['correct_answer'] is None:
                    await event.edit("❌ Quiz mode requires `-a <index>`.")
                    return
                if flags['correct_answer'] < 0 or flags['correct_answer'] >= len(options):
                    await event.edit(f"❌ Correct answer index must be between 1 and {len(options)}.")
                    return
                if flags['multiple_choice']:
                    await event.edit("❌ Quiz mode cannot be multiple choice.")
                    return

            if len(question) > 255:
                await event.edit("❌ Question too long (max 255 chars)")
                return
            for opt in options:
                if len(opt) > 100:
                    await event.edit(f"❌ Option too long: '{opt}' (max 100 chars)")
                    return

            reply_to = None
            if event.is_reply:
                reply_msg = await event.get_reply_message()
                reply_to = reply_msg.id

            # Delete the command message
            await event.delete()

            # ---- Try to send native poll ----
            try:
                poll = Poll(
                    id=0,
                    question=question,
                    answers=[PollAnswer(opt, opt) for opt in options],
                    public_voters=flags['public_voters'],
                    multiple_choice=flags['multiple_choice'],
                )
                if hasattr(poll, 'quiz'):
                    poll.quiz = flags['quiz']
                if hasattr(poll, 'correct_answer'):
                    poll.correct_answer = flags['correct_answer'] if flags['quiz'] else None
                if hasattr(poll, 'solution'):
                    poll.solution = flags['solution'] if flags['quiz'] else ''

                # Try `send_message` with poll parameter
                await client.send_message(
                    event.chat_id,
                    poll=poll,
                    reply_to=reply_to
                )
                return

            except TypeError:
                # Fallback: telethon doesn't support poll parameter
                pass

            # ---- Fallback: text-based poll ----
            text = f"📊 **{question}**\n\n"
            for i, opt in enumerate(options, 1):
                text += f"{i}. {opt}\n"
            text += f"\nReply with the number of your choice (e.g., `{1}`)."
            if flags['multiple_choice']:
                text += " You can choose multiple numbers (comma-separated)."
            await client.send_message(
                event.chat_id,
                text,
                reply_to=reply_to
            )

        except ValueError as e:
            try:
                await event.edit(f"❌ {e}")
            except Exception:
                await client.send_message(event.chat_id, f"❌ {e}")
        except Exception as e:
            try:
                await event.edit(f"❌ Error: {str(e)}")
            except Exception:
                await client.send_message(event.chat_id, f"❌ Error: {str(e)}")