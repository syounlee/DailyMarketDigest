# Daily Financial Data & News Agent

A daily-run agent that pulls US + Korean market data and news, synthesizes it into a
digest with an LLM, and emails it every morning.

- **Stack**: plain Python + cron/launchd (no agent framework running the pipeline itself)
- **Markets covered**: US (S&P 500, Nasdaq, Dow + your watchlist) and Korea (KOSPI, KOSDAQ + your watchlist)
- **News**: English via Finnhub (real-time, ticker + market-category news), Korean via Naver Search API — folded into one English-language digest
- **Synthesis**: LangChain, with a swappable LLM backend (Claude / Gemini / local Ollama). When using
  Ollama, synthesis runs as two stages on two different local models: a Korean-specialized model
  translates the Korean news, then a strong English model composes the full digest.
- **Delivery**: email via Gmail SMTP

## Process Flow

```mermaid
flowchart TD
    Start(["main.py — daily run"]) --> Config["Load config/watchlist.yaml"]

    Config --> Market["market_data.py<br/>fetch US + KR quotes (yfinance)"]
    Config --> NewsEN["news_data.py<br/>fetch English news (Finnhub)"]
    Config --> NewsKR["news_data_kr.py<br/>fetch Korean news (NAVER API HUB)"]
    Config --> Snap["storage.py<br/>load yesterday's snapshot"]

    Market --> Synth
    NewsEN --> Synth
    NewsKR --> Synth
    Snap --> Synth

    subgraph Synth["synthesize.py"]
        direction TB
        S1["Stage 1 — translate_kr_news()<br/>Korean-specialized model (EXAONE 3.5)"]
        S2["Stage 2 — build_digest()<br/>English composing model (Llama 3.1)"]
        S1 --> S2
    end

    Synth --> Email["email_sender.py<br/>send digest via Gmail SMTP"]
    Email --> SaveSnap["storage.py<br/>save today's snapshot"]
    SaveSnap --> Done(["Done"])

    Market -. on failure .-> FB["log error,<br/>fall back to empty list"]
    NewsEN -. on failure .-> FB
    NewsKR -. on failure .-> FB
    FB --> Synth
```

`Stage 1` only runs as a separate model call when `LLM_PROVIDER=ollama` (EXAONE → Llama 3.1
handoff, see [Dual-model synthesis](#dual-model-synthesis-ollama-only)). With `claude` or
`gemini`, both stages collapse into a single call on the one configured model. A failure in
any data-fetch step is logged and falls back to an empty result rather than stopping the
run — only a failure in the final email send aborts the whole pipeline.

## Project Structure

```
financial_advisor/
├── .env                      # secrets (gitignored, not committed)
├── .env.example               # template — copy to .env and fill in
├── .gitignore
├── requirements.txt
├── config/
│   └── watchlist.yaml        # tickers, indices, news keywords (edit this to customize)
├── src/
│   ├── market_data.py        # fetch_quotes() via yfinance (US + KR tickers)
│   ├── news_data.py          # fetch_all() English headlines via Finnhub (company + general news)
│   ├── news_data_kr.py       # fetch_all_kr() Korean headlines via Naver Search API
│   ├── storage.py            # daily JSON snapshots, load_yesterday()/save_today()
│   ├── llm_provider.py       # get_chat_model(role) factory: claude | gemini | ollama (role picks the Ollama model)
│   ├── synthesize.py         # 2-stage LCEL: translate_kr_news() -> build_digest() -> digest text
│   └── email_sender.py       # send_email() via Gmail SMTP
├── data/
│   ├── snapshots/            # one JSON file per day (gitignored)
│   └── agent.log             # run log (gitignored)
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

3. **Edit your watchlist**: `config/watchlist.yaml` ships with placeholder tickers
   (`AAPL`, `MSFT`, `SPY`, Samsung Electronics, SK Hynix). Replace with your own —
   Korean tickers need a `.KS` (KOSPI) or `.KQ` (KOSDAQ) suffix, e.g. `005930.KS`.

## Credentials needed

| Secret | Where to get it | Required for |
|---|---|---|
| `FINNHUB_API_KEY` | [finnhub.io](https://finnhub.io/register) free tier signup | English news (real-time, 60 calls/min) |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | [developers.naver.com](https://developers.naver.com) → register an app → enable the Search API | Korean news |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | only if `LLM_PROVIDER=claude` |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) | only if `LLM_PROVIDER=gemini` |
| — (local install) | [ollama.com](https://ollama.com), then `ollama pull exaone3.5:7.8b` and `ollama pull llama3.1:8b` | only if `LLM_PROVIDER=ollama` |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` | Google Account → Security → App Passwords (needs 2-Step Verification enabled) | sending the digest |

`market_data.py` needs no key — it uses `yfinance` (Yahoo Finance), which is free and
unauthenticated for both US and Korean tickers.

## Running manually

```bash
source .venv/bin/activate
python main.py
```

Each module can also be run standalone to sanity-check just that piece, e.g.:

```bash
python -m src.market_data     # print live quotes for your configured tickers
python -m src.news_data       # print English headlines (needs FINNHUB_API_KEY)
python -m src.news_data_kr    # print Korean headlines (needs Naver keys)
python -m src.llm_provider    # sanity-check the configured LLM backend
python -m src.synthesize      # build a sample digest with real prices + fake news
```

A single failed step (e.g. a missing news API key) logs an error and falls back to an
empty result rather than crashing the whole run — you'll still get a digest, just with
that section thin, until you add the missing key.

## Scheduling (not yet set up)

`run.sh` is the entry point cron/launchd should call — it `cd`s into the project,
activates the venv, runs `main.py`, and appends output to `data/agent.log`.

**cron** (`crontab -e`), e.g. to run at 7:00 AM daily:
```
0 7 * * * /Users/seunglee/works/financial_advisor/run.sh
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

## Dual-model synthesis (Ollama only)

When `LLM_PROVIDER=ollama`, synthesis runs as two sequential stages instead of one call,
each on a different local model — `get_chat_model(role)` in `src/llm_provider.py` picks
the model by role:

1. **`translate_kr_news()`** (role `"kr"`) — translates/summarizes the Korean headlines
   into English bullets. Uses `OLLAMA_MODEL_KR` (default `exaone3.5:7.8b`, LG's
   Korean-English bilingual model — chosen because it's purpose-trained on Korean rather
   than treating it as one of many secondary languages).
2. **`build_digest()`** (role `"en"`) — writes the full digest from US/KR market data,
   English news, and stage 1's translated Korean summary. Uses `OLLAMA_MODEL_EN` (default
   `llama3.1:8b` — stronger general English instruction-following/writing quality).

The two models are never loaded simultaneously — Ollama loads one, runs it, and swaps to
the other for the next stage, which is why this works fine on 16GB of unified memory.
For `claude`/`gemini`, `role` is ignored and the single configured model handles both
stages (no split needed — hosted frontier models are already strong at Korean).

To use different local models, override in `.env`:
```
OLLAMA_MODEL_KR=exaone3.5:7.8b
OLLAMA_MODEL_EN=llama3.1:8b
```

## Notes / things to revisit later

- Snapshots (`data/snapshots/*.json`) currently only feed a yesterday-vs-today diff into
  the prompt; there's no multi-day trend analysis or queryable database — decided against
  for now, revisit if you want richer historical context later.
- Korean headlines are summarized/translated into English before reaching the final digest
  rather than kept bilingual — if you'd prefer a Korean-language section too, that's a
  prompt change in `src/synthesize.py`.
- Output quality is best with Claude/Gemini. With Ollama, the composing model (`OLLAMA_MODEL_EN`)
  can sometimes invent a plausible-sounding but inaccurate cause for a price move instead of
  sticking strictly to the fed-in headline — worth spot-checking digests occasionally,
  especially with smaller local models.
- `main.py` aborts (rather than falling back) if the email step itself fails, since a
  digest that isn't delivered isn't useful — check `data/agent.log` if a scheduled run
  produces no email.
