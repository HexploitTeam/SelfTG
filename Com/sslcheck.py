"""!ssl: what certificate a host presents, read with Python's own ssl module.

No external API: `ssl` and `socket` do the handshake against the target itself.
That means no quota, no cache to poison, and no third party learning which hosts
the owner is looking at. The trade-off is that the Replit container must be able
to reach port 443, which it can.

Verification is attempted first. A failure is reported as a failure and the
handshake is retried unverified, so an expired or self-signed certificate still
shows its protocol and cipher instead of a bare exception.
"""
import logging
import ssl
from datetime import datetime, timezone

from telethon import events

import Com.core.api as api
from Com.core import brand, recon
from Com.core.reply import say

__HELP__ = (
    "!ssl <host> [port] → Certificate issuer, SANs, validity, days left, "
    "protocol and cipher (local handshake, no API).\n"
    "Examples:\n"
    "  !ssl example.com\n"
    "  !ssl mail.example.com 465"
)
__CATEGORY__ = "Information"

log = logging.getLogger("selftg.sslcheck")

MAX_SANS = 12
EXPIRY_WARNING_DAYS = 15


#------------------------------
#Rendering
#------------------------------

def _fmt_date(value):
    """`Sep 26 22:49:11 2026 GMT` -> `2026-09-26`."""
    if not value:
        return "?"
    try:
        stamp = ssl.cert_time_to_seconds(value)
        return datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()
    except (ValueError, OSError, OverflowError):
        return str(value)


def _render(host, port, info):
    lines = [f"🔐 <b>TLS certificate</b> · <code>{brand.esc(host)}:{port}</code>"]

    if info.get("verify_error"):
        lines.append(
            f"❌ <b>Verification failed</b> · {brand.esc(info['verify_error'])}"
        )
        lines.append("<i>Fields below come from an unverified handshake</i>")
    else:
        lines.append("<b>Verified</b> · yes, against the system trust store")

    subject = info.get("subject_cn")
    if subject:
        lines.append(f"<b>Subject</b> · <code>{brand.esc(subject)}</code>")

    issuer = info.get("issuer_org") or info.get("issuer_cn")
    if issuer:
        issuer_line = f"<b>Issuer</b> · {brand.esc(issuer)}"
        if info.get("issuer_cn") and info.get("issuer_org"):
            issuer_line += f" ({brand.esc(info['issuer_cn'])})"
        lines.append(issuer_line)

    if info.get("not_before") or info.get("not_after"):
        lines.append(
            f"<b>Valid</b> · <code>{_fmt_date(info.get('not_before'))}</code>"
            f" → <code>{_fmt_date(info.get('not_after'))}</code>"
        )

    days = info.get("days_left")
    if days is not None:
        if days < 0:
            lines.append(f"❌ <b>Expired {-days} days ago</b>")
        elif days <= EXPIRY_WARNING_DAYS:
            lines.append(f"⚠️ <b>Expires in {days} days</b>")
        else:
            lines.append(f"<b>Expires in</b> · <code>{days} days</code>")

    sans = info.get("sans") or []
    if sans:
        lines.append(f"<b>SANs</b> · {len(sans)} name(s)")
        for name in sans[:MAX_SANS]:
            lines.append(f"<code>{brand.esc(name)}</code>")
        if len(sans) > MAX_SANS:
            lines.append(f"<i>… {len(sans) - MAX_SANS} more</i>")

    if info.get("tls_version") or info.get("cipher"):
        lines.append(
            f"<b>Protocol</b> · <code>{brand.esc(info.get('tls_version') or '?')}</code>"
            f" · <code>{brand.esc(info.get('cipher') or '?')}</code>"
        )

    lines.append("<i>local handshake · no external API</i>")
    return "\n".join(lines)


#------------------------------
#Command
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(
        from_users=my_id, pattern=r"^!ssl\s+(\S+)(?:\s+(\d+))?\s*$"))
    async def ssl_cmd(event):
        raw = event.pattern_match.group(1)
        port_raw = event.pattern_match.group(2)

        # `!ssl host:8443` is what people type; keep the port instead of
        # letting clean_host silently drop it and checking 443
        if raw.count(":") == 1 and raw.rsplit(":", 1)[1].isdigit():
            raw, embedded_port = raw.rsplit(":", 1)
            port_raw = port_raw or embedded_port

        try:
            host = recon.clean_host(raw)
        except api.APIError:
            await say(
                event,
                f"❌ <b>Not a host name or IP</b> · <code>{brand.esc(raw)}</code>",
                name="ssl",
                parse_mode="html",
            )
            return

        port = 443
        if port_raw:
            port = int(port_raw)
            if not 1 <= port <= 65535:
                await say(event, "❌ <b>Port must be between 1 and 65535.</b>",
                          name="ssl", parse_mode="html")
                return

        try:
            info = await recon.tls_probe(host, port)
        except api.APIError as exc:
            await say(
                event,
                f"❌ <b>TLS check failed.</b> {brand.esc(exc)}\n"
                f"<i>{brand.esc(host)}:{port}</i>",
                name="ssl",
                parse_mode="html",
            )
            return
        except Exception as exc:  # noqa: BLE001 - never take the client down
            log.exception("ssl: unexpected failure")
            await say(
                event,
                f"❌ <b>{brand.esc(type(exc).__name__)}</b> · {brand.esc(exc)}",
                name="ssl",
                parse_mode="html",
            )
            return

        await say(event, _render(host, port, info), name="ssl", parse_mode="html")
