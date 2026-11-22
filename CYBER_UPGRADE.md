# Cyber command surface — upgrade report

Date: 2026-11-22. Target: Telethon 1.44.0 self-bot on Replit free tier.
Scope: the cyber/OSINT-flavoured commands and the shared helpers they need.

Every free API below was called from this workspace on the date above before it
was adopted or dropped. Where a source disagreed with the research notes in the
brief, the live result won and the source was discarded.

---

## 1. Current-state inventory

| Command | Module | What it actually did | Free source | Verdict |
|---|---|---|---|---|
| `!ip geo` | `Com/ip.py` | Geolocation, ip-api.com over plain HTTP, ipwho.is fallback | ip-api.com, ipwho.is | Working, thin: no region code, no datacenter flag, HTTP-first |
| `!ip dns` | `Com/ip.py` | One record type via local dnspython | dnspython resolver | Working, but optional dependency and no authority/SOA detail |
| `!ip resolve` | `Com/ip.py` | `getaddrinfo` in the executor | OS resolver | Working |
| `!ip reverse` | `Com/ip.py` | `socket.gethostbyaddr` | OS resolver | Working, but a PTR-only failure path |
| `!ip info` | `Com/ip.py` | geo + reverse, text-spliced | both above | Working, no network owner |
| `!ip ping` | `Com/ip.py` | `ping -c 4` subprocess | local binary | Handles "not found" and timeout; ICMP usually unavailable on Replit |
| `!ip port` | `Com/ip.py` | One TCP connect, no service name | none | Working |
| `!dnsprobe` | `Com/dnsprobe.py` | Bulk A/AAAA/MX/TXT/CNAME to a text file | dnspython resolver | Working, but every resolver call blocked the event loop |
| `!portsweep` | `Com/portsweep.py` | Sequential TCP scan, default 1–1024, from the Repl | none | Working, but 1,024 × 1 s worst case, loud, and hard to justify |
| `!subenum` | `Com/subenum.py` | crt.sh names, then one DNS lookup per name | crt.sh + OS resolver | Worked when crt.sh was up; no fallback, up to 5,000 sequential lookups |
| `!checkexp` | `Com/checkexp.py` | Own `aiohttp` session, headers printed as a Python dict, "XSS/SQLi points" from substring matches | target site | Misleading; the vulnerability lines were untrue |
| `!whois` | `Com/whois.py` | Telegram **user** lookup relayed through an owner-configured bot | a third-party Telegram bot | Not domain WHOIS. Left untouched; new domain command is `!rdap` |
| `!crypto` | `Com/crypto.py` | Coin prices | CoinGecko / CoinPaprika | Not network intelligence. Left untouched |
| `!encode`, `!decodecheck` | | Text codecs | none | Not network intelligence. Left untouched |
| `!shorturl`, `!speedtest`, `!wordlist` | | Link shortening, bandwidth, password list | | Not reconnaissance. Left untouched |

Shared helpers found: `Com/core/api.py` (cached HTTP with timeout, 429
handling, provider fallback) and `Com/core/reply.py` (edit-then-reply).
`Com/checkexp.py` was the one cyber module that bypassed the shared HTTP layer.

## 2. API verification table

| API | Free | Keyless | Limits / terms seen | Live check | Decision |
|---|---|---|---|---|---|
| ipwho.is | yes | yes | 1,000 requests/day per client IP; commercial use allowed on the free endpoint; HTTPS supported | 200, 670 B | **Primary geolocation** |
| ip-api.com | yes, non-commercial | yes | 45 req/min; HTTP only on free tier; `X-Rl: 44` header confirmed | 200, 282 B | **Fallback geolocation**, second |
| ipinfo.io | yes | yes (basic fields, no token) | tokenless use documented, `readme` field asks for a token; ~50k/month reported | 200, 304 B | **Third fallback** |
| ipapi.co | claimed | claimed | — | **HTTP 429** from this host on the first call | Discarded |
| Google DoH (`dns.google/resolve`) | yes | yes | no key, JSON | 200, MX + SOA | **Primary DNS** |
| Cloudflare DoH | yes | yes (`accept: application/dns-json`) | no key | 200, SOA | **Fallback DNS** |
| rdap.org | yes | yes | redirects to the authoritative registry | 200, domain + IP | **Primary RDAP** |
| IANA RDAP bootstrap | yes | yes | `dns.json`, `ipv4.json`, `ipv6.json` | 200 | **Fallback RDAP** |
| Shodan InternetDB | yes, non-commercial | yes, no account | ports/tags/CVEs/hostnames only; updated weekly | 200, 11 ports | **Passive port/exposure** |
| crt.sh | yes | yes | frequently overloaded | **HTTP 502 on every call during this work** | Kept as primary CT source; Cert Spotter added as fallback |
| Cert Spotter | yes | yes, anonymous | `x-ratelimit-limit: 10` (per hour, anonymous) | 200, 6.7 KB | **CT fallback** |
| Hackertarget | claimed | claimed | — | "API count exceeded" | Discarded |
| AlienVault OTX passive DNS | claimed | **no** | anonymous access now requires authentication | **HTTP 429, "Please authenticate"** | Discarded |
| Spamhaus DNSBL | yes | DNS | public-resolver queries are not permitted on the free tier | not called | Discarded |
| AbuseIPDB / VirusTotal | free tier with key | no | key required | not called | Not added |
| Python `ssl` + `socket` | yes | n/a | no quota, no third party | handshake against example.com | **TLS source** |

## 3. Upgrade decisions

* **`!ip geo`** — chain reordered to HTTPS-first: ipwho.is → ip-api.com →
  ipinfo.io. Added region, datacenter/hosting flag when the provider gives one,
  country code, ASN, rounded coordinates, and hostname resolution so
  `!ip geo example.com` answers instead of "invalid IP".
* **`!ip dns`** — now DNS over HTTPS with a 10-minute cache, Google first,
  Cloudflare second. Supports A, AAAA, MX, TXT, NS, SOA, CNAME, CAA, SRV, DS,
  PTR; explains NODATA with the SOA instead of pretending the record is missing;
  distinguishes NXDOMAIN. Drops the hard dependency on dnspython for this path.
* **`!ip resolve`** — DoH A/AAAA, so it does not depend on the platform resolver.
* **`!ip reverse`** — DoH PTR first, OS resolver only when DoH itself is down.
* **`!ip info`** — geo + reverse + the RDAP network the address belongs to.
* **`!ip port`** — fixed a real crash (`open_connection(..., timeout=)` is not a
  valid argument) and added service name, latency, and separate timeout/refused/
  unreachable messages.
* **`!ip ping`** — host now validated against a shell-safe pattern (a host
  beginning with `-` would have been read as a `ping` flag). Behaviour otherwise
  unchanged.
* **`!dnsprobe`** — resolver work moved into the executor, domains capped at 25,
  NS and SOA added, per-domain timeout, malformed `del` gets a usage message.
* **`!portsweep`** — **replaced the default path**: `!portsweep <host>` now asks
  Shodan InternetDB (passive, no traffic to the target). The real scan is
  explicit (`!portsweep <host> <range>`), capped at 256 ports, 64 concurrent,
  refuses private/loopback targets, and says where the traffic comes from.
* **`!subenum`** — crt.sh → Cert Spotter fallback, wildcard-DNS probe, bounded
  concurrent DNS validation (300 names), 500-name cap, clear "both sources
  failed" message.
* **`!checkexp`** — rewritten as a passive posture check: status, redirect chain,
  security headers with values, TLS summary, robots.txt, sitemap.xml. The
  "potential XSS/SQLi" heuristics and the fake CVE line are gone. It now uses the
  shared HTTP layer instead of its own `aiohttp` session.
* **Removed:** nothing. Every previous command name and argument form still
  routes; `!portsweep <host>` changes meaning from an active 1–1024 scan to a
  passive lookup, which is documented in `__HELP__`. `!portsweep del` still works.
* **Merged:** HTTP header inspection lives in `!checkexp` rather than a separate
  `!headers`; ASN lives in `!ip geo` rather than a separate `!asn`; reverse DNS
  lives in `!ip reverse`.

## 4. New commands

| Command | Why it earned its place | Free source | Failure path |
|---|---|---|---|
| `!rdap <domain\|IP>` | Registrar, registration/expiry dates, status, nameservers, DNSSEC and abuse contact are the first things an owner checks about a domain or netblock. Not covered by `!whois` (Telegram users) | rdap.org, then IANA bootstrap | invalid target, unknown object, both registries down |
| `!ssl <host> [port]` | Certificate issuer, SANs, validity, days-to-expiry, protocol and cipher. Catches an expired or wrong-host certificate before a user does | local `ssl`/`socket` | invalid target, refused, timeout, verification failure reported with the unverified protocol |

Deliberately **not** added:

* Separate `!asn`, `!headers`, `!reversedns` — each would duplicate a verb that
  now exists inside `!ip` / `!checkexp`.
* IP reputation / abuse score — the honest keyless sources are gone: OTX passive
  DNS now demands authentication and Spamhaus does not permit public-resolver
  queries on its free tier. InternetDB exposure data covers the useful half
  (open ports, known CVEs) without inventing a score.
* Hash lookup / breach check — no genuinely free, keyless source that is not a
  front for a paid API.
* `portscan.com` / third-party scanning — scanning someone else's target from
  someone else's infrastructure is exactly the ToS problem described in §7.
* Subdomain enumeration from a second vendor — the existing command already had
  the right idea; it needed a fallback, not a second command.

## 5. Shared HTTP layer decision

The project already had `Com/core/api.py` (one session, TTL cache, 429 →
`RateLimited`, bounded retry, `first_success`). It was kept and extended with one
function:

* `fetch_response()` — returns status, headers, bounded text and URLs without
  treating 4xx as an exception, because for `!checkexp` the status *is* the
  finding. 429 still raises.

A new shared module, `Com/core/recon.py`, holds what all the cyber commands
needed and none of them should reimplement:

* target validation (`is_ip`, `is_domain`, `clean_host`, `clean_domain`,
  `ptr_name`, `is_private`), including refusal of leading-dash and
  space-bearing hosts;
* `doh()` and `resolve_host()` over the two DoH providers;
* `rdap_lookup()` with the bootstrap fallback;
* `tls_probe()` — verified handshake first, unverified retry on verification
  failure so the owner still sees the protocol/cipher and the reason;
* small formatters (`iso_date`, `service_name`).

Every cyber command now goes through `api.py`; none opens its own session.
`Com/core/recon.py` has no `setup()` or `__HELP__`, so the loader ignores it.

## 6. Failure matrix

| Command | Scenario | User-facing answer |
|---|---|---|
| `!ip geo` | bad input | `❌ that is not a host name or IP address · <code>…</code>` |
| | unresolvable host | `❌ Could not resolve <code>host</code> · host does not exist` |
| | all providers down | `❌ Geolocation failed. ipwho.is: …; ip-api.com: …; ipinfo.io: …` + "All three free providers are down or rate limited" |
| | 429 | included in the provider list as `rate limit reached · HTTP 429 · retry in Ns` |
| `!ip dns` | unsupported type | lists the supported set |
| | NXDOMAIN | `❌ Domain does not exist.` |
| | NODATA | `No X records at this name` + the SOA |
| | both DoH down | `❌ DNS lookup failed. …` + "Both DNS over HTTPS providers failed" |
| `!ip reverse` | no PTR | `❌ No reverse DNS entry for …` |
| | DoH down, OS resolver empty | `❌ Reverse lookup failed. …` + "The platform resolver has no PTR entry either." |
| `!ip info` | unresolvable | `❌ Could not resolve …` |
| | RDAP failure | card still prints geo + reverse, with `RDAP network data unavailable` |
| `!ip ping` | no binary | `❌ ping is not installed here.` + port/portsweep hint |
| | host silent | `❌ Ping timed out.` |
| `!ip port` | closed | `❌ port N on host is closed` + "the host answered and refused" |
| | filtered | `❌ port N on host timed out` + "filtered, or the host drops silent packets" |
| `!rdap` | bad target | `❌ RDAP lookup failed. that is not a host name or IP address` |
| | unregistered | `❌ RDAP lookup failed. no RDAP record for …` |
| | registry down | provider descriptions joined, e.g. `rdap.org: server error · HTTP 502` |
| `!ssl` | bad target/port | `❌ Not a host name or IP …` / `❌ Port must be between 1 and 65535.` |
| | unreachable | `❌ TLS check failed. host does not resolve / refused the connection / timed out` |
| | verification failure | `❌ Verification failed · …` and the unverified protocol/cipher |
| `!portsweep` | bad host / range | `❌ <reason> · <code>target</code>` / usage line |
| | cloud not seen host | `🛰 No passive data …` + the exact active-scan command to run |
| | InternetDB down | `❌ Passive lookup failed. …` + retry hint |
| | >256 ports | `❌ Range too large.` + current cap and the passive alternative |
| | private target | `❌ Refusing to scan a private address …` |
| | scan already running | `❌ A scan is already running.` |
| | report undeliverable | completion message with counts + "Report file could not be sent." |
| `!checkexp` | bad domain | `❌ that is not a host name or IP address · <code>…</code>` |
| | nothing answers | `❌ Scan failed. neither HTTPS nor HTTP answered` + "nothing was saved" |
| | robots/sitemap missing | `HTTP 404` inside the report, scan still succeeds |
| `!subenum` | bad domain | `❌ that is not a host name or IP address …` |
| | both CT sources down | `❌ Both certificate-transparency sources failed` + limits |
| | no names | `❌ No certificate names found …` |
| | names but none resolve | `❌ No active subdomains found … (N CT names, none resolved)` |
| `!dnsprobe` | no argument | usage line |
| | >25 domains | `❌ Too many domains …` |
| | slow resolver | per-domain `resolver timed out` line in the report |

## 7. ToS / safety note

* **Passive by default.** `!portsweep <host>` no longer sends a packet to the
  target; it reads Shodan's public index. Shodan's InternetDB is free for
  non-commercial use only, which is the same restriction as the rest of this
  project.
* **Active scans are explicit.** The owner has to type a port range, gets a
  warning that traffic leaves from the Repl's IP, and may only scan hosts they
  own or have written permission to test. The range is capped at 256 ports and
  scans are serialised so the account cannot be used as a scan relay.
* **Private addresses are refused.** `!portsweep 10.x`, loopback, link-local and
  reserved ranges never enter the scanner, which also prevents probing Replit's
  own network.
* **Third-party CT APIs.** `!subenum` reads public certificate transparency
  logs; it does not contact the target. Anonymous Cert Spotter allows 10 requests
  an hour, so repeated scans fall back to the saved file.
* **`!checkexp` and `!ssl`** only make ordinary GET/HEAD and TLS connections to
  the named host. They send no payloads and brute-force no paths.
* **No volume or detectability change for Telegram.** This work adds no
  self-bot sends beyond the answers the owner requests; no cron jobs, no
  background polling, no extra logins.

## 8. Changes applied

**Shared helper**

| File | Change | Why | Could break |
|---|---|---|---|
| `Com/core/api.py` | added `fetch_response()` | `!checkexp` needs status/headers/redirects, not parsed JSON | nothing else calls it |
| `Com/core/recon.py` | new | validation, DoH, RDAP, TLS, formatters in one place | loader ignores it (no `setup`) |

**Upgrades**

| File | Change | Why | Could break |
|---|---|---|---|
| `Com/ip.py` | provider chain reordered/extended, DoH DNS/PTR, RDAP in `info`, coordinate rounding, port timeout fix, ping host validation, target context on errors | stale/thin command; one crash; one argument-injection path | `!ip dns` now answers from DoH rather than the local resolver; a record the local resolver had cached but DoH disagrees with will differ |
| `Com/dnsprobe.py` | executor, 25-domain cap, NS+SOA, timeouts, del usage | blocked event loop; unbounded input | pasting more than 25 domains now fails instead of running for minutes |
| `Com/portsweep.py` | passive default, explicit capped active scan, private refusal, one-scan-at-a-time, service names, fallback delivery | ToS, runtime, free-tier CPU | `!portsweep host` meaning changed; documented in help |
| `Com/subenum.py` | CT fallback, wildcard detection, concurrency, caps, clearer errors | crt.sh instability, 5,000 sequential DNS calls | a site with more than 300 names reports only the active ones among the first 300 |
| `Com/checkexp.py` | passive posture rewrite, shared HTTP layer, redirect chain, TLS, no fake vuln claims | output was raw dicts and untrue findings | report contents changed; `del <ID>` unchanged |

**New commands**

| File | Change | Why | Could break |
|---|---|---|---|
| `Com/rdap.py` | `!rdap` | domain/IP registration data, distinct from `!whois` | nothing |
| `Com/sslcheck.py` | `!ssl` | local certificate inspection | nothing |

**Incidental**

| File | Change | Why |
|---|---|---|
| `Com/ip.py` | `socket` imported at module level; dead optional dnspython guard removed | the guard was only there for the old DNS path |
| `Com/portsweep.py` | report file name/ID preserved | `del <ID>` compatibility |

## 9. Validation

Run in this workspace on 2026-11-22 with a stub Telegram client (handlers
invoked directly, no account, no messages sent) against the real free APIs:

* `tools/smoke.py` — **passes**: 111 files compile, branding checks pass, 76
  modules load and 164 handlers register. Optional modules skipped for missing
  packages (PIL, Faker, qrcode, Pygments, gTTS) as before.
* `!ip geo 8.8.8.8`, `!ip geo example.com`, `!ip geo <unresolvable>`,
  `!ip geo not_a_domain`
* `!ip dns example.com MX`, `AAAA`, `ANY` (rejected), a NODATA name
* `!ip reverse 8.8.8.8`, `1.1.1.1`
* `!ip info 1.1.1.1`, `!ip info <unresolvable>`
* `!ip port example.com 443` (open), `!ip port example.com 81` (timeout)
* `!rdap example.com`, `!rdap 8.8.8.8`, unregistered domain, `-bad` target
* `!ssl example.com`, `!ssl example.com 443`, `!ssl example.com:4443`
  (embedded port honoured; timed out), malformed host
* `!portsweep 1.1.1.1` (passive), `!portsweep example.com` (passive),
  private range refusal, 300-port range refusal, `!portsweep example.com 443`
  (active scan completed, report file sent, 443/https, 46 ms)
* `!checkexp example.com` (report inspected: status, headers, TLS, 404 robots),
  invalid domain, unresolvable domain
* `!subenum example.com` (crt.sh 502 → Cert Spotter, 2 active names, file sent)
  and its "already scanned" replay path
* `!dnsprobe example.com` (executor path, file sent)

Not tested, and not claimed:

* delivery through a real Telegram account/session, or the companion bot;
* `!subenum`'s wildcard-DNS branch (the test domain has a wildcard certificate
  but not wildcard DNS);
* a successful crt.sh response — it returned 502 for the whole session, so that
  branch was exercised only through its error handling;
* 429 handling end-to-end (no provider throttled us during the run), and
  malformed-payload handling (providers answered valid JSON);
* the InternetDB 404 ("host never seen") branch — both test hosts had data;
* portsweep active scans beyond a single port, and scans from Replit itself
  (this ran from the workspace VM, not the Repl);
* `!ip ping` on Replit, where ICMP is normally blocked.

## 10. Free-tier impact

| Command | Upstream cost | Cache | When the quota is gone |
|---|---|---|---|
| `!ip geo` | 1 call, up to 3 if providers fail | 24 h per IP | next uncached IP gets the failure card; cached answers keep working |
| `!ip dns` / `resolve` / `reverse` | 1–2 DoH calls | 10 min | failure card naming the DoH error |
| `!ip info` | geo + PTR + 1 RDAP | mix of the three | card still returns geo/reverse, notes missing RDAP |
| `!ip port`, `!ssl` | none external | none | no quota exists |
| `!rdap` | 1 call, up to 2 | 6 h | lookups fail with the provider error |
| `!portsweep` passive | 1 resolve + 1 InternetDB | 6 h | passive failure card; active scan unaffected |
| `!portsweep` active | none external | n/a | n/a; capped at 256 ports and one scan at a time |
| `!checkexp` | up to 8 requests | none | partial report, scan still saved |
| `!subenum` | 1 CT call (+1 wildcard probe) | 1 h CT, plus saved result file | falls back to Cert Spotter, then a clear error |
| `!dnsprobe` | 7 resolver queries per domain | none | per-domain `resolver timed out` lines |

Memory stays flat: no response body above 512 KiB is read by
`fetch_response()`, certificates are inspected one host at a time, and the only
growing structures are the existing `api._cache` (256 entries, earliest-expiry
eviction) and the per-run report files.

## 11. Dependency changelog

**None.** No package was added, removed or upgraded.

* `aiohttp==3.10.11` already present — the shared HTTP layer.
* `dnspython==2.6.1` already pinned — still used by `!dnsprobe`; `!ip` no longer
  imports it.
* TLS inspection uses the standard library (`ssl`, `socket`), which is why no
  `cryptography`/`certifi`/SSL-check package was added.

## 12. Remaining risks

* **crt.sh** is the most fragile dependency. It was 502 throughout this session.
  Cert Spotter covers it at 10 anonymous requests/hour; beyond that, `!subenum`
  reports the limit instead of guessing.
* **ipwho.is** is 1,000 requests/day per client IP. The Repl shares that IP with
  everything else on the host, and the 24 h cache is the main protection. If it
  runs dry, ip-api.com (45/min) and ipinfo.io answer.
* **ip-api.com** is HTTP-only and non-commercial on the free tier; the data is
  therefore visible on the wire. It is the second fallback, not the first.
* **ipinfo.io** without a token is rate-limited on an undocumented schedule. It
  is the last fallback deliberately.
* **InternetDB** is weekly, so passive ports can be days old, and it is
  non-commercial use only. For a current view the owner must run an active scan
  against a host they control.
* **RDAP** payloads differ by registry (ARIN uses `v4`, others `4`; some handles
  are ranges). The renderer tolerates both, but an unusual registry object can
  show fewer fields rather than an error.
* **Replit networking** may block outbound TCP to some ports. `!ip port` and
  active `!portsweep` then report timeouts; `!ssl` on 443 has been reliable in
  this workspace but should be confirmed on the Repl.

Suggested manual checks on the Repl before relying on these commands:
`!ip geo 8.8.8.8`, `!ip dns <own domain> TXT`, `!rdap <own domain>`,
`!ssl <own domain>`, `!portsweep <own server IP>`, and one `!subenum` against a
domain you own.
