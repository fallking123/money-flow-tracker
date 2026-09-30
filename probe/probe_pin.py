"""探測 Pinnacle 公開（訪客）API：聯賽編號、比賽列表、賠率格式"""
import json, requests
B = "https://guest.api.arcadia.pinnacle.com/0.1"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
     "Accept": "application/json", "Referer": "https://www.pinnacle.com/", "Origin": "https://www.pinnacle.com"}
out = {"leagues": {}, "samples": {}}
WANT = ["NBA", "NFL", "NHL", "MLB", "England - Premier League", "Spain - La Liga", "Italy - Serie A", "Germany - Bundesliga",
        "France - Ligue 1", "UEFA - Champions League", "NCAA"]
for sid in [3, 4, 15, 19, 29]:
    try:
        r = requests.get(f"{B}/sports/{sid}/leagues?all=false", headers=H, timeout=25)
        ls = r.json()
        out["leagues"][sid] = [{"id": l["id"], "name": l["name"], "n": l.get("matchupCount")} for l in ls
                               if any(w.lower() in l["name"].lower() for w in WANT)]
    except Exception as e:
        out["leagues"][sid] = str(e)[:200]
for sid, ls in out["leagues"].items():
    if not isinstance(ls, list):
        continue
    for l in ls[:4]:
        if not l.get("n"):
            continue
        res = {}
        for ep in ["matchups", "markets/straight"]:
            try:
                r = requests.get(f"{B}/leagues/{l['id']}/{ep}", headers=H, timeout=25)
                d = r.json()
                res[ep] = {"status": r.status_code, "n": len(d) if isinstance(d, list) else None,
                           "sample": d[:3] if isinstance(d, list) else d}
            except Exception as e:
                res[ep] = str(e)[:200]
        out["samples"][f"{sid}:{l['id']}:{l['name']}"] = res
json.dump(out, open("probe/pin_result.json", "w"), ensure_ascii=False, indent=1)
