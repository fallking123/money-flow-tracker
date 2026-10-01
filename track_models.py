"""
上線後實戰：三個模型「每一場都下注」，誰的獲利率最高
================================================================
每次排程跑的時候：
1. 還沒開賽的比賽：用現在最新的資料，記下每個策略這場會押哪一邊（獨贏）。
   一直更新到開賽前最後一次，開賽後就不再改（＝開賽前最後的判斷）。
2. 已經有賽果的比賽：用台彩賠率結算（有你記錄的台彩實際賠率就用實際的，沒有就用估計的）。

策略：
- model1   模型一・實力：押「台彩期望值比較高」的那一邊（模型一勝率 × 台彩賠率 − 1）
- model2   模型二・資金：還在累積資料，上線後加進來
- combo    綜合：等模型二
- favorite 都押熱門（參考）
- underdog 都押冷門（參考）
每場都當作押 1 單位；profit＝賺賠（贏：賠率−1，輸：−1，平手退款：0）。
ev＝開賽前估的期望值，看板用它算「只下划算的（ev > 0）」。

用法：python track_models.py mlb,nba,nfl,nhl   或   python track_models.py soccer
輸出：docs/data/<運動>/model_picks.csv（每個運動一個檔，美國四大和足球分開跑，才不會互相衝突）
"""
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

import build_dashboard as B
import record_tw_odds
from sports_common import parse_time, read_rows, sport_dir

FIELDS = ["sport", "league", "game_id", "game_time_utc", "away", "home", "away_zh", "home_zh", "strategy", "pick", "pick_zh",
          "p", "mkt_p", "us_odds", "tw_odds", "tw_src", "ev", "hours_before", "updated_utc",
          "result", "settle_odds", "settle_src", "profit"]
HORIZON_H = 48          # 開賽前多久開始記
DEFAULT_DISC = -9.0     # 完全沒有台彩記錄時，台彩賠率 ≈ 美國賠率 × (1 − 9%)


def path_for(sport):
    return os.path.join(sport_dir(sport), "model_picks.csv")


def discount(tw, sport, market="ml"):
    """台彩賠率比美國低多少（%）：有這個運動＋玩法的記錄就用它，沒有就用全部平均"""
    gs = [x for x in tw.get("by_group", []) if x.get("avg_discount_pct") is not None]
    hit = next((x for x in gs if x["sport"] == sport and x["market"] == market), None)
    if hit:
        return hit["avg_discount_pct"]
    return sum(x["avg_discount_pct"] for x in gs) / len(gs) if gs else DEFAULT_DISC


def ml_options(g):
    """獨贏各個選項：key、美國賠率、模型勝率 p、市場公平機率 m；沒有模型或賠率就回傳 []"""
    snap = next((s for s in reversed(g.get("snaps") or []) if s.get("ml")), None)
    if not snap:
        return [], None
    ml = snap["ml"]
    if g["sport"] == "soccer":
        mdl = g.get("model")
        if not mdl or len(ml) < 9:
            return [], snap
        keys, us = ["home", "draw", "away"], [ml[6], ml[7], ml[8]]
    elif g["sport"] == "nhl":
        # 台彩冰球獨贏＝60 分鐘三選一（客／和／主）
        r3 = g.get("r3")
        if not r3 or len(ml) < 6 or not ml[4] or not ml[5]:
            return [], snap
        return [{"key": k, "us": o, "p": p, "m": m, "est": round(1 / (m * (1 + r3["margin"])), 3)}
                for k, o, p, m in zip(["away", "draw", "home"], [ml[4], None, ml[5]], r3["p"], r3["q"])], snap
    else:
        mdl = g.get("m1")
        if not mdl or len(ml) < 6:
            return [], snap
        keys, us = ["away", "home"], [ml[4], ml[5]]
    if not all(us) or any(o <= 1 for o in us):
        return [], snap
    return [{"key": k, "us": o, "p": p, "m": m} for k, o, p, m in zip(keys, us, mdl["p"], mdl["mkt"])], snap


def pick_name(g, key):
    return "和局" if key == "draw" else (g.get(key + "_zh") or g[key])


def picks(g, tw):
    opts, snap = ml_options(g)
    if not opts:
        return {}, snap
    d = discount(tw, g["sport"])
    rec = ((g.get("tw") or {}).get("ml") or {})
    for o in opts:
        act = rec.get(o["key"])
        if act and act[0]:
            o["tw"], o["src"] = act[0], "actual"
        else:
            o["tw"], o["src"] = (o["est"] if "est" in o else round(o["us"] * (1 + d / 100), 3)), "est"
        o["ev"] = o["p"] * o["tw"] - 1
    two = [o for o in opts if o["key"] != "draw"]
    return {"model1": max(opts, key=lambda o: o["ev"]),
            "favorite": max(two, key=lambda o: o["m"]),
            "underdog": min(two, key=lambda o: o["m"])}, snap


def settle(row, g):
    """回傳 (result, 結算賠率, 賠率來源, 賺賠)"""
    res = g["result"]
    w, pick = res.get("winner"), row["pick"]
    if g["sport"] == "nhl":
        w = res.get("reg")        # 台彩冰球只算 60 分鐘
        if w is None:
            return "void", "", "", 0.0
        won = (w == "tie") if pick == "draw" else (w == pick)
    elif g["sport"] == "soccer":
        won = (w == "tie") if pick == "draw" else (w == pick)
    else:
        if w == "tie":
            return "push", "", "", 0.0
        won = w == pick
    act = (((g.get("tw") or {}).get("ml") or {}).get(pick) or [None])[0]
    odds, src = (act, "actual") if act else (float(row["tw_odds"]), row["tw_src"] or "est")
    return ("win" if won else "loss"), odds, src, round(odds - 1, 4) if won else -1.0


def run(sports, now=None):
    now = now or datetime.now(timezone.utc)
    data = B.build(now)
    tw = data["tw"]
    games = [g for g in data["games"] if g["sport"] in sports]
    finals = {(g["sport"], g["id"]): g for g in data["games"] + data["closed"] if g["sport"] in sports and g.get("result")}
    status = {(g["sport"], g["id"]): g["status"] for g in data["games"] if g["sport"] in sports}
    for sport in sports:
        path = path_for(sport)
        rows = {(r["game_id"], r["strategy"]): r for r in read_rows(path)}
        n_new = n_upd = n_set = 0
        for g in games:
            if g["sport"] != sport or g["status"] != "upcoming":
                continue
            t = parse_time(g["t"])
            if not (now < t <= now + timedelta(hours=HORIZON_H)):
                continue
            ps, snap = picks(g, tw)
            for strat, o in ps.items():
                k = (g["id"], strat)
                old = rows.get(k)
                if old and old.get("result"):
                    continue
                rows[k] = {"sport": sport, "league": g.get("league", sport), "game_id": g["id"], "game_time_utc": g["t"],
                           "away": g["away"], "home": g["home"], "away_zh": g.get("away_zh", ""), "home_zh": g.get("home_zh", ""),
                           "strategy": strat, "pick": o["key"], "pick_zh": pick_name(g, o["key"]),
                           "p": round(o["p"], 4), "mkt_p": round(o["m"], 4), "us_odds": o["us"], "tw_odds": o["tw"], "tw_src": o["src"],
                           "ev": round(o["ev"], 4), "hours_before": snap.get("hrs") if snap else "",
                           "updated_utc": now.strftime("%Y-%m-%dT%H:%MZ"),
                           "result": "", "settle_odds": "", "settle_src": "", "profit": ""}
                n_upd += bool(old)
                n_new += not old
        for k, r in rows.items():
            if r.get("result"):
                continue
            g = finals.get((sport, r["game_id"]))
            if g:
                r["result"], r["settle_odds"], r["settle_src"], r["profit"] = settle(r, g)
                n_set += 1
            elif status.get((sport, r["game_id"])) in ("canceled", "postponed") or (
                    (sport, r["game_id"]) not in status and parse_time(r["game_time_utc"]) < now - timedelta(days=3)):
                r["result"], r["profit"] = "void", 0.0
                n_set += 1
        out = sorted(rows.values(), key=lambda r: (r["game_time_utc"], r["game_id"], r["strategy"]))
        if out:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(out)
        print(f"  {sport}：新記錄 {n_new}、更新 {n_upd}、結算 {n_set}，共 {len(out)} 筆")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "mlb,nba,nfl,nhl"
    run([s for s in arg.split(",") if s])
