"""
職業版・NBA 資料：hoopR（sportsdataverse，CC BY 4.0）的每場球隊、球員數據，整理成精簡表格
================================================================
在 GitHub Actions 上跑（需要 pandas＋pyarrow 讀 parquet）。資料來源要註明：hoopR / sportsdataverse（CC BY 4.0）。
輸出：
  docs/data/pro/nba/team_games.csv    每場每隊：日期、季別、主客、得分、投籃、三分、罰球、籃板、失誤（算回合數、四大因素用）
  docs/data/pro/nba/player_games.csv  每場每位球員：上場分鐘、正負值、先發、得分（算「誰有上場、誰缺陣」用）
用法：python -m pro.nba_data /path/to/hoopr-nba-data
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data", "pro", "nba")
YEARS = range(2005, 2027)       # hoopR 的 season＝結束那一年（2025＝2024–25 季）

TEAM_COLS = {"game_id": "game_id", "season": "season", "season_type": "season_type", "game_date": "date", "team_id": "team_id",
             "team_abbreviation": "team", "team_home_away": "home_away", "team_score": "pts", "opponent_team_abbreviation": "opp",
             "opponent_team_score": "opp_pts", "field_goals_made": "fgm", "field_goals_attempted": "fga",
             "three_point_field_goals_made": "fg3m", "three_point_field_goals_attempted": "fg3a", "free_throws_made": "ftm",
             "free_throws_attempted": "fta", "offensive_rebounds": "orb", "defensive_rebounds": "drb", "turnovers": "tov",
             "team_turnovers": "team_tov", "total_turnovers": "total_tov"}
PLAYER_COLS = {"game_id": "game_id", "athlete_id": "player", "team_abbreviation": "team", "minutes": "min", "plus_minus": "pm",
               "starter": "starter", "points": "pts", "did_not_play": "dnp"}


def pick(df, cols):
    have = {k: v for k, v in cols.items() if k in df.columns}
    out = df[list(have)].rename(columns=have)
    return out


def main(src):
    os.makedirs(OUT, exist_ok=True)
    teams, players = [], []
    for y in YEARS:
        tp = os.path.join(src, "nba", "team_box", "parquet", f"team_box_{y}.parquet")
        pp = os.path.join(src, "nba", "player_box", "parquet", f"player_box_{y}.parquet")
        if os.path.exists(tp):
            t = pd.read_parquet(tp)
            if y == YEARS[0] or y == 2025:
                print(f"team_box 欄位（{y}）：", list(t.columns))
            teams.append(pick(t, TEAM_COLS))
        if os.path.exists(pp):
            p = pd.read_parquet(pp)
            if y == 2025:
                print("player_box 欄位：", list(p.columns))
            p = pick(p, PLAYER_COLS)
            if "dnp" in p.columns:
                p = p[p["dnp"] != True]       # noqa: E712
            p = p[pd.to_numeric(p.get("min"), errors="coerce").fillna(0) > 0]
            players.append(p.drop(columns=[c for c in ("dnp",) if c in p.columns]))
        print(f"NBA {y}：球隊 {len(teams[-1]) if teams else 0}、球員 {len(players[-1]) if players else 0}", flush=True)
    T = pd.concat(teams, ignore_index=True)
    P = pd.concat(players, ignore_index=True)
    T.to_csv(os.path.join(OUT, "team_games.csv"), index=False)
    P.to_csv(os.path.join(OUT, "player_games.csv"), index=False)
    print(f"寫入 team_games.csv {len(T)} 列、player_games.csv {len(P)} 列")


if __name__ == "__main__":
    main(sys.argv[1])
