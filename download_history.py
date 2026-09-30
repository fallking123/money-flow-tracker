"""
下載歷史比賽＋賠率（給「模型一・實力」訓練用）
=================================================
來源：
- sportsbookreviewsonline（SBRO）歷史檔案：NBA／NHL 2007-08 ～ 2022-23、NFL 2007-08 ～ 2021-22
  每場有開盤／收盤獨贏、讓分、大小分，以及各節比分
- ESPN：2022-23 季起（SBRO 沒有的季）用 ESPN 賽程＋ESPN 記錄的開盤／收盤賠率補上
  2022-23 兩邊都有，拿來核對兩個來源的隊名與賠率是否一致

輸出（每季一個檔）：docs/data/<運動>/history/<來源>_<季>.csv，欄位統一：
  season, date, away, home, away_score, home_score, neutral, periods_away, periods_home,
  ml_open_away, ml_open_home, ml_close_away, ml_close_home（美式賠率）,
  spread_close_home（主隊讓分，負＝主隊讓）, total_close, source, espn_id, away_abbr, home_abbr, season_type

用法：python download_history.py nba,nhl
已經下載過的季會略過（ESPN 最近一季每次重抓）
"""
import csv
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import requests

from sports_common import sport_dir

SBRO = "https://www.sportsbookreviewsonline.com/scoresoddsarchives/{sport}-odds-{season}"
SBRO_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
SBRO_SEASONS = {
    "nba": [f"{y}-{(y + 1) % 100:02d}" for y in range(2007, 2023)],
    "nhl": [f"{y}-{(y + 1) % 100:02d}" for y in range(2007, 2023) if y != 2020] + ["2021"],
    "nfl": [f"{y}-{(y + 1) % 100:02d}" for y in range(2007, 2022)],
}
ESPN_PATH = {"nba": ("basketball", "nba"), "nhl": ("hockey", "nhl"), "nfl": ("football", "nfl"), "mlb": ("baseball", "mlb")}
# ESPN 補的季：(季名, 起日, 迄日)
MLB_SBRO = "https://www.sportsbookreviewsonline.com/wp-content/uploads/sportsbookreviewsonline_com_737/mlb-odds-{year}.xlsx"
MLB_SBRO_YEARS = list(range(2010, 2022))
NFLVERSE = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
ESPN_SEASONS = {
    "nba": [("2022-23", "2022-10-15", "2023-06-20"), ("2023-24", "2023-10-20", "2024-06-25"),
            ("2024-25", "2024-10-18", "2025-06-30"), ("2025-26", "2025-10-18", "2026-06-30")],
    "nhl": [("2022-23", "2022-10-05", "2023-06-20"), ("2023-24", "2023-10-08", "2024-06-30"),
            ("2024-25", "2024-10-02", "2025-06-30"), ("2025-26", "2025-10-05", "2026-06-30")],
    "mlb": [("2021", "2021-04-01", "2021-11-05"), ("2022", "2022-04-07", "2022-11-06"), ("2023", "2023-03-30", "2023-11-02"),
            ("2024", "2024-03-20", "2024-11-01"), ("2025", "2025-03-18", "2025-11-02"), ("2026", "2026-03-25", "2026-11-10")],
}
FIELDS = ["season", "date", "away", "home", "away_score", "home_score", "neutral", "periods_away", "periods_home",
          "ml_open_away", "ml_open_home", "ml_close_away", "ml_close_home", "spread_close_home", "total_close",
          "source", "espn_id", "away_abbr", "home_abbr", "season_type", "away_pitcher", "home_pitcher", "away_qb", "home_qb",
          "away_rest", "home_rest", "div_game", "roof", "temp", "wind"]


def out_dir(sport):
    d = os.path.join(sport_dir(sport), "history")
    os.makedirs(d, exist_ok=True)
    return d


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def num(s):
    s = str(s).strip().lower()
    if s in ("pk", "p", "even", "ev"):
        return 0.0
    s = s.replace("½", ".5")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------- SBRO ----------------
def sbro_rows(html):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if cells and cells[0].isdigit() and len(cells) >= 8:
            rows.append(cells)
    return rows


def sbro_date(mmdd, season):
    m, d = int(mmdd[:-2]), int(mmdd[-2:])
    first = int(season[:4])
    y = first if (m >= 8 or len(season) == 4) else first + 1
    return date(y, m, d).isoformat()


def parse_sbro(sport, season, html):
    rows = sbro_rows(html)
    out = []
    prev = None
    for i in range(0, len(rows) - 1, 2):
        a, h = rows[i], rows[i + 1]
        if a[2] not in ("V", "N") or h[2] not in ("H", "N"):
            continue
        dt = date.fromisoformat(sbro_date(a[0], season))
        if prev and dt < prev - timedelta(days=30):   # 2019-20 泡泡季延到 8～10 月：日期倒退就加一年
            dt = dt.replace(year=dt.year + 1)
        prev = dt
        rec = {"season": season, "date": dt.isoformat(), "away": a[3], "home": h[3],
               "neutral": a[2] == "N", "source": "sbro"}
        if sport == "nhl":
            # 尾端 8 欄：開盤 ML、收盤 ML、讓分盤口、讓分賠率、開盤大小、賠率、收盤大小、賠率
            fa, fh = a[-9], h[-9]
            rec.update(away_score=num(fa), home_score=num(fh), periods_away="|".join(a[4:-9]), periods_home="|".join(h[4:-9]),
                       ml_open_away=num(a[-8]), ml_open_home=num(h[-8]), ml_close_away=num(a[-7]), ml_close_home=num(h[-7]),
                       spread_close_home=num(h[-6]), total_close=num(a[-2]) or num(h[-2]))
        else:
            # NBA／NFL：… 最終、開盤、收盤、獨贏、下半場；開盤／收盤欄＝讓分（比較小的數）或大小分（比較大的數）
            fa, fh = a[-5], h[-5]
            ca, ch = num(a[-3]), num(h[-3])
            spread = total = None
            if ca is not None and ch is not None:
                total, sp = max(ca, ch), min(ca, ch)
                spread = -sp if ch <= ca else sp   # 讓分寫在熱門隊那一列
            rec.update(away_score=num(fa), home_score=num(fh), periods_away="|".join(a[4:-5]), periods_home="|".join(h[4:-5]),
                       ml_close_away=num(a[-2]), ml_close_home=num(h[-2]), spread_close_home=spread, total_close=total)
        out.append(rec)
    return out


def download_sbro(sport):
    d = out_dir(sport)
    for season in SBRO_SEASONS.get(sport, []):
        path = os.path.join(d, f"sbro_{season}.csv")
        if os.path.exists(path):
            continue
        try:
            r = requests.get(SBRO.format(sport=sport, season=season), headers=SBRO_UA, timeout=60)
            r.raise_for_status()
            rows = parse_sbro(sport, season, r.text)
        except Exception as e:
            print(f"  SBRO {sport} {season}: 失敗 {e}")
            continue
        write(path, rows)
        print(f"  SBRO {sport} {season}: {len(rows)} 場")
        time.sleep(1)


# ---------------- ESPN ----------------
def espn_day(sport, day):
    s, l = ESPN_PATH[sport]
    for attempt in range(3):
        try:
            r = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/{s}/{l}/scoreboard",
                             params={"dates": day.strftime("%Y%m%d"), "limit": "300"}, timeout=30)
            r.raise_for_status()
            return r.json().get("events") or []
        except Exception:
            time.sleep(2 + attempt * 3)
    return []


def american(side, when, key):
    v = (((side or {}).get(when) or {}).get(key) or {}).get("american")
    return num(v) if v is not None else None


def espn_odds(sport, eid):
    s, l = ESPN_PATH[sport]
    for attempt in range(3):
        try:
            r = requests.get(f"https://sports.core.api.espn.com/v2/sports/{s}/leagues/{l}/events/{eid}/competitions/{eid}/odds",
                             timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            items = r.json().get("items") or []
            # 優先用有收盤資料、不是即時盤的那一家
            items = [i for i in items if "live" not in ((i.get("provider") or {}).get("name") or "").lower()] or items
            for it in items:
                aw, hm = it.get("awayTeamOdds") or {}, it.get("homeTeamOdds") or {}
                ml_ca, ml_ch = american(aw, "close", "moneyLine"), american(hm, "close", "moneyLine")
                if ml_ca is None:
                    ml_ca, ml_ch = num(aw.get("moneyLine")), num(hm.get("moneyLine"))
                sp_h = american(hm, "close", "pointSpread")
                tot = None
                t = it.get("total") or {}
                tc = (t.get("close") or {}).get("total") or {}
                if tc.get("american") is not None:
                    tot = num(str(tc["american"]).lstrip("ou"))
                if tot is None:
                    tot = it.get("overUnder")
                return {"ml_open_away": american(aw, "open", "moneyLine"), "ml_open_home": american(hm, "open", "moneyLine"),
                        "ml_close_away": ml_ca, "ml_close_home": ml_ch,
                        "spread_close_home": sp_h if sp_h is not None else (it.get("spread") if hm.get("favorite") else None),
                        "total_close": tot, "provider": (it.get("provider") or {}).get("name")}
            return None
        except Exception:
            time.sleep(2 + attempt * 3)
    return None


def download_espn(sport, only_missing=True):
    d = out_dir(sport)
    seasons = ESPN_SEASONS.get(sport, [])
    for idx, (season, start, end) in enumerate(seasons):
        path = os.path.join(d, f"espn_{season}.csv")
        last = idx == len(seasons) - 1
        if os.path.exists(path) and only_missing and not last:
            continue
        s0, s1 = date.fromisoformat(start), min(date.fromisoformat(end), date.today() - timedelta(days=1))
        days = [s0 + timedelta(days=i) for i in range((s1 - s0).days + 1)]
        with ThreadPoolExecutor(8) as ex:
            day_events = list(ex.map(lambda dd: espn_day(sport, dd), days))
        games = []
        for day, evs in zip(days, day_events):
            for e in evs:
                comp = (e.get("competitions") or [{}])[0]
                if not (comp.get("status") or {}).get("type", {}).get("completed"):
                    continue
                st = (e.get("season") or {}).get("type")
                if st not in (2, 3):   # 只要例行賽、季後賽
                    continue
                teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
                a, h = teams.get("away"), teams.get("home")
                if not a or not h:
                    continue
                games.append({"season": season, "date": day.isoformat(), "espn_id": e["id"],
                              "away": a["team"].get("displayName"), "home": h["team"].get("displayName"),
                              "away_abbr": a["team"].get("abbreviation"), "home_abbr": h["team"].get("abbreviation"),
                              "away_score": num(a.get("score")), "home_score": num(h.get("score")),
                              "periods_away": "|".join(str(int(x.get("value", 0))) for x in a.get("linescores") or []),
                              "periods_home": "|".join(str(int(x.get("value", 0))) for x in h.get("linescores") or []),
                              "neutral": bool(comp.get("neutralSite")), "source": "espn",
                              "away_pitcher": next((p.get("athlete", {}).get("displayName") for p in a.get("probables") or []), ""),
                              "home_pitcher": next((p.get("athlete", {}).get("displayName") for p in h.get("probables") or []), ""),
                              "season_type": "post" if st == 3 else "regular"})
        with ThreadPoolExecutor(8) as ex:
            odds = list(ex.map(lambda g: espn_odds(sport, g["espn_id"]), games))
        n_odds = 0
        for g, o in zip(games, odds):
            if o:
                g.update({k: v for k, v in o.items() if k in FIELDS})
                n_odds += o.get("ml_close_home") is not None
        write(path, games)
        print(f"  ESPN {sport} {season}: {len(games)} 場，{n_odds} 場有收盤獨贏")


# ---------------- MLB（SBRO Excel 檔，2010–2021）----------------
def download_mlb_sbro():
    import io
    import pandas as pd
    d = out_dir("mlb")
    for year in MLB_SBRO_YEARS:
        path = os.path.join(d, f"sbro_{year}.csv")
        if os.path.exists(path):
            continue
        try:
            r = requests.get(MLB_SBRO.format(year=year), headers=SBRO_UA, timeout=60)
            r.raise_for_status()
            x = pd.read_excel(io.BytesIO(r.content), header=None, dtype=str).fillna("")
        except Exception as e:
            print(f"  SBRO mlb {year}: 失敗 {e}")
            continue
        rows = [list(map(str.strip, map(str, row))) for row in x.values.tolist()]
        rows = [c for c in rows if c and c[0].replace(".0", "").isdigit()]
        out, prev = [], None
        for i in range(0, len(rows) - 1, 2):
            a, h = rows[i], rows[i + 1]
            if a[2] not in ("V", "N") or h[2] not in ("H", "N"):
                continue
            mmdd = a[0].replace(".0", "")
            dt = date(year, int(mmdd[:-2]), int(mmdd[-2:]))
            # 欄位：日期 輪次 VH 隊 投手 1..9局 最終 開盤 收盤 讓分 讓分賠率 開盤大小 賠率 收盤大小 賠率
            fin = 14
            out.append({"season": str(year), "date": dt.isoformat(), "away": a[3], "home": h[3], "neutral": a[2] == "N",
                        "away_pitcher": a[4], "home_pitcher": h[4],
                        "periods_away": "|".join(a[5:fin]), "periods_home": "|".join(h[5:fin]),
                        "away_score": num(a[fin]), "home_score": num(h[fin]),
                        "ml_open_away": num(a[fin + 1]), "ml_open_home": num(h[fin + 1]),
                        "ml_close_away": num(a[fin + 2]), "ml_close_home": num(h[fin + 2]),
                        "spread_close_home": num(h[fin + 3]), "total_close": num(a[fin + 7]) or num(h[fin + 7]), "source": "sbro"})
        write(path, out)
        print(f"  SBRO mlb {year}: {len(out)} 場")


# ---------------- NFL（nflverse：1999 年起每場的收盤讓分、大小、獨贏）----------------
def download_nflverse():
    import io
    import pandas as pd
    d = out_dir("nfl")
    r = requests.get(NFLVERSE, timeout=60)
    r.raise_for_status()
    g = pd.read_csv(io.StringIO(r.text))
    g = g[g["season"] >= 2006]
    for season, x in g.groupby("season"):
        rows = []
        for _, e in x.iterrows():
            if pd.isna(e["home_score"]):
                continue
            rows.append({"season": f"{season}", "date": e["gameday"], "away": e["away_team"], "home": e["home_team"],
                         "away_score": e["away_score"], "home_score": e["home_score"], "neutral": e["location"] == "Neutral",
                         "ml_close_away": e.get("away_moneyline"), "ml_close_home": e.get("home_moneyline"),
                         "spread_close_home": -e["spread_line"] if pd.notna(e["spread_line"]) else None, "total_close": e.get("total_line"),
                         "source": "nflverse", "espn_id": e.get("espn"), "season_type": "regular" if e["game_type"] == "REG" else "post",
                         "away_qb": e.get("away_qb_name"), "home_qb": e.get("home_qb_name"), "away_rest": e.get("away_rest"),
                         "home_rest": e.get("home_rest"), "div_game": e.get("div_game"), "roof": e.get("roof"),
                         "temp": e.get("temp"), "wind": e.get("wind")})
        write(os.path.join(d, f"nflverse_{season}.csv"), rows)
    print(f"  nflverse：{g['season'].min()}–{g['season'].max()} 季")


def run(sports):
    import traceback
    for sport in sports:
        print(f"== {sport} ==")
        try:
            run_one(sport)
        except Exception:
            msg = traceback.format_exc()
            print(msg)
            with open(os.path.join(out_dir(sport), "_error.txt"), "w") as f:
                f.write(msg)


def run_one(sport):
    if True:
        if sport == "nfl":
            download_nflverse()
            return
        if sport == "mlb":
            download_mlb_sbro()
        else:
            download_sbro(sport)
        download_espn(sport)


if __name__ == "__main__":
    run((sys.argv[1] if len(sys.argv) > 1 else "nba,nhl").split(","))
