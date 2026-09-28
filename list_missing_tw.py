"""
每天列出「需要台彩截圖」的比賽清單
============================================
用途：排程每天固定時間跑一次，把「已完賽、但你還沒傳過台彩截圖」的比賽列出來，
提醒你去補記錄。只看最近一段時間的比賽（LOOKBACK_HOURS），不會一直往前翻舊帳。

判斷邏輯：只要 tw_odds.csv 裡有這場比賽（不管哪個盤別）的任何一筆記錄，
就算「已經記錄過」，不會再列出來。
"""

from datetime import datetime, timezone, timedelta

from sports_common import DATA_DIR, active_sports, parse_time, read_rows, sport_dir
import os

LOOKBACK_HOURS = 36  # 抓最近這麼多小時內完賽的比賽（排程一天跑一次，抓超過 24 小時保險一點）
TW_ODDS_FILE = os.path.join(DATA_DIR, "tw_odds.csv")

FMT = "%m/%d %H:%M"
TZ = timezone(timedelta(hours=8))  # 台灣時間，只是用來顯示


def missing_games(now):
    recorded = {r["sbd_id"] for r in read_rows(TW_ODDS_FILE)}
    out = {}
    for sport, cfg in active_sports().items():
        rows = read_rows(os.path.join(sport_dir(sport), "results.csv"))
        games = []
        for r in rows:
            if r.get("status") != "final":
                continue
            if r["sbd_id"] in recorded:
                continue
            t = parse_time(r["game_time_utc"])
            if not (now - timedelta(hours=LOOKBACK_HOURS) <= t <= now):
                continue
            games.append((t, r))
        games.sort(key=lambda x: x[0])
        if games:
            out[sport] = [(t, r) for t, r in games]
    return out


def format_report(missing):
    if not missing:
        return "今天完賽的比賽都已經有台彩記錄了（或最近沒有完賽的比賽），不用傳截圖。"
    lines = ["今天這些已完賽的比賽，還沒有台彩賠率記錄，有截圖的話麻煩傳給我：", ""]
    for sport, games in missing.items():
        from sports_common import SPORTS
        lines.append(f"【{SPORTS[sport]['name']}】")
        for t, r in games:
            local = t.astimezone(TZ).strftime(FMT)
            score = f"{r['away_score']}－{r['home_score']}" if r.get("away_score") else ""
            lines.append(f"  {local}　{r['away_team']} @ {r['home_team']}　{score}")
        lines.append("")
    lines.append("没截图的场次跳过就好，不用每一场都补。")
    return "\n".join(lines).strip()


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    missing = missing_games(now)
    print(format_report(missing))
