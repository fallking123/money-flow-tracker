"""試探：英雄聯盟歷史資料（Oracle's Elixir）在哪裡下載、條款寫什麼。結果存 docs/data/esports/probe_lol.txt"""
import re
import requests
UA = {"User-Agent": "Mozilla/5.0 (personal research)"}
print("=== S3 清單 ===")
try:
    r = requests.get("https://oracleselixir-downloadable-match-data.s3-us-west-2.amazonaws.com/", headers=UA, timeout=30)
    print(r.status_code)
    for k in re.findall(r"<Key>([^<]+)</Key>", r.text):
        print(k)
except Exception as e:
    print("失敗", e)
print("\n=== 下載頁 ===")
for u in ["https://oracleselixir.com/tools/downloads", "https://lol.timsevenhuysen.com/matchdata/"]:
    try:
        r = requests.get(u, headers=UA, timeout=30)
        print(u, r.status_code, len(r.text))
        t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)
        links = set(re.findall(r'https?://[^"\'\s<>]*(?:drive\.google|amazonaws|docs\.google)[^"\'\s<>]*', r.text))
        print("連結:", *sorted(links), sep="\n  ")
        txt = re.sub(r"<[^>]+>", " ", t)
        txt = re.sub(r"\s+", " ", txt)
        for kw in ("terms", "Terms", "license", "License", "credit", "attribution", "commercial", "free"):
            for m in re.finditer(kw, txt):
                print("…", txt[max(0, m.start() - 200):m.start() + 250])
                break
    except Exception as e:
        print(u, "失敗", e)

print("\n=== 舊下載頁所有檔案連結 ===")
r = requests.get("https://lol.timsevenhuysen.com/matchdata/", headers=UA, timeout=30)
for h in sorted(set(re.findall(r'href="([^"]+)"', r.text))):
    if any(x in h.lower() for x in (".csv", ".xlsx", "drive", "amazonaws", "download")):
        print(h)
i = r.text.find("Below you will find")
print(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text[max(0, i - 3000):i + 3000])))
