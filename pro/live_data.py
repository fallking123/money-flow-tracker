"""
職業版・實戰用：每天更新「這一季」的 NHL 球員資料（GitHub Actions 上跑）
- sportsdataverse 這一季的每場球員、守門員、比賽資訊（parquet）→ 換掉舊檔裡這一季的部分
- MoneyPuck 這一季的逐球射門 → 每位球員／守門員每場的 xG，換掉這一季的部分
- MoneyPuck 每隊每場（第 1 版的整隊數據）
全部寫成「這一季」的小檔（*_cur.*），只在 GitHub Actions 上用、不 commit（不然專案每天變大好幾 MB）；讀資料的程式會自動合併。
用法：python -m pro.live_data nhl
"""
import csv
import gzip
import io
import os
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone

from pro import fetch_players as FP

D = os.path.join(FP.OUT, "nhl")


def season_years():
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 8 else now.year - 1
    return start, start + 1            # MoneyPuck 用開始那一年、sportsdataverse 用結束那一年


def nhl_box(end_year):
    import pandas as pd
    for tag, pre in (("nhl_skater_boxscores", "skater_box"), ("nhl_goalie_boxscores", "goalie_box"), ("nhl_game_info", "game_info")):
        raw = FP.get(FP.SDV.format(tag=tag, pre=pre, y=end_year))
        if not raw:
            print(f"{pre} {end_year}：沒有資料", flush=True)
            continue
        df = pd.read_parquet(io.BytesIO(raw))
        df = df[[c for c in df.columns if not any(k in c.lower() for k in FP.DROP)]]
        for c in df.columns:
            if df[c].dtype == object:
                nn = df[c].dropna()
                if len(nn) and not isinstance(nn.iloc[0], (str, int, float, bool)):
                    df[c] = df[c].astype(str)
        df["sdv_season"] = end_year
        df.to_csv(os.path.join(D, pre + "_cur.csv.gz"), index=False, compression={"method": "gzip", "compresslevel": 6})
        print(f"{pre}：這一季 {len(df)} 列", flush=True)


def nhl_shots(start_year):
    raw = FP.get(f"https://peter-tanner.com/moneypuck/downloads/shots_{start_year}.zip")
    if not raw:
        print("MoneyPuck 這一季的射門資料還沒有", flush=True)
        return
    sp, sg = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
    zf = zipfile.ZipFile(io.BytesIO(raw))
    name = [n for n in zf.namelist() if n.endswith(".csv")][0]
    for r in csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="utf-8", errors="replace")):
        if r.get("isPlayoffGame") == "1":
            continue
        try:
            gid = int(float(r["season"])) * 1000000 + int(float(r["game_id"]))
            xg, goal, on = float(r.get("xGoal") or 0), int(float(r.get("goal") or 0)), int(float(r.get("shotWasOnGoal") or 0))
        except (ValueError, KeyError):
            continue
        ev = r.get("homeSkatersOnIce") == "5" and r.get("awaySkatersOnIce") == "5"
        sh = r.get("shooterPlayerId")
        if sh and sh not in ("0", "0.0"):
            k = sp[(gid, r.get("teamCode"), str(int(float(sh))))]
            k["att"] += 1; k["xg"] += xg; k["g"] += goal; k["sog"] += on
            if ev:
                k["xg5"] += xg; k["att5"] += 1
        gl = r.get("goalieIdForShot")
        if gl and gl not in ("0", "0.0") and r.get("shotOnEmptyNet") != "1":
            opp = r.get("awayTeamCode") if r.get("isHomeTeam") == "1" else r.get("homeTeamCode")
            k = sg[(gid, opp, str(int(float(gl))))]
            k["att"] += 1; k["xg"] += xg; k["ga"] += goal; k["sog"] += on
            if ev:
                k["xg5"] += xg; k["ga5"] += goal
    for fn, data, key, fields in (("shot_players.csv.gz", sp, "player", ["att", "xg", "g", "sog", "xg5", "att5"]),
                                  ("shot_goalies.csv.gz", sg, "goalie", ["att", "xg", "ga", "sog", "xg5", "ga5"])):
        new = [{"game_id": g, "team": t, key: p, **{k: round(c.get(k, 0.0), 4) for k in fields}} for (g, t, p), c in data.items()]
        FP.write_gz(os.path.join(D, fn.replace(".csv.gz", "_cur.csv.gz")), new, ["game_id", "team", key, *fields])


def main():
    start, end = season_years()
    if "nhl" in sys.argv:
        nhl_box(end)
        nhl_shots(start)
        from pro import fetch_us
        raw = FP.get("https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv")
        if raw:
            rd = csv.DictReader(io.StringIO(raw.decode("utf-8", "replace")))
            keep = [k for k in fetch_us.NHL_KEEP if k in (rd.fieldnames or [])]
            rows = [{k: r[k] for k in keep} for r in rd if r.get("situation") in ("all", "5on5", "5on4", "4on5")
                    and r.get("playoffGame", "0") in ("0", "") and str(r.get("season")) == str(start)]
            with open(os.path.join(D, "team_games_cur.csv"), "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=keep)
                w.writeheader()
                w.writerows(rows)
            print(f"team_games 這一季 {len(rows)} 列", flush=True)


if __name__ == "__main__":
    main()
