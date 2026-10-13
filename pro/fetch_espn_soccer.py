"""
職業版・足球第 2 版資料：ESPN 每場比賽的先發名單、換人、球員數據（GitHub Actions 上跑，一個聯賽一個工作）
================================================================
- 跟專案其他地方一樣用 ESPN 公開的資料（傷兵、歷史賽程；hoopR 也是用 ESPN），請求放慢（每秒約 2 次）。
- 每個聯賽 2010/11 起：先用每天的賽程找到比賽，再抓每一場的名單。
輸出 docs/data/pro/soccer/espn_<聯賽>.csv.gz：每場每位有登錄的球員一列
  比賽、日期、主客隊、比分、這位球員的隊、先發、替補上場、被換下、換人的分鐘、位置、進球、助攻、射正、黃紅牌
用法：python -m pro.fetch_espn_soccer eng.1
"""
import csv
import gzip
import os
import re
import sys
import time
from datetime import date, timedelta

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data", "pro", "soccer")
UA = {"User-Agent": "money-flow-tracker research (personal, non-commercial)"}
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/{what}"
FIELDS = ["event", "date", "league", "home", "away", "hg", "ag", "team", "side", "player", "name", "starter", "sub_in", "sub_out",
          "min_in", "min_out", "pos", "goals", "assists", "sot", "shots", "yc", "rc"]
STAT = {"totalGoals": "goals", "goalAssists": "assists", "shotsOnTarget": "sot", "totalShots": "shots", "yellowCards": "yc", "redCards": "rc"}


def get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return None
        except Exception:
            pass
        time.sleep(2 * (i + 1))
    return None


def minute(play):
    m = re.match(r"(\d+)", str((play.get("clock") or {}).get("displayValue", "")))
    return int(m.group(1)) if m else ""


def events(lg, start, end):
    d = start
    seen = set()
    while d <= end:
        if d.month not in (6, 7) or d.year == 2020:          # 6、7 月沒有聯賽（2020 疫情延到 7 月）
            sb = get(BASE.format(lg=lg, what="scoreboard") + f"?dates={d:%Y%m%d}")
            for ev in (sb or {}).get("events") or []:
                st = ((ev.get("status") or {}).get("type") or {}).get("completed")
                if st and ev["id"] not in seen:
                    seen.add(ev["id"])
                    yield ev["id"], d
            time.sleep(0.4)
        d += timedelta(days=1)


def main(lg):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"espn_{lg}.csv.gz")
    done = set()
    if os.path.exists(path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            done = {r["event"] for r in csv.DictReader(f)}
    rows = []
    n = 0
    for eid, d in events(lg, date(2010, 7, 15), date.today()):
        if eid in done:
            continue
        sm = get(BASE.format(lg=lg, what="summary") + f"?event={eid}")
        time.sleep(0.4)
        if not sm:
            continue
        comp = ((sm.get("header") or {}).get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        h, a = teams.get("home", {}), teams.get("away", {})
        hn, an = (h.get("team") or {}).get("displayName", ""), (a.get("team") or {}).get("displayName", "")
        for t in sm.get("rosters") or []:
            side = t.get("homeAway")
            tn = (t.get("team") or {}).get("displayName", "")
            for p in t.get("roster") or []:
                ath = p.get("athlete") or {}
                st = {STAT[s["name"]]: s.get("value", s.get("displayValue")) for s in p.get("stats") or [] if s.get("name") in STAT}
                subs = [pl for pl in p.get("plays") or [] if pl.get("substitution")]
                rows.append({"event": eid, "date": d.isoformat(), "league": lg, "home": hn, "away": an, "hg": h.get("score", ""), "ag": a.get("score", ""),
                             "team": tn, "side": side, "player": ath.get("id", ""), "name": ath.get("displayName", ""),
                             "starter": int(bool(p.get("starter"))), "sub_in": int(bool(p.get("subbedIn"))), "sub_out": int(bool(p.get("subbedOut"))),
                             "min_in": minute(subs[0]) if p.get("subbedIn") and subs else "",
                             "min_out": minute(subs[-1]) if p.get("subbedOut") and subs else "",
                             "pos": (p.get("position") or {}).get("abbreviation", ""), **st})
        n += 1
        if n % 200 == 0:
            print(f"{lg}：{n} 場（{d}）", flush=True)
    old = []
    if os.path.exists(path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            old = list(csv.DictReader(f))
    with gzip.open(path, "wt", newline="", encoding="utf-8", compresslevel=9) as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(old + rows)
    print(f"{lg}：新抓 {n} 場，全部 {len(old) + len(rows)} 列", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
