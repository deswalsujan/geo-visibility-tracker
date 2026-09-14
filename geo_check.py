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
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = "gemini-3.6-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

PROMPT = "What are the best CRM tools for a small marketing team?"

RESULTS_FILE = "results.csv"
FIELDNAMES = ["timestamp", "trigger_type", "model", "prompt", "answer"]


def ask_gemini(prompt: str) -> str:
    response = requests.post(
        URL,
        params={"key": API_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=30,
    )
    response.raise_for_status()
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

    if args.trigger_type == "scheduled" and scheduled_row_exists(MODEL, PROMPT, today):
        print(f"scheduled row already exists for {today} / {MODEL} / {PROMPT}, skipping")
        sys.exit(0)

    answer = ask_gemini(PROMPT)
    save_result(PROMPT, answer, args.trigger_type)
    print(f"Saved {args.trigger_type} response to {RESULTS_FILE}")
