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
- model1_sp_tw／model1_ou_tw／model1_all_tw：跟對應的 _us 押同一注，改用台彩賠率結算（估的，有記錄用實際的）。
  冰球台彩只算 60 分鐘：獨贏打平算輸、大小分用前三節總分；台彩冰球讓分是三選一，跟美國 ±1.5 不能比，不下（void）。
  ev 欄記的是美國賠率的期望值（「只下划算的」＝美國划算的那幾注改去台彩下）
- draw_us／draw 都押和局（足球；冰球只有台彩 draw，60 分鐘打平）：每場都押和局，分別用美國賠率、台彩賠率（有記錄用實際的，沒有用估的）結算（參考）
- model1_us_draw／model1_tw_draw 不另外記：看板從 model1_us／model1_us_tw 裡挑「押和局」的那幾注算
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
from sports_common import nhl_reg_over, parse_time, read_rows, sport_dir

FIELDS = ["sport", "league", "game_id", "game_time_utc", "away", "home", "away_zh", "home_zh", "strategy", "pick", "pick_zh",
          "p", "mkt_p", "us_odds", "tw_odds", "tw_src", "ev", "hours_before", "updated_utc",
          "result", "settle_odds", "settle_src", "profit", "est_old"]
HORIZON_H = 48          # 開賽前多久開始記
DEFAULT_DISC = -9.0     # 完全沒有台彩記錄時，台彩賠率 ≈ 美國賠率 × (1 − 9%)


def path_for(sport):
    return os.path.join(sport_dir(sport), "model_picks.csv")


def old_discount(tw, sport, market="ml"):
    """改之前（2026-10-26 以前）的估法：這個運動＋玩法跟美國收盤比的平均折扣，沒有就用全部平均（不分賠率高低）"""
    gs = [x for x in tw.get("by_group", []) if x.get("avg_discount_pct") is not None]
    hit = next((x for x in gs if x["sport"] == sport and x["market"] == market), None)
    if hit:
        return hit["avg_discount_pct"]
    return sum(x["avg_discount_pct"] for x in gs) / len(gs) if gs else DEFAULT_DISC


def old_est(o, tw, sport):
    """舊估法估的台彩賠率：實際截圖照用、冰球照舊（60 分鐘另算，沒改過），其他＝美國共識盤 ×（1 + 平均折扣）"""
    if o.get("src") == "actual" or sport == "nhl" or not o.get("us"):
        return o["tw"]
    return round(o["us"] * (1 + old_discount(tw, sport) / 100), 3)


def discount(tw, sport, market="ml", odds=None, side="side"):
    """台彩賠率比美國低多少（%）。2026-10-26 起：
    - 獨贏（含和局）：台彩在機率上加固定值 k → 台彩 ≈ 1 ÷（1 ÷ 美國 + k），賠率越高打越兇（side＝"draw" 用和局的 k）
    - 讓分／大小分：照賠率級距
    沒有表時才用這個運動＋玩法的平均，再沒有就用全部平均"""
    import record_tw_odds
    if market == "ml" and odds:
        e = record_tw_odds.est_ml(tw.get("add"), sport, odds, side)
        if e:
            return (e / odds - 1) * 100
    bd = record_tw_odds.band_discount(tw.get("bands"), odds, market)
    if bd is not None:
        return bd
    gs = [x for x in tw.get("by_group", []) if x.get("avg_discount_pct") is not None]
    hit = next((x for x in gs if x["sport"] == sport and x["market"] == market), None)
    if hit:
        return hit["avg_discount_pct"]
    return sum(x["avg_discount_pct"] for x in gs) / len(gs) if gs else DEFAULT_DISC


def tw_from(g, tw, sport, mkt, key, us, line=None, nd=3):
    """估台彩賠率（2026-10-26 起）：從基準賠率（Pinnacle＋bet365，base_odds.py）估，那場沒有基準才用美國賠率"""
    import base_odds
    b, _ = base_odds.pick(g, mkt, key, line)
    ref = b or us
    if not ref or ref <= 1:
        return None
    return round(ref * (1 + discount(tw, sport, mkt, ref, "draw" if key == "draw" else "side") / 100), nd)


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
    rec = ((g.get("tw") or {}).get("ml") or {})
    for o in opts:
        act = rec.get(o["key"])
        if act and act[0]:
            o["tw"], o["src"] = act[0], "actual"
        else:
            o["tw"], o["src"] = (o["est"] if "est" in o else tw_from(g, tw, g["sport"], "ml", o["key"], o["us"])), "est"
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
    odds, src = (act, "actual") if act else (tw_from(g, tw, sport, "ml", key, us), "est")
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


def draw_opts(g, tw):
    """都押和局（不需要模型，打完的比賽也能補記）：((美國那一筆或 None, 台彩那一筆), snap)；p＝市場去抽水的和局機率。
    足球：90 分鐘和局，美國、台彩都有。冰球：台彩獨贏是 60 分鐘三選一，和局＝打進延長賽；美國沒有這個盤，只算台彩"""
    if g["sport"] not in ("soccer", "nhl"):
        return None
    pre = [x for x in (g.get("snaps") or []) if x.get("hrs") is None or x["hrs"] >= 0]
    act = (((g.get("tw") or {}).get("ml") or {}).get("draw") or [None])[0]
    if g["sport"] == "nhl":
        snap = next((x for x in reversed(pre) if x.get("ml") and len(x["ml"]) > 5 and x["ml"][4] and x["ml"][5]), None)
        if not snap or min(snap["ml"][4], snap["ml"][5]) <= 1:
            return None
        a, h = snap["ml"][4], snap["ml"][5]
        ou = next((x["ou"] for x in reversed(pre) if x.get("ou") and len(x["ou"]) > 4), None)
        m = B.nhl_reg3((1 / h) / (1 / a + 1 / h), ou[4] if ou else None)[1]
        two, src = (act, "actual") if act else (round(1 / (m * (1 + B.NHL3_MARGIN)), 3), "est")
        return (None, {"key": "draw", "name": "和局（60分鐘）", "us": "", "p": m, "m": m, "tw": two, "src": src, "ev": m * two - 1}), snap
    snap = next((x for x in reversed(pre) if x.get("ml") and len(x["ml"]) > 8 and all(x["ml"][6:9])), None)
    if not snap:
        return None
    us = snap["ml"][6:9]
    if any(o <= 1 for o in us):
        return None
    m = (1 / us[1]) / sum(1 / o for o in us)
    two, src = (act, "actual") if act else (tw_from(g, tw, "soccer", "ml", "draw", us[1]), "est")
    base = {"key": "draw", "name": "和局", "us": us[1], "p": m, "m": m}
    return ({**base, "tw": us[1], "src": "us", "ev": m * us[1] - 1},
            {**base, "tw": two, "src": src, "ev": m * two - 1}), snap


TW_TWINS = {"model1_sp_us": "model1_sp_tw", "model1_ou_us": "model1_ou_tw", "model1_all_us": "model1_all_tw"}
NHL_OU_MARGIN = 0.15   # 台彩冰球大小抽成（跟 alerts.py 一樣）


def tw_price(g, tw, pick):
    """「玩法|邊|盤口」這一注在台彩大約是多少賠率 → (賠率, 來源)；台彩不能下回傳 None"""
    mkt, key, ln = (pick.split("|") + ["", "", ""])[:3]
    line = float(ln) if ln not in ("", None) else None
    pre = [x for x in (g.get("snaps") or []) if x.get("hrs") is None or x["hrs"] >= 0]
    snap = next((x for x in reversed(pre) if x.get(mkt)), None)
    if not snap:
        return None
    import alerts
    ss = alerts.us_sides(g, snap, mkt)
    if not ss or any(not o or o <= 1 for _, o, _ in ss):
        return None
    rec = ((g.get("tw") or {}).get(mkt) or {}).get(key)
    if rec and rec[0] and (mkt == "ml" or rec[1] is None or rec[1] == line):
        return rec[0], "actual"
    us = next(o for k, o, _ in ss if k == key)
    if g["sport"] == "nhl":
        inv = {k: 1 / o for k, o, _ in ss}
        fair = {k: v / sum(inv.values()) for k, v in inv.items()}
        if mkt == "sp":
            return None          # 台彩冰球讓分是三選一，跟美國 ±1.5 不能比
        if mkt == "ml":
            ou = snap.get("ou") or []
            q3 = B.nhl_reg3(fair["home"], ou[4] if len(ou) > 4 else None)[2 if key == "home" else 0]
            return round(1 / (q3 * (1 + B.NHL3_MARGIN)), 3), "est"
        pp = nhl_reg_over(fair["over"], line) if key == "over" else 1 - nhl_reg_over(1 - fair["under"], line)
        return round(1 / (pp * (1 + NHL_OU_MARGIN)), 3), "est"
    return tw_from(g, tw, g["sport"], mkt, key, us, line), "est"


def tw_prob(g, pick, p):
    """同一注照台彩規則贏的機率：冰球獨贏＝60 分鐘就贏（打平算輸）、冰球大小＝只算 60 分鐘；其他跟美國一樣"""
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None
    mkt, key, ln = (pick.split("|") + ["", "", ""])[:3]
    if g["sport"] != "nhl" or mkt == "sp":
        return p
    pre = [x for x in (g.get("snaps") or []) if x.get("hrs") is None or x["hrs"] >= 0]
    snap = next((x for x in reversed(pre) if x.get("ou")), {})
    ou = snap.get("ou") or []
    if mkt == "ml":
        ph = p if key == "home" else 1 - p
        return B.nhl_reg3(ph, ou[4] if len(ou) > 4 else None)[2 if key == "home" else 0]
    line = float(ln) if ln not in ("", None) else None
    return nhl_reg_over(p, line) if key == "over" else 1 - nhl_reg_over(1 - p, line)


def twin_row(r, g, tw):
    """把 _us 那一筆複製成「改去台彩下」的一筆；台彩不能下就記 void。p 換成照台彩規則贏的機率"""
    tp = tw_price(g, tw, r["pick"])
    row = {**r, "strategy": TW_TWINS[r["strategy"]], "result": "", "settle_odds": "", "settle_src": "", "profit": ""}
    if tp:
        row["tw_odds"], row["tw_src"] = tp
    else:
        row["tw_odds"], row["tw_src"] = "", "none"
    pt = tw_prob(g, r["pick"], r["p"])
    if pt is not None:
        row["p"] = round(pt, 4)
    return row


def picks(g, tw):
    opts, snap = tw_opts(g, tw)
    if not opts:
        return {}, snap
    two = [o for o in opts if o["key"] != "draw"]
    # 比較兩種估法（使用者 2026-10-26 要求）：model1_old＝用舊估法挑邊、model1_new＝用新估法挑邊；兩個都用同一個台彩賠率結算
    olds = [{**o, "est_old": old_est(o, tw, g["sport"])} for o in opts]
    bo = max(olds, key=lambda o: o["p"] * o["est_old"] - 1)
    cmp = {"model1_old": {**bo, "ev": bo["p"] * bo["est_old"] - 1},
           "model1_new": {**max(opts, key=lambda o: o["ev"]), "est_old": next(o["est_old"] for o in olds if o["key"] == max(opts, key=lambda o: o["ev"])["key"])}}
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
    dr = draw_opts(g, tw)
    if dr:
        if dr[0][0]:
            out["draw_us"] = dr[0][0]
        out["draw"] = dr[0][1]
    out.update(cmp)
    return out, snap


TW_EV_STRATS = {"model1", "model1_new", "favorite", "underdog", "draw"}   # 這幾個策略的 ev＝台彩期望值（其他記的是美國期望值）


def backfill_compare(rows, sport, tw):
    """補記：過去（已開賽）的比賽，用記下來的熱門／冷門／和局三個選項，分別照舊估法、新估法重新挑邊。
    勝率＝模型一（和局＝1 − 主 − 客）；結算照那個選項記錄的台彩賠率（實際截圖或目前最準的估法）"""
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    n = 0
    for (gid, strat), r in list(rows.items()):
        if strat != "model1" or ((gid, "model1_old") in rows and (gid, "model1_new") in rows):
            continue
        fav, dog = rows.get((gid, "favorite")), rows.get((gid, "underdog"))
        if sport == "nhl" or not fav or not dog or num(fav.get("p")) is None or num(dog.get("p")) is None:
            for s in ("model1_old", "model1_new"):     # 冰球估法沒變：兩條都跟模型一一樣
                if (gid, s) not in rows:
                    rows[(gid, s)] = {**r, "strategy": s, "est_old": r.get("tw_odds", "")}
                    n += 1
            continue
        opts = [(num(fav["p"]), fav), (num(dog["p"]), dog)]
        dr = rows.get((gid, "draw"))
        if sport == "soccer" and dr:
            opts.append((max(0.0, 1 - opts[0][0] - opts[1][0]), dr))
        cand = []
        for p, o in opts:
            now = num(o.get("settle_odds")) or num(o.get("tw_odds"))
            if not now:
                continue
            old = now if o.get("tw_src") == "actual" or not num(o.get("us_odds")) else round(num(o["us_odds"]) * (1 + old_discount(tw, sport) / 100), 3)
            cand.append((p, now, old, o))
        if not cand:
            continue
        for s, key in (("model1_old", lambda c: c[0] * c[2]), ("model1_new", lambda c: c[0] * c[1])):
            if (gid, s) in rows:
                continue
            p, now, old, o = max(cand, key=key)
            rows[(gid, s)] = {**o, "strategy": s, "p": round(p, 4), "est_old": old,
                              "ev": round(p * (old if s == "model1_old" else now) - 1, 4)}
            n += 1
    return n


def reprice_est(rows, sport, tw, game_of=lambda gid: None):
    """估的台彩賠率照最新的估法重算（2026-10-26 起：從 Pinnacle＋bet365 基準估；獨贏加機率、讓分大小分照級距）。
    押哪一邊不變，只改估的台彩賠率、台彩期望值、已開獎那幾注的賺賠；實際截圖的賠率不動；冰球用自己的 60 分鐘算法，不動。"""
    if sport == "nhl":
        return 0
    n = 0
    for r in rows.values():
        if r.get("tw_src") != "est":
            continue
        try:
            us = float(r["us_odds"])
        except (TypeError, ValueError):
            continue
        if us <= 1:
            continue
        mkt, key, ln = (r["pick"].split("|") + ["", ""])[:3] if "|" in r["pick"] else ("ml", r["pick"], "")
        try:
            line = float(ln) if ln not in ("", None) else None
        except ValueError:
            line = None
        new = tw_from(game_of(r["game_id"]), tw, sport, mkt, key, us, line)
        if not new:
            continue
        try:
            if abs(float(r["tw_odds"]) - new) < 0.0005:
                continue
        except (TypeError, ValueError):
            pass
        r["tw_odds"] = new
        n += 1
        if r["strategy"] in TW_EV_STRATS:
            try:
                r["ev"] = round(float(r["p"]) * new - 1, 4)
            except (TypeError, ValueError):
                pass
        if r.get("result") in ("win", "loss", "push") and r.get("settle_src") == "est":
            r["settle_odds"] = new
            r["profit"] = round(new - 1, 4) if r["result"] == "win" else (0.0 if r["result"] == "push" else -1.0)
    return n


def settle(row, g):
    """回傳 (result, 結算賠率, 賠率來源, 賺賠)"""
    res = g["result"]
    w, pick = res.get("winner"), row["pick"]
    if row["strategy"] in TW_TWINS.values():   # 改去台彩下：冰球只算 60 分鐘；台彩不能下的記 void
        if row.get("tw_src") == "none" or not row.get("tw_odds"):
            return "void", "", "", 0.0
        mkt, key, ln = (pick.split("|") + ["", "", ""])[:3]
        odds, src = float(row["tw_odds"]), row["tw_src"] or "est"
        nhl = g["sport"] == "nhl"
        if mkt == "ml":
            wr = res.get("reg") if nhl else w
            if wr is None:
                return "void", "", "", 0.0
            if wr == "tie" and not nhl:
                return "push", odds, src, 0.0
            v = 1 if wr == key else -1          # 冰球 60 分鐘打平＝押哪隊都輸
        else:
            a, h, ln = float(res["away"]), float(res["home"]), float(ln)
            if mkt == "sp":
                d = (a - h if key == "away" else h - a) + ln
            else:
                tot = res.get("reg_total") if nhl else a + h
                if tot is None:
                    return "void", "", "", 0.0
                d = (tot - ln) if key == "over" else (ln - tot)
            v = (d > 0) - (d < 0)
        if v == 0:
            return "push", odds, src, 0.0
        return ("win" if v > 0 else "loss"), odds, src, round(odds - 1, 4) if v > 0 else -1.0
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
                           "result": "", "settle_odds": "", "settle_src": "", "profit": "", "est_old": o.get("est_old", "")}
                n_upd += bool(old)
                n_new += not old
                if strat in TW_TWINS:   # 同一注改去台彩下
                    rows[(g["id"], TW_TWINS[strat])] = twin_row(rows[k], g, tw)
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
        # 補記：足球都押和局（用每場開賽前最後的賠率）
        if sport in ("soccer", "nhl"):
            for (gid, strat), r in list(rows.items()):
                if strat != "favorite" or ((gid, "draw_us") in rows or sport == "nhl") and (gid, "draw") in rows:
                    continue
                g = finals.get((sport, gid)) or next((x for x in games if x["id"] == gid), None)
                dr = draw_opts(g, tw) if g else None
                if not dr:
                    continue
                for new_s, o in zip(("draw_us", "draw"), dr[0]):
                    if not o or (gid, new_s) in rows:
                        continue
                    rows.setdefault((gid, new_s), {**r, "strategy": new_s, "pick": "draw", "pick_zh": "和局", "p": round(o["p"], 4),
                                                   "mkt_p": round(o["m"], 4), "us_odds": o["us"], "tw_odds": o["tw"], "tw_src": o["src"],
                                                   "ev": round(o["ev"], 4), "result": "", "settle_odds": "", "settle_src": "", "profit": ""})
                    n_new += 1
        # 修正：以前的「台彩下」冰球那幾筆，勝率是含延長賽的，換成 60 分鐘的（只改 p，不動結算）
        for (gid, strat), r in list(rows.items()):
            if strat not in TW_TWINS or (gid, TW_TWINS[strat]) not in rows:
                continue
            t = rows[(gid, TW_TWINS[strat])]
            if sport == "nhl" and t.get("p") == r.get("p") and not r["pick"].startswith("sp"):
                g = finals.get((sport, gid)) or next((x for x in games if x["id"] == gid), None)
                pt = tw_prob(g, r["pick"], r["p"]) if g else None
                if pt is not None:
                    t["p"] = round(pt, 4)
        # 補記：已經有 _us、還沒有「台彩下」那一筆的比賽
        for (gid, strat), r in list(rows.items()):
            if strat not in TW_TWINS or (gid, TW_TWINS[strat]) in rows:
                continue
            g = finals.get((sport, gid)) or next((x for x in games if x["id"] == gid), None)
            if g:
                rows[(gid, TW_TWINS[strat])] = twin_row(r, g, tw)
                n_new += 1
        n_new += backfill_compare(rows, sport, tw)
        gidx = {g["id"]: g for g in games if g["sport"] == sport}
        n_rep = reprice_est(rows, sport, tw, lambda gid: finals.get((sport, gid)) or gidx.get(gid))
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
        print(f"  {sport}：新記錄 {n_new}、更新 {n_upd}、結算 {n_set}、重算估的台彩賠率 {n_rep}，共 {len(out)} 筆")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "mlb,nba,nfl,nhl"
    run([s for s in arg.split(",") if s])
