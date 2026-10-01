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
- side:   ml→away/home（足球多一個 draw＝和局）；sp→away/home；ou→over/under
- 足球（sport=soccer）：比賽編號存成 an+Action Network 編號，美國賠率用 Action Network 共識盤
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


SOCCER = "soccer"
# 足球：獨贏有和局；讓分存的是主隊讓分（美國運動存的是客隊讓分）
MARKET_FIELDS_SOCCER = {
    "ml": {"home": ("ml_home_odds", None), "draw": ("ml_draw_odds", None), "away": ("ml_away_odds", None)},
    "sp": {"home": ("sp_home_odds", "sp_home_line"), "away": ("sp_away_odds", "sp_home_line")},
    "ou": {"over": ("ou_over_odds", "ou_line"), "under": ("ou_under_odds", "ou_line")},
}


# 冰球：台彩「不讓分」只算 60 分鐘、有和局（三選一），美國獨贏含延長賽（二選一），兩個不能直接比折扣；
# 台彩冰球讓分也是三選一（2:0、1:0、0:1），跟美國 ±1.5 不同。這兩種只記實際賠率（給期望值和結算用），不算折扣。
NO_DISCOUNT = {("nhl", "ml"), ("nhl", "sp")}
MARKET_FIELDS_NHL = {**MARKET_FIELDS, "ml": {"away": (None, None), "draw": (None, None), "home": (None, None)}}


def fields_for(sport):
    return MARKET_FIELDS_SOCCER if sport == SOCCER else MARKET_FIELDS_NHL if sport == "nhl" else MARKET_FIELDS


def valid_sports():
    return list(active_sports()) + [SOCCER]


def game_id(r):
    """美國運動用 SBD 編號；足球用 an+Action Network 編號"""
    return r.get("sbd_id") or (f"an{r['an_id']}" if r.get("an_id") else "")


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
    if sport not in valid_sports():
        return {"ok": False, "error": f"{sport} 目前沒有在記錄"}
    mf = fields_for(sport)
    if market not in mf or side not in mf[market]:
        return {"ok": False, "error": f"market/side 不對：{market}/{side}（和局只有足球獨贏有）"}

    row = find_game(sport, away_team, home_team, game_date)
    if row is None and sport == SOCCER:  # 足球習慣主隊寫前面，順序反了也找得到
        row = find_game(sport, home_team, away_team, game_date)
    if row is None:
        return {"ok": False, "error": f"找不到 {game_date} {away_team}@{home_team} 這場比賽的資料"}

    odds_field, line_field = mf[market][side]
    us_odds = _num(row.get(odds_field)) if odds_field else None
    us_line = _num(row.get(line_field)) if line_field else None
    flip = "away" if sport == SOCCER else "home"  # 資料裡存的是哪一隊的讓分，另一隊要反過來
    if market == "sp" and side == flip and us_line is not None:
        us_line = -us_line
    if us_odds is None and (sport, market) not in NO_DISCOUNT:
        return {"ok": False, "error": "找到比賽了，但美國賠率資料是空的（可能太早記錄、賠率還沒抓到）"}

    discount = "" if us_odds is None or (sport, market) in NO_DISCOUNT else round((tw_odds - us_odds) / us_odds * 100, 2)

    sbd_id = game_id(row)
    existing = read_rows(TW_ODDS_FILE)
    if any(r["sbd_id"] == sbd_id and r["market"] == market and r["side"] == side for r in existing):
        return {"ok": False, "error": "這筆（同一場、同盤別、同邊）已經記錄過了，不重複記"}

    out = {
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "sport": sport, "sbd_id": sbd_id, "event_id": row.get("event_id", "") or row.get("an_id", ""),
        "game_time_utc": row["game_time_utc"],
        "away_team": row["away_team"], "home_team": row["home_team"],
        "market": market, "side": side,
        "tw_odds": tw_odds, "tw_line": tw_line if tw_line is not None else "",
        "us_odds": us_odds if us_odds is not None else "", "us_line": us_line if us_line is not None else "",
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


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def per_game():
    """每場比賽記錄到的台彩賠率：{(運動, 比賽編號): {盤別: {邊: [賠率, 盤口]}}}（同一個選項記過好幾次就用最後一次）"""
    out = {}
    for r in read_rows(TW_ODDS_FILE):
        o = _num(r["tw_odds"])
        if not o:
            continue
        out.setdefault((r["sport"], r["sbd_id"]), {}).setdefault(r["market"], {})[r["side"]] = [o, _num(r["tw_line"])]
    return out


def summary():
    """
    依運動+盤別統計（給儀表板用）：
    - avg_discount_pct：台彩賠率比美國收盤低多少（平均）
    - tw_margin_pct / us_margin_pct：抽成（兩邊賠率倒數相加 − 1），美國只算同盤口的場次
    - best：台彩給得最好（折扣最小）的幾筆，看台彩在哪些地方幾乎沒抽
    """
    rows = read_rows(TW_ODDS_FILE)
    groups, pairs = {}, {}
    for r in rows:
        # 盤口不同（例如台彩讓 2.5、美國讓 1.5）的賠率不能直接比，不算進平均折扣
        if (r["sport"], r["market"]) in NO_DISCOUNT:
            groups.setdefault((r["sport"], r["market"]), []).append(None)   # 只算抽成，不算折扣
        elif r["market"] == "ml" or _num(r["tw_line"]) == _num(r["us_line"]):
            groups.setdefault((r["sport"], r["market"]), []).append(_num(r["discount_pct"]))
        pairs.setdefault((r["sport"], r["market"], r["sbd_id"]), []).append(r)
    tw_m, us_m = {}, {}
    for (sport, market, _), ps in pairs.items():
        need = 3 if market == "ml" and sport in (SOCCER, "nhl") else 2  # 足球獨贏要主／和／客三個都有才算得出抽成
        if len({p["side"] for p in ps}) != need or len(ps) != need:
            continue
        tw = [_num(p["tw_odds"]) for p in ps]
        us = [_num(p["us_odds"]) for p in ps]
        if all(tw):
            tw_m.setdefault((sport, market), []).append((sum(1 / x for x in tw) - 1) * 100)
        if all(us) and all(_num(p["tw_line"]) == _num(p["us_line"]) for p in ps):
            us_m.setdefault((sport, market), []).append((sum(1 / x for x in us) - 1) * 100)
    out = []
    for (sport, market), vals in sorted(groups.items()):
        vals = [v for v in vals if v is not None]
        if not vals and (sport, market) not in NO_DISCOUNT:
            continue
        out.append({"sport": sport, "market": market, "n": len(vals),
                    "games": len(tw_m.get((sport, market), [])),
                    "avg_discount_pct": _avg(vals),
                    "tw_margin_pct": _avg(tw_m.get((sport, market), [])),
                    "us_margin_pct": _avg(us_m.get((sport, market), []))})
    # 同盤口才能比，盤口不同的（例如台彩讓 2.5、美國讓 1.5）不算
    same = [r for r in rows if (r["sport"], r["market"]) not in NO_DISCOUNT and _num(r["discount_pct"]) is not None and (r["market"] == "ml" or _num(r["tw_line"]) == _num(r["us_line"]))]
    same.sort(key=lambda r: -(_num(r["discount_pct"]) or -999))
    best = [{"sport": r["sport"], "t": r["game_time_utc"], "away": r["away_team"], "home": r["home_team"],
             "market": r["market"], "side": r["side"], "line": _num(r["tw_line"]),
             "tw": _num(r["tw_odds"]), "us": _num(r["us_odds"]), "d": _num(r["discount_pct"])}
            for r in same[:8]]
    return {"n_total": len(rows), "by_group": out, "best": best}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="記錄一筆台彩賠率，跟美國收盤賠率比對算折扣")
    p.add_argument("--sport", required=True, choices=valid_sports())
    p.add_argument("--date", required=True, help="比賽日期 YYYY-MM-DD（用開賽時間的日期，UTC）")
    p.add_argument("--away", required=True)
    p.add_argument("--home", required=True)
    p.add_argument("--market", required=True, choices=["ml", "sp", "ou"])
    p.add_argument("--side", required=True, choices=["away", "home", "draw", "over", "under"])
    p.add_argument("--odds", required=True, type=float, help="台彩賠率（十進位，例如 1.85）")
    p.add_argument("--line", type=float, default=None, help="台彩的讓分/大小分盤口（sp/ou 才需要）")
    p.add_argument("--note", default="")
    args = p.parse_args()
    result = add_tw_bet(args.sport, args.away, args.home, args.date, args.market, args.side,
                        args.odds, args.line, args.note)
    print(result if result["ok"] else f"失敗：{result['error']}")
    sys.exit(0 if result["ok"] else 1)
