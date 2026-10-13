"""
職業版・足球特徵搜尋（練習區），做法跟 MLB 一樣
================================================================
- 基本模型：第 1 階段的比分模型（只看比分、射正），每場的主／和／客機率（soccer_preds_all.csv.gz）。
- 「早盤」＝Pinnacle 賽前 2–3 天，「收盤」＝Pinnacle 收盤。成績：用早盤＋b×（模型−早盤）預測收盤，誤差少多少。
  （用「主勝 − 客勝」機率差當一個數字）
- 第二層：多類別羅吉斯迴歸（主／和／客），輸入＝模型的兩個對數比＋候選特徵，每季只用之前的季學。
- 練習區 2016/17–2024/25（2025/26 起是考試，不看），切 4 段。通過標準、門檻跟 MLB 一樣（試越多門檻越高）。
- 每次嘗試記在 docs/data/pro/search_log_soccer.json。
用法：python3 -m pro.soccer_search <候選…>
"""
import csv
import gzip
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from sklearn.linear_model import LogisticRegression

from pro import mlb_search as S
from pro import soccer_model as SM

OUT = SM.OUT
LOG = os.path.join(OUT, "search_log_soccer.json")
BLOCKS = [("2016", "2018"), ("2018", "2020"), ("2020", "2022"), ("2022", "2025")]     # 季的開始年 [a, b)
CALM = 0.08


def season_of(dt):
    return dt.year if dt.month >= 7 else dt.year - 1


def load():
    rows = SM.load()
    key = {(r["div"], r["dt"].strftime("%Y-%m-%d %H:%M"), r["home"]): r for r in rows}
    preds = []
    with gzip.open(os.path.join(OUT, "soccer_preds_all.csv.gz"), "rt", encoding="utf-8") as f:
        for p in csv.DictReader(f):
            r = key.get((p["div"], p["date"], p["home"]))
            if not r:
                continue
            ps, pc = SM.fair(r["ps"]), SM.fair(r["psc"])
            preds.append({"m": r, "ss": season_of(r["dt"]), "p": [float(p["p_h"]), float(p["p_d"]), float(p["p_a"])],
                          "y": 0 if r["hg"] > r["ag"] else 1 if r["hg"] == r["ag"] else 2, "po": ps, "pc": pc, "odds": r["ps"]})
    return rows, preds


def predict(preds, extra, lo, hi):
    def x(p):
        b = [math.log(p["p"][0] / p["p"][1]), math.log(p["p"][2] / p["p"][1])]
        return b + (extra.get(id(p["m"]), [0.0] * K) if K else [])
    K = len(next(iter(extra.values()))) if extra else 0
    out = []
    for s in range(lo, hi):
        tr = [p for p in preds if 2015 <= p["ss"] < s]
        te = [p for p in preds if p["ss"] == s]
        if len(tr) < 2000 or not te:
            continue
        A = np.array([x(p) for p in tr])
        mu, sd = A.mean(0), A.std(0) + 1e-9
        lr = LogisticRegression(C=1.0, max_iter=3000).fit((A - mu) / sd, [p["y"] for p in tr])
        P = lr.predict_proba((np.array([x(p) for p in te]) - mu) / sd)
        for p, q in zip(te, P):
            out.append({**p, "q": [float(v) for v in q]})
    return out


def score(rows):
    rs = [r for r in rows if r["po"] and r["pc"] and abs((r["pc"][0] - r["pc"][2]) - (r["po"][0] - r["po"][2])) < CALM]
    d = np.array([(r["q"][0] - r["q"][2]) - (r["po"][0] - r["po"][2]) for r in rs])
    m = np.array([(r["pc"][0] - r["pc"][2]) - (r["po"][0] - r["po"][2]) for r in rs])
    b = float(d @ m / (d @ d)) if len(rs) else 0.0
    clv = [r["pc"][k] * r["odds"][k] - 1 for r in rs for k in range(3) if r["q"][k] * r["odds"][k] - 1 >= 0.05]
    ll = {id(r["m"]): -math.log(r["q"][r["y"]]) for r in rows}
    return {"ids": [id(r["m"]) for r in rs], "err": (m - b * d) ** 2, "b": b, "n": len(rs),
            "clv": (float(np.mean(clv)), float(np.std(clv) / math.sqrt(len(clv))) if len(clv) > 1 else None, len(clv)),
            "ll_each": ll}


def blocks(preds, extra):
    return {blk: score(predict(preds, extra, int(blk[0]), int(blk[1]))) for blk in BLOCKS}


# ─────────── 候選特徵（只用比賽之前就知道的）───────────
def _by_team(rows):
    t = defaultdict(list)
    for r in rows:
        t[(r["div"], r["season"], r["home"])].append(r)
        t[(r["div"], r["season"], r["away"])].append(r)
    return t


def rest(rows, preds):
    """離上一場聯賽幾天（最多算 14 天）、兩隊是否都在 4 天內踢過"""
    last = {}
    out = {}
    for r in rows:
        v = {}
        for side in ("home", "away"):
            pv = last.get(r[side])
            v[side] = min((r["dt"] - pv).days, 14) if pv else 7
        out[id(r)] = [v["home"] - v["away"], float(v["home"] <= 3) - float(v["away"] <= 3)]
        last[r["home"]] = last[r["away"]] = r["dt"]
    return out


def motivation(rows, preds):
    """球季最後階段（剩 ≤ 8 場）：已經沒有目標（拿不到前 4、也不會降級）的隊；還在保級的隊"""
    total = defaultdict(int)
    for r in rows:
        total[(r["div"], r["season"], r["home"])] += 1
        total[(r["div"], r["season"], r["away"])] += 1
    pts, played = defaultdict(int), defaultdict(int)
    out = {}
    for r in rows:
        k = (r["div"], r["season"])
        teams = [t for (d, s, t) in total if (d, s) == k] if k not in motivation.cache else motivation.cache[k]
        motivation.cache[k] = teams
        table = sorted((pts[(k, t)] for t in teams), reverse=True)
        v = {}
        for side in ("home", "away"):
            t = r[side]
            rem = total[(r["div"], r["season"], t)] - played[(k, t)]
            if rem > 8 or len(table) < 10:
                v[side] = (0.0, 0.0)
                continue
            p = pts[(k, t)]
            fourth, drop = table[3], table[-4]
            dead = p + 3 * rem < fourth and p - drop > 3 * rem
            fight = (p - drop) <= 3 and p < table[len(table) // 2]
            v[side] = (float(dead), float(fight))
        out[id(r)] = [v["home"][0] - v["away"][0], v["home"][1] - v["away"][1]]
        h, a = (3, 0) if r["hg"] > r["ag"] else (1, 1) if r["hg"] == r["ag"] else (0, 3)
        pts[(k, r["home"])] += h
        pts[(k, r["away"])] += a
        played[(k, r["home"])] += 1
        played[(k, r["away"])] += 1
    return out


motivation.cache = {}


def promoted_early(rows, preds):
    """剛升級的隊，這季前 10 場"""
    fl = SM.season_flags(rows)
    played = defaultdict(int)
    out = {}
    for r in rows:
        v = {}
        for side in ("home", "away"):
            k = (r[side], r["season"])
            v[side] = float(fl.get(k, (0, 0, 0))[0] == 1 and played[k] < 10)
        out[id(r)] = [v["home"] - v["away"]]
        played[(r["home"], r["season"])] += 1
        played[(r["away"], r["season"])] += 1
    return out


CANDIDATES = {
    "rest": {"fn": rest, "label": "休息天數", "why": "賽程密（一週兩賽）比較累；早盤可能沒完全算進去"},
    "motivation": {"fn": motivation, "label": "球季末的戰意（沒有目標／還在保級）",
                   "why": "球季最後幾場，已經沒有目標的隊可能放水、還在保級的隊特別拚；職業圈常用，早盤可能低估"},
    "promoted_early": {"fn": promoted_early, "label": "剛升級的隊，開季前 10 場",
                       "why": "莊家和模型都只能用低一級聯賽的數據，剛開季最不準"},
}
SEG = {
    "early": ("開季前兩個月（8、9 月）", "跟 MLB 一樣：開季時莊家還靠去年的數據", lambda r: r["m"]["dt"].month in (7, 8, 9)),
    "div2": ("二級聯賽（英冠、西乙、義乙、德乙、法乙）", "關注的人少、下注的錢少，市場可能比較不準", lambda r: r["m"]["div"] in ("E1", "SP2", "I2", "D2", "F2")),
    "midweek": ("週中比賽（週二到週四）", "週中比賽常常輪換主力，早盤可能沒算到", lambda r: r["m"]["dt"].weekday() in (1, 2, 3)),
}


def load_log():
    return json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else {"sport": "soccer", "tries": []}


def log_try(log, entry):
    n = len(log["tries"]) + 1
    thr = S.threshold(n)
    ok = entry["z"] >= thr and entry["better_blocks"] >= 3
    log["tries"].append({"n": n, "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "z_needed": thr, "pass": ok, **entry})
    json.dump(log, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"#{n} {entry['name']}：z={entry['z']}（門檻 {thr}），{entry['better_blocks']}/4 段 → {'通過' if ok else '沒通過'}", flush=True)
    for b in entry["blocks"]:
        print("   ", b, flush=True)


def seg_eval(base, fn):
    res = {"blocks": [], "better_blocks": 0}
    ai, ao = [], []
    for blk, rows in base.items():
        ins, outs = [], []
        for r in rows:
            if not (r["po"] and r["pc"]) or abs((r["pc"][0] - r["pc"][2]) - (r["po"][0] - r["po"][2])) >= CALM:
                continue
            for k in range(3):
                if r["q"][k] * r["odds"][k] - 1 >= 0.05:
                    (ins if fn(r) else outs).append(r["pc"][k] * r["odds"][k] - 1)
        ai += ins
        ao += outs
        res["blocks"].append({"seasons": f"{blk[0]}–{int(blk[1]) - 1}", "n_in": len(ins), "clv_in": round(float(np.mean(ins)), 4) if ins else None,
                              "n_out": len(outs), "clv_out": round(float(np.mean(outs)), 4) if outs else None})
        res["better_blocks"] += int(bool(ins and outs) and np.mean(ins) > np.mean(outs))
    a, b = np.array(ai), np.array(ao)
    res["z"] = round(float((a.mean() - b.mean()) / math.sqrt(a.var() / len(a) + b.var() / len(b))), 2)
    res["clv_in_all"] = [round(float(a.mean()), 4), round(float(a.std() / math.sqrt(len(a))), 4), len(a)]
    res["clv_out_all"] = [round(float(b.mean()), 4), len(b)]
    return res


def main(names):
    rows, preds = load()
    print(f"足球：{len(preds)} 場有模型預測", flush=True)
    log = load_log()
    base_rows = {blk: predict(preds, {}, int(blk[0]), int(blk[1])) for blk in BLOCKS}
    base = {blk: score(v) for blk, v in base_rows.items()}
    if "--base" in names:
        for k, v in base.items():
            print(k, v["n"], round(v["b"], 3), v["clv"])
        return
    for nm in names:
        if nm.startswith("seg_"):
            label, why, fn = SEG[nm[4:]]
            log_try(log, {"name": nm, "kind": "segment", "label": label, "why": why, **seg_eval(base_rows, fn)})
            continue
        c = CANDIDATES[nm]
        extra = c["fn"](rows, preds)
        res = S.compare(base, blocks(preds, extra), BLOCKS)
        log_try(log, {"name": nm, "kind": "1x2", "label": c["label"], "why": c["why"], **res})


if __name__ == "__main__":
    main(sys.argv[1:])
