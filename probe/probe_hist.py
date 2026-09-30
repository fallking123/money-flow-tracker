"""探測（四）：ESPN core odds（近幾季）、SBRO NBA/NHL/NFL 頁面結構"""
import json, re, requests
out = {"core": {}, "sbro": {}}
PATH = {"nba": ("basketball", "nba", "20250115"), "nhl": ("hockey", "nhl", "20250115"), "mlb": ("baseball", "mlb", "20250615"), "nfl": ("football", "nfl", "20251012")}
for sp, (s, l, d) in PATH.items():
    try:
        j = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/{s}/{l}/scoreboard", params={"dates": d, "limit": "300"}, timeout=25).json()
        eid = j["events"][0]["id"]
        r = requests.get(f"https://sports.core.api.espn.com/v2/sports/{s}/leagues/{l}/events/{eid}/competitions/{eid}/odds", timeout=25)
        jj = r.json()
        items = jj.get("items") or []
        out["core"][sp] = {"status": r.status_code, "count": jj.get("count"), "providers": [(i.get("provider") or {}).get("name") for i in items],
                           "sample": items[0] if items else jj}
    except Exception as ex:
        out["core"][sp] = str(ex)[:300]
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
for sp in ["nba", "nhl", "nfl"]:
    try:
        r = requests.get(f"https://www.sportsbookreviewsonline.com/scoresoddsarchives/{sp}/{sp}oddsarchives.htm", headers=H, timeout=40)
        hrefs = re.findall(r'href="([^"]+)"', r.text)
        out["sbro"][sp] = {"status": r.status_code, "odds_links": [h for h in hrefs if "odds" in h.lower()][:40]}
        cand = [h for h in hrefs if re.search(r"(20\d\d)", h) and ("odds" in h.lower())]
        if cand:
            u = cand[0] if cand[0].startswith("http") else "https://www.sportsbookreviewsonline.com" + cand[0]
            r2 = requests.get(u, headers=H, timeout=40)
            out["sbro"][sp]["first"] = {"url": u, "status": r2.status_code, "type": r2.headers.get("content-type"), "len": len(r2.content),
                                        "table_head": re.sub(r"\s+", " ", r2.text[r2.text.find("<table"): r2.text.find("<table") + 1500]) if "html" in (r2.headers.get("content-type") or "") else ""}
    except Exception as ex:
        out["sbro"][sp] = str(ex)[:300]
json.dump(out, open("probe/hist_result.json", "w"), ensure_ascii=False, indent=1)
