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
# so it's the one local address we allow. A real deployment wouldn't need this.
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


def is_hidden(tag: str, attrs: dict) -> bool:
    """Whether an element is hidden from people reading the page."""
    # TODO: treat the hidden attribute, aria-hidden="true" and hiding styles as hidden
    style = (attrs.get("style") or "").replace(" ", "").lower()
    return (
        "hidden" in attrs
        or attrs.get("aria-hidden") == "true"
        or any(hiding in style for hiding in HIDDEN_STYLES)
    )


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
        # TODO: remember whether each open element is skipped (scripts, styles) or hidden
        self.open_tags.append(tag in SKIPPED_TAGS or is_hidden(tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        if tag not in VOID_TAGS and self.open_tags:
            self.open_tags.pop()

    def handle_data(self, data: str) -> None:
        # TODO: keep text only when no open element is skipped or hidden
        if not any(self.open_tags) and data.strip():
            self.parts.append(data.strip())


def sanitize(html: str) -> str:
    """The visible text of a page, without scripts, hidden elements or comments."""
    parser = VisibleText()
    parser.feed(html)
    return "\n".join(parser.parts)


def wrap_untrusted(text: str, url: str) -> str:
    """Mark page text as untrusted data, so the model doesn't treat it as instructions."""
    # TODO: remove any copy of our tags from the page, so it can't close the block early
    text = text.replace("<untrusted_content", "&lt;untrusted_content").replace(
        "</untrusted_content", "&lt;/untrusted_content"
    )
    # TODO: wrap the text in <untrusted_content> tags that name the source
    return f'<untrusted_content source="{url}">\n{text}\n</untrusted_content>'


def check_url(url: str) -> None:
    """Refuse URLs that point inside our own network."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Blocked {url}: only http and https URLs are allowed.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if (parts.hostname, port) == SITE:
        return
    # TODO: resolve the hostname, and check every address it resolves to
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, port)}
    except socket.gaierror as error:
        raise ValueError(f"Blocked {url}: the hostname doesn't resolve.") from error
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        # TODO: reject private, loopback, link-local and other non-public addresses
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
    """Download a page, checking the URL before every request, including after redirects."""
    # TODO: follow redirects yourself, so check_url runs on every address
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url)
        response = httpx.get(url, follow_redirects=False, timeout=TIMEOUT_S)
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
