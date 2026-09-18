# Loops through every question in questions.py and asks each of three
# providers (Gemini, Claude Haiku, OpenAI) for an answer, appending
# each prompt/answer pair as a new row in results.csv. Every row is
# tagged scheduled or manual via --trigger-type, so analysis scripts
# can filter to the clean scheduled baseline and ignore ad hoc test
# runs. Dedup is keyed on model + prompt + date, so a partial or
# retried run only fills in what's still missing.
#
# Run with: uv run geo_check.py --trigger-type manual
# The GitHub Action passes --trigger-type scheduled for the daily cron run.

import argparse
import csv
import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from questions import QUESTIONS

load_dotenv()

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
GEMINI_DELAY_SECONDS = 8  # keeps sustained throughput well under Gemini Flash's free-tier rate limit
GEMINI_MAX_ATTEMPTS = 3
GEMINI_RETRY_BACKOFF_SECONDS = 5  # doubles each retry: 5s, then 10s

HAIKU_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
HAIKU_DELAY_SECONDS = 2
HAIKU_MAX_ATTEMPTS = 3
HAIKU_RETRY_BACKOFF_SECONDS = 3  # doubles each retry: 3s, then 6s

OPENAI_MODEL = "gpt-5.6-luna"  # verified against platform.openai.com/docs/models, OpenAI's current lowest-cost general-purpose model
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_DELAY_SECONDS = 2
OPENAI_MAX_ATTEMPTS = 3
OPENAI_RETRY_BACKOFF_SECONDS = 3  # doubles each retry: 3s, then 6s

RESULTS_FILE = "results.csv"
FIELDNAMES = ["timestamp", "trigger_type", "model", "prompt", "answer"]


def request_with_retry(make_request, provider_name: str, max_attempts: int, backoff_seconds: int) -> requests.Response:
    for attempt in range(1, max_attempts + 1):
        response = make_request()
        if response.status_code in (429, 503) and attempt < max_attempts:
            wait = backoff_seconds * attempt
            print(f"{provider_name} returned {response.status_code}, retrying in {wait}s (attempt {attempt}/{max_attempts})")
            time.sleep(wait)
            continue
        break

    try:
        response.raise_for_status()
    except requests.HTTPError:
        # Never print the exception directly: depending on the provider it
        # can carry the full request URL or headers, which may include the
        # API key.
        raise RuntimeError(f"{provider_name} request failed with status {response.status_code}") from None

    return response


def ask_gemini(prompt: str) -> str:
    def make_request():
        return requests.post(
            GEMINI_URL,
            params={"key": GEMINI_API_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )

    response = request_with_retry(make_request, "Gemini", GEMINI_MAX_ATTEMPTS, GEMINI_RETRY_BACKOFF_SECONDS)
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def ask_haiku(prompt: str) -> str:
    def make_request():
        return requests.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": HAIKU_MODEL,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )

    response = request_with_retry(make_request, "Claude Haiku", HAIKU_MAX_ATTEMPTS, HAIKU_RETRY_BACKOFF_SECONDS)
    data = response.json()
    return data["content"][0]["text"]


def ask_openai(prompt: str) -> str:
    def make_request():
        return requests.post(
            OPENAI_URL,
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "content-type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )

    response = request_with_retry(make_request, "OpenAI", OPENAI_MAX_ATTEMPTS, OPENAI_RETRY_BACKOFF_SECONDS)
    data = response.json()
    return data["choices"][0]["message"]["content"]


PROVIDERS = [
    {"model": GEMINI_MODEL, "ask": ask_gemini, "delay_seconds": GEMINI_DELAY_SECONDS},
    {"model": HAIKU_MODEL, "ask": ask_haiku, "delay_seconds": HAIKU_DELAY_SECONDS},
    {"model": OPENAI_MODEL, "ask": ask_openai, "delay_seconds": OPENAI_DELAY_SECONDS},
]


def scheduled_row_exists(model: str, prompt: str, date_str: str) -> bool:
    if not os.path.exists(RESULTS_FILE):
        return False
    with open(RESULTS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["trigger_type"] != "scheduled":
                continue
            if row["timestamp"][:10] == date_str and row["model"] == model and row["prompt"] == prompt:
                return True
    return False


def save_result(model: str, prompt: str, answer: str, trigger_type: str) -> None:
    file_exists = os.path.exists(RESULTS_FILE)
    with open(RESULTS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger_type": trigger_type,
            "model": model,
            "prompt": prompt,
            "answer": answer,
        })


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger-type", required=True, choices=["scheduled", "manual"])
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    today = datetime.now(timezone.utc).date().isoformat()

    for prompt in QUESTIONS:
        for provider in PROVIDERS:
            model = provider["model"]

            if args.trigger_type == "scheduled" and scheduled_row_exists(model, prompt, today):
                print(f"scheduled row already exists for {today} / {model} / {prompt}, skipping")
                continue

            try:
                answer = provider["ask"](prompt)
                save_result(model, prompt, answer, args.trigger_type)
                print(f"Saved {args.trigger_type} response from {model} to {RESULTS_FILE} for: {prompt}")
            except Exception as e:
                print(f"failed to get a response from {model} for: {prompt} ({e})")

            time.sleep(provider["delay_seconds"])
