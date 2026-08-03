#!/usr/bin/env bash
cd "$(dirname "$0")"

# launchd runs jobs with a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin) that
# doesn't include Homebrew/local install locations - add them so `ollama`
# (and anything else installed there) can actually be found below.
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

# If this run uses a local Ollama model, make sure the server is actually up -
# it's not guaranteed to be running at an unattended scheduled trigger time.
if grep -q '^LLM_PROVIDER=ollama' .env 2>/dev/null && command -v ollama >/dev/null 2>&1; then
    if ! curl -s -o /dev/null http://localhost:11434; then
        nohup ollama serve > data/ollama.log 2>&1 &
        sleep 5
    fi
fi

source .venv/bin/activate
python main.py >> data/digest.log 2>&1
