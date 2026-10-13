"""
職業版・NFL 第 2 版資料：nflverse（github.com/nflverse/nflverse-data，開放資料）
================================================================
輸出（docs/data/pro/nfl/）：
  snaps.csv.gz     每場每位球員：進攻／防守出場次數與比例（2013 起才有）
  injuries.csv.gz  每週官方傷兵報告（Out／Doubtful／Questionable，比賽前就公布）
  players.csv      球員：生日、選秀順位、位置；snap 資料的 pfr 編號 ↔ pbp 的 gsis 編號
  qb_games.csv.gz  每場每隊：先發四分衛（第一個傳球回合的人）、每位四分衛的回合數與 EPA
  rosters.csv.gz   每週名單狀態（ACT 正常、RES 傷兵名單、CUT 被釋出…；週中就知道）
用法：python3 -m pro.nfl_player_data   （只更新每週名單：--rosters）
"""
import csv
import gzip
import io
import os
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data", "pro", "nfl")
REL = "https://github.com/nflverse/nflverse-data/releases/download/"


def fetch(path, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(REL + path, timeout=300) as r:
                return r.read()
        except Exception as e:
            print(f"  {path} 失敗：{e}", flush=True)
    return None


def rows(raw, gz=False):
    if raw is None:
        return []
    f = io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(raw)) if gz else io.BytesIO(raw), encoding="utf-8")
    return list(csv.DictReader(f))


def write(name, data, fields):
    path = os.path.join(OUT, name)
    op = gzip.open if name.endswith(".gz") else open
    with op(path, "wt", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(data)
    print(f"  寫入 {name}：{len(data)} 列（{os.path.getsize(path) // 1024} KB）", flush=True)


def rosters():
    out = []
    for y in range(2013, 2026):
        s = rows(fetch(f"weekly_rosters/roster_weekly_{y}.csv"))
        out += [{"season": r["season"], "week": r["week"], "team": r["team"], "gsis": r["gsis_id"], "pfr": r["pfr_id"], "status": r["status"]}
                for r in s if r.get("week")]
        print(f"rosters {y}：{len(s)}", flush=True)
    write("rosters.csv.gz", out, ["season", "week", "team", "gsis", "pfr", "status"])


def main():
    os.makedirs(OUT, exist_ok=True)
    if "--rosters" in __import__("sys").argv:
        return rosters()
    snaps, inj, qbs = [], [], []
    for y in range(2013, 2026):
        s = rows(fetch(f"snap_counts/snap_counts_{y}.csv"))
        snaps += [{"game_id": r["game_id"], "team": r["team"], "pfr": r["pfr_player_id"], "pos": r["position"],
                   "off": r["offense_snaps"], "off_pct": r["offense_pct"], "def": r["defense_snaps"], "def_pct": r["defense_pct"]} for r in s]
        print(f"snap {y}：{len(s)}", flush=True)
    for y in range(2009, 2026):
        s = rows(fetch(f"injuries/injuries_{y}.csv"))
        inj += [{k: r.get(k, "") for k in ("season", "game_type", "team", "week", "gsis_id", "position", "report_status")} for r in s]
        print(f"injuries {y}：{len(s)}", flush=True)
    for y in range(2006, 2026):
        pbp = rows(fetch(f"pbp/play_by_play_{y}.csv.gz"), gz=True)
        first, agg = {}, defaultdict(lambda: [0, 0.0])
        for r in pbp:
            if r.get("qb_dropback") != "1" or not r.get("posteam"):
                continue
            qb = r.get("passer_player_id") or (r.get("rusher_player_id") if r.get("qb_scramble") == "1" else "")
            if not qb:
                continue
            k = (r["game_id"], r["posteam"])
            first.setdefault(k, qb)
            try:
                epa = float(r.get("epa") or "")
            except ValueError:
                continue
            a = agg[(r["game_id"], r["posteam"], qb)]
            a[0] += 1
            a[1] += epa
        for (g, t, q), (n, e) in agg.items():
            qbs.append({"game_id": g, "team": t, "qb": q, "dropbacks": n, "epa": round(e, 3), "starter": int(first.get((g, t)) == q)})
        print(f"pbp {y}：{len(agg)} 四分衛場次", flush=True)
    pl = rows(fetch("players/players.csv"))
    players = [{"gsis": r["gsis_id"], "pfr": r["pfr_id"], "birth": r["birth_date"], "pos": r["position"], "draft_year": r["draft_year"],
                "draft_round": r["draft_round"], "draft_pick": r["draft_pick"], "rookie": r["rookie_season"]} for r in pl]
    write("snaps.csv.gz", snaps, ["game_id", "team", "pfr", "pos", "off", "off_pct", "def", "def_pct"])
    write("injuries.csv.gz", inj, ["season", "game_type", "team", "week", "gsis_id", "position", "report_status"])
    write("qb_games.csv.gz", qbs, ["game_id", "team", "qb", "dropbacks", "epa", "starter"])
    write("players.csv", players, ["gsis", "pfr", "birth", "pos", "draft_year", "draft_round", "draft_pick", "rookie"])


if __name__ == "__main__":
    main()
