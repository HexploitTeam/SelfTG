# Com/mock.py
import shlex
import random
from telethon import events
from faker import Faker

__HELP__ = (
    "!mock [options] [type] [count] → Generate mock data.\n"
    "Types: name, first_name, last_name, email, phone, address, city, country, \n"
    "  text, sentence, paragraph, job, company, date, datetime, year, month, \n"
    "  color, hex_color, rgb_color, uri, url, uuid, credit_card, iban,\n"
    "  all (or profile) → full profile (all fields).\n"
    "Options:\n"
    "  --locale <locale>  Set language (e.g., en_US, fa_IR, de_DE)\n"
    "  --count <n>        Number of items (default: 1)\n"
    "Example: !mock name 5\n"
    "         !mock --locale fa_IR address\n"
    "         !mock all --count 2\n"
    "         !mock profile --locale de_DE\n"
    "Available locales: en_US, fa_IR, de_DE, fr_FR, es_ES, it_IT, ...\n"
    "Without arguments, shows this help."
)
__CATEGORY__ = "Utilities"

# Persian cities and provinces for fa_IR locale
CITIES_IRAN = [
    "تهران", "مشهد", "اصفهان", "کرج", "شیراز", "تبریز", "قم", "اهواز", "کرمانشاه",
    "رشت", "زاهدان", "ارومیه", "همدان", "کرمان", "یزد", "اردبیل", "بندرعباس",
    "اراک", "اسلام‌شهر", "قزوین", "زنجان", "سنندج", "خرم‌آباد", "گرگان", "ساری",
    "شاهرود", "بابل", "ساوه", "کاشان", "شهرکرد", "بیرجند", "بوشهر", "ایلام",
    "نیشابور", "شهرضا", "ملارد", "بافت", "رودهن", "پردیس"
]
PROVINCES_IRAN = [
    "تهران", "خراسان رضوی", "اصفهان", "فارس", "خوزستان", "مازندران", "گیلان",
    "آذربایجان شرقی", "آذربایجان غربی", "کرمانشاه", "همدان", "کردستان", "لرستان",
    "ایلام", "بوشهر", "چهارمحال و بختیاری", "خراسان جنوبی", "خراسان شمالی",
    "سمنان", "سیستان و بلوچستان", "قزوین", "قم", "کرمان", "کهگیلویه و بویراحمد",
    "گلستان", "هرمزگان", "یزد", "اردبیل", "البرز", "مرکزی"
]

# Map of type names to faker methods
TYPE_MAP = {
    "name": "name",
    "first_name": "first_name",
    "last_name": "last_name",
    "email": "email",
    "phone": "phone_number",
    "address": "address",
    "city": "city",
    "country": "country",
    "text": "text",
    "sentence": "sentence",
    "paragraph": "paragraph",
    "job": "job",
    "company": "company",
    "date": "date",
    "datetime": "date_time",
    "year": "year",
    "month": "month_name",
    "color": "color_name",
    "hex_color": "hex_color",
    "rgb_color": "rgb_color",
    "uri": "uri",
    "url": "url",
    "uuid": "uuid4",
    "credit_card": "credit_card_number",
    "iban": "iban",
}

SPECIAL_TYPES = {"all", "profile"}

def parse_args(args):
    flags = {'locale': 'en_US', 'count': 1}
    remaining = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith('--'):
            if arg == '--locale':
                if i+1 >= len(args):
                    raise ValueError("Missing value for --locale")
                flags['locale'] = args[i+1]
                i += 2
            elif arg == '--count':
                if i+1 >= len(args):
                    raise ValueError("Missing value for --count")
                try:
                    flags['count'] = int(args[i+1])
                    if flags['count'] < 1:
                        flags['count'] = 1
                except ValueError:
                    raise ValueError("Count must be a number")
                i += 2
            else:
                raise ValueError(f"Unknown option: {arg}")
        else:
            remaining.append(arg)
            i += 1
    return flags, remaining

def generate_profile(fake, locale):
    """Generate a full profile dict with realistic Persian data if locale is fa_IR."""
    if locale == "fa_IR":
        # Custom Persian profile
        city = random.choice(CITIES_IRAN)
        province = random.choice(PROVINCES_IRAN)
        address = f"{random.randint(1, 999)} {fake.street_name()}, {city}, {province}"
        # Use Faker for other fields (they work for Persian names, etc.)
        return {
            "First Name": fake.first_name(),
            "Last Name": fake.last_name(),
            "Email": fake.email(),
            "Phone": fake.phone_number(),
            "Address": address,
            "City": city,
            "Country": "ایران",
            "Job": fake.job(),
            "Company": fake.company(),
            "Website": fake.url(),
            "UUID": fake.uuid4(),
            "Credit Card": fake.credit_card_number(),
            "Date of Birth": fake.date_of_birth().strftime("%Y-%m-%d"),
        }
    else:
        # Standard Faker for other locales
        return {
            "First Name": fake.first_name(),
            "Last Name": fake.last_name(),
            "Email": fake.email(),
            "Phone": fake.phone_number(),
            "Address": fake.address().replace("\n", ", "),
            "City": fake.city(),
            "Country": fake.country(),
            "Job": fake.job(),
            "Company": fake.company(),
            "Website": fake.url(),
            "UUID": fake.uuid4(),
            "Credit Card": fake.credit_card_number(),
            "Date of Birth": fake.date_of_birth().strftime("%Y-%m-%d"),
        }

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r'^!mock(?:\s+(.*))?$'))
    async def mock_cmd(event):
        try:
            arg_str = event.pattern_match.group(1)
            if not arg_str:
                await event.edit("📖 **Mock Help**\n" + __HELP__)
                return

            args = shlex.split(arg_str)
            flags, remaining = parse_args(args)

            mock_type = None
            count = flags['count']
            if remaining:
                mock_type = remaining[0].lower()
                if len(remaining) > 1:
                    try:
                        count = int(remaining[1])
                        if count < 1:
                            count = 1
                    except:
                        pass

            if not mock_type:
                await event.edit("❌ Please specify a type. Use `!mock` for help.")
                return

            try:
                fake = Faker(flags['locale'])
            except AttributeError:
                await event.edit(f"❌ Locale '{flags['locale']}' not available.\n"
                                 "Try: en_US, fa_IR, de_DE, fr_FR, es_ES, it_IT, ...")
                return

            # ---- Special type: "all" or "profile" ----
            if mock_type in SPECIAL_TYPES:
                data = []
                for _ in range(count):
                    profile = generate_profile(fake, flags['locale'])
                    lines = [f"{k}: {v}" for k, v in profile.items()]
                    data.append("\n".join(lines))
                output = f"📝 **Mock Profile** (locale: {flags['locale']})\n"
                output += f"📊 Count: {count}\n\n"
                if count == 1:
                    output += data[0]
                else:
                    for i, item in enumerate(data, 1):
                        output += f"--- Profile {i} ---\n{item}\n\n"
                output = output.rstrip()

                if len(output) > 4000:
                    import io
                    bio = io.BytesIO(output.encode("utf-8"))
                    bio.name = "mock_profile.txt"
                    await client.send_file(event.chat_id, bio, caption="📝 Mock Profile")
                    await event.delete()
                else:
                    await event.edit(output)
                return

            # ---- Normal types ----
            if mock_type not in TYPE_MAP:
                await event.edit(f"❌ Unknown type: {mock_type}\n"
                                 f"Available types: {', '.join(sorted(TYPE_MAP.keys()))}")
                return

            method_name = TYPE_MAP[mock_type]
            method = getattr(fake, method_name)
            data = []
            for _ in range(count):
                try:
                    data.append(str(method()))
                except Exception as e:
                    await event.edit(f"❌ Error generating data: {e}")
                    return

            output = f"📝 **Mock Data** ({mock_type})\n"
            output += f"🌍 Locale: {flags['locale']}\n"
            output += f"📊 Count: {count}\n\n"
            if count == 1:
                output += data[0]
            else:
                for i, item in enumerate(data, 1):
                    output += f"{i}. {item}\n"

            if len(output) > 4000:
                import io
                bio = io.BytesIO(output.encode("utf-8"))
                bio.name = f"mock_{mock_type}.txt"
                await client.send_file(event.chat_id, bio, caption=f"📝 Mock: {mock_type}")
                await event.delete()
            else:
                await event.edit(output)

        except ValueError as e:
            await event.edit(f"❌ {e}")
        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")