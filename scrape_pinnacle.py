"""
Pinnacle（平博）盤口記錄
================================
Pinnacle 是全世界公認最「精」的莊家：抽成最低、歡迎職業玩家，亞洲大戶和代理商的錢大量透過它下注。
它不公開下注比例，但盤口會跟著大錢移動 → 用「Pinnacle 盤口往哪邊動」當作職業／亞洲大錢的方向。

來源：pinnacle.com 網站本身用的公開訪客資料（不用登入）。
記錄：主盤（不含替代盤）的獨贏、讓分、大小、單隊大小，全場＋各時段
      （MLB 前五局／第一局、NBA/NFL 上半場、NHL 第一節、足球上半場），
      足球另外記角球、黃牌等子盤（units 欄位）。
      長格式（一個選項一列），而且只寫「跟上一筆比有變動」的選項，不變的不重複寫，檔案才不會太大。
      要看某個時間點的完整盤口：取該時間以前每個選項的最後一筆。
      limit＝這個盤目前最多收多少（美元）；越接近開賽越高，代表莊家對這條線越有把握。

用法：python scrape_pinnacle.py mlb,nba,nfl,nhl   或   python scrape_pinnacle.py soccer
輸出：docs/data/<運動>/pinnacle_YYYY-MM.csv
"""
import sys
from datetime import datetime, timedelta, timezone

import requests

from sports_common import append_rows, monthly_path, parse_time, read_rows, recent_monthly_files

BASE = "https://guest.api.arcadia.pinnacle.com/0.1"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
           "Accept": "application/json", "Referer": "https://www.pinnacle.com/", "Origin": "https://www.pinnacle.com"}
# 運動 → [(聯賽代碼, Pinnacle 聯賽編號)]
LEAGUES = {
    "mlb": [("mlb", 246)],
    "nba": [("nba", 487)],
    "nfl": [("nfl", 889)],
    "nhl": [("nhl", 1456)],
    "soccer": [("epl", 1980), ("laliga", 2196), ("seriea", 2436), ("bundesliga", 1842), ("ligue1", 2036), ("ucl", 2627)],
}
HORIZON_H = {"mlb": 48, "nba": 48, "nhl": 48, "nfl": 24 * 7, "soccer": 24 * 12}
FIELDS = ["timestamp_utc", "sport", "league", "pin_id", "units", "game_time_utc", "hours_until_game", "home_team", "away_team",
          "period", "market", "team", "side", "line", "odds", "limit"]


def dec(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if v == 0 else round(1 + (v / 100 if v > 0 else 100 / -v), 4)


def get(path):
    r = requests.get(f"{BASE}/{path}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def league_rows(sport, league, lid, now):
    matchups = get(f"leagues/{lid}/matchups")
    markets = get(f"leagues/{lid}/markets/straight")
    games = {}
    for m in matchups:
        if m.get("type") != "matchup" or m.get("isLive") or not m.get("startTime"):
            continue
        t = parse_time(m["startTime"])
        hrs = (t - now).total_seconds() / 3600
        if not (0 < hrs <= HORIZON_H[sport]):
            continue
        teams = {p.get("alignment"): p.get("name", "") for p in m.get("participants") or []}
        if "home" not in teams or "away" not in teams:
            continue
        games[m["id"]] = {"parent": m.get("parentId") or m["id"], "units": m.get("units") or "Regular", "t": t, "hrs": hrs,
                          "home": teams["home"], "away": teams["away"]}
    by_parent = {}
    for mk in markets:
        g = games.get(mk.get("matchupId"))
        if not g or mk.get("isAlternate") or mk.get("status") != "open":
            continue
        lim = next((x.get("amount") for x in mk.get("limits") or [] if x.get("type") == "maxRiskStake"), None)
        for p in mk.get("prices") or []:
            by_parent.setdefault(g["parent"], []).append({
                "timestamp_utc": now.isoformat(), "sport": sport, "league": league, "pin_id": g["parent"], "units": g["units"],
                "game_time_utc": g["t"].isoformat(), "hours_until_game": round(g["hrs"], 2),
                "home_team": g["home"], "away_team": g["away"], "period": mk.get("period"), "market": mk.get("type"),
                "team": mk.get("side") or "", "side": p.get("designation"), "line": p.get("points"),
                "odds": dec(p.get("price")), "limit": lim})
    # 子盤（角球等）的隊名跟主盤一樣就好；以主盤的隊名為準
    return by_parent


def row_key(r):
    return (str(r["pin_id"]), r["units"], str(r["period"]), r["market"], r["team"], r["side"])


def last_known(sport):
    """從已經寫過的檔案找每個選項最後一次的盤口與賠率（不用另外存狀態檔）"""
    last = {}
    for path in recent_monthly_files(sport, "pinnacle", months=2):
        for r in read_rows(path):
            last[row_key(r)] = (str(r["line"]), str(r["odds"]))
    return last


def run(sports):
    now = datetime.now(timezone.utc)
    for sport in sports:
        last = last_known(sport)
        new = []
        for league, lid in LEAGUES[sport]:
            try:
                by_parent = league_rows(sport, league, lid, now)
            except Exception as e:
                print(f"  Pinnacle {sport}/{league}: 讀取失敗 {e}")
                continue
            for rows in by_parent.values():
                for r in rows:
                    cur = ("" if r["line"] is None else str(r["line"]), "" if r["odds"] is None else str(r["odds"]))
                    if last.get(row_key(r)) != cur:
                        new.append(r)
        append_rows(monthly_path(sport, "pinnacle", now), FIELDS, new)
        print(f"  Pinnacle {sport}: 寫入 {len(new)} 筆變動")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "mlb,nba,nfl,nhl,soccer"
    run([s for s in arg.split(",") if s in LEAGUES])
