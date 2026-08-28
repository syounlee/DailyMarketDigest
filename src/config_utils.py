"""Small helpers for reading config/watchlist.yaml."""


def tickers(holdings: list[dict]) -> list[str]:
    """Extract ticker symbols from a list of watchlist holding entries.

    Each entry is a dict with at least `ticker`, plus optional per-holding
    fields (buy_date, buy_price, shares, cost) that data-fetching code
    doesn't need - only the rendering/portfolio-tracking layer would.
    """
    return [h["ticker"] for h in holdings]
