# Builds a 20-row blind sample from results.db + results.csv for a
# hand-check of parse_mentions.py's accuracy. This checks whether the
# parser correctly read what's in the text, not whether the model's
# answer is true.
#
# 10 rows where the parser says mentioned=1 (preferring rows where
# mentions_url=1 too, the shakiest part of the parser), 10 where it says
# mentioned=0. One row per (date, model, brand) combination, picked
# round-robin across brands so Carta and Pulley (the two brands with the
# most rows) don't dominate either group.
#
# Writes eval_sample.csv with id, date, model, brand, answer_text only.
# mentioned and mentions_url are left out on purpose, so the human
# judgment column gets filled in blind, without seeing the parser's own
# call first.
#
# Run with: uv run eval_sample.py

import csv
import random
import sqlite3

DB_FILE = "results.db"
RESULTS_FILE = "results.csv"
OUT_FILE = "eval_sample.csv"
TARGET_PER_GROUP = 10
SAMPLE_SEED = 20260921  # fixed so a re-run reproduces the same sample


def load_answers() -> dict[str, str]:
    with open(RESULTS_FILE, newline="", encoding="utf-8") as f:
        return {row["timestamp"]: row["answer"] for row in csv.DictReader(f)}


def combos_for(conn: sqlite3.Connection, mentioned: int) -> list[dict]:
    # One representative row per (date, model, brand) combo. Ordering by
    # mentions_url DESC before taking the first row seen per combo means
    # a combo that has any mentions_url=1 row gets that one as its
    # representative.
    cur = conn.execute(
        """
        SELECT id, timestamp, date, model, brand, mentions_url
        FROM mentions
        WHERE mentioned = ?
        ORDER BY mentions_url DESC, id ASC
        """,
        (mentioned,),
    )
    seen: dict[tuple, dict] = {}
    for row_id, timestamp, date, model, brand, mentions_url in cur.fetchall():
        key = (date, model, brand)
        if key not in seen:
            seen[key] = {
                "id": row_id,
                "timestamp": timestamp,
                "date": date,
                "model": model,
                "brand": brand,
                "mentions_url": mentions_url,
            }
    return list(seen.values())


def round_robin_pick(rows: list[dict], n: int, rng: random.Random) -> list[dict]:
    # Cycles through brands so one brand can't supply a run of picks
    # before the others get a turn.
    by_brand: dict[str, list[dict]] = {}
    for row in rows:
        by_brand.setdefault(row["brand"], []).append(row)
    for bucket in by_brand.values():
        rng.shuffle(bucket)

    brands = list(by_brand.keys())
    rng.shuffle(brands)

    picked = []
    while len(picked) < n and any(by_brand.values()):
        for brand in brands:
            bucket = by_brand[brand]
            if bucket:
                picked.append(bucket.pop())
                if len(picked) == n:
                    break
    return picked


def build_group(conn: sqlite3.Connection, mentioned: int, target: int, rng: random.Random) -> list[dict]:
    combos = combos_for(conn, mentioned)

    if mentioned == 1:
        prioritized = [c for c in combos if c["mentions_url"] == 1]
        rest = [c for c in combos if c["mentions_url"] == 0]
    else:
        prioritized = []
        rest = combos

    picked = round_robin_pick(prioritized, target, rng)

    if len(picked) < target:
        used_brands = {p["brand"] for p in picked}
        fresh = [c for c in rest if c["brand"] not in used_brands]
        picked += round_robin_pick(fresh, target - len(picked), rng)

    if len(picked) < target:
        remaining = [c for c in rest if c not in picked]
        picked += round_robin_pick(remaining, target - len(picked), rng)

    return picked


def main() -> None:
    conn = sqlite3.connect(DB_FILE)
    rng = random.Random(SAMPLE_SEED)

    mentioned_rows = build_group(conn, 1, TARGET_PER_GROUP, rng)
    not_mentioned_rows = build_group(conn, 0, TARGET_PER_GROUP, rng)
    conn.close()

    answers = load_answers()

    sample = mentioned_rows + not_mentioned_rows
    rng.shuffle(sample)  # mixes the two groups so row order gives nothing away

    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "date", "model", "brand", "answer_text"])
        for row in sample:
            writer.writerow([
                row["id"],
                row["date"],
                row["model"],
                row["brand"],
                answers[row["timestamp"]],
            ])

    brands = sorted({r["brand"] for r in sample})
    models = sorted({r["model"] for r in sample})
    print(f"wrote {len(sample)} rows to {OUT_FILE}")
    print(f"brands covered: {brands}")
    print(f"models covered: {models}")


if __name__ == "__main__":
    main()
