"""
英雄聯盟歷史比賽資料（Oracle's Elixir，免費提供給分析者、評論者和球迷；比賽數據屬於 Riot Games）
使用者給的 Google Drive 檔案 → 只留「每場每隊一列」需要的欄位（首殺、首條巴龍等），存成小檔
輸出 docs/data/esports/lol_teams_<年>.csv.gz
用法：python fetch_lol.py <Google Drive 檔案 ID> <年>
"""
import csv, gzip, io, os, sys
import requests

FID, YEAR = sys.argv[1], sys.argv[2]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "esports")
KEEP = ["gameid", "league", "year", "split", "playoffs", "date", "game", "patch", "side", "teamname", "teamid", "gamelength", "result",
        "kills", "deaths", "firstblood", "firstdragon", "firstherald", "firstbaron", "firsttower", "barons", "towers", "dragons",
        "golddiffat10", "golddiffat15"]
s = requests.Session()
r = s.get("https://drive.usercontent.google.com/download", params={"id": FID, "export": "download", "confirm": "t"}, timeout=300)
r.raise_for_status()
txt = r.content.decode("utf-8-sig", errors="ignore")
print("下載", len(r.content) // 1024 // 1024, "MB", txt[:200].replace("\n", " | "))
rows = [x for x in csv.DictReader(io.StringIO(txt)) if x.get("position") == "team"]
os.makedirs(OUT, exist_ok=True)
with gzip.open(os.path.join(OUT, f"lol_teams_{YEAR}.csv.gz"), "wt", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=KEEP, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
print("隊伍列", len(rows))
