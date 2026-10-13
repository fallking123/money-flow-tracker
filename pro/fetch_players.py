"""
職業版・各運動第 2 版（用球員組出球隊）的資料：在 GitHub Actions 上跑（工作環境連不到這些網站、也讀不了 parquet）
================================================================
MLB（Retrosheet 逐打席）：
  docs/data/pro/mlb/bat_players.csv.gz    每場每位打者：棒次、是否先發、各種結果；_L＝面對左投
  docs/data/pro/mlb/pitch_players.csv.gz  每場每位投手：是否先發、投球數、各種結果；_L＝面對左打
  docs/data/pro/mlb/birth.csv             生日（Chadwick Baseball Bureau register，ODC-BY）
  "The information used here was obtained free of charge from and is copyrighted by Retrosheet.
   Interested parties may contact Retrosheet at www.retrosheet.org."
NHL：
  docs/data/pro/nhl/skater_box.csv.gz、goalie_box.csv.gz、game_info.csv.gz
      每場每位球員的上場時間、得分、射門…（fastRhockey／sportsdataverse，MIT）
  docs/data/pro/nhl/shot_players.csv.gz   每場每位球員的射門品質 xG（MoneyPuck.com 逐球射門資料，非商業使用）
  docs/data/pro/nhl/shot_goalies.csv.gz   每場每位守門員面對的 xG、失分（同上）
MLB 每場資訊（mlbinfo）：
  docs/data/pro/mlb/game_info.csv      每場：溫度、風向風速、天空、場地、主審、開賽時間、日夜、兩隊先發捕手
  docs/data/pro/mlb/framing.csv.gz     每場每組投手＋捕手：打者沒揮棒的球裡，被判好球／壞球幾顆（捕手偷好球）
用法：python -m pro.fetch_players mlb nhl mlbinfo
"""
import csv
import gzip
import io
import os
import sys
import time
import zipfile
from collections import defaultdict

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data", "pro")
UA = {"User-Agent": "money-flow-tracker research (personal, non-commercial)"}
KEYS = ("pa", "K", "BB", "HBP", "HR", "1B", "2B", "3B", "ROE", "OUT")
PITCH_CHARS = set("BCFHIKLMOPQRSTUVXY")


def get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=300)
            if r.status_code == 200:
                return r.content
            print(f"  {url} → {r.status_code}", flush=True)
            if r.status_code == 404:
                return None
        except Exception as e:
            print(f"  {url} 失敗：{e}", flush=True)
        time.sleep(5 * (i + 1))
    return None


def write_gz(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8", compresslevel=9) as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", restval="0")
        w.writeheader()
        w.writerows(rows)
    print(f"  寫入 {path}：{len(rows)} 列（{os.path.getsize(path) // 1024} KB）", flush=True)


# ───────── MLB ─────────
def mlb_year(year):
    from pro.fetch_us import classify
    raw = get(f"https://www.retrosheet.org/events/{year}eve.zip")
    if not raw:
        return [], []
    zf = zipfile.ZipFile(io.BytesIO(raw))
    hands = {}
    for name in zf.namelist():
        if name.upper().endswith(".ROS"):
            for ln in zf.read(name).decode("latin-1").splitlines():
                f = ln.split(",")
                if len(f) >= 5:
                    hands[f[0]] = (f[3].strip(), f[4].strip())
    brows, prows = [], []
    for name in zf.namelist():
        if not name.upper().endswith((".EVA", ".EVN")):
            continue
        gid = None
        st = {}

        def flush():
            if not gid:
                return
            for (team, pid), c in st["bat"].items():
                brows.append({"game_id": gid, "team": team, "batter": pid, "slot": st["slot"].get(pid, 0),
                              "starter": int(pid in st["bstart"]), **c})
            for (team, pid), c in st["pit"].items():
                prows.append({"game_id": gid, "team": team, "pitcher": pid, "starter": int(pid in st["pstart"]), **c})

        for ln in zf.read(name).decode("latin-1").splitlines():
            f = ln.split(",")
            if f[0] == "id":
                flush()
                gid = f[1]
                st = {"teams": {}, "cur": {}, "slot": {}, "bstart": set(), "pstart": set(),
                      "bat": defaultdict(lambda: defaultdict(int)), "pit": defaultdict(lambda: defaultdict(int)),
                      "badj": {}, "padj": {}}
            elif gid is None:
                continue
            elif f[0] == "info" and f[1] in ("visteam", "hometeam"):
                st["teams"][0 if f[1] == "visteam" else 1] = f[2]
            elif f[0] in ("start", "sub") and len(f) >= 6:
                pid, side = f[1], int(f[3])
                try:
                    slot = int(f[4])
                except ValueError:
                    slot = 0
                if f[5].strip() == "1":
                    st["cur"][side] = pid
                    if f[0] == "start":
                        st["pstart"].add(pid)
                if 1 <= slot <= 9 and pid not in st["slot"]:
                    st["slot"][pid] = slot
                    if f[0] == "start":
                        st["bstart"].add(pid)
            elif f[0] == "badj" and len(f) >= 3:
                st["badj"][f[1]] = f[2].strip()
            elif f[0] == "padj" and len(f) >= 3:
                st["padj"][f[1]] = f[2].strip()
            elif f[0] == "play" and len(f) >= 7:
                kind = classify(f[6])
                if not kind:
                    continue
                bat_side, batter = int(f[2]), f[3]
                pit = st["cur"].get(1 - bat_side)
                ph = st["padj"].get(pit) or (hands.get(pit, ("", ""))[1])
                bh = st["badj"].pop(batter, None) or hands.get(batter, ("", ""))[0]
                if bh == "B":                  # 左右開弓：站在投手的另一邊
                    bh = "R" if ph == "L" else "L"
                bteam, fteam = st["teams"].get(bat_side), st["teams"].get(1 - bat_side)
                b = st["bat"][(bteam, batter)]
                b["pa"] += 1
                b[kind] += 1
                if ph == "L":
                    b["pa_L"] += 1
                    b[kind + "_L"] += 1
                if pit:
                    p = st["pit"][(fteam, pit)]
                    p["pa"] += 1
                    p[kind] += 1
                    p["pitches"] += sum(1 for ch in f[5] if ch in PITCH_CHARS)
                    if bh == "L":
                        p["pa_L"] += 1
                        p[kind + "_L"] += 1
        flush()
    return brows, prows


def mlb_birth():
    out = []
    for h in "0123456789abcdef":
        raw = get(f"https://raw.githubusercontent.com/chadwickbureau/register/master/data/people-{h}.csv")
        if not raw:
            continue
        for r in csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))):
            if r.get("key_retro") and r.get("birth_year"):
                out.append({"id": r["key_retro"], "birth": f"{r['birth_year']}-{(r.get('birth_month') or '7').zfill(2)}-{(r.get('birth_day') or '1').zfill(2)}"})
    return out


def mlb():
    B, P = [], []
    for y in range(2005, 2026):
        b, p = mlb_year(y)
        B += b
        P += p
        print(f"MLB {y}：打者 {len(b)}、投手 {len(p)}", flush=True)
    d = os.path.join(OUT, "mlb")
    split = [k + "_L" for k in KEYS if k != "OUT"]
    write_gz(os.path.join(d, "bat_players.csv.gz"), B, ["game_id", "team", "batter", "slot", "starter", *KEYS, *split])
    write_gz(os.path.join(d, "pitch_players.csv.gz"), P, ["game_id", "team", "pitcher", "starter", "pitches", *KEYS, *split])
    bd = mlb_birth()
    with open(os.path.join(d, "birth.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "birth"])
        w.writeheader()
        w.writerows(bd)
    print(f"  生日 {len(bd)} 位")


# ───────── NHL ─────────
SDV = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/{tag}/{pre}_{y}.parquet"
DROP = ("url", "headshot", "logo", "image", "photo")


def nhl_box():
    import pandas as pd
    d = os.path.join(OUT, "nhl")
    cols_txt = []
    for tag, pre, out in (("nhl_skater_boxscores", "skater_box", "skater_box"), ("nhl_goalie_boxscores", "goalie_box", "goalie_box"),
                          ("nhl_game_info", "game_info", "game_info")):
        frames = []
        for y in range(2011, 2028):
            raw = get(SDV.format(tag=tag, pre=pre, y=y))
            if not raw:
                continue
            df = pd.read_parquet(io.BytesIO(raw))
            df = df[[c for c in df.columns if not any(k in c.lower() for k in DROP)]]
            for c in df.columns:                 # 巢狀欄位（list／dict／陣列）轉成文字
                if df[c].dtype == object:
                    nn = df[c].dropna()
                    if len(nn) and not isinstance(nn.iloc[0], (str, int, float, bool)):
                        df[c] = df[c].astype(str)
            df["sdv_season"] = y
            frames.append(df)
            print(f"NHL {pre} {y}：{len(df)} 列", flush=True)
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        cols_txt.append(f"{pre}：{list(df.columns)}\n  例：{df.iloc[-1].to_dict()}\n")
        path = os.path.join(d, out + ".csv.gz")
        df.to_csv(path, index=False, compression={"method": "gzip", "compresslevel": 9})
        print(f"  寫入 {path}：{len(df)} 列（{os.path.getsize(path) // 1024} KB）", flush=True)
    with open(os.path.join(d, "_columns.txt"), "w", encoding="utf-8") as f:
        f.writelines(cols_txt)


def nhl_shots():
    d = os.path.join(OUT, "nhl")
    sp, sg = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
    shown = False
    for y in range(2010, 2026):
        raw = get(f"https://peter-tanner.com/moneypuck/downloads/shots_{y}.zip")
        if not raw:
            continue
        zf = zipfile.ZipFile(io.BytesIO(raw))
        name = [n for n in zf.namelist() if n.endswith(".csv")][0]
        rd = csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="utf-8", errors="replace"))
        if not shown:
            print("MoneyPuck 射門欄位：", ",".join(rd.fieldnames or [])[:4000], flush=True)
            shown = True
        n = 0
        for r in rd:
            if r.get("isPlayoffGame") == "1":
                continue
            try:
                gid = int(float(r["season"])) * 1000000 + int(float(r["game_id"]))
                xg = float(r.get("xGoal") or 0)
                goal = int(float(r.get("goal") or 0))
                on = int(float(r.get("shotWasOnGoal") or 0))
            except (ValueError, KeyError):
                continue
            hs, as_ = r.get("homeSkatersOnIce"), r.get("awaySkatersOnIce")
            ev = "5" if hs == "5" and as_ == "5" else "o"
            team = r.get("teamCode")
            shooter = r.get("shooterPlayerId")
            if shooter and shooter not in ("0", "0.0"):
                k = sp[(gid, team, str(int(float(shooter))))]
                k["att"] += 1
                k["xg"] += xg
                k["g"] += goal
                k["sog"] += on
                if ev == "5":
                    k["xg5"] += xg
                    k["att5"] += 1
            gl = r.get("goalieIdForShot")
            if gl and gl not in ("0", "0.0") and r.get("shotOnEmptyNet") != "1":
                opp = r.get("awayTeamCode") if r.get("isHomeTeam") == "1" else r.get("homeTeamCode")
                k = sg[(gid, opp, str(int(float(gl))))]
                k["att"] += 1
                k["xg"] += xg
                k["ga"] += goal
                k["sog"] += on
                if ev == "5":
                    k["xg5"] += xg
                    k["ga5"] += goal
            n += 1
        print(f"NHL 射門 {y}：{n} 次", flush=True)
    rp = [{"game_id": g, "team": t, "player": p, **{k: round(v, 4) for k, v in c.items()}} for (g, t, p), c in sp.items()]
    rg = [{"game_id": g, "team": t, "goalie": p, **{k: round(v, 4) for k, v in c.items()}} for (g, t, p), c in sg.items()]
    write_gz(os.path.join(d, "shot_players.csv.gz"), rp, ["game_id", "team", "player", "att", "xg", "g", "sog", "xg5", "att5"])
    write_gz(os.path.join(d, "shot_goalies.csv.gz"), rg, ["game_id", "team", "goalie", "att", "xg", "ga", "sog", "xg5", "ga5"])


INFO_KEYS = ("temp", "winddir", "windspeed", "sky", "precip", "fieldcond", "umphome", "starttime", "daynight", "site")


def mlb_info_year(year):
    raw = get(f"https://www.retrosheet.org/events/{year}eve.zip")
    if not raw:
        return [], []
    zf = zipfile.ZipFile(io.BytesIO(raw))
    from pro.fetch_us import classify
    infos, fr = [], []
    for name in zf.namelist():
        if not name.upper().endswith((".EVA", ".EVN")):
            continue
        gid, info, pit, cat, teams, cnt = None, {}, {}, {}, {}, None

        def flush():
            if gid:
                infos.append({"game_id": gid, **info})
                for (team, p, c), v in cnt.items():
                    fr.append({"game_id": gid, "team": team, "pitcher": p, "catcher": c, "cs": v[0], "b": v[1]})

        for ln in zf.read(name).decode("latin-1").splitlines():
            f = ln.split(",")
            if f[0] == "id":
                flush()
                gid, info, pit, cat, teams, cnt = f[1], {}, {}, {}, {}, defaultdict(lambda: [0, 0])
            elif gid is None:
                continue
            elif f[0] == "info" and len(f) >= 3:
                if f[1] in ("visteam", "hometeam"):
                    teams[0 if f[1] == "visteam" else 1] = f[2]
                elif f[1] in INFO_KEYS:
                    info[f[1]] = f[2].strip()
            elif f[0] in ("start", "sub") and len(f) >= 6:
                side, pos = int(f[3]), f[5].strip()
                if pos == "1":
                    pit[side] = f[1]
                elif pos == "2":
                    if f[0] == "start":
                        info[("home" if side == 1 else "vis") + "_catcher"] = f[1]
                    cat[side] = f[1]
            elif f[0] == "play" and len(f) >= 7 and classify(f[6]):
                fs = 1 - int(f[2])
                k = cnt[(teams.get(fs), pit.get(fs), cat.get(fs))]
                for ch in f[5]:
                    if ch == "C":
                        k[0] += 1
                    elif ch == "B":
                        k[1] += 1
        flush()
    return infos, fr


def mlb_info():
    I, F = [], []
    for y in range(2005, 2026):
        i, f = mlb_info_year(y)
        I += i
        F += f
        print(f"MLB info {y}：{len(i)} 場、{len(f)} 組投捕", flush=True)
    d = os.path.join(OUT, "mlb")
    with open(os.path.join(d, "game_info.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["game_id", *INFO_KEYS, "home_catcher", "vis_catcher"], extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(I)
    write_gz(os.path.join(d, "framing.csv.gz"), F, ["game_id", "team", "pitcher", "catcher", "cs", "b"])


if __name__ == "__main__":
    which = sys.argv[1:] or ["mlb", "nhl"]
    if "nhl" in which:
        nhl_box()
        nhl_shots()
    if "mlb" in which:
        mlb()
    if "mlbinfo" in which:
        mlb_info()
