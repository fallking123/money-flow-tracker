"""
自動回填賽果（不用手動輸入比分）
============================================
建議排程：每天固定跑 1-2 次（例如清晨跑一次，抓昨天+前天所有已完賽的比賽）。
直接查 MLB 官方 Stats API 的比分，寫進 results.csv，跟 odds_history.csv 用 game_id 對起來。
"""

import csv
import os
from datetime import datetime, timezone, timedelta

from mlb_common import get_schedule

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "docs", "data")
RESULTS_CSV = os.path.join(DATA_DIR, "results.csv")


def load_existing_ids() -> set:
    if not os.path.exists(RESULTS_CSV):
        return set()
    with open(RESULTS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["game_id"] for row in reader}


def run(days_back: int = 3):
    now = datetime.now(timezone.utc)
    existing_ids = load_existing_ids()

    file_exists = os.path.exists(RESULTS_CSV)
    new_rows = []

    for i in range(days_back):
        date_str = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        games = get_schedule(date_str)
        for g in games:
            gid = str(g["game_id"])
            if gid in existing_ids:
                continue
            if g["status"] != "Final":
                continue
            if g["away_score"] is None or g["home_score"] is None:
                continue
            winner = g["away_team"] if g["away_score"] > g["home_score"] else g["home_team"]
            new_rows.append(
                {
                    "game_id": gid,
                    "game_date": date_str,
                    "away_team": g["away_team"],
                    "home_team": g["home_team"],
                    "away_score": g["away_score"],
                    "home_score": g["home_score"],
                    "winner": winner,
                }
            )
            existing_ids.add(gid)

    if not new_rows:
        print("沒有新的已完賽比賽需要回填。")
        return

    with open(RESULTS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["game_id", "game_date", "away_team", "home_team", "away_score", "home_score", "winner"],
        )
        if not file_exists:
            writer.writeheader()
        for row in new_rows:
            writer.writerow(row)

    print(f"回填 {len(new_rows)} 場新完賽比賽的比分。")


if __name__ == "__main__":
    run()
