"""一次性探測：Action Network 各運動有哪些玩法、哪些有下注人數/金額%（單隊大小、前五局、第一局…）"""
import json, os
from datetime import datetime, timedelta, timezone
import requests
UA = {"User-Agent": "Mozilla/5.0"}
out = {}
now = datetime.now(timezone.utc)
for lg in ["mlb", "nhl", "nba", "nfl"]:
    info = {}
    for d in range(0, 3):
        day = (now + timedelta(days=d)).strftime("%Y%m%d")
        for books in ["15", "15,30,68,69,71,75,79"]:
            try:
                r = requests.get(f"https://api.actionnetwork.com/web/v2/scoreboard/{lg}", params={"bookIds": books, "date": day, "periods": "event,firsthalf,firstquarter,firstperiod,firstinning,firstfiveinnings"}, headers=UA, timeout=30)
                games = r.json().get("games") or []
            except Exception as e:
                info[f"{day}_{books}"] = str(e); continue
            if not games: continue
            g = games[0]
            mk = g.get("markets") or {}
            summ = {}
            for bid, per in mk.items():
                for period, m in (per or {}).items():
                    for bt, outs in (m or {}).items():
                        with_split = sum(1 for o in outs if ((o.get("bet_info") or {}).get("tickets") or {}).get("percent"))
                        summ[f"{bid}/{period}/{bt}"] = {"n": len(outs), "with_split": with_split, "sample": {k: outs[0].get(k) for k in ("side", "value", "odds", "team_id", "is_alt_market")} if outs else None}
            info[f"{day}_{books}"] = {"games": len(games), "game": f"{g.get('away_team_id')}@{g.get('home_team_id')} {g.get('start_time')}", "markets": summ}
            break
        if info: break
    out[lg] = info
# 另外試 v1 game 端點（單場詳細）
os.makedirs("probe", exist_ok=True)
json.dump(out, open("probe/markets_result.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps(out, indent=1)[:4000])
