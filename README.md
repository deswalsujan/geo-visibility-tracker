# geo-visibility-tracker

A small pipeline that asks real buyer questions to three AI models and tracks whether specific brands get mentioned in the answers over time.

## What it does

- 27 buyer-style questions for the cap table / equity management SaaS category, asked daily to three models: Gemini Flash, Claude Haiku, and gpt-5.6-luna (OpenAI). Each answer is appended to `results.csv` with a timestamp, model name, and `trigger_type` (`scheduled` for the daily run, `manual` for a run triggered by hand). Scheduled runs skip a row if one already exists for the same date, model, and prompt; manual runs always write, so testing never blocks the real data.
- `parse_mentions.py` rebuilds `results.db` (SQLite) from `results.csv`, checking every answer against 8 tracked brands (Carta, Pulley, EquityList, Ledgy, Vestd, Qapita, Cake Equity, Astrella) and flagging domain-shaped mentions in a `mentions_url` column. This is a mention flag, not a verified citation. It catches a real domain and a hallucinated one the same way.
- `weekly_diff.py` compares the trailing 7 days against the preceding 7 days, by brand and by model, and posts the result to Slack. Dates are always ISO 8601. Any comparison window under 200 rows gets "(limited history)" added to the message itself, so a delta doesn't read as a real signal before there's enough data behind it.
- `compare_eval.py` checks the parser against a 20-row hand-labeled sample. Current agreement: 18/20 (90%). Two known gaps: a brand name inside a clarifying question can get counted as a real mention, and a shortened brand name a model actually uses (like "Cake" for "Cake Equity") isn't caught by the current matcher.

## Running it

Requires [uv](https://docs.astral.sh/uv/) and API keys for Gemini, Claude, and OpenAI.

```
cp .env.example .env
# paste your keys into .env

uv run geo_check.py --trigger-type manual
uv run parse_mentions.py
uv run weekly_diff.py --post
```

## Automation

Two GitHub Actions:
- `.github/workflows/geo_check.yml` runs daily, asks all 27 questions across all three models, and commits the updated `results.csv` back to the repo.
- `.github/workflows/weekly-diff.yml` runs weekly, rebuilds `results.db` from `results.csv`, and posts the diff to Slack.

Both also support a manual "Run workflow" trigger from the Actions tab.

API keys live only as GitHub Actions secrets (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, plus a Slack webhook secret). None are written into code or committed to this repo.

## What it costs

At current volume, 27 questions across three models once a day, combined spend across all three providers has stayed under $1 cumulative since the API keys were created on 18 Sept. Each provider's console defaults to a different reporting window: Gemini's is trailing 28 days, OpenAI's resets each calendar month, Claude's is a running total that never resets. None of them hand you a clean single-day figure directly.

## Built with

[Claude Code](https://claude.com/claude-code).
