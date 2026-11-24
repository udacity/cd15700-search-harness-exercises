"""MCP server that gives an agent historical exchange rates, from the Frankfurter API."""

from __future__ import annotations

import httpx
from fastmcp import FastMCP

RATES_URL = "https://api.frankfurter.dev/v1"

mcp = FastMCP("rates")


@mcp.tool
def get_rate(date: str, from_currency: str, to_currency: str) -> dict:
    """The exchange rate between two currencies on a date. On a weekend or holiday,
    it returns the rate from the last working day before it.

    Args:
        date: The date, as YYYY-MM-DD.
        from_currency: The currency to convert from, e.g. "USD".
        to_currency: The currency to convert to, e.g. "EUR".
    """
    response = httpx.get(f"{RATES_URL}/{date}", params={"base": from_currency, "symbols": to_currency}, timeout=30)
    response.raise_for_status()
    data = response.json()
    return {"date": data["date"], "from": from_currency, "to": to_currency, "rate": data["rates"][to_currency]}


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
