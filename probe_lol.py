"""試探第 2 輪：舊下載頁的實際檔案網址、Leaguepedia（lol.fandom.com）API 有沒有首殺欄位"""
import re, json
import requests
UA = {"User-Agent": "money-flow-tracker personal research (non-commercial)"}
r = requests.get("https://lol.timsevenhuysen.com/matchdata/", headers=UA, timeout=30)
print("=== 舊下載頁含 2019/2020 的網址 ===")
for h in sorted(set(re.findall(r'(?:href|data-[a-z-]+)="([^"]+)"', r.text))):
    if re.search(r"20(1\d|2\d)", h) and "wp-content/themes" not in h:
        print(h)
print("\n=== Leaguepedia API ===")
API = "https://lol.fandom.com/api.php"
for table in ("ScoreboardGames", "ScoreboardPlayers", "ScoreboardTeams"):
    try:
        q = {"action": "cargofields", "table": table, "format": "json"}
        j = requests.get(API, params=q, headers=UA, timeout=30).json()
        print(table, list((j.get("cargofields") or {}).keys()))
    except Exception as e:
        print(table, "失敗", e)
try:
    q = {"action": "cargoquery", "tables": "ScoreboardGames", "fields": "Tournament,Team1,Team2,Winner,DateTime_UTC", "where": "Tournament LIKE '%Worlds 2025%'", "limit": "3", "format": "json"}
    print(requests.get(API, params=q, headers=UA, timeout=30).text[:1500])
except Exception as e:
    print("query 失敗", e)
print("\n=== Leaguepedia 條款相關 ===")
r = requests.get("https://lol.fandom.com/wiki/Help:API_Documentation", headers=UA, timeout=30)
t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)))
for kw in ("rate", "limit", "commercial", "scrap", "bot"):
    m = re.search(kw, t)
    if m: print("…", t[max(0, m.start()-250):m.start()+300])
