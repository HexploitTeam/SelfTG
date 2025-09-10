from telethon import events
import os
import importlib

__HELP__ = "!help → Lists all available commands"


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!help$"))
    async def help_cmd(event):
        help_text = "📄 Available commands:\n"
        com_folder = "Com"
        for filename in os.listdir(com_folder):
            if filename.endswith(".py") and filename != "__init__.py":
                modulename = filename[:-3]
                module = importlib.import_module(f"{com_folder}.{modulename}")
                if hasattr(module, "__HELP__"):
                    help_text += f"{module.__HELP__}\n"
        await event.edit(help_text)
