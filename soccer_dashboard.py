"""
看板用的足球資料整理（給 build_dashboard.py 呼叫）
============================================
輸出格式跟美國運動一樣（games / closed），另外：
- snaps 的 ml 是三向：[主人數, 主金額, 和人數, 和金額, 客人數, 客金額, 主賠率, 和賠率, 客賠率]
- sp / ou 跟美國運動同格式（sp 的第 5 格是客隊讓分）
- th / ta：主隊／客隊單隊大小 [大人數, 大金額, 小人數, 小金額, 線, 大賠率, 小賠率]
- eu：對應到的歐洲賠率（football-data.co.uk 最新一筆）
"""

import os
import re
import unicodedata
from datetime import timedelta
from zoneinfo import ZoneInfo

from sports_common import all_monthly_files, parse_time, read_rows, recent_monthly_files, sport_dir

LONDON = ZoneInfo("Europe/London")
LEAGUE_ZH = {"epl": "英超", "laliga": "西甲", "seriea": "義甲", "bundesliga": "德甲", "ligue1": "法甲", "ucl": "歐冠"}

# 台灣常用中文隊名（依 Action Network 的隊名；沒有的就顯示英文）
ZH = {
    # 英超
    "Arsenal": "兵工廠", "Aston Villa": "阿斯頓維拉", "AFC Bournemouth": "伯恩茅斯", "Brentford": "布倫特福德",
    "Brighton & Hove Albion": "布萊頓", "Burnley": "伯恩利", "Chelsea": "切爾西", "Crystal Palace": "水晶宮",
    "Everton": "艾佛頓", "Fulham": "富勒姆", "Leeds United": "里茲聯", "Liverpool": "利物浦",
    "Manchester City": "曼城", "Manchester United": "曼聯", "Newcastle United": "紐卡索", "Nottingham Forest": "諾丁漢森林",
    "Sunderland": "桑德蘭", "Tottenham Hotspur": "熱刺", "West Ham United": "西漢姆", "Wolverhampton Wanderers": "狼隊",
    "Ipswich Town": "伊普斯維奇", "Coventry City": "考文垂", "Leicester City": "萊斯特城", "Southampton": "南安普敦",
    "Sheffield United": "謝菲爾德聯", "Hull City": "赫爾城",
    # 西甲
    "Real Madrid": "皇家馬德里", "Barcelona": "巴塞隆納", "Atletico Madrid": "馬德里競技", "Athletic Bilbao": "畢爾包",
    "Real Sociedad": "皇家社會", "Real Betis": "貝提斯", "Villarreal": "比利亞雷亞爾", "Sevilla": "塞維亞",
    "Valencia": "瓦倫西亞", "Girona": "赫羅納", "Celta Vigo": "塞爾塔", "Osasuna": "奧薩蘇納", "Getafe": "赫塔費",
    "Rayo Vallecano": "巴列卡諾", "Mallorca": "馬略卡", "Deportivo Alaves": "阿拉維斯", "Espanyol": "西班牙人",
    "Levante": "萊萬特", "Elche": "埃爾切", "Real Oviedo": "奧維耶多", "Las Palmas": "拉斯帕爾馬斯", "Leganes": "雷加內斯",
    "Real Valladolid": "瓦拉多利德", "Malaga CF": "馬拉加", "RC Deportivo La Coruna": "拉科魯尼亞",
    # 義甲
    "Inter": "國際米蘭", "AC Milan": "AC米蘭", "Juventus": "尤文圖斯", "SSC Napoli": "拿坡里", "Napoli": "拿坡里",
    "AS Roma": "羅馬", "Roma": "羅馬", "Lazio": "拉齊歐", "Atalanta": "亞特蘭大", "Fiorentina": "佛羅倫斯",
    "Bologna": "波隆那", "Torino": "杜林", "Genoa": "熱那亞", "Udinese": "烏迪內斯", "Hellas Verona": "維羅納",
    "Lecce": "萊切", "Cagliari": "卡利亞里", "Parma Calcio 1913": "帕爾馬", "Parma": "帕爾馬", "Como": "科莫",
    "Sassuolo": "薩索洛", "Cremonese": "克雷莫納", "Pisa": "比薩", "Frosinone Calcio": "弗羅西諾內", "Empoli": "恩波利",
    "Venezia": "威尼斯", "Monza": "蒙札",
    # 德甲
    "Bayern Munich": "拜仁慕尼黑", "Borussia Dortmund": "多特蒙德", "Bayer Leverkusen": "勒沃庫森", "RB Leipzig": "萊比錫",
    "Eintracht Frankfurt": "法蘭克福", "VfB Stuttgart": "斯圖加特", "Borussia Monchengladbach": "門興", "VfL Wolfsburg": "沃夫斯堡",
    "SC Freiburg": "弗萊堡", "Hoffenheim": "霍芬海姆", "Mainz 05": "美因茲", "Augsburg": "奧格斯堡", "Union Berlin": "柏林聯",
    "Werder Bremen": "不萊梅", "Heidenheim": "海登海姆", "St. Pauli": "聖保利", "Hamburger SV": "漢堡", "FC Koln": "科隆",
    "Paderborn": "帕德博恩", "Elversberg": "埃爾弗斯貝格", "Borussia Moenchengladbach": "門興", "FC Koeln": "科隆",
    # 法甲
    "Paris Saint-Germain": "巴黎聖日耳曼", "Marseille": "馬賽", "Lyon": "里昂", "Monaco": "摩納哥", "Lille": "里爾",
    "Nice": "尼斯", "Lens": "朗斯", "Rennes": "雷恩", "Nantes": "南特", "Strasbourg": "史特拉斯堡", "Brest": "布雷斯特",
    "Toulouse": "土魯斯", "Auxerre": "歐塞爾", "Angers": "昂熱", "Le Havre": "勒哈佛", "Lorient": "洛里昂", "Metz": "梅斯",
    "Paris FC": "巴黎FC", "Le Mans": "勒芒", "Saint-Etienne": "聖埃蒂安", "Reims": "漢斯", "Montpellier": "蒙彼利埃",
}

# Action Network 主色是白色（白卡片上看不見）或不對的，改用球隊代表色
COLOR_FIX = {
    "Athletic Bilbao": "#EE2523", "Atletico Madrid": "#CB3524", "Auxerre": "#1D4F91", "Borussia Moenchengladbach": "#1A1A1A",
    "Elche": "#05642C", "Elversberg": "#1A1A1A", "FC Koeln": "#ED1C24", "Fulham": "#1A1A1A", "Hamburger SV": "#0A3F86",
    "Lazio": "#6CC4EE", "Lyon": "#DA0812", "RB Leipzig": "#DD0741", "Rayo Vallecano": "#E53027", "Real Madrid": "#00529F",
    "Real Sociedad": "#0067B1", "Sunderland": "#EB172B", "Tottenham Hotspur": "#132257", "VfB Stuttgart": "#E32219",
    "Juventus": "#1A1A1A", "Newcastle United": "#241F20", "Swansea City": "#1A1A1A", "Augsburg": "#BA3733",
}

# football-data.co.uk 的簡稱 → 比較容易對上的全名
FD_ALIAS = {
    "man united": "manchester united", "man city": "manchester city", "nott m forest": "nottingham forest",
    "wolves": "wolverhampton", "ath bilbao": "athletic bilbao", "ath madrid": "atletico madrid", "sociedad": "real sociedad",
    "vallecano": "rayo vallecano", "espanol": "espanyol", "ein frankfurt": "eintracht frankfurt",
    "m gladbach": "monchengladbach", "fc koln": "koln", "paris sg": "paris saint germain", "st etienne": "saint etienne",
    "betis": "real betis", "celta": "celta vigo", "sheffield weds": "sheffield wednesday", "st pauli": "pauli",
}
STOP = {"fc", "cf", "ac", "sc", "afc", "ssc", "as", "rc", "sv", "club", "de", "1", "calcio", "1913", "town", "city", "united", "real"}


def num(v):
    if v in (None, ""):
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return int(f) if f.is_integer() else round(f, 4)


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return FD_ALIAS.get(s, s)


def toks(s):
    t = set(norm(s).split())
    core = t - STOP
    return core or t


def color(c, team=""):
    if team in COLOR_FIX:
        return COLOR_FIX[team]
    c = (c or "").strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        return None
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    if 0.299 * r + 0.587 * g + 0.114 * b > 235:  # 接近白色：改成灰藍，不然看不見
        return "#8A97AB"
    return f"#{c}"


def snap_of(r):
    ts = parse_time(r["timestamp_utc"])
    away_line = num(r["sp_home_line"])
    away_line = -away_line if away_line is not None else None
    g = lambda *ks: [num(r.get(k)) for k in ks]
    tt = lambda s: g(f"tt_{s}_over_bets_pct", f"tt_{s}_over_money_pct", f"tt_{s}_under_bets_pct", f"tt_{s}_under_money_pct",
                     f"tt_{s}_line", f"tt_{s}_over_odds", f"tt_{s}_under_odds")
    return {
        "ts": ts.strftime("%Y-%m-%dT%H:%MZ"), "hrs": num(r["hours_until_game"]),
        "ml": g("ml_home_bets_pct", "ml_home_money_pct", "ml_draw_bets_pct", "ml_draw_money_pct",
                "ml_away_bets_pct", "ml_away_money_pct", "ml_home_odds", "ml_draw_odds", "ml_away_odds"),
        "sp": g("sp_away_bets_pct", "sp_away_money_pct", "sp_home_bets_pct", "sp_home_money_pct")
              + [away_line] + g("sp_away_odds", "sp_home_odds"),
        "ou": g("ou_over_bets_pct", "ou_over_money_pct", "ou_under_bets_pct", "ou_under_money_pct",
                "ou_line", "ou_over_odds", "ou_under_odds"),
        "th": tt("home"), "ta": tt("away"),
    }


def open_of(first):
    hl = num(first["sp_home_line"])
    return {"ml3": [num(first["ml_home_odds"]), num(first["ml_draw_odds"]), num(first["ml_away_odds"])],
            "sp": -hl if hl is not None else None, "ou": num(first["ou_line"])}


def pre_game(rows):
    pre = [r for r in rows if num(r.get("hours_until_game")) is None or num(r["hours_until_game"]) >= 0]
    return pre or rows


def thin(rows, k):
    if len(rows) <= k:
        return rows
    idx = sorted({round(i * (len(rows) - 1) / (k - 1)) for i in range(k)})
    return [rows[i] for i in idx]


def eu_index():
    """歐洲賠率：每場（聯賽, 英國日期）留最新一筆"""
    idx = {}
    for path in recent_monthly_files("soccer", "eu_odds", months=3):
        for r in read_rows(path):
            key = (r["league"], r["date"], r["home_team"], r["away_team"])
            idx[key] = r
    by_day = {}
    for (lg, d, _, _), r in idx.items():
        by_day.setdefault((lg, d), []).append(r)
    return by_day


def match_eu(by_day, league, t, home, away):
    d = t.astimezone(LONDON).strftime("%d/%m/%Y")
    best, score = None, 0
    th, ta = toks(home), toks(away)
    for r in by_day.get((league, d), []):
        s = len(th & toks(r["home_team"])) + len(ta & toks(r["away_team"]))
        if th & toks(r["home_team"]) and ta & toks(r["away_team"]) and s > score:
            best, score = r, s
    if not best:
        return None
    f = lambda k: num(best.get(k))
    return {"avg": [f("avg_h"), f("avg_d"), f("avg_a")], "max": [f("max_h"), f("max_d"), f("max_a")],
            "b365": [f("b365_h"), f("b365_d"), f("b365_a")], "bfe": [f("bfe_h"), f("bfe_d"), f("bfe_a")],
            "ou": [f("avg_over25"), f("avg_under25")], "ou_max": [f("max_over25"), f("max_under25")],
            "ah": f("ah_line"), "ah_avg": [f("avg_ah_home"), f("avg_ah_away")],
            "ts": best["timestamp_utc"][:16] + "Z"}


def game_of(aid, rows, res, now, snaps_k=None):
    rows = sorted(rows, key=lambda r: r["timestamp_utc"])
    last = rows[-1]
    t = parse_time(last["game_time_utc"])
    home, away = last["home_team"], last["away_team"]
    pre = pre_game(rows)
    status = "final" if res and res.get("status") == "final" else ("upcoming" if t > now else "started")
    hc, ac = color(last.get("home_color"), last["home_team"]), color(last.get("away_color"), last["away_team"])
    return {
        "sport": "soccer", "league": last["league"], "league_zh": LEAGUE_ZH.get(last["league"], last["league"]),
        "id": f"an{aid}", "t": t.strftime("%Y-%m-%dT%H:%MZ"), "season": "",
        "away": away, "home": home, "away_zh": ZH.get(away, ""), "home_zh": ZH.get(home, ""),
        "away_ab": last.get("away_abbr") or away[:3].upper(), "home_ab": last.get("home_abbr") or home[:3].upper(),
        "away_c": [ac, ac] if ac else None, "home_c": [hc, hc] if hc else None,
        "status": status, "open": open_of(rows[0]),
        "snaps": [snap_of(r) for r in (thin(pre, snaps_k) if snaps_k else rows[-40:])],
        "result": None if status != "final" else {
            "away": num(res["away_score"]), "home": num(res["home_score"]), "winner": res["winner"],
            "margin": num(res["margin"]), "total": num(res["total_points"]),
            "halves": [res.get("home_periods", ""), res.get("away_periods", "")]},
        "ctx": None,
    }


def build_soccer(now, recent_days=14, closed_snaps=8):
    d = sport_dir("soccer")
    results = {r["an_id"]: r for r in read_rows(os.path.join(d, "results.csv"))}
    by_day = eu_index()
    games, closed = [], []
    recent = {}
    for path in recent_monthly_files("soccer", "odds_history"):
        for r in read_rows(path):
            if parse_time(r["game_time_utc"]) >= now - timedelta(days=recent_days):
                recent.setdefault(r["an_id"], []).append(r)
    for aid, rows in recent.items():
        g = game_of(aid, rows, results.get(aid), now)
        g["eu"] = match_eu(by_day, g["league"], parse_time(rows[-1]["game_time_utc"]), g["home"], g["away"])
        games.append(g)
    allrows = {}
    for path in all_monthly_files("soccer", "odds_history"):
        for r in read_rows(path):
            if r["an_id"] in results and results[r["an_id"]].get("status") == "final":
                allrows.setdefault(r["an_id"], []).append(r)
    for aid, rows in allrows.items():
        closed.append(game_of(aid, rows, results[aid], now, snaps_k=closed_snaps))
    return games, closed


def stats():
    snaps, ids, first = 0, set(), None
    for path in all_monthly_files("soccer", "odds_history"):
        for r in read_rows(path):
            snaps += 1
            ids.add(r["an_id"])
            first = r["timestamp_utc"] if first is None or r["timestamp_utc"] < first else first
    fin = sum(1 for r in read_rows(os.path.join(sport_dir("soccer"), "results.csv")) if r.get("status") == "final")
    eu_dir = os.path.join(sport_dir("soccer"), "eu")
    hist = 0
    if os.path.isdir(eu_dir):
        for f in os.listdir(eu_dir):
            with open(os.path.join(eu_dir, f), encoding="utf-8-sig", errors="ignore") as fh:
                hist += max(0, sum(1 for _ in fh) - 1)
    return {"snaps": snaps, "games": len(ids), "finals": fin, "history_games": hist}
