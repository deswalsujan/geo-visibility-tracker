# Compares the hand-checked judgments in eval_sample_human.csv against
# parse_mentions.py's own mentioned/mentions_url values for those same
# rows, pulled fresh from results.db by id. Reports the agreement rate
# and prints every row where the human and the parser disagreed, so
# disagreements can be read one by one instead of just counted.
#
# This checks whether the parser correctly read what's in the text, not
# whether the model's answer is true.
#
# Writes the same report to eval_report.md so it isn't only in the
# terminal scrollback.
#
# Run with: uv run compare_eval.py

import csv
import sqlite3

HUMAN_FILE = "eval_sample_human.csv"
DB_FILE = "results.db"
REPORT_FILE = "eval_report.md"


def load_human_rows() -> list[dict]:
    with open(HUMAN_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parser_verdict(conn: sqlite3.Connection, row_id: int) -> tuple[int, int]:
    cur = conn.execute(
        "SELECT mentioned, mentions_url FROM mentions WHERE id = ?",
        (row_id,),
    )
    result = cur.fetchone()
    if result is None:
        raise ValueError(f"id {row_id} not found in {DB_FILE}'s mentions table")
    return result


def build_report(rows: list[dict], conn: sqlite3.Connection) -> tuple[str, int, int]:
    total = len(rows)
    agree = 0
    disagreements = []

    for row in rows:
        row_id = int(row["id"])
        human_mentioned = int(row["human_mentioned"])
        parser_mentioned, parser_mentions_url = parser_verdict(conn, row_id)

        if human_mentioned == parser_mentioned:
            agree += 1
        else:
            disagreements.append({
                "id": row_id,
                "date": row["date"],
                "model": row["model"],
                "brand": row["brand"],
                "human_mentioned": human_mentioned,
                "parser_mentioned": parser_mentioned,
                "parser_mentions_url": parser_mentions_url,
            })

    rate = agree / total * 100

    lines = []
    lines.append("# Eval report: human judgment vs parser output")
    lines.append("")
    lines.append(f"Agreement rate: {agree}/{total} ({rate:.0f}%)")
    lines.append("")

    if disagreements:
        lines.append("## Disagreements")
        lines.append("")
        lines.append("| id | date | model | brand | human said | parser said |")
        lines.append("|---|---|---|---|---|---|")
        for d in disagreements:
            lines.append(
                f"| {d['id']} | {d['date']} | {d['model']} | {d['brand']} "
                f"| {d['human_mentioned']} | {d['parser_mentioned']} "
                f"(mentions_url={d['parser_mentions_url']}) |"
            )
    else:
        lines.append("No disagreements. Human and parser matched on all rows.")

    return "\n".join(lines), agree, total


def main() -> None:
    rows = load_human_rows()
    conn = sqlite3.connect(DB_FILE)
    report, agree, total = build_report(rows, conn)
    conn.close()

    print(report)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report + "\n")

    print()
    print(f"report written to {REPORT_FILE}")


if __name__ == "__main__":
    main()
