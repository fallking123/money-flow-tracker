"""
自動回填賽果（多運動版）
============================================
每天跑一次：找出 odds_history 裡已經開打超過 4 小時、還沒有賽果的比賽，
到 ESPN 查比分，寫進 docs/data/<運動>/results.csv。
results.csv 用 sbd_id 跟 odds_history 對起來（同一場比賽的編號）。

欄位說明：
- season_type：preseason 季前賽 / regular 例行賽 / postseason 季後賽
- series_note：季後賽系列賽說明（例如「ALDS - Game 3」「NYY leads series 2-1」）
- winner：away 客隊勝 / home 主隊勝 / tie 和局
- margin：主隊得分 − 客隊得分（算讓分盤用）；total_points：兩隊總分（算大小分用）
- status：final 完賽 / canceled 取消 / postponed 延賽
"""

import os
from datetime import datetime, timezone, timedelta

from sports_common import (SPORTS, active_sports, espn_events, is_college, match_event, parse_time,
                           read_rows, recent_monthly_files, sport_dir, append_rows)

RESULT_FIELDS = [
    "sport", "sbd_id", "event_id", "game_time_utc", "season_type", "series_note",
    "away_team", "home_team", "away_score", "home_score", "winner", "margin", "total_points", "status",
]
LOOKBACK_DAYS = 10
WAIT_HOURS = 4


def pending_games(sport, now):
    """odds_history 裡該有賽果、但 results.csv 還沒有的比賽"""
    done = {r["sbd_id"] for r in read_rows(os.path.join(sport_dir(sport), "results.csv"))}
    games = {}
    for path in recent_monthly_files(sport, "odds_history"):
        for r in read_rows(path):
            sid = r["sbd_id"]
            if sid in done:
                continue
            t = parse_time(r["game_time_utc"])
            if not (now - timedelta(days=LOOKBACK_DAYS) <= t <= now - timedelta(hours=WAIT_HOURS)):
                continue
            g = games.setdefault(sid, {"id": sid, "scheduled": r["game_time_utc"], "event_id": "",
                                       "away_team": r["away_team"], "home_team": r["home_team"]})
            g["scheduled"] = r["game_time_utc"]  # 以最後一次快照的開賽時間為準
            if r.get("event_id"):
                g["event_id"] = r["event_id"]
    return list(games.values())


def result_row(sport, g, ev):
    st = ev["status"]
    status = "final" if ev["completed"] else ("canceled" if "CANCEL" in st else "postponed" if "POSTPONE" in st else "")
    row = {
        "sport": sport, "sbd_id": g["id"], "event_id": ev["event_id"], "game_time_utc": g["scheduled"],
        "season_type": ev["season_type"], "series_note": ev["series_note"],
        "away_team": g["away_team"], "home_team": g["home_team"], "status": status,
    }
    if status == "final":
        try:
            a, h = float(ev["away"]["score"]), float(ev["home"]["score"])
        except (TypeError, ValueError, KeyError):
            return None
        a, h = int(a) if a.is_integer() else a, int(h) if h.is_integer() else h
        row.update({"away_score": a, "home_score": h, "margin": h - a, "total_points": a + h,
                    "winner": "home" if h > a else "away" if a > h else "tie"})
    return row


def run_sport(sport, now):
    games = pending_games(sport, now)
    if not games:
        return 0
    start = min(parse_time(g["scheduled"]) for g in games) - timedelta(days=1)
    events = espn_events(sport, start, now)
    by_id = {e["event_id"]: e for e in events}
    rows = []
    for g in games:
        ev = by_id.get(g["event_id"])
        if ev is None:
            # 舊資料沒有 ESPN 編號：用隊名 + 開賽時間對
            fake = {"scheduled": g["scheduled"], "competitors": {
                "away": {"name": g["away_team"]}, "home": {"name": g["home_team"]}}}
            ev = match_event(fake, events, college=is_college(sport))
        if ev is None or not (ev["completed"] or ev["state"] == "post"):
            continue
        row = result_row(sport, g, ev)
        if row and row["status"]:
            rows.append(row)
    append_rows(os.path.join(sport_dir(sport), "results.csv"), RESULT_FIELDS, rows)
    return len(rows)


def run():
    now = datetime.now(timezone.utc)
    for sport, cfg in active_sports().items():
        try:
            n = run_sport(sport, now)
            print(f"{cfg['name']}: 回填 {n} 場賽果")
        except Exception as e:
            print(f"{cfg['name']}: 回填失敗 {e}")


if __name__ == "__main__":
    run()
