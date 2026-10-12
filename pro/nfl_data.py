"""
職業版・NFL 資料：nflverse 每一個 play（2006 起），整理成每場每隊的攻守效率
================================================================
來源：nflverse（github.com/nflverse/nflverse-data，開放資料）。原始檔每季 15–20 MB，只留下每場摘要。
EPA＝這一個 play 讓「預期得分」多了幾分（例如第三檔短碼推進成功 +1.2、被抄截 −4）；success＝EPA > 0。
輸出：
  docs/data/pro/nfl/games.csv       每場：季、週、日期、主客隊、比分、場地、收盤讓分／大小（nflverse 提供的）
  docs/data/pro/nfl/team_games.csv  每場每隊進攻：play 數、EPA、成功率（全部／傳球／跑球／比賽還沒定局時）、主要四分衛
用法：python3 -m pro.nfl_data
"""
import csv
import gzip
import io
import os
import sys
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data", "pro", "nfl")
URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{}.csv.gz"
YEARS = range(2006, 2026)


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def season(year):
    with urllib.request.urlopen(URL.format(year), timeout=300) as r:
        raw = r.read()
    rd = csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(raw)), encoding="utf-8"))
    games, tg = {}, defaultdict(lambda: defaultdict(float))
    qb = defaultdict(lambda: defaultdict(float))
    for r in rd:
        gid = r["game_id"]
        if gid not in games:
            games[gid] = {"game_id": gid, "season": r["season"], "week": r["week"], "season_type": r["season_type"], "date": r["game_date"],
                          "home": r["home_team"], "away": r["away_team"], "roof": r.get("roof", ""), "surface": r.get("surface", ""),
                          "temp": r.get("temp", ""), "wind": r.get("wind", ""), "spread_line": r.get("spread_line", ""),
                          "total_line": r.get("total_line", ""), "home_score": "", "away_score": "", "div_game": r.get("div_game", "")}
        g = games[gid]
        if r.get("home_score") not in (None, ""):
            g["home_score"], g["away_score"] = r["home_score"], r["away_score"]
        pos, epa = r.get("posteam"), f(r.get("epa"))
        if not pos or epa is None:
            continue
        is_pass, is_rush = r.get("pass") == "1", r.get("rush") == "1"
        if not (is_pass or is_rush):
            continue
        t = tg[(gid, pos)]
        wp = f(r.get("wp"))
        neutral = wp is not None and 0.1 <= wp <= 0.9 and not (f(r.get("game_seconds_remaining")) or 9999) < 120
        succ = 1.0 if epa > 0 else 0.0
        for pre, ok in (("", True), ("n_", neutral)):
            if not ok:
                continue
            t[pre + "plays"] += 1
            t[pre + "epa"] += epa
            t[pre + "succ"] += succ
            if is_pass:
                t[pre + "pass"] += 1
                t[pre + "pass_epa"] += epa
            else:
                t[pre + "rush"] += 1
                t[pre + "rush_epa"] += epa
        if is_pass and r.get("passer_player_id"):
            qb[(gid, pos)][r["passer_player_id"]] += 1
    rows = []
    for (gid, pos), t in tg.items():
        q = qb.get((gid, pos)) or {}
        main = max(q, key=q.get) if q else ""
        g = games[gid]
        rows.append({"game_id": gid, "team": pos, "opp": g["away"] if pos == g["home"] else g["home"], "qb": main,
                     **{k: round(v, 3) for k, v in t.items()}})
    return list(games.values()), rows


GF = ["game_id", "season", "week", "season_type", "date", "home", "away", "home_score", "away_score", "roof", "surface", "temp", "wind",
      "spread_line", "total_line", "div_game"]
TF = ["game_id", "team", "opp", "qb", "plays", "epa", "succ", "pass", "pass_epa", "rush", "rush_epa",
      "n_plays", "n_epa", "n_succ", "n_pass", "n_pass_epa", "n_rush", "n_rush_epa"]


def main():
    os.makedirs(OUT, exist_ok=True)
    G, T = [], []
    for y in YEARS:
        g, t = season(y)
        G += g
        T += t
        print(f"NFL {y}：{len(g)} 場、{len(t)} 隊次", flush=True)
    for name, rows, fields in (("games.csv", G, GF), ("team_games.csv", T, TF)):
        with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", restval="0")
            w.writeheader()
            w.writerows(rows)
        print(f"  寫入 {name}：{len(rows)} 列")


if __name__ == "__main__":
    main()
