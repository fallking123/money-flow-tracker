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
- model1_us 模型一・美國賠率：同一個模型，押「美國賠率期望值比較高」的那一邊，用美國賠率結算（看模型本身準不準）
- model1_us_tw 跟 model1_us 押同一邊，但改用台彩賠率結算（冰球台彩算 60 分鐘、和局算輸）：看「照美國賠率的建議去台彩下」會不會賺
  （ev 欄記的是美國賠率的期望值，所以「只下划算的」＝美國划算的那幾注改去台彩下）
- model1_sp_us／model1_ou_us 只下讓分／只下大小分：每場押那個玩法裡美國賠率期望值比較高的一邊（拿來比較三種玩法）
- model1_all_us 不限獨贏：獨贏、讓分、大小分裡挑「美國賠率期望值最高」的那一注，用美國賠率結算
  （獨贏勝率用模型一；讓分、大小分用 Pinnacle 去抽水的機率，沒有 Pinnacle 就用美國共識賠率去抽水）。pick 欄寫成「玩法|邊|盤口」，例如 sp|home|-1.5
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


def us_options(g):
    """用美國賠率下注：含延長賽的二選一（足球三選一），勝率用模型一（足球用足球模型）"""
    snap = next((s for s in reversed(g.get("snaps") or []) if s.get("ml")), None)
    if not snap:
        return []
    ml = snap["ml"]
    if g["sport"] == "soccer":
        mdl = g.get("model")
        if not mdl or len(ml) < 9:
            return []
        keys, us = ["home", "draw", "away"], [ml[6], ml[7], ml[8]]
    else:
        mdl = g.get("m1")
        if not mdl or len(ml) < 6:
            return []
        keys, us = ["away", "home"], [ml[4], ml[5]]
    if not all(us) or any(o <= 1 for o in us):
        return []
    return [{"key": k, "us": o, "p": p, "m": m, "tw": o, "src": "us", "ev": p * o - 1}
            for k, o, p, m in zip(keys, us, mdl["p"], mdl["mkt"])]


def pick_name(g, key):
    return "和局" if key == "draw" else (g.get(key + "_zh") or g[key])


def tw_opts(g, tw):
    """台彩的每個獨贏選項：台彩賠率（有記錄用實際的，沒有用估的）、模型勝率、期望值"""
    opts, snap = ml_options(g)
    d = discount(tw, g["sport"])
    rec = ((g.get("tw") or {}).get("ml") or {})
    for o in opts:
        act = rec.get(o["key"])
        if act and act[0]:
            o["tw"], o["src"] = act[0], "actual"
        else:
            o["tw"], o["src"] = (o["est"] if "est" in o else round(o["us"] * (1 + d / 100), 3)), "est"
        o["ev"] = o["p"] * o["tw"] - 1
    return opts, snap


def retro_tw(g, tw, r):
    """舊比賽（已經沒有模型即時資料）：用當時記下的美國賠率、勝率，換算台彩那一邊的賠率"""
    key, sport = r["pick"], g["sport"]
    try:
        us, p, m = float(r["us_odds"]), float(r["p"]), float(r["mkt_p"])
    except (TypeError, ValueError):
        return None
    act = (((g.get("tw") or {}).get("ml") or {}).get(key) or [None])[0]
    if sport == "nhl":   # 台彩冰球＝60 分鐘三選一：用含延長賽的勝率換算成 60 分鐘就贏的機率
        snap = next((x for x in reversed(g.get("snaps") or []) if x.get("ou")), {})
        ou = snap.get("ou") or []
        total = ou[4] if len(ou) > 4 else None
        i = 2 if key == "home" else 0
        ph = lambda x: x if key == "home" else 1 - x
        p3, q3 = B.nhl_reg3(ph(p), total)[i], B.nhl_reg3(ph(m), total)[i]
        odds, src = (act, "actual") if act else (round(1 / (q3 * (1 + B.NHL3_MARGIN)), 3), "est")
        return {"p": p3, "m": q3, "tw": odds, "src": src, "ev": p3 * odds - 1}
    odds, src = (act, "actual") if act else (round(us * (1 + discount(tw, sport) / 100), 3), "est")
    return {"p": p, "m": m, "tw": odds, "src": src, "ev": p * odds - 1}


def all_us_options(g, p_ml=None):
    """美國賠率的獨贏、讓分、大小分每一個選項：[{mkt, key, line, us, p, ev, name}]（足球不算：亞洲讓分有四分之一盤）"""
    import alerts   # alerts 也 import 這個檔，放這裡才不會互相 import
    if g["sport"] == "soccer":
        return []
    pre = [x for x in (g.get("snaps") or []) if x.get("hrs") is None or x["hrs"] >= 0]
    snap = next((x for x in reversed(pre) if any(x.get(m) for m in ("ml", "sp", "ou"))), None)
    if not snap:
        return []
    out = []
    for mkt in ("ml", "sp", "ou"):
        ss = alerts.us_sides(g, snap, mkt)
        if not ss or any(not o or o <= 1 for _, o, _ in ss):
            continue
        for key, us, line in ss:
            if mkt != "ml" and line is None:
                continue
            if mkt == "ml" and p_ml:
                p = p_ml.get(key)
            else:
                p, _ = alerts.prob(g, mkt, key, line)
            if not p and mkt != "ml":   # 沒有 Pinnacle：用美國各家共識賠率去抽水（跟看板一樣的備用算法）
                inv = [1 / o for _, o, _ in ss]
                p = (1 / us) / sum(inv)
            if not p or not (0.02 < p < 0.98):
                continue
            out.append({"mkt": mkt, "key": key, "line": line, "us": us, "p": p, "ev": p * us - 1,
                        "name": alerts.pick_name(g, mkt, key, line)})
    return out


def best_all(g, p_ml=None, only=None):
    opts = [o for o in all_us_options(g, p_ml) if not only or o["mkt"] == only]
    if not opts:
        return None
    o = max(opts, key=lambda x: x["ev"])
    ln = "" if o["line"] is None else f"{o['line']:g}"
    label = {"ml": "獨贏", "sp": "讓分", "ou": "大小"}[o["mkt"]]
    return {"key": f"{o['mkt']}|{o['key']}|{ln}", "name": f"{label}・{o['name']}", "us": o["us"], "p": o["p"], "m": o["p"],
            "tw": o["us"], "src": "us", "ev": o["ev"]}


def picks(g, tw):
    opts, snap = tw_opts(g, tw)
    if not opts:
        return {}, snap
    two = [o for o in opts if o["key"] != "draw"]
    out = {"model1": max(opts, key=lambda o: o["ev"]),
           "favorite": max(two, key=lambda o: o["m"]),
           "underdog": min(two, key=lambda o: o["m"])}
    us = us_options(g)
    if us:   # 同一個模型，改用美國賠率下：看得出模型本身準不準（不被台彩抽成蓋掉）
        out["model1_us"] = max(us, key=lambda o: o["ev"])
        same = next((o for o in opts if o["key"] == out["model1_us"]["key"]), None)
        if same:   # 押同一邊、改去台彩下；ev 記美國賠率的期望值（「美國划算才下」用的是同一個判斷）
            out["model1_us_tw"] = {**same, "ev": out["model1_us"]["ev"]}
    for strat, only in (("model1_all_us", None), ("model1_sp_us", "sp"), ("model1_ou_us", "ou")):
        ba = best_all(g, only=only)
        if ba:   # 不限獨贏（三種玩法挑最好）／只下讓分／只下大小分
            out[strat] = ba
    return out, snap


def settle(row, g):
    """回傳 (result, 結算賠率, 賠率來源, 賺賠)"""
    res = g["result"]
    w, pick = res.get("winner"), row["pick"]
    if row["strategy"] in ("model1_all_us", "model1_sp_us", "model1_ou_us"):   # 不限獨贏：pick＝玩法|邊|盤口，美國賠率、含延長賽
        mkt, key, ln = (pick.split("|") + ["", "", ""])[:3]
        odds = float(row["tw_odds"])
        if mkt == "ml":
            if w == "tie":
                return "push", "", "", 0.0
            v = 1 if w == key else -1
        else:
            a, h, ln = float(res["away"]), float(res["home"]), float(ln)
            if mkt == "sp":
                d = (a - h if key == "away" else h - a) + ln
            else:
                d = (a + h - ln) if key == "over" else (ln - a - h)
            v = (d > 0) - (d < 0)
        if v == 0:
            return "push", odds, "us", 0.0
        return ("win" if v > 0 else "loss"), odds, "us", round(odds - 1, 4) if v > 0 else -1.0
    if row["strategy"].endswith("_us"):   # 美國賠率：含延長賽，用開賽前最後記到的美國賠率結算
        if g["sport"] == "soccer":
            won = (w == "tie") if pick == "draw" else (w == pick)
        else:
            if w == "tie":
                return "push", "", "", 0.0
            won = w == pick
        odds = float(row["tw_odds"])
        return ("win" if won else "loss"), odds, "us", round(odds - 1, 4) if won else -1.0
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
                           "strategy": strat, "pick": o["key"], "pick_zh": o.get("name") or pick_name(g, o["key"]),
                           "p": round(o["p"], 4), "mkt_p": round(o["m"], 4), "us_odds": o["us"], "tw_odds": o["tw"], "tw_src": o["src"],
                           "ev": round(o["ev"], 4), "hours_before": snap.get("hrs") if snap else "",
                           "updated_utc": now.strftime("%Y-%m-%dT%H:%MZ"),
                           "result": "", "settle_odds": "", "settle_src": "", "profit": ""}
                n_upd += bool(old)
                n_new += not old
        # 補記：以前只有 model1_us 的比賽，照它押的那一邊補一筆「改用台彩下」
        for (gid, strat), r in list(rows.items()):
            if strat != "model1_us" or (gid, "model1_us_tw") in rows:
                continue
            g = finals.get((sport, gid)) or next((x for x in games if x["id"] == gid), None)
            if not g:
                continue
            opts, _ = tw_opts(g, tw)
            o = next((x for x in opts if x["key"] == r["pick"]), None) or retro_tw(g, tw, r)
            if not o:
                continue
            rows[(gid, "model1_us_tw")] = {**r, "strategy": "model1_us_tw", "p": round(o["p"], 4), "mkt_p": round(o["m"], 4),
                                           "tw_odds": o["tw"], "tw_src": o["src"], "ev": r["ev"],
                                           "result": "", "settle_odds": "", "settle_src": "", "profit": ""}
            n_new += 1
        # 補記：不限獨贏（過去的比賽用當時記下的模型一勝率；讓分、大小分要有 Pinnacle 資料才算得出來）
        for (gid, strat), r in list(rows.items()):
            if strat != "model1_us":
                continue
            g = finals.get((sport, gid)) or next((x for x in games if x["id"] == gid), None)
            if not g:
                continue
            try:
                p = float(r["p"])
            except (TypeError, ValueError):
                continue
            other = "home" if r["pick"] == "away" else "away"
            for new_s, only in (("model1_all_us", None), ("model1_sp_us", "sp"), ("model1_ou_us", "ou")):
                if (gid, new_s) in rows:
                    continue
                ba = best_all(g, {r["pick"]: p, other: 1 - p}, only)
                if not ba:
                    continue
                rows[(gid, new_s)] = {**r, "strategy": new_s, "pick": ba["key"], "pick_zh": ba["name"],
                                      "p": round(ba["p"], 4), "mkt_p": round(ba["m"], 4), "us_odds": ba["us"],
                                      "tw_odds": ba["tw"], "tw_src": "us", "ev": round(ba["ev"], 4),
                                      "result": "", "settle_odds": "", "settle_src": "", "profit": ""}
                n_new += 1
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
