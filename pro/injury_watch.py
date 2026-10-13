"""
職業版・NBA 傷兵消息的「時間點」記錄（為了以後研究：消息出來後，盤口多久、移多少）
================================================================
常駐工作每 10 分鐘跑一次：抓 ESPN 的 NBA 傷兵名單（一個請求就有全部球隊），跟上一次比，
只記「有變動」的：新出現、狀態改變（例如 Questionable → Out）、從名單消失。
- 我們記下的時間＝我們看到的時間（最多晚 10 分鐘）；ESPN 自己標的更新時間也一起存。
- Pinnacle 盤口本來就每 10 分鐘記一次（docs/data/nba/pinnacle_*.csv），之後兩個對時間就能研究。
輸出：docs/data/nba/injury_log_YYYY-MM.csv；上一次的狀態存在 docs/data/state/nba_injuries.json
用法：python -m pro.injury_watch nba
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = {"nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"}
FIELDS = ["seen_utc", "sport", "team", "player", "player_id", "change", "status_before", "status", "espn_date", "detail", "comment"]


def fetch(sport):
    r = requests.get(URL[sport], timeout=30, headers={"User-Agent": "money-flow-tracker research"})
    r.raise_for_status()
    cur = {}
    for blk in r.json().get("injuries") or []:
        team = blk.get("displayName") or blk.get("abbreviation") or ""
        for inj in blk.get("injuries") or []:
            a = inj.get("athlete") or {}
            pid = str(a.get("id") or a.get("uid") or a.get("displayName"))
            det = inj.get("details") or {}
            cur[pid] = {"team": (a.get("team") or {}).get("displayName") or team, "player": a.get("displayName", ""), "player_id": pid,
                        "status": inj.get("status") or (inj.get("type") or {}).get("description", ""),
                        "espn_date": inj.get("date", ""), "detail": " ".join(str(det.get(k, "")) for k in ("type", "location", "detail", "side")).strip(),
                        "comment": (inj.get("shortComment") or "")[:300]}
    return cur


def main(sport):
    now = datetime.now(timezone.utc)
    state_p = os.path.join(ROOT, "docs", "data", "state", f"{sport}_injuries.json")
    prev = json.load(open(state_p, encoding="utf-8")) if os.path.exists(state_p) else None
    try:
        cur = fetch(sport)
    except Exception as e:
        print(f"{sport} 傷兵名單抓取失敗：{e}")
        return
    rows = []
    if prev is not None:
        for pid, c in cur.items():
            p = prev.get(pid)
            if p is None:
                rows.append({**c, "change": "new", "status_before": ""})
            elif p.get("status") != c["status"]:
                rows.append({**c, "change": "status", "status_before": p.get("status", "")})
        for pid, p in prev.items():
            if pid not in cur:
                rows.append({**p, "change": "removed", "status_before": p.get("status", ""), "status": ""})
    else:
        rows = [{**c, "change": "initial", "status_before": ""} for c in cur.values()]
    if rows:
        path = os.path.join(ROOT, "docs", "data", sport, f"injury_log_{now:%Y-%m}.csv")
        new = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            if new:
                w.writeheader()
            for r in rows:
                w.writerow({**r, "seen_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "sport": sport})
    os.makedirs(os.path.dirname(state_p), exist_ok=True)
    json.dump(cur, open(state_p, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{sport} 傷兵名單：{len(cur)} 人，變動 {len(rows)} 筆")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "nba")
