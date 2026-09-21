# Reads results.csv and rebuilds results.db, a SQLite table with one row
# per (result row, brand) pair for all 8 tracked cap-table/equity brands.
# Every brand is checked against every answer, not just the ones that hit,
# so "brand never mentioned" is a real, countable row instead of a missing
# one. Lets later steps (weekly diff, eval) query mention stats with SQL
# instead of re-scanning raw answer text each time.
#
# Run with: uv run parse_mentions.py
# Wipes and rebuilds the mentions table on every run (DROP + CREATE), so
# re-running against the same results.csv is safe and never duplicates
# rows. Uses Python's csv module, not line-based tools: the answer column
# has embedded newlines inside quoted fields that break grep/cut/awk
# (confirmed the hard way on 18 and 19 Sept).

import csv
import re
import sqlite3

RESULTS_FILE = "results.csv"
DB_FILE = "results.db"

# From sprint/PLAN.md's 14 Sept decision: the category is cap table /
# equity management SaaS, these are the 8 brands to watch.
BRANDS = [
    "Carta",
    "Pulley",
    "EquityList",
    "Ledgy",
    "Vestd",
    "Qapita",
    "Cake Equity",
    "Astrella",
]

# How close a URL, markdown link, or bare domain has to be to a mention
# to count as nearby, in characters, on each side of the match.
URL_WINDOW = 100

# How much surrounding text to keep as a readable snippet around the
# first mention, in characters, on each side of the match.
SNIPPET_RADIUS = 60

# Matches http(s):// links, markdown link syntax, and bare domains like
# "pulley.com" or "captable.io" with no scheme or brackets. A match here
# means a domain-shaped string appears nearby, not that it's a real,
# live, or verified source, so it's a narrower claim than "citation".
URL_PATTERN = re.compile(
    r"https?://"
    r"|\[[^\]]+\]\([^)]+\)"
    r"|\b[a-z0-9-]+\.(?:com|io|co|net|org|ai|app|so)\b",
    re.IGNORECASE,
)


def brand_pattern(brand: str) -> re.Pattern:
    # \b on each end keeps "Carta" from matching inside a longer word,
    # and for a two-word brand like "Cake Equity" it only requires
    # boundaries at the very start and end of the phrase.
    return re.compile(r"\b" + re.escape(brand) + r"\b", re.IGNORECASE)


def mentions_url_near(answer: str, match: re.Match) -> bool:
    start = max(0, match.start() - URL_WINDOW)
    end = min(len(answer), match.end() + URL_WINDOW)
    return bool(URL_PATTERN.search(answer[start:end]))


def make_snippet(answer: str, match: re.Match) -> str:
    start = max(0, match.start() - SNIPPET_RADIUS)
    end = min(len(answer), match.end() + SNIPPET_RADIUS)
    return answer[start:end].replace("\n", " ")


def mentions_for_row(row: dict) -> list[tuple]:
    answer = row["answer"] or ""
    date = row["timestamp"][:10]
    out = []

    for brand in BRANDS:
        matches = list(brand_pattern(brand).finditer(answer))

        if matches:
            first = matches[0]
            out.append((
                row["timestamp"],
                date,
                row["trigger_type"],
                row["model"],
                row["prompt"],
                brand,
                1,
                len(matches),
                first.start(),
                int(mentions_url_near(answer, first)),
                make_snippet(answer, first),
            ))
        else:
            out.append((
                row["timestamp"],
                date,
                row["trigger_type"],
                row["model"],
                row["prompt"],
                brand,
                0,
                0,
                None,
                0,
                None,
            ))

    return out


def build_mentions(rows: list[dict]) -> list[tuple]:
    mentions = []
    for row in rows:
        mentions.extend(mentions_for_row(row))
    return mentions


def main() -> None:
    with open(RESULTS_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    mentions = build_mentions(rows)

    conn = sqlite3.connect(DB_FILE)
    conn.execute("DROP TABLE IF EXISTS mentions")
    conn.execute("""
        CREATE TABLE mentions (
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            date TEXT,
            trigger_type TEXT,
            model TEXT,
            prompt TEXT,
            brand TEXT,
            mentioned INTEGER,
            mention_count INTEGER,
            first_position INTEGER,
            -- 1 if a domain-shaped string appears nearby, true or fake, live or dead: not a verified citation
            mentions_url INTEGER,
            snippet TEXT
        )
    """)
    conn.executemany(
        """
        INSERT INTO mentions
            (timestamp, date, trigger_type, model, prompt, brand, mentioned,
             mention_count, first_position, mentions_url, snippet)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        mentions,
    )
    conn.commit()
    conn.close()

    hits = sum(1 for m in mentions if m[6] == 1)
    print(f"{len(rows)} result rows x {len(BRANDS)} brands = {len(mentions)} rows written to {DB_FILE}")
    print(f"{hits} of those rows have mentioned=1")


if __name__ == "__main__":
    main()
