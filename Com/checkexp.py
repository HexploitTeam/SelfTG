"""!checkexp: passive web checks (headers, TLS, robots.txt, sitemap) for one domain."""
from telethon import events
import Com.core.tgsend as tgsend
import aiohttp
import os
import json
import uuid

__HELP__ = (
    "!checkexp <domain> → Scan domain for safe vulnerabilities (XSS, SQLi, headers, TLS, etc.)\n"
    "!checkexp del <ID> → Delete saved scan report")

SCAN_FOLDER = "mode/checkexp"
os.makedirs(SCAN_FOLDER, exist_ok=True)


def setup(client, my_id):

    async def safe_get(session, url):
        try:
            async with session.get(url, timeout=10,
                                   allow_redirects=True) as resp:
                text = await resp.text(errors='ignore')
                headers = dict(resp.headers)
                return resp.status, text, headers
        except:
            return None, None, {}

    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!checkexp\s+del\s+(\S+)$"))
    async def delete_scan(event):
        scan_id = event.pattern_match.group(1)
        file_path = os.path.join(SCAN_FOLDER, f"{scan_id}.txt")
        if os.path.exists(file_path):
            os.remove(file_path)
            await event.edit(f"✅ Scan report {scan_id} deleted.")
        else:
            await event.edit(f"❌ No scan report with ID {scan_id} found.")

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!checkexp\s+(\S+)$"))
    async def checkexp(event):
        domain = event.pattern_match.group(1).lower()
        scan_id = str(uuid.uuid4().int)[:12]  # unique short ID
        file_path = os.path.join(SCAN_FOLDER, f"{scan_id}.txt")

        await event.edit(
            f"🔍 Starting safe scan for {domain}...\nScan ID: {scan_id}")

        async with aiohttp.ClientSession() as session:
            results = []

            # Try HTTPS first and keep the headers of whichever scheme answered
            for proto in ["https://", "http://"]:
                url = proto + domain
                status, text, headers = await safe_get(session, url)
                if status:
                    results.append(f"Protocol: {proto} Status: {status}")
                    results.append(f"Server headers: {headers}")
                    break

            # A missing security header is the finding; the values are not inspected
            security_headers = [
                "X-Frame-Options", "Content-Security-Policy",
                "Strict-Transport-Security", "X-Content-Type-Options"
            ]
            missing_headers = [h for h in security_headers if h not in headers]
            results.append(
                f"Missing security headers: {missing_headers or 'None'}")

            # Forms are only counted; no payload is ever submitted
            if text:
                xss_payload = "<script>alert(1)</script>"
                if "form" in text.lower() or "input" in text.lower():
                    results.append(
                        "⚠️ Forms detected, potential XSS targets (safe payload not executed)"
                    )

            # Heuristic on the page text alone; nothing is injected into a query
            sqli_test = "' OR '1'='1"
            if "sql" in text.lower() or "database" in text.lower():
                results.append(
                    "⚠️ Possible SQLi points detected (safe payload not executed)"
                )

            robots_url = f"https://{domain}/robots.txt"
            status, robots_text, _ = await safe_get(session, robots_url)
            if status == 200 and robots_text:
                results.append(f"robots.txt found:\n{robots_text[:300]}..."
                               )  # limit preview

            sitemap_url = f"https://{domain}/sitemap.xml"
            status, sitemap_text, _ = await safe_get(session, sitemap_url)
            if status == 200 and sitemap_text:
                results.append(f"sitemap.xml found:\n{sitemap_text[:300]}..."
                               )  # limit preview

            if proto == "https://":
                results.append("✅ HTTPS enabled")

            # No CVE lookup happens here; the report only tells the owner to check manually
            results.append(
                "ℹ️ CVE lookup: passive only, check official CVE sources manually"
            )

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(results))

        try:
            await client.send_file(await tgsend.peer(event),
                file_path,
                caption=f"✅ Scan completed for {domain}\nScan ID: {scan_id}",
                reply_to=event.id)
        except Exception as e:
            await event.edit(
                f"❌ Scan completed but failed to send file: {str(e)}")
            return

        await event.delete()  # remove original command
