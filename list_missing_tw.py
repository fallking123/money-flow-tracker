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


GOAL = 20  # 每個運動記到這麼多場就夠了（跟 App 台彩頁一樣），之後不再提醒


def recorded_counts():
    games = {(r["sport"], r["sbd_id"]) for r in read_rows(TW_ODDS_FILE)}
    out = {}
    for sport, _ in games:
        out[sport] = out.get(sport, 0) + 1
    return out


def missing_games(now):
    recorded = {r["sbd_id"] for r in read_rows(TW_ODDS_FILE)}
    counts = recorded_counts()
    out = {}
    for sport, cfg in active_sports().items():
        if sport not in ("mlb", "nba") or counts.get(sport, 0) >= GOAL:   # 玩運彩只有 MLB、NBA 附台彩賠率
            continue
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
    # 足球（比賽編號是 an+Action Network 編號）
    if True:   # 足球：玩運彩沒有附台彩賠率，不提醒
        return out
    games = []
    for r in read_rows(os.path.join(sport_dir("soccer"), "results.csv")):
        if r.get("status") != "final" or f"an{r['an_id']}" in recorded:
            continue
        t = parse_time(r["game_time_utc"])
        if now - timedelta(hours=LOOKBACK_HOURS) <= t <= now:
            games.append((t, r))
    if games:
        out["soccer"] = sorted(games, key=lambda x: x[0])
    return out


def format_report(missing):
    if not missing:
        return "今天完賽的比賽都已經有台彩記錄了（或最近沒有完賽的比賽），不用傳截圖。"
    lines = ["今天這些已完賽的比賽，還沒有台彩賠率記錄，有截圖的話麻煩傳給我：", ""]
    from sports_common import SPORTS
    lg = {"epl": "英超", "laliga": "西甲", "seriea": "義甲", "bundesliga": "德甲", "ligue1": "法甲", "ucl": "歐冠"}
    for sport, games in missing.items():
        lines.append(f"【{'足球' if sport == 'soccer' else SPORTS[sport]['name']}】")
        for t, r in games:
            local = t.astimezone(TZ).strftime(FMT)
            if sport == "soccer":  # 足球主隊寫前面
                score = f"{r['home_score']}－{r['away_score']}" if r.get("home_score") != "" else ""
                lines.append(f"  {local}　{lg.get(r.get('league'), '')}　{r['home_team']} vs {r['away_team']}　{score}")
                continue
            score = f"{r['away_score']}－{r['home_score']}" if r.get("away_score") else ""
            lines.append(f"  {local}　{r['away_team']} @ {r['home_team']}　{score}")
        lines.append("")
    counts = recorded_counts()
    lines.append("進度：" + "、".join(f"{'足球' if k == 'soccer' else k.upper()} {v}/{GOAL}" for k, v in sorted(counts.items())) + f"（每個運動記到 {GOAL} 場就夠了）")
    lines.append("沒截圖的場次跳過就好，不用每一場都補。App 的「台彩」頁也看得到這份清單。")
    return "\n".join(lines).strip()


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    missing = missing_games(now)
    print(format_report(missing))
