import yfinance as yf


def fetch_quotes(tickers: list[str]) -> list[dict]:
    """Fetch current price, prior close, % change, and volume for each ticker.

    Works identically for US tickers (AAPL) and Korean tickers (005930.KS,
    000660.KQ) since yfinance resolves the exchange from the suffix.
    """
    quotes = []
    for ticker in tickers:
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = info.get("lastPrice")
        prior_close = info.get("previousClose")
        pct_change = None
        if price is not None and prior_close:
            pct_change = (price - prior_close) / prior_close * 100

        quotes.append(
            {
                "ticker": ticker,
                "name": _display_name(t, ticker),
                "price": price,
                "prior_close": prior_close,
                "pct_change": pct_change,
                "volume": info.get("lastVolume"),
                "currency": info.get("currency"),
            }
        )
    return quotes


def _display_name(t: yf.Ticker, ticker: str) -> str:
    try:
        return t.info.get("shortName", ticker)
    except Exception:
        return ticker


if __name__ == "__main__":
    import yaml

    with open("config/watchlist.yaml") as f:
        config = yaml.safe_load(f)

    all_tickers = (
        config["indices_us"]
        + config["indices_kr"]
        + config["watchlist_us"]
        + config["watchlist_kr"]
    )
    for q in fetch_quotes(all_tickers):
        print(q)
