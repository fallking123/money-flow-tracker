"""探測：各運動歷史比賽的收盤賠率從哪裡拿得到、涵蓋哪幾季"""
import json, requests
H = {"User-Agent": "Mozilla/5.0"}
out = {"espn": {}, "espn_summary": {}, "other": {}}
PATH = {"nba": "basketball/nba", "nhl": "hockey/nhl", "mlb": "baseball/mlb", "nfl": "football/nfl"}
DATES = {"nba": ["20100115", "20140115", "20170115", "20190115", "20210215", "20230115", "20250115"],
         "nhl": ["20100115", "20140115", "20170115", "20190115", "20210215", "20230115", "20250115"],
         "mlb": ["20100615", "20140615", "20170615", "20190615", "20210615", "20230615", "20250615"],
         "nfl": ["20101010", "20141012", "20171015", "20191013", "20211010", "20231015", "20251012"]}
for sp, ds in DATES.items():
    out["espn"][sp] = {}
    for d in ds:
        try:
            j = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/{PATH[sp]}/scoreboard", params={"dates": d}, headers=H, timeout=25).json()
            evs = j.get("events") or []
            with_odds = 0; sample = None; eid = None
            for e in evs:
                o = (e["competitions"][0].get("odds") or [])
                if o:
                    with_odds += 1
                    if sample is None:
                        sample = o[0]; eid = e["id"]
            out["espn"][sp][d] = {"games": len(evs), "with_odds": with_odds, "sample": sample, "eid": eid or (evs[0]["id"] if evs else None)}
        except Exception as ex:
            out["espn"][sp][d] = str(ex)[:200]
    # summary pickcenter for one old and one recent game
    for d in (ds[1], ds[4], ds[6]):
        eid = (out["espn"][sp].get(d) or {}).get("eid") if isinstance(out["espn"][sp].get(d), dict) else None
        if not eid:
            continue
        try:
            j = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/{PATH[sp]}/summary", params={"event": eid}, headers=H, timeout=25).json()
            out["espn_summary"][f"{sp}_{d}"] = {"pickcenter": (j.get("pickcenter") or [])[:2], "odds": (j.get("odds") or [])[:1],
                                                "keys": list(j.keys())}
        except Exception as ex:
            out["espn_summary"][f"{sp}_{d}"] = str(ex)[:200]
import re
for sp in ["nba", "nhl", "mlb"]:
    try:
        r = requests.get(f"https://www.sportsbookreviewsonline.com/scoresoddsarchives/{sp}/{sp}oddsarchives.htm", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}, timeout=40)
        links = re.findall(r'href="([^"]+\.xlsx?)"', r.text, re.I)
        out["other"][f"sbro_{sp}_links"] = links[:40]
        if links:
            u = links[0] if links[0].startswith("http") else "https://www.sportsbookreviewsonline.com/scoresoddsarchives/" + sp + "/" + links[0]
            r2 = requests.get(u, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}, timeout=40)
            out["other"][f"sbro_{sp}_first"] = {"url": u, "status": r2.status_code, "len": len(r2.content), "type": r2.headers.get("content-type")}
    except Exception as ex:
        out["other"][f"sbro_{sp}"] = str(ex)[:200]
json.dump(out, open("probe/hist_result.json", "w"), ensure_ascii=False, indent=1)
