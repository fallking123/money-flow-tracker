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

from sports_common import (active_sports, parse_time, read_rows, recent_monthly_files, sport_dir)

RECENT_DAYS = 14
MAX_SNAPS = 40
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
                "status": status,
                "open": {"ml": [num(first["ml_away_open_odds"]), num(first["ml_home_open_odds"])],
                         "sp": num(first["sp_away_open_line"]), "ou": num(first["ou_open_line"])},
                "snaps": [snap_of(r) for r in rows[-MAX_SNAPS:]],
                "result": None if not res or res["status"] != "final" else {
                    "away": num(res["away_score"]), "home": num(res["home_score"]),
                    "winner": res["winner"], "margin": num(res["margin"]), "total": num(res["total_points"])},
                "ctx": None if not ctx else {
                    "venue": ctx["venue"], "indoor": ctx["indoor"] == "True",
                    "temp_f": num(ctx["temp_f"]), "wind_mph": num(ctx["wind_mph"]),
                    "precip": num(ctx["precip_prob_pct"]),
                    "away_p": ctx["away_probable_pitcher"], "home_p": ctx["home_probable_pitcher"]},
            })
    games.sort(key=lambda g: g["t"])
    return {
        "generated_utc": now.strftime("%Y-%m-%dT%H:%MZ"),
        "sports": {k: v["name"] for k, v in active_sports().items()},
        "games": games,
    }


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    data = build(now)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    n_up = sum(g["status"] in ("upcoming", "started") for g in data["games"])
    n_fin = sum(g["status"] == "final" for g in data["games"])
    print(f"儀表板資料：{len(data['games'])} 場（即將開賽 {n_up}、已完賽 {n_fin}），{os.path.getsize(OUT) // 1024} KB")
    if "--check" in sys.argv:
        print(json.dumps(data["games"][0], ensure_ascii=False)[:1500])
