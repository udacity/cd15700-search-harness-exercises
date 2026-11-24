"""MCP server for competitor research, with a naive fetch and a hardened one.

The hardened fetch removes hidden content from the HTML, marks the page as
untrusted, and refuses addresses inside our own network.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx
from fastmcp import FastMCP

# The fixture server stands in for the public web. It runs locally
# so it's the one local address we allow.
SITE = ("127.0.0.1", 8766)
SEARCH_URL = "http://127.0.0.1:8766/search"
MAX_PAGE_CHARS = 12_000
MAX_REDIRECTS = 5
TIMEOUT_S = 5

SKIPPED_TAGS = {"script", "style", "noscript", "template", "iframe", "object", "svg"}
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}
HIDDEN_STYLES = ("display:none", "visibility:hidden", "font-size:0", "opacity:0")

mcp = FastMCP("web")


@mcp.tool
def search(query: str) -> list[dict]:
    """Search the web. Returns the title, URL and a short snippet of each result,
    not the full pages. Use fetch to read the pages worth reading.

    Args:
        query: What to search for, e.g. "Acme Analytics pricing".
    """
    response = httpx.get(SEARCH_URL, params={"q": query}, timeout=TIMEOUT_S)
    response.raise_for_status()
    return response.json()["results"]


def all_text(html: str) -> str:
    """Every piece of text on a page, as a naive scraper sees it. The tags are
    removed, but the text of comments, scripts and hidden elements is kept, so
    nothing shows that it was hidden."""
    html = html.replace("<!--", " ").replace("-->", " ")
    lines = re.sub(r"<[^>]+>", " ", html).splitlines()
    return "\n".join(" ".join(line.split()) for line in lines if line.strip())


@mcp.tool
def naive_fetch(url: str) -> str:
    """Read the text of one web page.

    Args:
        url: The full address of the page.
    """
    response = httpx.get(url, follow_redirects=True, timeout=TIMEOUT_S)
    response.raise_for_status()
    return all_text(response.text)[:MAX_PAGE_CHARS]


def is_hidden(attrs: dict) -> bool:
    """Whether an element is hidden from people reading the page."""
    # TODO Step 1: get the element's style without spaces and in lowercase, so "Display: None"
    # matches "display:none".
    # An element without a style attribute has an empty style.
    style = (attrs.get("style") or "").replace(" ", "").lower()
    # TODO Step 2: the element is hidden when it has the hidden attribute, aria-hidden="true", or
    # one of the HIDDEN_STYLES in its style.
    hidden = (
        "hidden" in attrs
        or attrs.get("aria-hidden") == "true"
        or any(hiding in style for hiding in HIDDEN_STYLES)
    )
    return hidden


class VisibleText(HTMLParser):
    """Collect only the text a person would see. Comments are dropped, because
    HTMLParser only passes them to handle_comment, which we don't keep."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.open_tags: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in VOID_TAGS:
            return
        # TODO: add to open_tags whether this element is skipped (a tag in SKIPPED_TAGS) or hidden.
        # handle_endtag removes it when the element closes, so open_tags always describes the
        # elements around the text being read.
        # Hint: attrs arrives as a list of (name, value) pairs:
        # https://docs.python.org/3/library/html.parser.html#html.parser.HTMLParser.handle_starttag
        self.open_tags.append(tag in SKIPPED_TAGS or is_hidden(dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        if tag not in VOID_TAGS and self.open_tags:
            self.open_tags.pop()

    def handle_data(self, data: str) -> None:
        # TODO: add the text, stripped, to parts, unless it's empty or one of the open elements
        # is skipped or hidden.
        if not any(self.open_tags) and data.strip():
            self.parts.append(data.strip())


def sanitize(html: str) -> str:
    """The visible text of a page, without scripts, hidden elements or comments."""
    parser = VisibleText()
    parser.feed(html)
    return "\n".join(parser.parts)


def wrap_untrusted(text: str, url: str) -> str:
    """Mark page text as untrusted data, so the model doesn't treat it as instructions."""
    # TODO Step 1: a page could close our block early by containing "</untrusted_content>"
    # itself. Escape any copy of our opening or closing tag in the text, for example by
    # replacing its "<" with "&lt;".
    text = text.replace("<untrusted_content", "&lt;untrusted_content").replace(
        "</untrusted_content", "&lt;/untrusted_content"
    )
    # TODO Step 2: return the text wrapped in tags that name its source, like:
    # <untrusted_content source="https://example.com/pricing">
    # ...the page text...
    # </untrusted_content>
    text_with_tags = f'<untrusted_content source="{url}">\n{text}\n</untrusted_content>'
    return text_with_tags


def resolve(
    hostname: str, port: int
) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every address a hostname resolves to. An IPv4 address wrapped in an IPv6 one, like
    ::ffff:127.0.0.1, comes back as the IPv4 address it wraps, so it's checked as one."""
    try:
        infos = socket.getaddrinfo(hostname, port)
    except socket.gaierror as error:
        raise ValueError(f"Blocked: {hostname} doesn't resolve.") from error
    addresses = set()
    for info in infos:
        # An IPv6 address can end with a network interface, like fe80::1%eth0.
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        addresses.add(ip)
    return addresses


def check_url(url: str) -> None:
    """Refuse URLs that point inside our own network."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Blocked {url}: only http and https URLs are allowed.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if (parts.hostname, port) == SITE:
        return
    # TODO: raise a ValueError that says why the URL was blocked when any address the hostname
    # resolves to, from resolve(), isn't public: private, loopback, link-local, unspecified,
    # reserved or multicast.
    # Hint: https://docs.python.org/3/library/ipaddress.html#ipaddress.IPv4Address.is_private
    for ip in resolve(parts.hostname, port):
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_unspecified
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise ValueError(
                f"Blocked {url}: it resolves to {ip}, which isn't a public address."
            )


def get_checked(url: str) -> str:
    """Download a page, checking the URL before every request, including after redirects.

    A redirect is a server's answer that a page has moved, with the new address in its
    Location header. An attacker can pass a URL that check_url allows and that redirects inside
    our network, like http://127.0.0.1:8766/redirect?to=http://127.0.0.1:8767/admin. If httpx
    followed redirects itself, check_url would only check the URL the agent asked for, never
    the internal address it redirects to.
    """
    # One request for the page, plus one for each redirect, up to MAX_REDIRECTS.
    for _ in range(MAX_REDIRECTS + 1):
        # TODO Step 1: check the URL with check_url, then download it without following redirects.
        # Hint: https://www.python-httpx.org/quickstart/#redirection-and-history
        check_url(url)
        response = httpx.get(url, follow_redirects=False, timeout=TIMEOUT_S)
        # TODO Step 2: when the response is a redirect, move to the URL in its Location header and
        # go round the loop again. Otherwise, return the page's text.
        # Hint: the Location can be relative to the current URL:
        # https://docs.python.org/3/library/urllib.parse.html#urllib.parse.urljoin
        if response.is_redirect:
            url = urljoin(url, response.headers["location"])
            continue
        response.raise_for_status()
        return response.text
    raise ValueError(f"Blocked {url}: too many redirects.")


@mcp.tool
def fetch(url: str) -> str:
    """Read the visible text of one web page, marked as untrusted content.

    Args:
        url: The full address of the page.
    """
    return wrap_untrusted(sanitize(get_checked(url))[:MAX_PAGE_CHARS], url)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
