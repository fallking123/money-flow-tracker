"""
職業版・「下注規則」測試：直接問「照這個規則用開盤價下注，對收盤的期望值（CLV）是不是正的」
================================================================
這才是真的「打贏莊家」。通過標準（先訂好）：全部注的平均 CLV > 0，z ≥ 門檻（跟其他嘗試一起算次數），
而且 4 段裡至少 3 段 CLV > 0。
- MLB：獨贏，用 SBRO 開盤價，CLV＝收盤公平勝率 × 開盤賠率 − 1。
- NBA：讓分，用開盤讓分下注（−110 賠率），收盤時這注的勝率用常態分布估：Φ（收盤與開盤差幾分 ÷ 12），CLV＝勝率 × 1.909 − 1。
每個規則記在各運動的 search_log（kind＝rule）。
用法：python3 -m pro.rule_search mlb <規則…>  /  nba <規則…>
"""
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
from scipy.stats import norm

from pro import mlb_search as S

SIG = {"nba": 12.0, "nfl": 13.5}


def mlb_bets(cond, edge, extra_name=None):
    games, feats = S.base_features()
    fb = {f["game_id"]: f for f in feats}
    extra = {}
    if extra_name:
        from pro import mlb_candidates as C
        extra = C.CANDIDATES[extra_name]["fn"](games, feats)
    out = {}
    for blk in S.BLOCKS:
        bets = []
        for r in S.predict(feats, extra, blk):
            if not (r["pc"] and r["po"]) or abs(r["pc"] - r["po"]) >= S.CALM:
                continue
            f = fb[r["game_id"]]
            for p, pc, o in ((r["p"], r["pc"], r["oo_h"]), (1 - r["p"], 1 - r["pc"], r["oo_a"])):
                if p * o - 1 >= edge and cond(f):
                    bets.append(pc * o - 1)
        out[blk] = bets
    return out


def nba_bets(cond, dmin, sport="nba", extra_name=None):
    from pro import spread_search as SS
    games, feats, R = SS.base(sport)
    extra = SS.CANDIDATES[extra_name]["fn"](sport, feats) if extra_name else {}
    out = {}
    for blk in SS.CFG[sport]["blocks"]:
        bets = []
        for r in SS.predict(sport, feats, extra, blk, R.get("alpha", 5.0)):
            if r["so"] is None or abs(r["sc"] - r["so"]) >= SS.CFG[sport]["calm"]:
                continue
            d = r["pm"] - r["so"]
            if abs(d) >= dmin and cond(r["f"]):
                pw = norm.cdf(np.sign(d) * (r["sc"] - r["so"]) / SIG[sport])
                bets.append(pw * (1 + 100 / 110) - 1)
        out[blk] = bets
    return out


MONTH = lambda f, ms: f["date"][5:7] in ms
RULES = {
    "mlb": {
        "early_10": ("開季 3–5 月＋模型比開盤看好 ≥ 10%", "兩個已知的訊號合起來：開季模型比較有用、差很多時收盤移比較多",
                     lambda: mlb_bets(lambda f: MONTH(f, ("03", "04", "05")), 0.10)),
        "all_15": ("全季，模型比開盤看好 ≥ 15%", "只挑模型跟開盤差最多的",
                   lambda: mlb_bets(lambda f: True, 0.15)),
        "early_turn_5": ("開季 3–5 月＋加上「換很多人的隊」特徵＋看好 ≥ 5%", "差一點通過的特徵，只用在它應該有用的開季",
                         lambda: mlb_bets(lambda f: MONTH(f, ("03", "04", "05")), 0.05, "turnover_early")),
    },
    "nba": {
        "early_3": ("開季 10–11 月＋模型跟開盤讓分差 ≥ 3 分", "開季收盤往模型移最多，再只挑差很多的",
                    lambda: nba_bets(lambda f: MONTH(f, ("10", "11")), 3.0)),
        "all_4": ("全季，模型跟開盤讓分差 ≥ 4 分", "只挑差最多的", lambda: nba_bets(lambda f: True, 4.0)),
        "early_tank_3": ("開季 10–11 月或後段擺爛隊特徵＋差 ≥ 3 分", "兩個通過的訊號一起用",
                         lambda: nba_bets(lambda f: MONTH(f, ("10", "11", "02", "03", "04")), 3.0, extra_name="tank")),
    },
}


def main(sport, names):
    log_path = S.LOG if sport == "mlb" else os.path.join(S.OUT, f"search_log_{sport}.json")
    log = json.load(open(log_path, encoding="utf-8"))
    for nm in names:
        label, why, fn = RULES[sport][nm]
        per = fn()
        res = {"blocks": [], "better_blocks": 0}
        allb = []
        for blk, b in per.items():
            allb += b
            m = float(np.mean(b)) if b else 0.0
            res["blocks"].append({"seasons": f"{blk[0]}–{blk[1]}", "n": len(b), "clv": round(m, 4),
                                  "se": round(float(np.std(b) / math.sqrt(len(b))), 4) if len(b) > 1 else None})
            res["better_blocks"] += int(m > 0)
        a = np.array(allb)
        res["z"] = round(float(a.mean() / (a.std() / math.sqrt(len(a)))), 2) if len(a) > 1 else 0.0
        res["clv_all"] = [round(float(a.mean()), 4), round(float(a.std() / math.sqrt(len(a))), 4), len(a)]
        n = len(log["tries"]) + 1
        thr = S.threshold(n)
        ok = res["z"] >= thr and res["better_blocks"] >= 3
        log["tries"].append({"n": n, "name": "rule_" + nm, "kind": "rule", "label": label, "why": why,
                             "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "z_needed": thr, "pass": ok, **res})
        json.dump(log, open(log_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"#{n} {nm}：CLV {res['clv_all']}，z={res['z']}（門檻 {thr}），{res['better_blocks']}/4 段正的 → {'打贏' if ok else '沒有'}", flush=True)
        for b in res["blocks"]:
            print("   ", b, flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
