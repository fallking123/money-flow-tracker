"""
職業版・足球資料來源試探：ESPN 的比賽頁有沒有先發名單、上場時間、射門數據，往前能到幾年
（GitHub Actions 上跑，只印結果，不存資料）
"""
import json
import time

import requests

UA = {"User-Agent": "money-flow-tracker research"}
LEAGUES = ["eng.1", "eng.2", "esp.1", "esp.2", "ita.1", "ita.2", "ger.1", "ger.2", "fra.1", "fra.2"]


def get(url):
    for _ in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code != 404:
                print("  ", r.status_code, url)
            return None
        except Exception as e:
            print("  失敗", e)
        time.sleep(2)
    return None


def main():
    for lg in LEAGUES:
        for y, d in ((2010, "1016"), (2013, "1019"), (2016, "1015"), (2019, "1019"), (2022, "1015"), (2025, "1018")):
            sb = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={y}{d}")
            evs = (sb or {}).get("events") or []
            if not evs:
                print(lg, y, "沒有比賽")
                continue
            eid = evs[0]["id"]
            sm = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/summary?event={eid}")
            if not sm:
                print(lg, y, "沒有 summary")
                continue
            ros = sm.get("rosters") or []
            n_players = sum(len(t.get("roster") or []) for t in ros)
            starters = sum(1 for t in ros for p in (t.get("roster") or []) if p.get("starter"))
            sub_info = any("subbedIn" in p or "subbedOut" in p for t in ros for p in (t.get("roster") or []))
            pstats = set()
            for t in ros:
                for p in t.get("roster") or []:
                    for s in p.get("stats") or []:
                        pstats.add(s.get("name"))
            tstats = set()
            for t in (sm.get("boxscore") or {}).get("teams") or []:
                for s in t.get("statistics") or []:
                    tstats.add(s.get("name"))
            print(lg, y, f"比賽 {len(evs)} 場；名單 {n_players} 人、先發 {starters}、換人資訊 {sub_info}；球員數據 {sorted(pstats)[:12]}；球隊數據 {sorted(tstats)[:14]}", flush=True)
            if lg == "eng.1" and y == 2016 and ros:
                print(json.dumps(ros[0]["roster"][0], ensure_ascii=False)[:1500])
            time.sleep(0.5)


if __name__ == "__main__":
    main()
