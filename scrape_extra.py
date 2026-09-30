"""
其他玩法的賠率（美國四大運動）
================================
資料來源：Action Network 共識盤（book 15）。記錄主盤以外的玩法：
- 單隊大小（全場）
- MLB：前五局 獨贏／讓分／大小
- NHL：第一節 獨贏（含和局）／讓分／大小／單隊大小
- NBA、NFL：上半場、第一節 獨贏／讓分／大小／單隊大小

注意：這些玩法網站只有賠率，沒有下注人數／金額%（2026/9 探測過，只有全場三種主盤有）。
所以這裡是拿來：看賠率怎麼動、跟台彩賠率比抽多少、之後用比分算歷史機率。
網站之後如果開始提供比例，欄位已經留好，會自動記到。

每場比賽只有賠率有變動時才寫一筆（長格式：一個選項一列）。
輸出：docs/data/<運動>/extra_odds_YYYY-MM.csv
"""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import requests

from sports_common import ET, STATE_DIR, UA, active_sports, append_rows, monthly_path, parse_time

AN_URL = "https://api.actionnetwork.com/web/v2/scoreboard/{league}"
PERIODS = {
    "mlb": ["event", "firstfiveinnings", "firstinning"],
    "nhl": ["event", "firstperiod"],
    "nba": ["event", "firsthalf", "firstquarter"],
    "nfl": ["event", "firsthalf", "firstquarter"],
}
HORIZON_DAYS = {"mlb": 2, "nhl": 2, "nba": 2, "nfl": 7}
MAIN = {"moneyline", "spread", "total"}   # 全場這三種已經由 scrape_odds.py（SBD）記了
STATE_FILE = os.path.join(STATE_DIR, "extra_state.json")
FIELDS = ["timestamp_utc", "sport", "an_id", "game_time_utc", "hours_until_game", "away_team", "home_team",
          "period", "market", "side", "team", "line", "odds", "bets_pct", "money_pct"]
MARKET_NAME = {"core_bet_type_6_team_score": "team_total"}


def dec(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if v == 0 else round(1 + (v / 100 if v > 0 else 100 / -v), 4)


def rows_for(sport, g, now):
    teams = {t["id"]: t for t in g.get("teams") or []}
    side_of = {g.get("away_team_id"): "away", g.get("home_team_id"): "home"}
    t = parse_time(g["start_time"])
    base = {"timestamp_utc": now.isoformat(), "sport": sport, "an_id": g["id"], "game_time_utc": t.isoformat(),
            "hours_until_game": round((t - now).total_seconds() / 3600, 2),
            "away_team": teams.get(g.get("away_team_id"), {}).get("full_name", ""),
            "home_team": teams.get(g.get("home_team_id"), {}).get("full_name", "")}
    out = []
    for period, mk in (((g.get("markets") or {}).get("15")) or {}).items():
        for bt, outs in (mk or {}).items():
            if period == "event" and bt in MAIN:
                continue
            for o in outs or []:
                if o.get("is_alt_market"):
                    continue
                bi = o.get("bet_info") or {}
                tp, mp = (bi.get("tickets") or {}).get("percent"), (bi.get("money") or {}).get("percent")
                out.append({**base, "period": period, "market": MARKET_NAME.get(bt, bt), "side": o.get("side"),
                            "team": side_of.get(o.get("team_id"), ""), "line": o.get("value"), "odds": dec(o.get("odds")),
                            "bets_pct": tp or None, "money_pct": mp or None})
    return out


def run():
    now = datetime.now(timezone.utc)
    try:
        state = json.load(open(STATE_FILE))
    except Exception:
        state = {}
    total = 0
    for sport in PERIODS:
        if sport not in active_sports():
            continue
        new = []
        for i in range(HORIZON_DAYS[sport] + 1):
            day = (now.astimezone(ET) + timedelta(days=i)).strftime("%Y%m%d")
            try:
                r = requests.get(AN_URL.format(league=sport), headers=UA, timeout=30,
                                 params={"bookIds": "15", "date": day, "periods": ",".join(PERIODS[sport])})
                games = r.json().get("games") or []
            except Exception as e:
                print(f"  {sport} {day}: 讀取失敗 {e}")
                continue
            for g in games:
                if g.get("status") not in ("scheduled", "delayed") or not g.get("start_time"):
                    continue
                if parse_time(g["start_time"]) <= now:
                    continue
                rows = rows_for(sport, g, now)
                if not rows:
                    continue
                sig = hashlib.md5(json.dumps([(r["period"], r["market"], r["side"], r["team"], r["line"], r["odds"], r["bets_pct"], r["money_pct"])
                                              for r in rows], sort_keys=True).encode()).hexdigest()
                key = f"{sport}:{g['id']}"
                if state.get(key, {}).get("sig") == sig:
                    continue
                state[key] = {"sig": sig, "t": now.isoformat(), "game": g["start_time"]}
                new += rows
        append_rows(monthly_path(sport, "extra_odds", now), FIELDS, new)
        total += len(new)
        print(f"  {sport}: 其他玩法寫入 {len(new)} 筆")
    # 清掉 3 天前的比賽
    cutoff = now - timedelta(days=3)
    state = {k: v for k, v in state.items() if parse_time(v.get("game", v["t"])) > cutoff}
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump(state, open(STATE_FILE, "w"), indent=0)
    print(f"其他玩法：共 {total} 筆")


if __name__ == "__main__":
    run()
