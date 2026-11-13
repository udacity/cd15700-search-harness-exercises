"""MCP server that gives an agent historical exchange rates from the Frankfurter API,
with a rate limiter and a cache, so the agent can't flood the API.

The cache answers a rate we already have without calling the API at all:
a past exchange rate never changes.
"""

from __future__ import annotations

import time

import httpx
from fastmcp import FastMCP

RATES_URL = "https://api.frankfurter.dev/v1"
BUCKET_SIZE = 5
REFILL_PER_S = 1.0
MAX_WAIT_S = 3.0

mcp = FastMCP("rates")


class TokenBucket:
    """A rate limiter. The bucket holds up to `size` tokens, each API call takes one, and
    tokens come back at `refill_per_s` a second. So the agent can make a short burst of
    calls, but not a steady flood.
    """

    def __init__(self, size: int, refill_per_s: float) -> None:
        self.size = size
        self.refill_per_s = refill_per_s
        self.tokens = float(size)
        self.last_refill = time.monotonic()

    def refill(self) -> None:
        """Add the tokens earned since the last refill, without going over the bucket's size."""
        now = time.monotonic()
        # TODO: add refill_per_s tokens for every second since last_refill, up to size,
        # and move last_refill to now.
        self.tokens = min(self.size, self.tokens + (now - self.last_refill) * self.refill_per_s)
        self.last_refill = now

    def take(self, max_wait_s: float) -> bool:
        """Take a token for one API call. If the bucket is empty, wait for one, but give up
        after max_wait_s. Returns whether we got a token."""
        # TODO: refill, then take a token if there is a whole one. If not, sleep a little and
        # try again, until max_wait_s has passed.
        deadline = time.monotonic() + max_wait_s
        while True:
            self.refill()
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)


# One bucket and one cache for the whole server: they last as long as the server runs.
bucket = TokenBucket(BUCKET_SIZE, REFILL_PER_S)
cache: dict[tuple[str, str, str], dict] = {}


@mcp.tool
def get_rate(date: str, from_currency: str, to_currency: str) -> dict:
    """The exchange rate between two currencies on a date. On a weekend or holiday,
    it returns the rate from the last working day before it.

    Args:
        date: The date, as YYYY-MM-DD.
        from_currency: The currency to convert from, e.g. "USD".
        to_currency: The currency to convert to, e.g. "EUR".
    """
    key = (date, from_currency.upper(), to_currency.upper())
    # TODO Step 1: if the cache already has this rate, return it, marked as cached.
    if key in cache:
        return {**cache[key], "cached": True}
    # TODO Step 2: otherwise take a token from the bucket. Without one, tell the model to wait
    # and try again.
    if not bucket.take(MAX_WAIT_S):
        return {"error": "Too many rate requests. Wait a moment, then try again."}
    # TODO Step 3: call the API, save the rate in the cache, and return it.
    response = httpx.get(
        f"{RATES_URL}/{date}", params={"base": key[1], "symbols": key[2]}, timeout=30
    )
    response.raise_for_status()
    data = response.json()
    cache[key] = {
        "date": data["date"],
        "from": key[1],
        "to": key[2],
        "rate": data["rates"][key[2]],
    }
    return {**cache[key], "cached": False}


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
