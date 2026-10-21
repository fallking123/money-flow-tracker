"""
足球賽事清單（五大聯賽以外的也在這裡）：代號、中文名、分類、ESPN 路徑、Pinnacle 聯賽名稱、Action Network 名稱
- group：big5＝五大聯賽（原本的模型一）、euro＝歐洲賽事、cup＝國內盃賽、intl＝國家隊、league＝其他聯賽
- kind：club＝俱樂部、national＝國家隊（全球足球模型用不同的強弱分數）
- pin：Pinnacle 聯賽名稱（完全一樣，或用 * 結尾表示「開頭一樣」）
- an：Action Network 名稱（有的才有下注比例＝資金流向）
"""

COMPS = {
    # 五大聯賽（原本的模型一，不動）
    "epl":        {"zh": "英超", "group": "big5", "kind": "club", "espn": ["eng.1"], "pin": ["England - Premier League"], "an": "epl"},
    "laliga":     {"zh": "西甲", "group": "big5", "kind": "club", "espn": ["esp.1"], "pin": ["Spain - La Liga"], "an": "laliga"},
    "seriea":     {"zh": "義甲", "group": "big5", "kind": "club", "espn": ["ita.1"], "pin": ["Italy - Serie A"], "an": "seriea"},
    "bundesliga": {"zh": "德甲", "group": "big5", "kind": "club", "espn": ["ger.1"], "pin": ["Germany - Bundesliga"], "an": "bundesliga"},
    "ligue1":     {"zh": "法甲", "group": "big5", "kind": "club", "espn": ["fra.1"], "pin": ["France - Ligue 1"], "an": "ligue1"},
    # 歐洲賽事
    "ucl":  {"zh": "歐冠", "group": "euro", "kind": "club", "espn": ["uefa.champions", "uefa.champions_qual"], "pin": ["UEFA - Champions League", "UEFA - Champions League Qualifiers*"], "an": "champions"},
    "uel":  {"zh": "歐霸", "group": "euro", "kind": "club", "espn": ["uefa.europa", "uefa.europa_qual"], "pin": ["UEFA - Europa League", "UEFA - Europa League Qualifiers*"], "an": "europa"},
    "uecl": {"zh": "歐協聯", "group": "euro", "kind": "club", "espn": ["uefa.europa.conf", "uefa.europa.conf_qual"], "pin": ["UEFA - Conference League", "UEFA - Conference League Qualifiers*"]},
    # 國內盃賽
    "facup":  {"zh": "英足總盃", "group": "cup", "kind": "club", "espn": ["eng.fa"], "pin": ["England - FA Cup"]},
    "eflcup": {"zh": "英聯賽盃", "group": "cup", "kind": "club", "espn": ["eng.league_cup"], "pin": ["England - EFL Cup", "England - League Cup"]},
    "cdr":    {"zh": "國王盃", "group": "cup", "kind": "club", "espn": ["esp.copa_del_rey"], "pin": ["Spain - Copa del Rey", "Spain - Cup"]},
    "coppa":  {"zh": "義大利盃", "group": "cup", "kind": "club", "espn": ["ita.coppa_italia"], "pin": ["Italy - Coppa Italia", "Italy - Cup"]},
    "dfb":    {"zh": "德國盃", "group": "cup", "kind": "club", "espn": ["ger.dfb_pokal"], "pin": ["Germany - Cup", "Germany - DFB Pokal"]},
    "cdf":    {"zh": "法國盃", "group": "cup", "kind": "club", "espn": ["fra.coupe_de_france"], "pin": ["France - Cup", "France - Coupe de France"]},
    "libertadores": {"zh": "南美解放者盃", "group": "cup", "kind": "club", "espn": ["conmebol.libertadores"], "pin": ["CONMEBOL - Copa Libertadores"]},
    "sudamericana": {"zh": "南美球會盃", "group": "cup", "kind": "club", "espn": ["conmebol.sudamericana"], "pin": ["CONMEBOL - Copa Sudamericana"]},
    # 國家隊
    "wc":    {"zh": "世界盃", "group": "intl", "kind": "national", "espn": ["fifa.world"], "pin": ["FIFA - World Cup"]},
    "wcq":   {"zh": "世界盃資格賽", "group": "intl", "kind": "national", "espn": ["fifa.worldq.uefa", "fifa.worldq.conmebol", "fifa.worldq.afc", "fifa.worldq.concacaf", "fifa.worldq.caf"],
              "pin": ["FIFA - World Cup Qualifiers*", "World Cup - Qualif*", "FIFA - World Cup Qualification*"]},
    "unl":   {"zh": "歐國聯", "group": "intl", "kind": "national", "espn": ["uefa.nations"], "pin": ["UEFA - Nations League*"]},
    "euro":  {"zh": "歐洲盃", "group": "intl", "kind": "national", "espn": ["uefa.euro", "uefa.euroq"], "pin": ["UEFA - EURO", "UEFA - EURO Qualifiers*", "UEFA - European Championship*"]},
    "copa":  {"zh": "美洲盃", "group": "intl", "kind": "national", "espn": ["conmebol.america"], "pin": ["CONMEBOL - Copa America"]},
    "asian": {"zh": "亞洲盃", "group": "intl", "kind": "national", "espn": ["afc.asian.cup"], "pin": ["AFC - Asian Cup*"]},
    "friendly": {"zh": "國際友誼賽", "group": "intl", "kind": "national", "espn": ["fifa.friendly"], "pin": ["International - Friendlies", "FIFA - Friendlies", "International Friendlies", "Friendlies - International*"]},
    # 其他聯賽
    "champ": {"zh": "英冠", "group": "league", "kind": "club", "espn": ["eng.2"], "pin": ["England - Championship"]},
    "mls":   {"zh": "美職", "group": "league", "kind": "club", "espn": ["usa.1"], "pin": ["USA - Major League Soccer"], "an": "mls"},
    "ligamx": {"zh": "墨超", "group": "league", "kind": "club", "espn": ["mex.1"], "pin": ["Mexico - Liga MX"]},
    "ered":  {"zh": "荷甲", "group": "league", "kind": "club", "espn": ["ned.1"], "pin": ["Netherlands - Eredivisie"]},
    "por":   {"zh": "葡超", "group": "league", "kind": "club", "espn": ["por.1"], "pin": ["Portugal - Primeira Liga"]},
    "bel":   {"zh": "比甲", "group": "league", "kind": "club", "espn": ["bel.1"], "pin": ["Belgium - Pro League"]},
    "tur":   {"zh": "土超", "group": "league", "kind": "club", "espn": ["tur.1"], "pin": ["Turkey - Super League"]},
    "sco":   {"zh": "蘇超", "group": "league", "kind": "club", "espn": ["sco.1"], "pin": ["Scotland - Premiership"]},
    "gre":   {"zh": "希超", "group": "league", "kind": "club", "espn": ["gre.1"], "pin": ["Greece - Super League"]},
    "aut":   {"zh": "奧超", "group": "league", "kind": "club", "espn": ["aut.1"], "pin": ["Austria - Bundesliga"]},
    "sui":   {"zh": "瑞士超", "group": "league", "kind": "club", "espn": ["sui.1"], "pin": ["Switzerland - Super League"]},
    "den":   {"zh": "丹超", "group": "league", "kind": "club", "espn": ["den.1"], "pin": ["Denmark - Superliga"]},
    "nor":   {"zh": "挪超", "group": "league", "kind": "club", "espn": ["nor.1"], "pin": ["Norway - Eliteserien"]},
    "swe":   {"zh": "瑞典超", "group": "league", "kind": "club", "espn": ["swe.1"], "pin": ["Sweden - Allsvenskan"]},
    "rus":   {"zh": "俄超", "group": "league", "kind": "club", "espn": ["rus.1"], "pin": ["Russia - Premier League"]},
    "bra":   {"zh": "巴甲", "group": "league", "kind": "club", "espn": ["bra.1"], "pin": ["Brazil - Serie A"]},
    "arg":   {"zh": "阿甲", "group": "league", "kind": "club", "espn": ["arg.1"], "pin": ["Argentina - Liga Pro", "Argentina - Primera Division"]},
    "jpn":   {"zh": "日職", "group": "league", "kind": "club", "espn": ["jpn.1"], "pin": ["Japan - J League"]},
    "kor":   {"zh": "韓職", "group": "league", "kind": "club", "espn": ["kor.1"], "pin": ["Korea Republic - K League 1"]},
    "chn":   {"zh": "中超", "group": "league", "kind": "club", "espn": ["chn.1"], "pin": ["China - Super League"]},
    "ksa":   {"zh": "沙烏地聯", "group": "league", "kind": "club", "espn": ["ksa.1"], "pin": ["Saudi Arabia - Pro League"]},
    "aus":   {"zh": "澳職", "group": "league", "kind": "club", "espn": ["aus.1"], "pin": ["Australia - A League"]},
}
GROUP_ZH = {"big5": "五大聯賽", "euro": "歐洲賽事", "cup": "盃賽", "intl": "國家隊", "league": "其他聯賽"}
BIG5 = [k for k, v in COMPS.items() if v["group"] == "big5"]


def pin_comp(name):
    """Pinnacle 聯賽名稱 → 我們的代號（對不到回傳 None）"""
    n = (name or "").strip().lower()
    for code, c in COMPS.items():
        for p in c["pin"]:
            p = p.lower()
            if (p.endswith("*") and n.startswith(p[:-1])) or n == p:
                return code
    return None
