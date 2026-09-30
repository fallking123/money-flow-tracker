"""
儀表板資料整理
============================================
把各運動的 odds_history / results / context 整理成一個 dashboard/data.json，
給 Claude 儀表板網頁讀取。排程每天跑幾次：抓 repo → 跑這支 → 更新網頁資料。

收錄範圍：
- 即將開賽：已開始記錄、還沒開打的比賽（含每次快照，畫走勢用）
- 最近結果：過去 RECENT_DAYS 天、有資金流向紀錄的比賽（含比分，做小回測用）
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

from sports_common import (_norm, active_sports, all_monthly_files, parse_time, read_rows,
                            recent_monthly_files, sport_dir)
import record_tw_odds
import soccer_dashboard
import pinnacle_dashboard

RECENT_DAYS = 14
MAX_SNAPS = 40
MAX_CLOSED = 5000  # 「累積驗證」用的已完賽比賽上限（每種運動一季頂多幾百場，5000 場夠用很久）
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard", "data.json")

# 台灣常用中文隊名（依運動分開，因為不同聯盟有同名的隊，例如 Giants、Cardinals、Rangers）
ZH = {
    "mlb": {
        "Diamondbacks": "響尾蛇", "Braves": "勇士", "Orioles": "金鶯", "Red Sox": "紅襪", "Cubs": "小熊",
        "White Sox": "白襪", "Reds": "紅人", "Guardians": "守護者", "Rockies": "洛磯", "Tigers": "老虎",
        "Astros": "太空人", "Royals": "皇家", "Angels": "天使", "Dodgers": "道奇", "Marlins": "馬林魚",
        "Brewers": "釀酒人", "Twins": "雙城", "Mets": "大都會", "Yankees": "洋基", "Athletics": "運動家",
        "Phillies": "費城人", "Pirates": "海盜", "Padres": "教士", "Mariners": "水手", "Giants": "巨人",
        "Cardinals": "紅雀", "Rays": "光芒", "Rangers": "遊騎兵", "Blue Jays": "藍鳥", "Nationals": "國民",
    },
    "nba": {
        "Hawks": "老鷹", "Celtics": "塞爾提克", "Nets": "籃網", "Hornets": "黃蜂", "Bulls": "公牛",
        "Cavaliers": "騎士", "Mavericks": "獨行俠", "Nuggets": "金塊", "Pistons": "活塞", "Warriors": "勇士",
        "Rockets": "火箭", "Pacers": "溜馬", "Clippers": "快艇", "Lakers": "湖人", "Grizzlies": "灰熊",
        "Heat": "熱火", "Bucks": "公鹿", "Timberwolves": "灰狼", "Pelicans": "鵜鶘", "Knicks": "尼克",
        "Thunder": "雷霆", "Magic": "魔術", "76ers": "七六人", "Suns": "太陽", "Trail Blazers": "拓荒者",
        "Kings": "國王", "Spurs": "馬刺", "Raptors": "暴龍", "Jazz": "爵士", "Wizards": "巫師",
    },
    "nfl": {
        "Cardinals": "紅雀", "Falcons": "獵鷹", "Ravens": "烏鴉", "Bills": "比爾", "Panthers": "黑豹",
        "Bears": "熊", "Bengals": "孟加拉虎", "Browns": "布朗", "Cowboys": "牛仔", "Broncos": "野馬",
        "Lions": "雄獅", "Packers": "包裝工", "Texans": "德州人", "Colts": "小馬", "Jaguars": "美洲虎",
        "Chiefs": "酋長", "Raiders": "突擊者", "Chargers": "閃電", "Rams": "公羊", "Dolphins": "海豚",
        "Vikings": "維京人", "Patriots": "愛國者", "Saints": "聖徒", "Giants": "巨人", "Jets": "噴射機",
        "Eagles": "老鷹", "Steelers": "鋼人", "49ers": "49人", "Seahawks": "海鷹", "Buccaneers": "海盜",
        "Titans": "泰坦", "Commanders": "指揮官",
    },
    "nhl": {
        "Ducks": "鴨", "Bruins": "棕熊", "Sabres": "軍刀", "Flames": "火焰", "Hurricanes": "颶風",
        "Blackhawks": "黑鷹", "Avalanche": "雪崩", "Blue Jackets": "藍衣", "Stars": "星", "Red Wings": "紅翼",
        "Oilers": "油人", "Panthers": "美洲豹", "Kings": "國王", "Wild": "荒野", "Canadiens": "加拿大人",
        "Predators": "掠奪者", "Devils": "魔鬼", "Islanders": "島人", "Rangers": "遊騎兵", "Senators": "參議員",
        "Flyers": "飛人", "Penguins": "企鵝", "Sharks": "鯊魚", "Kraken": "海怪", "Blues": "藍調",
        "Lightning": "閃電", "Maple Leafs": "楓葉", "Mammoth": "猛瑪象", "Canucks": "加人",
        "Golden Knights": "金騎士", "Capitals": "首都", "Jets": "噴射機",
    },
}


# 球隊代表色（主色、副色），做隊伍徽章用（不用官方隊徽）
COLORS = {
    "mlb": {
        "Diamondbacks": ("#A71930", "#E3D4AD"), "Braves": ("#13274F", "#CE1141"), "Orioles": ("#DF4601", "#000000"),
        "Red Sox": ("#BD3039", "#0C2340"), "Cubs": ("#0E3386", "#CC3433"), "White Sox": ("#27251F", "#C4CED4"),
        "Reds": ("#C6011F", "#000000"), "Guardians": ("#00385D", "#E50022"), "Rockies": ("#333366", "#C4CED4"),
        "Tigers": ("#0C2340", "#FA4616"), "Astros": ("#002D62", "#EB6E1F"), "Royals": ("#004687", "#BD9B60"),
        "Angels": ("#BA0021", "#003263"), "Dodgers": ("#005A9C", "#EF3E42"), "Marlins": ("#00A3E0", "#EF3340"),
        "Brewers": ("#12284B", "#FFC52F"), "Twins": ("#002B5C", "#D31145"), "Mets": ("#002D72", "#FF5910"),
        "Yankees": ("#0C2340", "#C4CED3"), "Athletics": ("#003831", "#EFB21E"), "Phillies": ("#E81828", "#002D72"),
        "Pirates": ("#27251F", "#FDB827"), "Padres": ("#2F241D", "#FFC425"), "Mariners": ("#0C2C56", "#005C5C"),
        "Giants": ("#FD5A1E", "#27251F"), "Cardinals": ("#C41E3A", "#0C2340"), "Rays": ("#092C5C", "#8FBCE6"),
        "Rangers": ("#003278", "#C0111F"), "Blue Jays": ("#134A8E", "#1D2D5C"), "Nationals": ("#AB0003", "#14225A"),
    },
    "nfl": {
        "Cardinals": ("#97233F", "#FFB612"), "Falcons": ("#A71930", "#000000"), "Ravens": ("#241773", "#9E7C0C"),
        "Bills": ("#00338D", "#C60C30"), "Panthers": ("#0085CA", "#101820"), "Bears": ("#0B162A", "#C83803"),
        "Bengals": ("#FB4F14", "#000000"), "Browns": ("#311D00", "#FF3C00"), "Cowboys": ("#003594", "#869397"),
        "Broncos": ("#FB4F14", "#002244"), "Lions": ("#0076B6", "#B0B7BC"), "Packers": ("#203731", "#FFB612"),
        "Texans": ("#03202F", "#A71930"), "Colts": ("#002C5F", "#A2AAAD"), "Jaguars": ("#006778", "#D7A22A"),
        "Chiefs": ("#E31837", "#FFB81C"), "Raiders": ("#000000", "#A5ACAF"), "Chargers": ("#0080C6", "#FFC20E"),
        "Rams": ("#003594", "#FFA300"), "Dolphins": ("#008E97", "#FC4C02"), "Vikings": ("#4F2683", "#FFC62F"),
        "Patriots": ("#002244", "#C60C30"), "Saints": ("#101820", "#D3BC8D"), "Giants": ("#0B2265", "#A71930"),
        "Jets": ("#125740", "#FFFFFF"), "Eagles": ("#004C54", "#A5ACAF"), "Steelers": ("#101820", "#FFB612"),
        "49ers": ("#AA0000", "#B3995D"), "Seahawks": ("#002244", "#69BE28"), "Buccaneers": ("#D50A0A", "#34302B"),
        "Titans": ("#0C2340", "#4B92DB"), "Commanders": ("#5A1414", "#FFB612"),
    },
    "nba": {
        "Hawks": ("#E03A3E", "#C1D32F"), "Celtics": ("#007A33", "#BA9653"), "Nets": ("#000000", "#FFFFFF"),
        "Hornets": ("#1D1160", "#00788C"), "Bulls": ("#CE1141", "#000000"), "Cavaliers": ("#860038", "#FDBB30"),
        "Mavericks": ("#00538C", "#B8C4CA"), "Nuggets": ("#0E2240", "#FEC524"), "Pistons": ("#C8102E", "#1D42BA"),
        "Warriors": ("#1D428A", "#FFC72C"), "Rockets": ("#CE1141", "#000000"), "Pacers": ("#002D62", "#FDBB30"),
        "Clippers": ("#C8102E", "#1D428A"), "Lakers": ("#552583", "#FDB927"), "Grizzlies": ("#5D76A9", "#12173F"),
        "Heat": ("#98002E", "#F9A01B"), "Bucks": ("#00471B", "#EEE1C6"), "Timberwolves": ("#0C2340", "#78BE20"),
        "Pelicans": ("#0C2340", "#C8102E"), "Knicks": ("#006BB6", "#F58426"), "Thunder": ("#007AC1", "#EF3B24"),
        "Magic": ("#0077C0", "#C4CED4"), "76ers": ("#006BB6", "#ED174C"), "Suns": ("#1D1160", "#E56020"),
        "Trail Blazers": ("#E03A3E", "#000000"), "Kings": ("#5A2D81", "#63727A"), "Spurs": ("#C4CED4", "#000000"),
        "Raptors": ("#CE1141", "#000000"), "Jazz": ("#002B5C", "#F9A01B"), "Wizards": ("#002B5C", "#E31837"),
    },
    "nhl": {
        "Ducks": ("#F47A38", "#B9975B"), "Bruins": ("#000000", "#FFB81C"), "Sabres": ("#003087", "#FFB81C"),
        "Flames": ("#C8102E", "#F1BE48"), "Hurricanes": ("#CC0000", "#000000"), "Blackhawks": ("#CF0A2C", "#000000"),
        "Avalanche": ("#6F263D", "#236192"), "Blue Jackets": ("#002654", "#CE1126"), "Stars": ("#006847", "#8F8F8C"),
        "Red Wings": ("#CE1126", "#FFFFFF"), "Oilers": ("#041E42", "#FF4C00"), "Panthers": ("#041E42", "#C8102E"),
        "Kings": ("#111111", "#A2AAAD"), "Wild": ("#154734", "#A6192E"), "Canadiens": ("#AF1E2D", "#192168"),
        "Predators": ("#FFB81C", "#041E42"), "Devils": ("#CE1126", "#000000"), "Islanders": ("#00539B", "#F47D30"),
        "Rangers": ("#0038A8", "#CE1126"), "Senators": ("#DA1A32", "#000000"), "Flyers": ("#F74902", "#000000"),
        "Penguins": ("#000000", "#FCB514"), "Sharks": ("#006D75", "#EA7200"), "Kraken": ("#001628", "#99D9D9"),
        "Blues": ("#002F87", "#FCB514"), "Lightning": ("#002868", "#FFFFFF"), "Maple Leafs": ("#00205B", "#FFFFFF"),
        "Mammoth": ("#6CACE4", "#010101"), "Canucks": ("#00205B", "#00843D"), "Golden Knights": ("#333F42", "#B4975A"),
        "Capitals": ("#041E42", "#C8102E"), "Jets": ("#041E42", "#AC162C"),
    },
}


def team_color(sport, team):
    team = team or ""
    best = ""
    for en in COLORS.get(sport, {}):
        if team == en or team.endswith(" " + en):
            best = en if len(en) > len(best) else best
    return list(COLORS[sport][best]) if best else None


def zh_name(sport, team):
    team = team or ""
    best = ""
    for en in ZH.get(sport, {}):
        if team == en or team.endswith(" " + en):
            best = en if len(en) > len(best) else best
    return ZH[sport][best] if best else ""


def short_name(team):
    return (team or "").split()[-1] if team else ""


def num(v):
    if v in (None, ""):
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return int(f) if f.is_integer() else round(f, 4)


def snap_of(r):
    ts = parse_time(r["timestamp_utc"])
    return {
        "ts": ts.strftime("%Y-%m-%dT%H:%MZ"),
        "hrs": num(r["hours_until_game"]),
        # [客 bet%, 客 money%, 主 bet%, 主 money%, 客賠率, 主賠率]
        "ml": [num(r[k]) for k in ("ml_away_bets_pct", "ml_away_money_pct", "ml_home_bets_pct",
                                    "ml_home_money_pct", "ml_away_odds", "ml_home_odds")],
        # [客 bet%, 客 money%, 主 bet%, 主 money%, 客讓分, 客賠率, 主賠率]
        "sp": [num(r[k]) for k in ("sp_away_bets_pct", "sp_away_money_pct", "sp_home_bets_pct",
                                    "sp_home_money_pct", "sp_away_line", "sp_away_odds", "sp_home_odds")],
        # [大 bet%, 大 money%, 小 bet%, 小 money%, 總分線, 大賠率, 小賠率]
        "ou": [num(r[k]) for k in ("ou_over_bets_pct", "ou_over_money_pct", "ou_under_bets_pct",
                                    "ou_under_money_pct", "ou_line", "ou_over_odds", "ou_under_odds")],
    }


CLOSED_SNAPS = 8  # 已完賽比賽保留幾筆快照（算 CLV、盤口逆向用；太多會讓資料檔變太大）


def pre_game_rows(rows):
    """開賽前（含）的快照；都沒有的話就用全部。最後一筆 = 收盤，跟網頁 JS 的 closing() 一致"""
    pre = [r for r in rows if num(r.get("hours_until_game")) is None or num(r["hours_until_game"]) >= 0]
    return pre or rows


def closing_row(rows):
    return pre_game_rows(rows)[-1]


def thin(rows, k=CLOSED_SNAPS):
    """平均挑 k 筆，一定包含第一筆跟最後一筆"""
    if len(rows) <= k:
        return rows
    idx = sorted({round(i * (len(rows) - 1) / (k - 1)) for i in range(k)})
    return [rows[i] for i in idx]


def open_of(first):
    return {"ml": [num(first["ml_away_open_odds"]), num(first["ml_home_open_odds"])],
            "sp": num(first["sp_away_open_line"]), "ou": num(first["ou_open_line"])}


def build_closed():
    """
    「累積驗證」用的長期資料：把每種運動『全部歷史』（不只最近 14 天）已完賽的比賽，
    各自取一筆收盤快照 + 賽果，存成跟 games 一樣的格式（但 snaps 只留 1 筆，網頁邏輯不用改）。
    這份資料只會越存越多、不會因為調整訊號門檻而需要重新收集 —— 門檻只是事後在網頁上篩選這份資料。
    """
    closed = []
    for sport in active_sports():
        results = {r["sbd_id"]: r for r in read_rows(os.path.join(sport_dir(sport), "results.csv"))
                   if r.get("status") == "final"}
        if not results:
            continue
        by_id = {}
        for path in all_monthly_files(sport, "odds_history"):
            for r in read_rows(path):
                sid = r["sbd_id"]
                if sid not in results:
                    continue
                by_id.setdefault(sid, []).append(r)
        for sid, rows in by_id.items():
            rows.sort(key=lambda r: r["timestamp_utc"])
            pre = pre_game_rows(rows)
            last = pre[-1]
            res = results[sid]
            t = parse_time(last["game_time_utc"])
            away, home = last["away_team"], last["home_team"]
            closed.append({
                "sport": sport, "id": sid, "t": t.strftime("%Y-%m-%dT%H:%MZ"),
                "away": away, "home": home,
                "away_zh": zh_name(sport, away), "home_zh": zh_name(sport, home),
                "away_ab": last.get("away_abbr") or short_name(away),
                "home_ab": last.get("home_abbr") or short_name(home),
                "away_c": team_color(sport, away), "home_c": team_color(sport, home),
                "status": "final",
                "open": open_of(rows[0]),
                "snaps": [snap_of(r) for r in thin(pre)],
                "result": {"away": num(res["away_score"]), "home": num(res["home_score"]),
                           "winner": res["winner"], "margin": num(res["margin"]), "total": num(res["total_points"])},
            })
    closed.sort(key=lambda g: g["t"], reverse=True)
    return closed[:MAX_CLOSED]


# 特徵值（模型之後會用的輸入資料），給說明頁顯示
# common：每個運動都有；SPORT_FEATURES：各運動自己特別要看的（have＝已經在收，plan＝之後再加）
FEATURES = [
    ("資金流向", ["獨贏 人數%", "獨贏 金額%", "讓分 人數%", "讓分 金額%", "大小分 人數%", "大小分 金額%", "錢比人多（金額−人數）"]),
    ("賠率與盤口", ["獨贏賠率", "讓分盤口", "讓分賠率", "總分線", "大小分賠率", "開盤賠率／盤口", "去水公平機率", "參與莊家數"]),
    ("盤口變化", ["開盤→目前變動", "盤口逆向移動", "訊號出現時間", "距開賽時數"]),
    ("兩隊狀況", ["整季戰績", "主場／客場戰績", "休息天數", "背靠背", "7 天內出賽數", "上一場在客場（移動）", "傷兵名單"]),
    ("比賽背景", ["賽季階段", "系列賽", "主客場", "球場"]),
    ("台彩", ["台彩賠率", "台彩抽成", "台彩 vs 美國折扣"]),
]
SPORT_FEATURES = {
    "mlb": {"name": "MLB 棒球", "why": "先發投手影響最大，天氣和球場會影響大小分。",
            "have": ["先發投手", "投手本季成績", "氣溫", "風速", "降雨機率", "室內／屋頂球場", "每局比分（前五局、單隊大小）"],
            "plan": ["牛棚最近三天用量", "主審好球帶", "球場得分因子", "打線對左右投成績"]},
    "nba": {"name": "NBA 籃球", "why": "背靠背和球星缺陣影響最大，一個主力沒上盤口就會動好幾分。",
            "have": ["背靠背", "休息天數", "7 天內出賽數", "傷兵名單（缺陣／存疑）", "上一場在客場"],
            "plan": ["球隊節奏（每場回合數）", "攻守效率", "球星上場時間"]},
    "nfl": {"name": "NFL 美式足球", "why": "四分衛和天氣（尤其風速）影響最大，週四短週、bye 週後休息天數差很多。",
            "have": ["休息天數（短週／bye 後）", "傷兵名單", "氣溫", "風速", "降雨機率", "室內／屋頂球場"],
            "plan": ["先發四分衛確認", "分區對戰", "跨時區移動"]},
    "soccer": {"name": "足球（五大聯賽＋歐冠）", "why": "有和局，所以獨贏是三選一；歐洲莊家的賠率最準，拿來跟美國的資金流向對照。",
               "have": ["1X2 人數%／金額%（含和局）", "讓球、大小、單隊大小的人數%／金額%", "歐洲各家平均／最高賠率", "Betfair 交易所賠率",
                        "亞洲讓球盤", "上下半場比分", "2014 年起完整賽果＋收盤賠率（含英冠、西乙等次級聯賽）",
                        "Elo 強弱分數（看勝負）", "pi-rating（看淨勝球，主客場分開）", "賽前賠率 vs 臨場賠率",
                        "角球、黃紅牌、射門、射正、犯規（結果已收，賠率還沒有）"],
               "plan": ["先發陣容確認", "傷停名單", "歐冠／國內盃賽前後的輪換", "xG（預期進球）走勢"]},
    "nhl": {"name": "NHL 冰球", "why": "先發門將影響最大，背靠背時常換替補門將。",
            "have": ["先發門將", "門將本季成績（失分率、擋球率）", "背靠背", "休息天數", "傷兵名單"],
            "plan": ["門將最近幾場擋球率", "多打少／少打多效率"]},
}


def us_model_reports():
    """美國四大「模型一・實力」的成績（us_model.py 產生）"""
    out = {}
    for sp in ("nba", "nhl", "nfl", "mlb"):
        p = os.path.join(sport_dir(sp), "model", "report_ml.json")
        if os.path.exists(p):
            r = json.load(open(p, encoding="utf-8"))
            out[sp] = {k: r.get(k) for k in ("seasons", "test_seasons", "train_games", "test_games", "chosen", "accuracy",
                                             "hit_rate", "calibration", "betting", "open_vs_close", "generated_utc")}
    return out


def data_stats():
    """資料量統計：方法說明頁的進度用"""
    snaps, games, finals, first, per = 0, set(), 0, None, {}
    for sport in active_sports():
        n_s, g_s = 0, set()
        for path in all_monthly_files(sport, "odds_history"):
            for r in read_rows(path):
                n_s += 1
                g_s.add(r["sbd_id"])
                t = r["timestamp_utc"]
                first = t if first is None or t < first else first
        f_s = sum(1 for r in read_rows(os.path.join(sport_dir(sport), "results.csv")) if r.get("status") == "final")
        snaps += n_s
        games |= {sport + sid for sid in g_s}
        finals += f_s
        per[sport] = {"snaps": n_s, "games": len(g_s), "finals": f_s}
    ss = soccer_dashboard.stats()
    snaps += ss["snaps"]
    finals += ss["finals"]
    per["soccer"] = {"snaps": ss["snaps"], "games": ss["games"], "finals": ss["finals"], "history": ss["history_games"]}
    soccer_model_report = ss["model"]
    games |= {"soccer" + str(i) for i in range(ss["games"])}
    return {"snaps": snaps, "games": len(games), "finals": finals, "since": first[:10] if first else None,
            "per": per, "features": [{"group": g, "items": it} for g, it in FEATURES],
            "sport_features": {k: v for k, v in SPORT_FEATURES.items() if k in active_sports() or k == "soccer"},
            "soccer_model": soccer_model_report,
            "us_models": us_model_reports(),
            "n_features": sum(len(it) for _, it in FEATURES)}


def extra_index(sport, now):
    """其他玩法（scrape_extra.py）：每場留第一次和最新一次的賠率"""
    by = {}
    for path in recent_monthly_files(sport, "extra_odds"):
        for r in read_rows(path):
            t = parse_time(r["game_time_utc"])
            if t < now - timedelta(days=RECENT_DAYS):
                continue
            g = by.setdefault(r["an_id"], {"away": r["away_team"], "home": r["home_team"], "t": t, "snaps": {}})
            g["snaps"].setdefault(r["timestamp_utc"], []).append(
                [r["period"], r["market"], r["side"], r["team"], num(r["line"]), num(r["odds"]), num(r["bets_pct"]), num(r["money_pct"])])
    out = {}
    for g in by.values():
        ts = sorted(g["snaps"])
        key = (_norm(g["away"]), _norm(g["home"]))
        out.setdefault(key, []).append({"t": g["t"], "ts": ts[-1][:16] + "Z", "last": g["snaps"][ts[-1]], "first": g["snaps"][ts[0]]})
    return out


def match_extra(index, away, home, t):
    for x in index.get((_norm(away), _norm(home)), []):
        if abs((x["t"] - t).total_seconds()) < 3 * 3600:
            first = {tuple(r[:4]): r for r in x["first"]}
            return {"ts": x["ts"], "rows": [r + [(first.get(tuple(r[:4])) or [None] * 6)[5] if (first.get(tuple(r[:4])) or [None] * 5)[4] == r[4] else None]
                                          for r in x["last"]]}
    return None


def team_ctx(ctx, side, k):
    """背景資料裡各隊的狀況（舊資料沒有這些欄位就回傳空值）"""
    col = {"record": f"{side}_record", "split": "away_road_record" if side == "away" else "home_home_record",
           "rest": f"{side}_rest_days", "b2b": f"{side}_b2b", "g7": f"{side}_games_7d",
           "last_away": f"{side}_last_away", "out_n": f"{side}_out_n", "inj": f"{side}_injuries"}[k]
    v = ctx.get(col, "")
    if k in ("rest", "g7", "out_n"):
        return num(v)
    if k in ("b2b", "last_away"):
        return True if v == "True" else False if v == "False" else None
    return v or ""


def build(now):
    games = []
    for sport in active_sports():
        results = {r["sbd_id"]: r for r in read_rows(os.path.join(sport_dir(sport), "results.csv"))}
        ctx_by_event = {}
        for r in read_rows(os.path.join(sport_dir(sport), "context.csv")):
            if r.get("event_id"):
                ctx_by_event[r["event_id"]] = r  # 留最新一筆

        by_id = {}
        for path in recent_monthly_files(sport, "odds_history"):
            for r in read_rows(path):
                t = parse_time(r["game_time_utc"])
                if t < now - timedelta(days=RECENT_DAYS):
                    continue
                g = by_id.setdefault(r["sbd_id"], {"rows": []})
                g["rows"].append(r)

        extra = extra_index(sport, now)
        pins = pinnacle_dashboard.load(sport, now, RECENT_DAYS)
        for sid, g in by_id.items():
            rows = sorted(g["rows"], key=lambda r: r["timestamp_utc"])
            last = rows[-1]
            t = parse_time(last["game_time_utc"])
            eid = next((r["event_id"] for r in reversed(rows) if r.get("event_id")), "")
            season = next((r["season_type"] for r in reversed(rows) if r.get("season_type")), "")
            res = results.get(sid)
            status = "final" if res and res["status"] == "final" else (
                res["status"] if res else ("upcoming" if t > now else "started"))
            if status in ("canceled", "postponed") and t < now - timedelta(days=2):
                continue
            ctx = ctx_by_event.get(eid)
            first = rows[0]
            away, home = last["away_team"], last["home_team"]
            games.append({
                "sport": sport, "id": sid, "eid": eid, "t": t.strftime("%Y-%m-%dT%H:%MZ"),
                "season": season or (res or {}).get("season_type", ""),
                "series": (res or {}).get("series_note") or (ctx or {}).get("series_note", ""),
                "away": away, "home": home,
                "away_zh": zh_name(sport, away), "home_zh": zh_name(sport, home),
                "away_ab": last.get("away_abbr") or short_name(away),
                "home_ab": last.get("home_abbr") or short_name(home),
                "away_c": team_color(sport, away), "home_c": team_color(sport, home),
                "status": status,
                "open": open_of(first),
                "extra": match_extra(extra, away, home, t),
                "pin": pinnacle_dashboard.find(pins, home, away, t),
                "snaps": [snap_of(r) for r in rows[-MAX_SNAPS:]],
                "result": None if not res or res["status"] != "final" else {
                    "away": num(res["away_score"]), "home": num(res["home_score"]),
                    "winner": res["winner"], "margin": num(res["margin"]), "total": num(res["total_points"])},
                "ctx": None if not ctx else {
                    "venue": ctx["venue"], "indoor": ctx["indoor"] == "True",
                    "temp_f": num(ctx["temp_f"]), "wind_mph": num(ctx["wind_mph"]),
                    "precip": num(ctx["precip_prob_pct"]),
                    "away_p": ctx["away_probable_pitcher"], "home_p": ctx["home_probable_pitcher"],
                    "away_ps": ctx.get("away_pitcher_stat", ""), "home_ps": ctx.get("home_pitcher_stat", ""),
                    **{f"{side}_{k}": team_ctx(ctx, side, k) for side in ("away", "home")
                       for k in ("record", "split", "rest", "b2b", "g7", "last_away", "out_n", "inj")}},
            })
    sg, sclosed = soccer_dashboard.build_soccer(now, RECENT_DAYS, CLOSED_SNAPS)
    games += sg
    games.sort(key=lambda g: g["t"])
    tw = record_tw_odds.summary()
    for b in tw.get("best", []):
        if b["sport"] == "soccer":
            b["away"] = soccer_dashboard.ZH.get(b["away"]) or b["away"]
            b["home"] = soccer_dashboard.ZH.get(b["home"]) or b["home"]
            continue
        b["away"] = zh_name(b["sport"], b["away"]) or b["away"]
        b["home"] = zh_name(b["sport"], b["home"]) or b["home"]
    return {
        "stats": data_stats(),
        "generated_utc": now.strftime("%Y-%m-%dT%H:%MZ"),
        "sports": {**{k: v["name"] for k, v in active_sports().items()}, "soccer": "足球"},
        "games": games,
        "closed": build_closed() + sclosed,
        "tw": tw,
    }


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    data = build(now)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    n_up = sum(g["status"] in ("upcoming", "started") for g in data["games"])
    n_fin = sum(g["status"] == "final" for g in data["games"])
    print(f"儀表板資料：{len(data['games'])} 場（即將開賽 {n_up}、已完賽 {n_fin}），"
          f"累積驗證 {len(data['closed'])} 場，台彩對照 {data['tw']['n_total']} 筆，"
          f"{os.path.getsize(OUT) // 1024} KB")
    if "--check" in sys.argv:
        print(json.dumps(data["games"][0], ensure_ascii=False)[:1500])
