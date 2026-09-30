"""探測：各運動歷史比賽的收盤賠率從哪裡拿得到、涵蓋哪幾季"""
import json, requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
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
for k, u in {"nflverse": "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
             "sbro_nba_page": "https://www.sportsbookreviewsonline.com/scoresoddsarchives/nba/nbaoddsarchives.htm",
             "sbro_nba_xlsx": "https://www.sportsbookreviewsonline.com/scoresoddsarchives/nba/nba%20odds%202019-20.xlsx",
             "sbro_nhl_xlsx": "https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl/nhl%20odds%202018-19.xlsx",
             "sbro_mlb_xlsx": "https://www.sportsbookreviewsonline.com/scoresoddsarchives/mlb/mlb%20odds%202019.xlsx",
             "moneypuck": "https://moneypuck.com/moneypuck/playerData/seasonSummary/2023/regular/teams.csv",
             "retrosheet_gl": "https://www.retrosheet.org/gamelogs/gl2023.zip"}.items():
    try:
        r = requests.get(u, headers=H, timeout=40)
        out["other"][k] = {"status": r.status_code, "len": len(r.content), "type": r.headers.get("content-type"), "head": r.text[:600] if "text" in (r.headers.get("content-type") or "") or k == "nflverse" else ""}
    except Exception as ex:
        out["other"][k] = str(ex)[:200]
json.dump(out, open("probe/hist_result.json", "w"), ensure_ascii=False, indent=1)
