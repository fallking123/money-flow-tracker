"""
台彩賠率記錄與折扣計算
============================================
用途：把你截圖給 Claude 看的台彩賠率，記錄下來並跟當時美國收盤賠率比較，
算出「台彩折扣」（台彩通常賠率比美國低一些，因為台彩要抽成）。

⚠️ 這支程式不是排程自動跑的，是你把台彩截圖傳給 Claude 時，由 Claude
   讀圖辨識出隊伍/賠率之後，呼叫這裡的 add_tw_bet() 或用命令列執行來記錄。

流程：
1. 用隊名 + 日期，在對應運動的 odds_history 裡找出是哪一場比賽（sbd_id）
2. 取出那場比賽「收盤」（開賽前最後一筆）的美國賠率
3. 算折扣：(台彩賠率 - 美國賠率) / 美國賠率 * 100%　（負數代表台彩賠率比較低）
4. 寫進 docs/data/tw_odds.csv，用 sbd_id+market+side 當 key，避免重複記錄同一筆

存檔欄位說明：
- market: ml（獨贏）/ sp（讓分）/ ou（大小分）
- side:   ml→away/home；sp→away/home；ou→over/under
- tw_odds: 你截圖給的台彩賠率（十進位，例如 1.85）
- us_odds: 對應的美國收盤賠率（十進位，從 odds_history 找到的）
- discount_pct: (tw_odds - us_odds) / us_odds * 100
"""

import argparse
import csv
import os
import sys
import unicodedata
from datetime import datetime, timezone, timedelta

from sports_common import DATA_DIR, active_sports, all_monthly_files, read_rows

TW_ODDS_FILE = os.path.join(DATA_DIR, "tw_odds.csv")

FIELDS = [
    "recorded_utc", "sport", "sbd_id", "event_id", "game_time_utc",
    "away_team", "home_team", "market", "side",
    "tw_odds", "tw_line", "us_odds", "us_line", "discount_pct", "note",
]

MARKET_FIELDS = {
    "ml": {"away": ("ml_away_odds", None), "home": ("ml_home_odds", None)},
    "sp": {"away": ("sp_away_odds", "sp_away_line"), "home": ("sp_home_odds", "sp_away_line")},
    "ou": {"over": ("ou_over_odds", "ou_line"), "under": ("ou_under_odds", "ou_line")},
}


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return "".join(c for c in s if c.isalnum())


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def find_game(sport, away_team, home_team, game_date):
    """用隊名（模糊比對）+ 日期，在 odds_history 裡找出這場比賽最新的一筆快照"""
    na, nh = _norm(away_team), _norm(home_team)
    target = datetime.fromisoformat(game_date).date() if isinstance(game_date, str) else game_date
    best = None
    for path in all_monthly_files(sport, "odds_history"):
        for r in read_rows(path):
            try:
                t = datetime.fromisoformat(r["game_time_utc"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if t.date() != target:
                continue
            ra, rh = _norm(r.get("away_team")), _norm(r.get("home_team"))
            if na and na in ra and nh and nh in rh:
                if best is None or r["timestamp_utc"] > best["timestamp_utc"]:
                    best = r
    return best


def add_tw_bet(sport, away_team, home_team, game_date, market, side, tw_odds, tw_line=None, note=""):
    """主要進入點：找到比賽 → 取美國收盤賠率 → 算折扣 → 寫入 tw_odds.csv"""
    if sport not in active_sports():
        return {"ok": False, "error": f"{sport} 目前沒有在記錄"}
    if market not in MARKET_FIELDS or side not in MARKET_FIELDS[market]:
        return {"ok": False, "error": f"market/side 不對：{market}/{side}"}

    row = find_game(sport, away_team, home_team, game_date)
    if row is None:
        return {"ok": False, "error": f"找不到 {game_date} {away_team}@{home_team} 這場比賽的資料"}

    odds_field, line_field = MARKET_FIELDS[market][side]
    us_odds = _num(row.get(odds_field))
    us_line = _num(row.get(line_field)) if line_field else None
    if us_odds is None:
        return {"ok": False, "error": "找到比賽了，但美國賠率資料是空的（可能太早記錄、賠率還沒抓到）"}

    discount = round((tw_odds - us_odds) / us_odds * 100, 2)

    sbd_id = row["sbd_id"]
    existing = read_rows(TW_ODDS_FILE)
    if any(r["sbd_id"] == sbd_id and r["market"] == market and r["side"] == side for r in existing):
        return {"ok": False, "error": "這筆（同一場、同盤別、同邊）已經記錄過了，不重複記"}

    out = {
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "sport": sport, "sbd_id": sbd_id, "event_id": row.get("event_id", ""),
        "game_time_utc": row["game_time_utc"],
        "away_team": row["away_team"], "home_team": row["home_team"],
        "market": market, "side": side,
        "tw_odds": tw_odds, "tw_line": tw_line if tw_line is not None else "",
        "us_odds": us_odds, "us_line": us_line if us_line is not None else "",
        "discount_pct": discount, "note": note,
    }
    exists = os.path.exists(TW_ODDS_FILE)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TW_ODDS_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(out)
    return {"ok": True, "row": out}


def summary():
    """依運動+盤別統計台彩折扣的平均值、筆數（給儀表板用）"""
    rows = read_rows(TW_ODDS_FILE)
    groups = {}
    for r in rows:
        key = (r["sport"], r["market"])
        groups.setdefault(key, []).append(_num(r["discount_pct"]))
    out = []
    for (sport, market), vals in sorted(groups.items()):
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        out.append({"sport": sport, "market": market, "n": len(vals),
                    "avg_discount_pct": round(sum(vals) / len(vals), 2)})
    return {"n_total": len(rows), "by_group": out}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="記錄一筆台彩賠率，跟美國收盤賠率比對算折扣")
    p.add_argument("--sport", required=True, choices=list(active_sports()))
    p.add_argument("--date", required=True, help="比賽日期 YYYY-MM-DD（用開賽時間的日期，UTC）")
    p.add_argument("--away", required=True)
    p.add_argument("--home", required=True)
    p.add_argument("--market", required=True, choices=["ml", "sp", "ou"])
    p.add_argument("--side", required=True, choices=["away", "home", "over", "under"])
    p.add_argument("--odds", required=True, type=float, help="台彩賠率（十進位，例如 1.85）")
    p.add_argument("--line", type=float, default=None, help="台彩的讓分/大小分盤口（sp/ou 才需要）")
    p.add_argument("--note", default="")
    args = p.parse_args()
    result = add_tw_bet(args.sport, args.away, args.home, args.date, args.market, args.side,
                        args.odds, args.line, args.note)
    print(result if result["ok"] else f"失敗：{result['error']}")
    sys.exit(0 if result["ok"] else 1)
