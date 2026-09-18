# Sends one prompt to Gemini Flash and appends the question, answer, and
# timestamp as a new row in results.csv. Every row is tagged scheduled or
# manual via --trigger-type, so analysis scripts can filter to the clean
# scheduled baseline and ignore ad hoc test runs.
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

API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = "gemini-3.6-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
DELAY_SECONDS = 8  # pause between questions, keeps sustained throughput well under Gemini Flash's free-tier rate limit
MAX_ATTEMPTS = 3  # retries for a single question on 429/503 before giving up on it
RETRY_BACKOFF_SECONDS = 5  # doubles each retry: 5s, then 10s

RESULTS_FILE = "results.csv"
FIELDNAMES = ["timestamp", "trigger_type", "model", "prompt", "answer"]


def ask_gemini(prompt: str) -> str:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = requests.post(
            URL,
            params={"key": API_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        if response.status_code in (429, 503) and attempt < MAX_ATTEMPTS:
            wait = RETRY_BACKOFF_SECONDS * attempt
            print(f"Gemini returned {response.status_code}, retrying in {wait}s (attempt {attempt}/{MAX_ATTEMPTS})")
            time.sleep(wait)
            continue
        break

    try:
        response.raise_for_status()
    except requests.HTTPError:
        # Never print the exception directly: it carries the full request
        # URL, which contains the API key as a query param.
        raise RuntimeError(f"Gemini API request failed with status {response.status_code}") from None

    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


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


def save_result(prompt: str, answer: str, trigger_type: str) -> None:
    file_exists = os.path.exists(RESULTS_FILE)
    with open(RESULTS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger_type": trigger_type,
            "model": MODEL,
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
        if args.trigger_type == "scheduled" and scheduled_row_exists(MODEL, prompt, today):
            print(f"scheduled row already exists for {today} / {MODEL} / {prompt}, skipping")
            continue

        try:
            answer = ask_gemini(prompt)
            save_result(prompt, answer, args.trigger_type)
            print(f"Saved {args.trigger_type} response to {RESULTS_FILE} for: {prompt}")
        except Exception as e:
            print(f"failed to get a response for: {prompt} ({e})")

        time.sleep(DELAY_SECONDS)
