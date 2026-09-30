import json, re, requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "zh-CN,zh;q=0.9"}
out = {}
for k, u in {"500_jclq": "https://trade.500.com/jclq/", "500_jczq": "https://trade.500.com/jczq/",
             "500_jclq_sf": "https://trade.500.com/jclq/?playid=313", "500_jczq_spf": "https://trade.500.com/jczq/?playid=269",
             "sbobet": "https://www.sbobet.com/euro/basketball"}.items():
    try:
        r = requests.get(u, headers=H, timeout=25); r.encoding = r.apparent_encoding; t = r.text
        ctx = []
        for w in ["支持率", "投注比例", "比例", "交易量", "必发", "vote", "ratio", "support"]:
            for m in list(re.finditer(w, t))[:3]:
                ctx.append(w + " :: " + re.sub(r"\s+", " ", t[max(0, m.start()-200): m.end()+300]))
        out[k] = {"status": r.status_code, "ctx": ctx[:12], "scripts": re.findall(r'src="([^"]+\.js[^"]*)"', t)[:20],
                  "ajax": list(set(re.findall(r'["\'](/[a-z_/]+\.(?:php|json|do|aspx)[^"\']*)', t)))[:30],
                  "matches": re.findall(r'(?:主队|客队|homesxname|awaysxname)[^<]{0,80}', t)[:6]}
    except Exception as e:
        out[k] = {"error": str(e)[:200]}
json.dump(out, open("probe/asia_result.json", "w"), ensure_ascii=False, indent=1)
