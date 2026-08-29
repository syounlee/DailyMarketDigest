# DailyMarketDigest

A scheduled pipeline that pulls US + Korean market data and news, synthesizes it into a
digest with an LLM, and emails it every morning.

- **Stack**: plain Python + cron/launchd (a deterministic pipeline, not an autonomous agent — see [Notes](#notes--things-to-revisit-later) for why)
- **Markets covered**: US (S&P 500, Nasdaq, Dow + your watchlist) and Korea (KOSPI, KOSDAQ + your watchlist)
- **News**: English via Finnhub (real-time, ticker + market-category news), Korean via Naver
  Search API — Korean headlines are shown as-is (untranslated), commentary is in English
- **Synthesis**: LangChain, with a swappable LLM backend (Claude / Gemini / local Ollama). One
  model handles everything - it reads both English and Korean headlines directly and writes
  English commentary grounded in both.
- **Delivery**: email via Gmail SMTP
- **Schedule-aware**: sends a different email format depending on the day — see
  [Day-of-week behavior](#day-of-week-behavior)
- **Portfolio-aware**: tracks each person's actual holdings (shares, buy price, cost) and shows
  total value/cost/gain-loss per currency — see [Portfolio Status](#portfolio-status)

## Process Flow

```mermaid
flowchart TD
    Start(["main.py — daily run"]) --> Config["Load config/watchlist.yaml + config/people.yaml"]

    Config --> Market["market_data.py<br/>fetch US + KR quotes (yfinance)"]
    Config --> NewsEN["news_data.py<br/>fetch English news (Finnhub)"]
    Config --> NewsKR["news_data_kr.py<br/>fetch Korean news (NAVER API HUB)"]
    Config --> Snap["storage.py<br/>load yesterday's snapshot"]

    Market --> Portfolio["portfolio.py<br/>compute_totals() - value/cost/gain-loss per currency"]
    Market --> Synth
    NewsEN --> Synth
    NewsKR --> Synth
    Snap --> Synth
    Portfolio --> Synth

    Synth["synthesize.py<br/>build_digest() - one model call, reads EN + KR headlines directly"]

    Synth --> Email["email_sender.py<br/>send digest via Gmail SMTP"]
    Email --> SaveSnap["storage.py<br/>save today's snapshot"]
    SaveSnap --> Done(["Done"])

    Market -. on failure .-> FB["log error,<br/>fall back to empty list"]
    NewsEN -. on failure .-> FB
    NewsKR -. on failure .-> FB
    FB --> Synth
```

A failure in any data-fetch step is logged and falls back to an empty result rather than
stopping the run — only a failure in the final email send aborts the whole pipeline. This
diagram shows the Tue–Sat path specifically — see the next section for Sunday/Monday.

## Day-of-week behavior

Both markets are closed Sat/Sun, and the US session for "today" hasn't opened yet by 7 AM
KST Monday (it opens ~11:30 PM KST) — so a plain daily digest on those two days is either a
duplicate of Saturday's (Sunday: nothing changed) or misleadingly stale (Monday: shows
Friday's close as if current). `main.py` picks the format by weekday instead:

| Day | Email | Built by |
|---|---|---|
| Tue–Sat | Regular daily digest | `synthesize.build_digest()` |
| Sunday | **Weekly Recap** — this Friday vs. last Friday's close, aggregated headlines from the week (`data/snapshots/*.json`) | `weekly.build_weekly_summary()` |
| Monday | **Week Ahead** — last Friday's closing levels (clearly labeled as such), confirmed earnings this week for US watchlist tickers (`src/earnings_calendar.py`, Finnhub), today's news | `weekly.build_week_ahead()` |

Both variants reuse the exact same visual style (`src/formatting.py`) as the daily digest,
just with different sections/headers, and both still save a snapshot at the end so Tuesday's
day-over-day framing keeps working uninterrupted. Same anti-hallucination approach as the
daily digest: all prices/dates are rendered directly from fetched data, and the LLM is only
ever asked to write commentary grounded in what it was actually given.

## Project Structure

```
DailyMarketDigest/
├── .env                      # secrets (gitignored, not committed)
├── .env.example               # template — copy to .env and fill in
├── .gitignore
├── requirements.txt
├── config/
│   ├── watchlist.yaml        # shared: indices, news keywords (same for everyone)
│   └── people.yaml           # per-person: name, email, holdings - each person gets their own personalized email
├── src/
│   ├── config_utils.py       # tickers() - extracts ticker symbols from watchlist holding entries
│   ├── market_data.py        # fetch_quotes() via yfinance (US + KR tickers)
│   ├── news_data.py          # fetch_all() English headlines via Finnhub (company + general news)
│   ├── news_data_kr.py       # fetch_all_kr() Korean headlines via Naver Search API
│   ├── earnings_calendar.py  # fetch_upcoming_earnings() via Finnhub (US tickers only)
│   ├── portfolio.py          # compute_totals() - per-currency value/cost/gain-loss, no LLM
│   ├── storage.py            # daily JSON snapshots, load_yesterday()/load_snapshot()/save_today()
│   ├── llm_provider.py       # get_chat_model(role) factory: claude | gemini | ollama (role picks the Ollama model)
│   ├── formatting.py         # shared pure-Python rendering helpers (used by synthesize.py + weekly.py)
│   ├── synthesize.py         # build_digest() -> daily digest (one LLM call for commentary)
│   ├── weekly.py             # build_weekly_summary() (Sunday) + build_week_ahead() (Monday)
│   └── email_sender.py       # send_email() via Gmail SMTP
├── data/
│   ├── snapshots/            # one JSON file per day (gitignored)
│   └── digest.log            # run log (gitignored)
├── main.py                   # orchestrates the full daily pipeline
└── run.sh                    # cron/launchd entry point
```

## Setup

1. **Install dependencies** (already done if you're picking this up fresh, otherwise):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure secrets**: copy `.env.example` to `.env` and fill in the values you need
   (see [Credentials](#credentials-needed) below — you don't need all of them, only the
   ones matching your chosen `LLM_PROVIDER`).

3. **Edit `config/people.yaml`**: each person gets their own personalized email — the
   shared market overview (US/KR indices, general news) is identical for everyone, but
   the Watchlist section (and news about those specific holdings) only shows up in that
   person's own email. Ships with one placeholder person:
   ```yaml
   people:
     - id: seung
       name: Seung
       email: syounlee@naver.com
       watchlist_us:
         - ticker: AAPL
           buy_date: 2026-01-15   # optional
           buy_price: 150.00      # optional
           shares: 10              # optional
           cost: 1512.50           # optional - entered separately, not computed, so it can include fees
       watchlist_kr:
         - ticker: 005930.KS
   ```
   Only `id`, `name`, `email`, and each holding's `ticker` are required. `shares` and
   `buy_price`/`cost` power the [Portfolio Status](#portfolio-status) section — fill them
   in once you know your actual holdings, or leave them out to skip that section entirely
   for a holding (it just won't contribute to the totals). `buy_date` is stored but not
   used yet. Korean tickers need a `.KS` (KOSPI) or `.KQ` (KOSDAQ) suffix. Add more people
   by copying the block. `config/watchlist.yaml` now only holds the shared indices/news
   config — no per-person data.

## Portfolio Status

Computed by `src/portfolio.py` (pure Python, no LLM) and shown in the daily digest and
weekly recap, right below the Watchlist table. For each currency (KRW for Korean holdings,
USD for US holdings — kept separate, never added together), it sums:
- **Value**: `price × shares` across all holdings priced in that currency
- **Cost**: each holding's `cost` field if set, otherwise `buy_price × shares`
- **Gain/loss**: value − cost, in both $ /₩ and %

A holding only contributes once it has both `shares` and a matching live quote. If no
holding in a currency group has a computable cost (`cost` or `buy_price` set), that
group's totals still show `value` but omit the cost/gain-loss comparison rather than
showing a misleading `$0` cost basis.

## Credentials needed

| Secret | Where to get it | Required for |
|---|---|---|
| `FINNHUB_API_KEY` | [finnhub.io](https://finnhub.io/register) free tier signup | English news (real-time, 60 calls/min) |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | [developers.naver.com](https://developers.naver.com) → register an app → enable the Search API | Korean news |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | only if `LLM_PROVIDER=claude` |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) | only if `LLM_PROVIDER=gemini` |
| — (local install) | [ollama.com](https://ollama.com), then `ollama pull llama3.1:8b` | only if `LLM_PROVIDER=ollama` |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` | Google Account → Security → App Passwords (needs 2-Step Verification enabled) | sending the digest |

`market_data.py` needs no key — it uses `yfinance` (Yahoo Finance), which is free and
unauthenticated for both US and Korean tickers.

`DIGEST_RECIPIENT` is no longer read by `main.py` — recipients now come from each
person's `email` in `config/people.yaml`, since each person gets their own personalized
email rather than everyone receiving an identical broadcast. The env var still works as
`src/email_sender.py`'s own standalone-test default (`python -m src.email_sender`).

## Running manually

```bash
source .venv/bin/activate
python main.py
```

Each module can also be run standalone to sanity-check just that piece, e.g.:

```bash
python -m src.market_data       # print live quotes for your configured tickers
python -m src.news_data         # print English headlines (needs FINNHUB_API_KEY)
python -m src.news_data_kr      # print Korean headlines (needs Naver keys)
python -m src.earnings_calendar # print this week's confirmed earnings for your US watchlist
python -m src.llm_provider      # sanity-check the configured LLM backend
python -m src.synthesize        # build a sample daily digest with real prices + fake news
python -m src.weekly            # build sample Weekly Recap + Week Ahead emails
```

A single failed step (e.g. a missing news API key) logs an error and falls back to an
empty result rather than crashing the whole run — you'll still get a digest, just with
that section thin, until you add the missing key.

## Scheduling (not yet set up)

`run.sh` is the entry point cron/launchd should call — it `cd`s into the project,
activates the venv, runs `main.py`, and appends output to `data/digest.log`.

**cron** (`crontab -e`), e.g. to run at 7:00 AM daily:
```
0 7 * * * /Users/seunglee/works/DailyMarketDigest/run.sh
```

**launchd** is generally more reliable on macOS (cron jobs can silently fail to fire
due to sleep/permissions). If you'd rather use that, say so and I'll generate the
`.plist` file and load it — just let me know your preferred run time and I'll wire it up.

## Switching LLM providers

Change one line in `.env`:
```
LLM_PROVIDER=claude   # or: gemini | ollama
```
No other code changes needed — `src/llm_provider.py` handles the swap.

## Notes / things to revisit later

- **Why "Digest" and not "Agent"**: this is a fixed, deterministic pipeline (same steps,
  same order, every run) with an LLM invoked as a subroutine for writing — it doesn't
  perceive changing conditions, choose its own tools, or act autonomously toward a goal,
  which is what "agent" implies. That was a deliberate choice (see the [Process Flow](#process-flow)
  above): a scheduled daily report doesn't benefit from an LLM deciding what to fetch: predictability
  matters more here. A genuinely agentic version of this project would be a separate,
  interactive system built on the same data modules (`market_data.py`, `news_data.py`,
  `news_data_kr.py`) with real tool-calling and reasoning — not a change to this pipeline.
- Snapshots (`data/snapshots/*.json`) currently only feed a yesterday-vs-today diff into
  the prompt; there's no multi-day trend analysis or queryable database — decided against
  for now, revisit if you want richer historical context later.
- Korean headlines are shown as-is (not translated) — the commentary model reads them
  directly for grounding but writes its own paragraphs in English. Comprehension quality
  for Korean input depends on the configured model; this read fine with `llama3.1:8b` in
  testing, but a weaker local model might do worse at understanding Korean than EXAONE
  did (the previous, now-removed, Korean-specialized translation stage).
- Output quality is best with Claude/Gemini. With Ollama, the model can sometimes invent
  a plausible-sounding but inaccurate cause for a price move instead of sticking strictly
  to the fed-in headline — worth spot-checking digests occasionally, especially with
  smaller local models.
- `main.py` aborts (rather than falling back) if the email step itself fails, since a
  digest that isn't delivered isn't useful — check `data/digest.log` if a scheduled run
  produces no email.
