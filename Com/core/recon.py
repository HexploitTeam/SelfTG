"""Keyless network-intelligence helpers shared by the cyber commands.

What lives here, and why
------------------------
`!ip`, `!rdap`, `!ssl`, `!checkexp`, `!portsweep` and `!subenum` all need the
same three things: a strict validator for the target the owner typed, DNS over
HTTPS, and a TLS handshake that reports instead of raising. Before this module
each command would have grown its own copy, and copies drift -- one accepts
`http://host/path`, another passes a host straight into `ping`, a third turns a
missing PTR into an exception.

Everything here is keyless and free:

* DNS over HTTPS, Google first and Cloudflare second. No dnspython requirement,
  no UDP/53 assumption, and the JSON also carries the SOA in the authority
  section, which is what an empty answer should explain itself with.
* RDAP, through rdap.org and then the IANA bootstrap file, so a domain is looked
  up at the registry that actually holds it rather than at a hardcoded WHOIS
  server.
* TLS, with Python's own `ssl` and `socket`. No third party sees the target and
  there is no quota; verification failure is retried unverified so the owner
  still learns the issuer and the expiry.

Failure behaviour
-----------------
`api.APIError` is the only exception that leaves this module; a malformed
upstream payload is an APIError too. Callers catch that one type and answer with
a sentence. Nothing here prints, edits or sends anything.

This module has no `setup()` and no `__HELP__`: main.py imports it during the
command scan and registers nothing for it.
"""
import asyncio
import ipaddress
import logging
import re
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import quote

import Com.core.api as api

log = logging.getLogger("selftg.recon")

#------------------------------
#Limits
#------------------------------

DOH_CACHE_TTL = 600          # 10 min; DNS answers move, but not per message
RDAP_CACHE_TTL = 6 * 3600    # registration data changes on a scale of days
BOOTSTRAP_CACHE_TTL = 24 * 3600
TLS_TIMEOUT = 8
MAX_ADDRESSES = 8

DOH_PROVIDERS = (
    ("dns.google", "https://dns.google/resolve", None),
    ("cloudflare-dns.com", "https://cloudflare-dns.com/dns-query",
     {"accept": "application/dns-json"}),
)

DOH_TYPES = {
    "A", "AAAA", "CAA", "CNAME", "DS", "MX", "NS", "PTR", "SOA", "SRV", "TXT",
}

DNS_BOOTSTRAP = "https://data.iana.org/rdap/dns.json"
IPV4_BOOTSTRAP = "https://data.iana.org/rdap/ipv4.json"
IPV6_BOOTSTRAP = "https://data.iana.org/rdap/ipv6.json"
RDAP_ORG = "https://rdap.org"

# Same rule the old `!ip` used, plus the length bounds a real name has.
# Underscores are allowed because `_dmarc` and `_acme-challenge` are real names.
_DOMAIN_LABEL = re.compile(r"^(?!-)[A-Za-z0-9_-]{1,63}(?<!-)$")

# Shell-safe host characters; a leading dash is rejected separately because
# `ping -c 4 <host>` would read it as a flag
_HOST = re.compile(r"^[A-Za-z0-9._:-]+$")


#------------------------------
#Validation
#------------------------------

def is_ip(value):
    """True for a literal IPv4/IPv6 address."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def is_domain(value):
    """True for a syntactically valid DNS name (not an IP)."""
    value = (value or "").strip().rstrip(".")
    if not value or len(value) > 253:
        return False
    labels = value.split(".")
    if len(labels) < 2 or not all(_DOMAIN_LABEL.match(label) for label in labels):
        return False
    # A TLD is letters (or an IDN punycode label), never a bare number
    return bool(re.match(r"^(?:[A-Za-z]{2,63}|xn--[A-Za-z0-9-]{2,59})$", labels[-1]))


def is_host(value):
    """True when `value` is a domain or an IP the commands may target."""
    return is_domain(value) or is_ip(value)


def clean_host(value):
    """Normalise owner input to a bare host, or raise APIError.

    Accepts a pasted URL, a `host:port` pair or a bare name; refuses anything
    that would change the meaning of a command line, such as a leading dash or
    a space.
    """
    raw = (value or "").strip()
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    raw = raw.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if raw.startswith("["):                       # [v6]:port
        raw = raw[1:].split("]", 1)[0]
    elif raw.count(":") == 1:                     # host:port
        raw = raw.split(":", 1)[0]
    if raw.startswith("-") or not _HOST.match(raw):
        raise api.APIError("that is not a host name or IP address")
    if not is_host(raw):
        raise api.APIError("that is not a host name or IP address")
    return raw


def clean_domain(value):
    """Normalise owner input to a bare domain, or raise APIError."""
    host = clean_host(value).rstrip(".").lower()
    if not is_domain(host):
        raise api.APIError("that is not a domain name")
    return host


def ptr_name(value):
    """The in-addr.arpa / ip6.arpa name for an address."""
    try:
        return ipaddress.ip_address(value).reverse_pointer
    except ValueError:
        raise api.APIError("that is not an IP address") from None


def is_private(value):
    """True for loopback, private, link-local and other non-public addresses."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (address.is_private or address.is_loopback or address.is_link_local
            or address.is_reserved or address.is_multicast)


#------------------------------
#DNS over HTTPS
#------------------------------

async def doh(name, record_type="A"):
    """Resolve `name` and return a small result dict.

    Keys: ``status`` (``ok``, ``nodata`` or ``nxdomain``), ``answers`` (list of
    strings), ``ttl``, ``provider`` and ``authority`` (SOA text when the answer
    is empty, which is what makes a NODATA reply explain itself).
    """
    record_type = (record_type or "A").upper()
    if record_type not in DOH_TYPES:
        raise api.APIError(
            f"unsupported record type {record_type}; "
            f"use one of {', '.join(sorted(DOH_TYPES))}"
        )

    last_error = None
    for label, url, headers in DOH_PROVIDERS:
        try:
            data = await api.fetch_json(
                url,
                params={"name": name, "type": record_type},
                provider=label,
                cache_ttl=DOH_CACHE_TTL,
                timeout=8,
                headers=headers,
            )
        except api.APIError as exc:
            last_error = exc
            log.info("doh: %s failed for %s %s (%s)", label, name,
                     record_type, exc.describe())
            continue

        if not isinstance(data, dict):
            last_error = api.APIError("unexpected DNS payload", provider=label)
            continue

        status = data.get("Status")
        if status == 3:
            return {"status": "nxdomain", "answers": [], "ttl": None,
                    "provider": label, "authority": []}
        if status != 0:
            last_error = api.APIError(
                f"resolver returned status {status}", provider=label
            )
            continue

        answer = data.get("Answer") or []
        answers = []
        ttl = None
        for entry in answer:
            if not isinstance(entry, dict):
                continue
            value = entry.get("data")
            if value:
                answers.append(str(value))
                if ttl is None:
                    ttl = entry.get("TTL")
        authority = [
            str(entry.get("data"))
            for entry in (data.get("Authority") or [])
            if isinstance(entry, dict) and entry.get("data")
        ]
        return {
            "status": "ok" if answers else "nodata",
            "answers": answers,
            "ttl": ttl,
            "provider": label,
            "authority": authority,
        }

    raise last_error or api.APIError("every DoH provider failed", provider="doh")


async def resolve_host(host):
    """Return `host`'s addresses as strings; raise APIError if it has none."""
    if is_ip(host):
        return [host]
    if not is_domain(host):
        raise api.APIError("that is not a host name or IP address")

    addresses = []
    for record_type in ("A", "AAAA"):
        result = await doh(host, record_type)
        if result["status"] == "nxdomain":
            raise api.APIError(f"{host} does not exist", provider="doh")
        if result["status"] == "ok":
            addresses.extend(result["answers"])
        if len(addresses) >= MAX_ADDRESSES:
            break

    unique = []
    for address in addresses:
        if address not in unique:
            unique.append(address)
    if not unique:
        raise api.APIError(f"{host} has no A or AAAA record", provider="doh")
    return unique[:MAX_ADDRESSES]


#------------------------------
#RDAP
#------------------------------

async def _bootstrap_url(kind, value):
    """Registry base URL for `value`, from the IANA bootstrap files."""
    if kind == "domain":
        tld = value.rsplit(".", 1)[-1].lower()
        data = await api.fetch_json(
            DNS_BOOTSTRAP, provider="iana-rdap",
            cache_ttl=BOOTSTRAP_CACHE_TTL, timeout=12,
        )
        for service in data.get("services") or []:
            if len(service) != 2:
                continue
            keys, urls = service
            if tld in [str(key).lower() for key in keys] and urls:
                return str(urls[0])
        raise api.APIError(f"no RDAP registry publishes .{tld}", provider="iana-rdap")

    address = ipaddress.ip_address(value)
    source = IPV4_BOOTSTRAP if address.version == 4 else IPV6_BOOTSTRAP
    data = await api.fetch_json(
        source, provider="iana-rdap", cache_ttl=BOOTSTRAP_CACHE_TTL, timeout=12
    )
    best = None
    for service in data.get("services") or []:
        if len(service) != 2:
            continue
        keys, urls = service
        if not urls:
            continue
        for key in keys:
            try:
                network = ipaddress.ip_network(str(key), strict=False)
            except ValueError:
                continue
            if address in network and (best is None
                                       or network.prefixlen > best[0].prefixlen):
                best = (network, str(urls[0]))
    if best:
        return best[1]
    raise api.APIError("no RDAP registry covers that address", provider="iana-rdap")


async def rdap_lookup(kind, value):
    """Fetch RDAP JSON for a ``domain`` or ``ip``.

    rdap.org is tried first because it redirects to the authoritative registry;
    the IANA bootstrap is the fallback for when the redirector is down.
    """
    if kind not in ("domain", "ip"):
        raise api.APIError(f"unknown RDAP object type {kind!r}")

    async def via_org():
        return await api.fetch_json(
            f"{RDAP_ORG}/{kind}/{quote(value, safe='')}",
            provider="rdap.org", cache_ttl=RDAP_CACHE_TTL, timeout=20, retries=1,
        )

    async def via_registry():
        base = await _bootstrap_url(kind, value)
        url = base.rstrip("/") + f"/{kind}/{quote(value, safe='')}"
        return await api.fetch_json(
            url, provider="RDAP registry", cache_ttl=RDAP_CACHE_TTL,
            timeout=20, retries=1,
        )

    failures = []
    for label, factory in (("rdap.org", via_org), ("registry", via_registry)):
        try:
            data = await factory()
        except api.APIError as exc:
            failures.append(exc)
            log.info("rdap: %s failed for %s %s (%s)", label, kind, value,
                     exc.describe())
            continue
        if not isinstance(data, dict):
            raise api.APIError("RDAP returned an unexpected payload",
                               provider="rdap")
        return data

    # Both registries saying 404 is an answer: the object is not registered
    if failures and all(exc.status == 404 for exc in failures):
        raise api.APIError(f"no RDAP record for {value}", provider="rdap")
    raise api.APIError(
        "; ".join(exc.describe() for exc in failures) or "RDAP lookup failed",
        provider="rdap",
    )


#------------------------------
#TLS
#------------------------------

def _cert_field(cert, field):
    """Flatten ssl's nested subject/issuer tuples into one string."""
    for rdn in cert.get(field) or []:
        for key, value in rdn:
            if key == "commonName":
                return value
    return None


def _cert_org(cert):
    for rdn in cert.get("issuer") or []:
        for key, value in rdn:
            if key == "organizationName":
                return value
    return None


def _probe_sync(host, port, timeout, verify):
    context = ssl.create_default_context()
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            cert = tls.getpeercert() or {}
            not_after = cert.get("notAfter")
            days_left = None
            if not_after:
                try:
                    expires = ssl.cert_time_to_seconds(not_after)
                    days_left = int(
                        (expires - datetime.now(timezone.utc).timestamp()) // 86400
                    )
                except ValueError:
                    days_left = None
            sans = [value for kind, value in cert.get("subjectAltName") or []
                    if kind == "DNS"]
            return {
                "subject_cn": _cert_field(cert, "subject"),
                "issuer_cn": _cert_field(cert, "issuer"),
                "issuer_org": _cert_org(cert),
                "sans": sans,
                "not_before": cert.get("notBefore"),
                "not_after": not_after,
                "days_left": days_left,
                "tls_version": tls.version(),
                "cipher": (tls.cipher() or [None])[0],
                "verify_error": None,
            }


async def tls_probe(host, port=443, timeout=TLS_TIMEOUT):
    """Inspect the certificate `host:port` presents.

    Verification is attempted first. If it fails the handshake is retried
    without verification, so the owner sees both the failure and the issuer
    instead of a bare exception. Certificate fields are empty in that case:
    Python does not expose an unverified certificate as a dict.
    """
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _probe_sync, host, port, timeout, True),
            timeout + 4,
        )
    except ssl.SSLCertVerificationError as exc:
        verify_error = getattr(exc, "verify_message", None) or str(exc)
    except asyncio.TimeoutError:
        raise api.APIError(f"TLS handshake with {host}:{port} timed out",
                           provider="tls") from None
    except socket.gaierror:
        raise api.APIError(f"{host} does not resolve", provider="tls") from None
    except ConnectionRefusedError:
        raise api.APIError(f"{host}:{port} refused the connection",
                           provider="tls") from None
    except ssl.SSLError as exc:
        raise api.APIError(f"TLS handshake failed ({exc.reason or exc})",
                           provider="tls") from None
    except OSError as exc:
        raise api.APIError(f"{host}:{port} is unreachable ({exc.strerror or exc})",
                           provider="tls") from None

    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(None, _probe_sync, host, port, timeout, False),
            timeout + 4,
        )
    except Exception as exc:  # noqa: BLE001 - the first error is the useful one
        raise api.APIError(
            f"TLS handshake failed: {verify_error} ({type(exc).__name__})",
            provider="tls",
        ) from None
    info["verify_error"] = verify_error
    return info


#------------------------------
#Formatting
#------------------------------

def iso_date(value):
    """`2026-08-19T14:34:18-04:00` -> `2026-08-19`; anything else unchanged."""
    if not value:
        return "N/A"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return str(value)


def service_name(port):
    """TCP service name for a port, or None when the platform has no entry."""
    try:
        return socket.getservbyport(port, "tcp")
    except OSError:
        return None
