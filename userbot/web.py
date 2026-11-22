"""Safe page fetcher for the read-later feature (blocks private/internal addresses)."""
import html
import ipaddress
import re
import socket
import urllib.parse

import httpx


def _check(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("bad link")
    for i in socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80)):
        if not ipaddress.ip_address(i[4][0].split("%")[0]).is_global:
            raise ValueError("blocked address")


async def fetch_text(url, limit=9000):
    cur = url
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0"}) as c:
        for _ in range(4):
            _check(cur)
            r = await c.get(cur)
            if r.is_redirect and r.headers.get("location"):
                cur = urllib.parse.urljoin(cur, r.headers["location"])
                continue
            break
        else:
            raise ValueError("too many redirects")
    if r.status_code >= 400 or not any(t in r.headers.get("content-type", "") for t in ("html", "text")):
        raise ValueError("not a readable page")
    body = r.text[:1_500_000]
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", body)
    body = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", body)
    body = html.unescape(re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", body))).strip()
    return ((f"Title: {html.unescape(title.group(1)).strip()}\n\n" if title else "") + body)[:limit]
