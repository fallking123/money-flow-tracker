"""探測：亞洲（中國官方體彩、賠率網站）有沒有公開的 NBA／足球下注比例"""
import json, requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
     "Referer": "https://www.sporttery.cn/", "Accept-Language": "zh-CN,zh;q=0.9"}
URLS = {
 "sporttery_bk_list": "https://webapi.sporttery.cn/gateway/jc/basketball/getMatchListV1.qry?clientCode=3001",
 "sporttery_bk_calc": "https://webapi.sporttery.cn/gateway/jc/basketball/getMatchCalculatorV1.qry?poolCode=hdc,hilo,mnl,wnm&channel=c",
 "sporttery_fb_calc": "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry?channel=c&poolCode=hhad,had",
 "sporttery_fb_list": "https://webapi.sporttery.cn/gateway/jc/football/getMatchListV1.qry?clientCode=3001",
 "sporttery_vote": "https://webapi.sporttery.cn/gateway/jc/common/getVoteV1.qry",
 "500_jclq": "https://trade.500.com/jclq/",
 "500_jczq": "https://trade.500.com/jczq/",
 "500_odds": "https://odds.500.com/lq/",
 "okooo": "https://www.okooo.com/jingcai/",
 "titan007_nba": "https://nba.titan007.com/",
 "titan007_odds": "https://live.titan007.com/",
 "hkjc_fb": "https://bet.hkjc.com/football/",
 "hkjc_api": "https://info.cld.hkjc.com/graphql/base/",
 "betfair_ex": "https://www.betfair.com/exchange/plus/basketball",
 "sbobet": "https://www.sbobet.com/euro/basketball",
 "pinnacle_guest": "https://guest.api.arcadia.pinnacle.com/0.1/sports/4/leagues?all=false",
}
out = {}
for k, u in URLS.items():
    try:
        r = requests.get(u, headers=H, timeout=25)
        t = r.text
        out[k] = {"status": r.status_code, "len": len(t), "head": t[:1500],
                  "has_pct": any(w in t for w in ["支持率", "投注比例", "support", "vote", "ratio", "bets_pct", "交易量"])}
    except Exception as e:
        out[k] = {"error": str(e)[:300]}
json.dump(out, open("probe/asia_result.json", "w"), ensure_ascii=False, indent=1)
