# Reads results.db (built by parse_mentions.py) and compares the
# trailing 7 calendar days against the 7 calendar days before that,
# by brand and by model, using mention_count from the mentions table.
# Formats the comparison as a short Slack message. Each window's line
# in the message shows its own row count, and gets "(limited history)"
# prepended when that window has fewer than ROW_COUNT_THRESHOLD result
# rows, since early weeks (or weeks spanning a change in run volume)
# don't carry a real trend signal yet.
#
# Dry run (prints the message, does not post): uv run weekly_diff.py
# Real post to Slack: uv run weekly_diff.py --post
# The GitHub Action passes --post for the scheduled weekly run.
# Assumes results.db is already built for today's results.csv; run
# parse_mentions.py first if it might be stale.

import argparse
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from parse_mentions import BRANDS

load_dotenv()

DB_FILE = "results.db"
WINDOW_DAYS = 7
ROW_COUNT_THRESHOLD = 200


def window_bounds(today: "datetime.date") -> tuple:
    # .isoformat() gives YYYY-MM-DD, deliberately: no slash format anywhere
    # in the message, since mm/dd/yy and dd/mm/yy are each ambiguous to some
    # reader and results.db already uses this same format for its date column.
    trailing_end = today
    trailing_start = today - timedelta(days=WINDOW_DAYS - 1)
    preceding_end = trailing_start - timedelta(days=1)
    preceding_start = preceding_end - timedelta(days=WINDOW_DAYS - 1)
    return (
        (trailing_start.isoformat(), trailing_end.isoformat()),
        (preceding_start.isoformat(), preceding_end.isoformat()),
    )


def row_count(conn: sqlite3.Connection, start: str, end: str) -> int:
    # mentions has exactly len(BRANDS) rows per result row (one per
    # brand, even on a miss), so dividing back out gives the real
    # count of API response rows behind this window.
    (count,) = conn.execute(
        "SELECT COUNT(*) FROM mentions WHERE date BETWEEN ? AND ?", (start, end)
    ).fetchone()
    return count // len(BRANDS)


def totals_by(conn: sqlite3.Connection, column: str, start: str, end: str) -> dict:
    rows = conn.execute(
        f"SELECT {column}, SUM(mention_count) FROM mentions WHERE date BETWEEN ? AND ? GROUP BY {column}",
        (start, end),
    ).fetchall()
    return {key: total for key, total in rows}


def format_delta(trailing: int, preceding: int) -> str:
    if preceding == 0 and trailing > 0:
        return f"{trailing} (new)"
    if trailing == 0 and preceding > 0:
        return f"0 (dropped from {preceding})"
    delta = trailing - preceding
    sign = "+" if delta >= 0 else ""
    return f"{trailing} ({sign}{delta})"


def format_window_line(label: str, start: str, end: str, rows: int) -> str:
    prefix = "(limited history) " if rows < ROW_COUNT_THRESHOLD else ""
    return f"{prefix}{label}: {start} to {end} — {rows} rows"


def format_section(title: str, trailing_totals: dict, preceding_totals: dict) -> str:
    keys = sorted(set(trailing_totals) | set(preceding_totals))
    lines = [f"*{title}* (mentions, trailing vs preceding)"]
    for key in keys:
        trailing = trailing_totals.get(key, 0)
        preceding = preceding_totals.get(key, 0)
        lines.append(f"• {key}: {format_delta(trailing, preceding)}")
    return "\n".join(lines)


def build_message(conn: sqlite3.Connection, today: "datetime.date") -> str:
    (trailing_start, trailing_end), (preceding_start, preceding_end) = window_bounds(today)

    trailing_rows = row_count(conn, trailing_start, trailing_end)
    preceding_rows = row_count(conn, preceding_start, preceding_end)

    trailing_brands = totals_by(conn, "brand", trailing_start, trailing_end)
    preceding_brands = totals_by(conn, "brand", preceding_start, preceding_end)
    trailing_models = totals_by(conn, "model", trailing_start, trailing_end)
    preceding_models = totals_by(conn, "model", preceding_start, preceding_end)

    lines = [
        "*Weekly GEO visibility diff*",
        format_window_line("Trailing", trailing_start, trailing_end, trailing_rows),
        format_window_line("Preceding", preceding_start, preceding_end, preceding_rows),
        "",
        format_section("By brand", trailing_brands, preceding_brands),
        "",
        format_section("By model", trailing_models, preceding_models),
    ]
    return "\n".join(lines)


def post_to_slack(webhook_url: str, text: str) -> None:
    response = requests.post(webhook_url, json={"text": text}, timeout=30)
    response.raise_for_status()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--post", action="store_true", help="Post the message to Slack instead of only printing it")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    today = datetime.now(timezone.utc).date()

    conn = sqlite3.connect(DB_FILE)
    message = build_message(conn, today)
    conn.close()

    print(message)

    if args.post:
        webhook_url = os.environ["SLACK_WEBHOOK_URL"]
        post_to_slack(webhook_url, message)
        print("\nPosted to Slack.")
