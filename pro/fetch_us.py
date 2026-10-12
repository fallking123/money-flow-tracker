"""
職業版・第 2 階段資料：在 GitHub Actions 上下載（這些網站從 Claude 的工作環境連不到），整理成精簡的每場表格存進專案
================================================================
資料來源（都允許非商業使用，網頁上會註明）：
- MLB：Retrosheet（www.retrosheet.org）逐打席紀錄＋比賽紀錄。
  "The information used here was obtained free of charge from and is copyrighted by Retrosheet.
   Interested parties may contact Retrosheet at www.retrosheet.org."
- NHL：MoneyPuck（moneypuck.com）每隊每場的射門品質（xG）。非商業使用，註明 MoneyPuck.com。
（NFL 用 nflverse，在 GitHub 上，工作環境直接下載，不在這裡。）

輸出（都很小，可以放進專案）：
  docs/data/pro/mlb/games.csv        每場：日期、主客隊、球場、比分、先發投手
  docs/data/pro/mlb/pitch_lines.csv  每場每位投手：面對打席、三振、四壞、觸身、全壘打、安打
  docs/data/pro/mlb/bat_lines.csv    每場每隊打擊：同上
  docs/data/pro/mlb/players.csv      球員：投球手、打擊手
  docs/data/pro/nhl/team_games.csv   每場每隊：全部／5 對 5 的 xG、射門、進球
用法：python -m pro.fetch_us mlb nhl
"""
import csv
import io
import os
import sys
import time
import zipfile

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data", "pro")
UA = {"User-Agent": "money-flow-tracker research (personal, non-commercial)"}
MLB_YEARS = range(2005, 2026)


def get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=120)
            if r.status_code == 200:
                return r.content
            print(f"  {url} → {r.status_code}")
            if r.status_code == 404:
                return None
        except Exception as e:
            print(f"  {url} 失敗：{e}")
        time.sleep(5 * (i + 1))
    return None


# ───────── MLB：Retrosheet ─────────
NON_PA = ("NP", "BK", "CS", "DI", "OA", "PB", "WP", "PO", "SB", "FLE")


def classify(ev):
    """一個打席的結果：K BB HBP HR 1B 2B 3B ROE OUT；不是打席回傳 None"""
    e = ev.split("/")[0].split(".")[0]
    if not e:
        return None
    if e.startswith(NON_PA):
        return None
    if e.startswith("K"):
        return "K"
    if e.startswith("HP"):
        return "HBP"
    if e.startswith(("IW", "W")) or e == "I" or e.startswith("I+"):
        return "BB"
    if e.startswith(("HR", "H")):
        return "HR"
    if e.startswith("DGR") or (e.startswith("D") and len(e) > 1 and e[1].isdigit()) or e == "D":
        return "2B"
    if e.startswith("S") and (len(e) == 1 or e[1].isdigit() or e[1] in "?"):
        return "1B"
    if e.startswith("T") and (len(e) == 1 or e[1].isdigit()):
        return "3B"
    if e.startswith("E") or e.startswith("C"):
        return "ROE"
    if e.startswith("FC") or e[0].isdigit():
        return "OUT"
    return None


KEYS = ("pa", "K", "BB", "HBP", "HR", "1B", "2B", "3B", "ROE", "OUT")


def parse_events(year):
    raw = get(f"https://www.retrosheet.org/events/{year}eve.zip")
    if not raw:
        return [], [], {}
    zf = zipfile.ZipFile(io.BytesIO(raw))
    plines, blines, players = [], [], {}
    for name in zf.namelist():
        if name.upper().endswith(".ROS"):
            for ln in zf.read(name).decode("latin-1").splitlines():
                f = ln.split(",")
                if len(f) >= 5:
                    players[f[0]] = {"id": f[0], "name": f"{f[2]} {f[1]}", "bats": f[3], "throws": f[4]}
            continue
        if not name.upper().endswith((".EVA", ".EVN")):
            continue
        gid, cur, starters, ptab, btab = None, {}, set(), {}, {}

        def flush():
            for (team, pid), c in ptab.items():
                plines.append({"game_id": gid, "team": team, "pitcher": pid, "starter": int(pid in starters), **{k: c[k] for k in KEYS}})
            for team, c in btab.items():
                blines.append({"game_id": gid, "team": team, **{k: c[k] for k in KEYS}})

        teams = {}
        for ln in zf.read(name).decode("latin-1").splitlines():
            f = ln.split(",")
            if f[0] == "id":
                if gid:
                    flush()
                gid, cur, starters, ptab, btab, teams = f[1], {}, set(), {}, {}, {}
            elif f[0] == "info" and f[1] in ("visteam", "hometeam"):
                teams[0 if f[1] == "visteam" else 1] = f[2]
            elif f[0] in ("start", "sub") and len(f) >= 6 and f[5].strip() == "1":
                side = int(f[3])
                cur[side] = f[1]
                if f[0] == "start":
                    starters.add(f[1])
            elif f[0] == "play" and len(f) >= 7:
                bat_side = int(f[2])
                kind = classify(f[6])
                if not kind:
                    continue
                pid = cur.get(1 - bat_side)
                fteam, bteam = teams.get(1 - bat_side), teams.get(bat_side)
                if pid:
                    c = ptab.setdefault((fteam, pid), dict.fromkeys(KEYS, 0))
                    c["pa"] += 1
                    c[kind] += 1
                b = btab.setdefault(bteam, dict.fromkeys(KEYS, 0))
                b["pa"] += 1
                b[kind] += 1
        if gid:
            flush()
    return plines, blines, players


def parse_gamelog(year):
    raw = get(f"https://www.retrosheet.org/gamelogs/gl{year}.zip")
    if not raw:
        return []
    zf = zipfile.ZipFile(io.BytesIO(raw))
    out = []
    for name in zf.namelist():
        for f in csv.reader(io.StringIO(zf.read(name).decode("latin-1"))):
            if len(f) < 105:
                continue
            d, num, vis, home = f[0], f[1], f[3], f[6]
            out.append({"game_id": f"{home}{d}{num}", "date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "vis": vis, "home": home,
                        "vis_score": f[9], "home_score": f[10], "outs": f[11], "daynight": f[12], "park": f[16],
                        "vis_sp": f[101], "home_sp": f[103]})
    return out


def write(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  寫入 {path}：{len(rows)} 列")


def mlb():
    games, pl, bl, players = [], [], [], {}
    for y in MLB_YEARS:
        g = parse_gamelog(y)
        p, b, pls = parse_events(y)
        games += g
        pl += p
        bl += b
        players.update(pls)
        print(f"MLB {y}：{len(g)} 場、{len(p)} 投手場次、{len(b)} 打擊場次")
    d = os.path.join(OUT, "mlb")
    write(os.path.join(d, "games.csv"), games, ["game_id", "date", "vis", "home", "vis_score", "home_score", "outs", "daynight", "park", "vis_sp", "home_sp"])
    write(os.path.join(d, "pitch_lines.csv"), pl, ["game_id", "team", "pitcher", "starter", *KEYS])
    write(os.path.join(d, "bat_lines.csv"), bl, ["game_id", "team", *KEYS])
    write(os.path.join(d, "players.csv"), list(players.values()), ["id", "name", "bats", "throws"])


# ───────── NHL：MoneyPuck ─────────
NHL_KEEP = ["season", "gameId", "playerTeam", "opposingTeam", "home_or_away", "gameDate", "situation",
            "xGoalsFor", "xGoalsAgainst", "goalsFor", "goalsAgainst", "shotsOnGoalFor", "shotsOnGoalAgainst",
            "shotAttemptsFor", "shotAttemptsAgainst", "highDangerxGoalsFor", "highDangerxGoalsAgainst",
            "scoreVenueAdjustedxGoalsFor", "scoreVenueAdjustedxGoalsAgainst", "iceTime", "penaltiesFor", "penaltiesAgainst"]


def nhl():
    raw = get("https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv")
    if not raw:
        print("NHL：MoneyPuck 下載失敗")
        return
    rd = csv.DictReader(io.StringIO(raw.decode("utf-8", "replace")))
    print("MoneyPuck 欄位：", ",".join(rd.fieldnames or [])[:3000])
    keep = [k for k in NHL_KEEP if k in (rd.fieldnames or [])]
    rows = [{k: r[k] for k in keep} for r in rd if r.get("situation") in ("all", "5on5", "5on4", "4on5") and r.get("playoffGame", "0") in ("0", "")]
    write(os.path.join(OUT, "nhl", "team_games.csv"), rows, keep)
    g = get("https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_goalies.csv")
    print("MoneyPuck 守門員逐場：", "有" if g else "沒有")
    if g:
        rd = csv.DictReader(io.StringIO(g.decode("utf-8", "replace")))
        print("守門員欄位：", ",".join(rd.fieldnames or [])[:2000])


if __name__ == "__main__":
    which = sys.argv[1:] or ["mlb", "nhl"]
    if "mlb" in which:
        mlb()
    if "nhl" in which:
        nhl()
