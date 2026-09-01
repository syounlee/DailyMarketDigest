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

# The Mac can start this job during a brief "darkwake" maintenance window
# (not a full wake) and drop back to sleep before it finishes, killing it
# mid-run - a scheduled digest can take anywhere from ~1 to ~45 min depending
# on Ollama's load. caffeinate holds a power assertion for the lifetime of
# main.py so the system won't sleep again until it's actually done.
caffeinate -is python main.py >> data/digest.log 2>&1
