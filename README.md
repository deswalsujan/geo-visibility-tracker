# geo-visibility-tracker

A small script that asks Gemini a buyer question and saves the answer. It runs daily on a schedule and tracks whether certain brands get mentioned in AI answers over time.

## What it does

`geo_check.py` sends one prompt to Gemini Flash and appends the response to `results.csv`, along with a timestamp and the model name. Every row is tagged `trigger_type`: `scheduled` for the daily automated run, `manual` for a run you trigger yourself. Scheduled runs skip writing a duplicate if a row already exists for the same date, model, and prompt. Manual runs always write, so testing never blocks the real data.

## Running it

Requires [uv](https://docs.astral.sh/uv/) and a free Gemini API key from [Google AI Studio](https://aistudio.google.com/).

```
cp .env.example .env
# paste your key into .env

uv run geo_check.py --trigger-type manual
```

## Automation

A GitHub Action in `.github/workflows/geo_check.yml` runs this daily at 09:00 IST and commits the updated `results.csv` back to the repo. It also supports a manual "Run workflow" trigger from the Actions tab. The API key is stored as a GitHub Actions secret named `GEMINI_API_KEY`, never in the code.

## What it costs

Google AI Studio's free tier covers this at one call a day. No paid usage expected at this scale.

## Built with

[Claude Code](https://claude.com/claude-code).
