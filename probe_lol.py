"""試探第 3 輪：舊資料頁（2016–2020）實際下載網址"""
import re
import requests
UA = {"User-Agent": "money-flow-tracker personal research (non-commercial)"}
for s in ["2019-spring", "2019-worlds", "2020-summer", "2018-spring"]:
    r = requests.get(f"https://lol.timsevenhuysen.com/gamedata/{s}/", headers=UA, timeout=30)
    print("==", s, r.status_code, len(r.text))
    for h in sorted(set(re.findall(r'(?:href|src|data-[a-z-]+)="([^"]+)"', r.text))):
        if any(x in h.lower() for x in (".csv", ".xls", "drive", "amazonaws", "download", "docs.google", "dropbox")):
            print("  ", h)
