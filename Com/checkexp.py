"""!checkexp: passive web posture for one domain.

What it answers: does the site answer, where does it redirect, which security
headers are present or missing, what certificate does it serve, and does it
publish robots.txt / sitemap.xml.

What it no longer does: the old version searched the HTML for the words "form",
"input", "sql" and "database" and printed "potential XSS targets" and "possible
SQLi points". Those lines were untrue -- no payload was ever sent, and the words
appear on almost every page -- and a false vulnerability report is worse than no
report. The scan is passive, and the report says so.

The report is still saved under `mode/checkexp/<id>.txt` and sent as a file, so
`!checkexp del <ID>` keeps working.
"""
from telethon import events
import Com.core.tgsend as tgsend
import os
import uuid
from urllib.parse import urljoin, urlsplit

import Com.core.api as api
from Com.core import brand, recon
from Com.core.reply import say

__HELP__ = (
    "!checkexp <domain> → Passive posture: reachability, redirects, security "
    "headers, TLS summary, robots.txt and sitemap.xml (no payloads sent).\n"
    "!checkexp del <ID> → Delete a saved scan report")
__CATEGORY__ = "Recon & Discovery"

SCAN_FOLDER = "mode/checkexp"
os.makedirs(SCAN_FOLDER, exist_ok=True)

MAX_REDIRECTS = 4
HEADER_PREVIEW = 120
FILE_PREVIEW = 300

SECURITY_HEADERS = (
    ("strict-transport-security", "HSTS"),
    ("content-security-policy", "CSP"),
    ("x-frame-options", "X-Frame-Options"),
    ("x-content-type-options", "X-Content-Type-Options"),
    ("referrer-policy", "Referrer-Policy"),
    ("permissions-policy", "Permissions-Policy"),
)


def setup(client, my_id):

    def first_line(text, limit=HEADER_PREVIEW):
        return " ".join((text or "").split())[:limit]

    async def fetch_chain(url):
        """Follow redirects one hop at a time; return (chain, last response)."""
        chain = []
        current = url
        response = None
        for _ in range(MAX_REDIRECTS + 1):
            response = await api.fetch_response(current, provider="site",
                                                timeout=10)
            location = response["headers"].get("location")
            chain.append((response["status"], current, location))
            if response["status"] in (301, 302, 303, 307, 308) and location:
                current = urljoin(current, location)
                continue
            break
        return chain, response

    async def probe(domain):
        """Run the passive checks; raises APIError when nothing answered."""
        for scheme in ("https://", "http://"):
            try:
                chain, response = await fetch_chain(scheme + domain)
            except api.APIError:
                continue
            return scheme, chain, response
        raise api.APIError("neither HTTPS nor HTTP answered", provider=domain)

    def security_lines(headers):
        missing = []
        present = []
        for header, label in SECURITY_HEADERS:
            value = headers.get(header)
            if value:
                present.append(f"  {label}: {first_line(value)}")
            else:
                missing.append(label)
        return missing, present

    async def tls_line(final_url):
        host = urlsplit(final_url).hostname or ""
        if not host:
            return "TLS: not checked (no host in the final URL)"
        try:
            info = await recon.tls_probe(host, 443)
        except api.APIError as exc:
            return f"TLS: unavailable ({exc})"
        issuer = info.get("issuer_org") or info.get("issuer_cn") or "unknown issuer"
        days = info.get("days_left")
        line = (f"TLS: {info.get('tls_version') or '?'} · {issuer} · "
                f"{info.get('cipher') or '?'}")
        if days is not None:
            line += f" · expires in {days} days"
        if info.get("verify_error"):
            line += f"\n  verification failed: {info['verify_error']}"
        return line

    async def fetch_text_file(url):
        try:
            response = await api.fetch_response(
                url, provider="site", timeout=8, max_bytes=2048)
        except api.APIError as exc:
            return f"  unavailable ({exc})"
        if response["status"] != 200:
            return f"  HTTP {response['status']}"
        preview = first_line(response["text"], FILE_PREVIEW)
        return f"  HTTP 200 · {preview}" if preview else "  HTTP 200 (empty)"

    async def run_scan(domain, scan_id):
        scheme, chain, response = await probe(domain)
        headers = response["headers"]
        final_url = response["url"]
        origin = f"{urlsplit(final_url).scheme}://{urlsplit(final_url).netloc}"

        lines = [
            f"Site: {domain}",
            f"Scheme tried: {scheme}",
            f"Final: {final_url}",
            f"Status: {response['status']}",
            "Redirects:",
        ]
        if chain:
            for status, url, location in chain:
                if location:
                    lines.append(f"  {status} {url} -> {location}")
                else:
                    lines.append(f"  {status} {url}")
        else:
            lines.append("  none")

        server = headers.get("server")
        content_type = headers.get("content-type")
        lines.append(f"Server: {first_line(server) if server else 'not disclosed'}")
        if content_type:
            lines.append(f"Content-Type: {first_line(content_type)}")

        missing, present = security_lines(headers)
        lines.append("Security headers:")
        lines.append(f"  missing: {', '.join(missing) if missing else 'none'}")
        if present:
            lines.extend(present)

        lines.append(await tls_line(final_url))

        lines.append("robots.txt:")
        lines.append(await fetch_text_file(origin + "/robots.txt"))
        lines.append("sitemap.xml:")
        lines.append(await fetch_text_file(origin + "/sitemap.xml"))

        lines.append("")
        lines.append("Passive checks only: no payload was sent, no path was "
                     "brute-forced.")
        lines.append(f"Scan ID: {scan_id}")

        report = "\n".join(lines)
        path = os.path.join(SCAN_FOLDER, f"{scan_id}.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(report)

        summary = (
            f"✅ <b>Scan complete</b> · {brand.esc(domain)}\n"
            f"<b>Status</b> · <code>{response['status']}</code> · "
            f"<b>missing headers</b> · {len(missing)}\n"
            f"Scan ID · <code>{brand.esc(scan_id)}</code>"
        )
        return path, summary

    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!checkexp\s+del\s+(\S+)$"))
    async def delete_scan(event):
        scan_id = event.pattern_match.group(1)
        file_path = os.path.join(SCAN_FOLDER, f"{scan_id}.txt")
        if os.path.exists(file_path):
            os.remove(file_path)
            await say(
                event,
                f"✅ <b>Scan report deleted</b> · <code>{scan_id}</code>",
                name="checkexp",
                parse_mode="html",
            )
        else:
            await say(
                event,
                f"❌ <b>No scan report with ID</b> <code>{scan_id}</code>",
                name="checkexp",
                parse_mode="html",
            )

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!checkexp\s+(\S+)$"))
    async def checkexp(event):
        raw = event.pattern_match.group(1)
        try:
            domain = recon.clean_domain(raw)
        except api.APIError as exc:
            await say(
                event,
                f"❌ <b>{brand.esc(exc)}</b> · <code>{brand.esc(raw)}</code>",
                name="checkexp",
                parse_mode="html",
            )
            return

        scan_id = str(uuid.uuid4().int)[:12]
        await say(
            event,
            f"🔍 <b>Passive scan</b> · {brand.esc(domain)}\n"
            f"<b>Scan ID</b> · <code>{scan_id}</code>",
            name="checkexp",
            parse_mode="html",
        )

        try:
            path, summary = await run_scan(domain, scan_id)
        except api.APIError as exc:
            await say(
                event,
                f"❌ <b>Scan failed.</b> {brand.esc(exc)}\n"
                f"<i>{brand.esc(domain)} · nothing was saved</i>",
                name="checkexp",
                parse_mode="html",
            )
            return
        except Exception as exc:  # noqa: BLE001 - a scan must not crash the client
            await say(
                event,
                f"❌ <b>{brand.esc(type(exc).__name__)}</b> · {brand.esc(exc)}",
                name="checkexp",
                parse_mode="html",
            )
            return

        try:
            await client.send_file(
                await tgsend.peer(event),
                path,
                caption=brand.sign(summary, "checkexp"),
                parse_mode="html",
                reply_to=event.id,
            )
        except Exception as e:  # noqa: BLE001 - the report is already on disk
            await say(
                event,
                f"❌ <b>Scan finished but the report could not be sent.</b> "
                f"{brand.esc(e)}",
                name="checkexp",
                parse_mode="html",
            )
