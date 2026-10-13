"""
職業版・特徵搜尋用：SBRO 歷史檔案裡的「開盤讓分、開盤大小分」（以前只存了收盤獨贏）
在 GitHub Actions 上跑（工作環境連不到）。NBA 2007-08～2022-23、NFL 2007-08～2021-22。
輸出 docs/data/pro/<nba|nfl>/sbro_lines.csv：日期、主客、比分、開盤／收盤讓分（主隊，負＝主隊讓）、開盤／收盤大小、收盤獨贏
用法：python -m pro.fetch_sbro_open
"""
import csv
import os
import time
from datetime import date, timedelta

import requests

import download_history as DH

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def split(a, h):
    """SBRO 每列的開盤／收盤欄：讓分（比較小的數，寫在熱門那一列）或大小分（比較大的數）"""
    a, h = DH.num(a), DH.num(h)
    if a is None or h is None:
        return None, None
    total, sp = max(a, h), min(a, h)
    return (-sp if h <= a else sp), total


def parse(season, html):
    rows = DH.sbro_rows(html)
    out, prev = [], None
    for i in range(0, len(rows) - 1, 2):
        a, h = rows[i], rows[i + 1]
        if a[2] not in ("V", "N") or h[2] not in ("H", "N"):
            continue
        dt = date.fromisoformat(DH.sbro_date(a[0], season))
        if prev and dt < prev - timedelta(days=30):
            dt = dt.replace(year=dt.year + 1)
        prev = dt
        so, to = split(a[-4], h[-4])
        sc, tc = split(a[-3], h[-3])
        out.append({"season": season, "date": dt.isoformat(), "away": a[3], "home": h[3], "neutral": int(a[2] == "N"),
                    "away_score": DH.num(a[-5]), "home_score": DH.num(h[-5]), "spread_open_home": so, "total_open": to,
                    "spread_close_home": sc, "total_close": tc, "ml_close_away": DH.num(a[-2]), "ml_close_home": DH.num(h[-2])})
    return out


def main():
    for sport, seasons in (("nba", DH.SBRO_SEASONS["nba"]), ("nfl", DH.SBRO_SEASONS["nfl"])):
        allr = []
        for s in seasons:
            try:
                r = requests.get(DH.SBRO.format(sport=sport, season=s), headers=DH.SBRO_UA, timeout=60)
                r.raise_for_status()
                rows = parse(s, r.text)
            except Exception as e:
                print(f"{sport} {s} 失敗：{e}", flush=True)
                continue
            print(f"{sport} {s}：{len(rows)} 場，有開盤讓分 {sum(1 for x in rows if x['spread_open_home'] is not None)}", flush=True)
            allr += rows
            time.sleep(1)
        d = os.path.join(ROOT, "docs", "data", "pro", sport)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "sbro_lines.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(allr[0].keys()))
            w.writeheader()
            w.writerows(allr)


if __name__ == "__main__":
    main()
