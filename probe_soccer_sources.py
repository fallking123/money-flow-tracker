"""
試探：五大聯賽以外的足球賽事，各資料來源的代號（Pinnacle 聯賽編號、Action Network 名稱、ESPN 路徑）
只印結果（GitHub Actions 上跑，結果存 docs/data/soccer/probe_sources.txt）
"""
import time
from datetime import datetime, timedelta, timezone

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept": "application/json", "Referer": "https://www.pinnacle.com/", "Origin": "https://www.pinnacle.com"}

print("=== Pinnacle 足球聯賽（有比賽的）===")
try:
    L = requests.get("https://guest.api.arcadia.pinnacle.com/0.1/sports/29/leagues?all=false", headers=UA, timeout=30).json()
    for x in sorted(L, key=lambda x: -(x.get("matchupCount") or 0)):
        if (x.get("matchupCount") or 0) > 0:
            print(x.get("id"), "|", x.get("name"), "|", x.get("matchupCount"), "|", (x.get("group") or ""))
except Exception as e:
    print("失敗", e)

print("\n=== Action Network 足球（未來 7 天場數）===")
AN = ["champions", "ucl", "europa", "uel", "conference", "uecl", "europa-conference", "mls", "liga-mx", "eredivisie", "primeira-liga",
      "ligaportugal", "fa-cup", "facup", "efl-cup", "carabao-cup", "copa-del-rey", "coppa-italia", "dfb-pokal", "coupe-de-france",
      "championship", "efl", "scottish-premiership", "brasileirao", "argentina", "world-cup", "wcq", "world-cup-qualifiers", "nations-league",
      "uefa-nations-league", "international", "friendlies", "intl-friendlies", "euro", "copa-america", "j-league", "k-league", "soccer"]
now = datetime.now(timezone.utc)
for slug in AN:
    n, ok = 0, False
    for i in range(8):
        d = (now + timedelta(days=i)).strftime("%Y%m%d")
        try:
            r = requests.get(f"https://api.actionnetwork.com/web/v2/scoreboard/{slug}", params={"bookIds": "15", "date": d},
                             headers={"User-Agent": UA["User-Agent"]}, timeout=20)
            if r.status_code == 200:
                ok = True
                gs = r.json().get("games") or []
                n += len(gs)
                if gs and i == 0:
                    lg = gs[0].get("league_name") or gs[0].get("league_id")
            time.sleep(0.3)
        except Exception:
            pass
    print(slug, "可用" if ok else "不行", n)

print("\n=== ESPN（最近 60 天有沒有比賽）===")
ESPN = ["uefa.champions", "uefa.europa", "uefa.europa.conf", "eng.fa", "eng.league_cup", "esp.copa_del_rey", "ita.coppa_italia",
        "ger.dfb_pokal", "fra.coupe_de_france", "fifa.worldq.uefa", "fifa.worldq.conmebol", "fifa.worldq.afc", "fifa.worldq.concacaf",
        "fifa.worldq.caf", "uefa.nations", "fifa.friendly", "fifa.world", "uefa.euro", "conmebol.america", "afc.asian.cup",
        "por.1", "ned.1", "bel.1", "tur.1", "sco.1", "eng.2", "usa.1", "mex.1", "bra.1", "arg.1", "jpn.1", "kor.1", "chn.1", "aus.1",
        "sau.1", "gre.1", "aut.1", "sui.1", "den.1", "nor.1", "swe.1"]
for slug in ESPN:
    n = 0
    try:
        for k in range(0, 60, 3):
            d = (now - timedelta(days=k)).strftime("%Y%m%d")
            r = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard", params={"dates": d}, timeout=20)
            if r.status_code == 200:
                n += len(r.json().get("events") or [])
            time.sleep(0.2)
        print(slug, n)
    except Exception as e:
        print(slug, "失敗", e)
