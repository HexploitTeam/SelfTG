"""!rdap: domain and IP registration data from RDAP, the WHOIS replacement.

`!whois` in this project is a Telegram user lookup relay, not a domain tool, so
this is a separate command rather than a rewrite of that one.

RDAP is served by the registries themselves as JSON, which is why this reads far
better than WHOIS text: the registrar, the abuse contact, the events and the
nameservers are fields, not lines to be scraped. Free, keyless, no quota worth
tracking. `Com/core/recon.py` tries rdap.org first and the IANA bootstrap file
second, so a domain is always asked of the registry that holds it.
"""
import logging

from telethon import events

import Com.core.api as api
from Com.core import brand, recon
from Com.core.reply import say

__HELP__ = (
    "!rdap <domain|IP> → Registration data from RDAP (registrar, dates, "
    "nameservers, abuse contact).\n"
    "Examples:\n"
    "  !rdap example.com\n"
    "  !rdap 8.8.8.8"
)
__CATEGORY__ = "Information"

log = logging.getLogger("selftg.rdap")

EVENT_LABELS = {
    "registration": "Registered",
    "expiration": "Expires",
    "last changed": "Updated",
    "last update of RDAP database": "RDAP updated",
    "transfer": "Transferred",
}

MAX_STATUS = 4
MAX_NAMESERVERS = 6


#------------------------------
#Entity helpers
#------------------------------

def _walk_entities(entity):
    """Yield `entity` and every nested entity."""
    if not isinstance(entity, dict):
        return
    yield entity
    for nested in entity.get("entities") or []:
        yield from _walk_entities(nested)


def _vcard_value(entity, field):
    """One vCard field (`fn`, `email`) as a string, or None."""
    vcard = entity.get("vcardArray") or []
    if len(vcard) < 2 or not isinstance(vcard[1], list):
        return None
    for item in vcard[1]:
        if not isinstance(item, list) or len(item) < 4:
            continue
        if item[0] != field:
            continue
        value = item[3]
        if isinstance(value, list):
            value = " ".join(str(part) for part in value)
        return str(value)
    return None


def _role_value(data, role, field="fn"):
    """First non-empty vCard `field` among entities holding `role`."""
    for entity in _walk_entities(data):
        roles = entity.get("roles") or []
        if role in roles:
            value = _vcard_value(entity, field)
            if value:
                return value
    return None


def _events(data):
    """Map registered/expires/updated to ISO dates."""
    found = {}
    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue
        label = EVENT_LABELS.get(str(event.get("eventAction") or "").lower())
        if label and label not in found:
            found[label] = recon.iso_date(event.get("eventDate"))
    return found


#------------------------------
#Rendering
#------------------------------

def _render_domain(data):
    name = data.get("unicodeName") or data.get("ldhName") or "unknown"
    lines = [
        f"🌐 <b>RDAP · domain</b> · <code>{brand.esc(name)}</code>",
    ]

    registrar = _role_value(data, "registrar")
    if registrar:
        lines.append(f"<b>Registrar</b> · {brand.esc(registrar)}")

    events = _events(data)
    for label in ("Registered", "Expires", "Updated"):
        if events.get(label):
            lines.append(f"<b>{label}</b> · <code>{brand.esc(events[label])}</code>")

    statuses = data.get("status") or []
    if statuses:
        shown = ", ".join(str(s) for s in statuses[:MAX_STATUS])
        if len(statuses) > MAX_STATUS:
            shown += f" (+{len(statuses) - MAX_STATUS})"
        lines.append(f"<b>Status</b> · {brand.esc(shown)}")

    nameservers = [
        ns.get("ldhName") for ns in data.get("nameservers") or []
        if isinstance(ns, dict) and ns.get("ldhName")
    ]
    if nameservers:
        lines.append("<b>Nameservers</b>")
        for nameserver in nameservers[:MAX_NAMESERVERS]:
            lines.append(f"<code>{brand.esc(nameserver)}</code>")
        if len(nameservers) > MAX_NAMESERVERS:
            lines.append(f"<i>… {len(nameservers) - MAX_NAMESERVERS} more</i>")

    secure = (data.get("secureDNS") or {}).get("delegationSigned")
    if secure is not None:
        lines.append(f"<b>DNSSEC</b> · {'signed' if secure else 'unsigned'}")

    abuse = _role_value(data, "abuse", "email")
    if abuse:
        lines.append(f"<b>Abuse</b> · <code>{brand.esc(abuse)}</code>")

    lines.append("<i>source: RDAP · cached 6h</i>")
    return "\n".join(lines)


def _render_ip(data):
    name = data.get("name") or data.get("handle") or "unknown"
    lines = [f"🔎 <b>RDAP · network</b> · <code>{brand.esc(name)}</code>"]

    if data.get("handle") and data.get("handle") != name:
        lines.append(f"<b>Handle</b> · <code>{brand.esc(data['handle'])}</code>")

    if data.get("startAddress") and data.get("endAddress"):
        lines.append(
            f"<b>Range</b> · <code>{brand.esc(data['startAddress'])} – "
            f"{brand.esc(data['endAddress'])}</code>"
        )
    if data.get("ipVersion"):
        # ARIN says "v4"; other registries say "4"
        version = str(data["ipVersion"]).lstrip("vV")
        lines.append(f"<b>Version</b> · IPv{brand.esc(version)}")
    if data.get("country"):
        lines.append(f"<b>Country</b> · {brand.esc(data['country'])}")
    if data.get("type"):
        lines.append(f"<b>Type</b> · {brand.esc(data['type'])}")

    events = _events(data)
    for label in ("Registered", "Updated"):
        if events.get(label):
            lines.append(f"<b>{label}</b> · <code>{brand.esc(events[label])}</code>")

    abuse = _role_value(data, "abuse", "email")
    if abuse:
        lines.append(f"<b>Abuse</b> · <code>{brand.esc(abuse)}</code>")

    lines.append("<i>source: RDAP · cached 6h</i>")
    return "\n".join(lines)


#------------------------------
#Lookup
#------------------------------

async def lookup(target):
    """Human-readable RDAP card for a domain or an IP."""
    if recon.is_ip(target):
        kind = "ip"
    else:
        kind = "domain"

    data = await recon.rdap_lookup(kind, target)
    if "objectClassName" not in data:
        return (
            f"❌ <b>RDAP returned no object for</b> "
            f"<code>{brand.esc(target)}</code>"
        )
    return _render_ip(data) if kind == "ip" else _render_domain(data)


#------------------------------
#Command
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!rdap(?:\s+(\S+))?$"))
    async def rdap_cmd(event):
        raw = event.pattern_match.group(1)
        if not raw:
            await say(
                event,
                "❌ Usage: <code>!rdap &lt;domain|IP&gt;</code>",
                name="rdap",
                parse_mode="html",
            )
            return

        try:
            target = recon.clean_host(raw)
            message = await lookup(target)
        except api.APIError as exc:
            await say(
                event,
                f"❌ <b>RDAP lookup failed.</b> {brand.esc(exc)}\n"
                f"<i>Target · {brand.esc(raw)}</i>",
                name="rdap",
                parse_mode="html",
            )
            return
        except Exception as exc:  # noqa: BLE001 - a lookup must not crash the client
            log.exception("rdap: unexpected failure")
            await say(
                event,
                f"❌ <b>{brand.esc(type(exc).__name__)}</b> · {brand.esc(exc)}",
                name="rdap",
                parse_mode="html",
            )
            return

        await say(event, message, name="rdap", parse_mode="html")
