"""
全球足球歷史賽果（給「全球足球模型」用）——在 GitHub Actions 上跑
================================================================
- 俱樂部：ESPN 每個賽事每天的賽程表（聯賽、盃賽、歐洲賽事）。ESPN 的球隊編號在所有賽事都一樣，
  所以同一支球隊在聯賽、盃賽、歐冠的比賽會接在一起（這樣才算得出各國聯賽誰強誰弱）。
- 國家隊：martj42/international_results（CC0 公開資料，1872 年起每一場國際賽）。
輸出 docs/data/soccer/world/espn_<賽事>.csv、intl_results.csv
用法：python fetch_world_soccer.py espn <賽事代號>   /   python fetch_world_soccer.py intl
已經抓過的日期會跳過（重跑只補新的）。
"""
import csv
import os
import sys
import time
from datetime import date, datetime, timedelta

import requests

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "soccer", "world")
UA = {"User-Agent": "money-flow-tracker research (personal, non-commercial)"}
FIELDS = ["date", "comp", "event", "home_id", "home", "away_id", "away", "hg", "ag", "neutral", "shootout_winner", "note"]
START = date(2014, 7, 1)


def espn(comp):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"espn_{comp}.csv")
    old, seen_days = [], set()
    if os.path.exists(path):
        old = list(csv.DictReader(open(path, encoding="utf-8")))
        seen_days = {r["date"] for r in old}
    last = max(seen_days) if seen_days else None
    d = START if not last else datetime.strptime(last, "%Y-%m-%d").date() - timedelta(days=3)
    keep = [r for r in old if not last or r["date"] < d.isoformat()]
    rows, n, empty_run = [], 0, 0
    today = date.today()
    while d <= today:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{comp}/scoreboard"
        js = None
        for i in range(3):
            try:
                r = requests.get(url, params={"dates": d.strftime("%Y%m%d"), "limit": "200"}, headers=UA, timeout=30)
                if r.status_code == 200:
                    js = r.json()
                    break
                if r.status_code in (400, 404):
                    break
            except Exception:
                time.sleep(2 * (i + 1))
        for ev in (js or {}).get("events") or []:
            c = (ev.get("competitions") or [{}])[0]
            st = ((c.get("status") or ev.get("status") or {}).get("type") or {})
            if not st.get("completed"):
                continue
            t = {x.get("homeAway"): x for x in c.get("competitors") or []}
            h, a = t.get("home") or {}, t.get("away") or {}
            sw = ""
            for side, x in (("home", h), ("away", a)):
                if x.get("shootoutScore") is not None and x.get("winner"):
                    sw = side
            rows.append({"date": d.isoformat(), "comp": comp, "event": ev.get("id"),
                         "home_id": (h.get("team") or {}).get("id", ""), "home": (h.get("team") or {}).get("displayName", ""),
                         "away_id": (a.get("team") or {}).get("id", ""), "away": (a.get("team") or {}).get("displayName", ""),
                         "hg": h.get("score", ""), "ag": a.get("score", ""), "neutral": int(bool(c.get("neutralSite"))),
                         "shootout_winner": sw, "note": (st.get("shortDetail") or "")[:20]})
            n += 1
        time.sleep(0.25)
        d += timedelta(days=1)
    seen = set()
    out = []
    for r in keep + rows:
        if r["event"] in seen:
            continue
        seen.add(r["event"])
        out.append(r)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    print(f"{comp}：新抓 {n} 場，全部 {len(out)} 場")


def intl():
    os.makedirs(OUT, exist_ok=True)
    r = requests.get("https://raw.githubusercontent.com/martj42/international_results/master/results.csv", headers=UA, timeout=60)
    r.raise_for_status()
    open(os.path.join(OUT, "intl_results.csv"), "w", encoding="utf-8").write(r.text)
    print("國家隊賽果", r.text.count("\n"), "行")


if __name__ == "__main__":
    if sys.argv[1] == "intl":
        intl()
    else:
        espn(sys.argv[2])
