"""
職業版・NHL 特徵搜尋與下注規則（練習區）
================================================================
- SBRO 冰球盤口：2007-08～2013-14 欄位錯位（兩邊機率加起來約 197%），不能用；2014-15 起正常 → 練習區 2014-15～2022-23。
  （以前說「SBRO 冰球盤口壞了」，其實只壞前 7 季。）每場再檢查一次：開盤、收盤兩邊加起來要在 100–110%。
- 基本模型＝NHL 第 2 版「開盤版」（上一場名單、守門員用猜的），第二層羅吉斯迴歸，每季只用之前的季學。
- 成績、通過標準跟 MLB 一樣；美國冰球獨贏含延長賽。紀錄 docs/data/pro/search_log_nhl.json。
用法：python3 -m pro.nhl_search <候選或規則…>
"""
import json
import math
import os
import pickle
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from sklearn.linear_model import LogisticRegression

from pro import mlb_search as S
from pro import us_eval as E

OUT = S.OUT
LOG = os.path.join(OUT, "search_log_nhl.json")
BLOCKS = [(2014, 2015), (2016, 2017), (2018, 2019), (2020, 2022)]       # MoneyPuck 季別＝開始那一年
CALM = 0.08
EDGE_MAX = 0.30


def base():
    p = os.path.join(os.environ.get("PRO_CACHE", "/tmp"), "nhl_base_prev.pkl")
    if os.path.exists(p):
        return pickle.load(open(p, "rb"))
    from pro import nhl_player_model as NH
    R = json.load(open(os.path.join(OUT, "us_report.json"), encoding="utf-8"))["nhl2"]["chosen"]
    games = NH.V1.load()
    feats = NH.features(games, NH.load_players(), {**R, "lineup": "prev"}, NH.v1_features(games))
    for f in feats:
        ok = f["oo_h"] and f["oc_h"] and f.get("src") == "sbro" and f["season"] >= 2014
        if ok:
            so, sc = 1 / f["oo_h"] + 1 / f["oo_a"], 1 / f["oc_h"] + 1 / f["oc_a"]
            ok = 1.0 <= so <= 1.10 and 1.0 <= sc <= 1.10
        f["use"] = bool(ok)
    pickle.dump((games, feats), open(p, "wb"))
    return games, feats


def predict(feats, extra, seasons):
    K = len(next(iter(extra.values()))) if extra else 0
    X = lambda f: np.array(list(f["x"]) + (extra.get(f["game_id"], [0.0] * K) if K else []))
    out = []
    for s in range(seasons[0], seasons[1] + 1):
        tr = [f for f in feats if 2011 <= f["season"] < s and f["y"] is not None]
        te = [f for f in feats if f["season"] == s and f["y"] is not None]
        if len(tr) < 3000 or not te:
            continue
        A = np.array([X(f) for f in tr])
        mu, sd = A.mean(0), A.std(0) + 1e-9
        lr = LogisticRegression(C=1.0, max_iter=2000).fit((A - mu) / sd, [f["y"] for f in tr])
        P = lr.predict_proba((np.array([X(f) for f in te]) - mu) / sd)[:, 1]
        for f, p in zip(te, P):
            u = f["use"]
            out.append({"game_id": f["game_id"], "season": s, "p": float(p), "y": f["y"], "f": f,
                        "po": E.devig2(f["oo_h"], f["oo_a"]) if u else None, "pc": E.devig2(f["oc_h"], f["oc_a"]) if u else None,
                        "oo_h": f["oo_h"], "oo_a": f["oo_a"]})
    return out


def score(preds):
    rs = [r for r in preds if r["po"] and abs(r["pc"] - r["po"]) < CALM]
    d = np.array([r["p"] - r["po"] for r in rs])
    m = np.array([r["pc"] - r["po"] for r in rs])
    b = float(d @ m / (d @ d)) if len(rs) else 0.0
    clv = [pc * o - 1 for r in rs for p, pc, o in ((r["p"], r["pc"], r["oo_h"]), (1 - r["p"], 1 - r["pc"], r["oo_a"])) if p * o - 1 >= 0.05]
    return {"ids": [r["game_id"] for r in rs], "err": (m - b * d) ** 2, "b": b, "n": len(rs),
            "clv": (float(np.mean(clv)) if clv else 0.0, float(np.std(clv) / math.sqrt(len(clv))) if len(clv) > 1 else None, len(clv)),
            "ll_each": {r["game_id"]: -math.log(r["p"] if r["y"] else 1 - r["p"]) for r in preds}}


def rule(feats, edge, cond=lambda f: True, extra=None):
    out = {}
    for blk in BLOCKS:
        b = []
        for r in predict(feats, extra or {}, blk):
            # 10/15 地基檢查後：不再排除「之後盤口大移動」的比賽（那是偷看未來）；改用下注當下就知道的條件：
            # 開盤兩邊一樣（佔位價）不下、模型比開盤多看好 > 30%（像資料錯）不下。見 audit_clean.json
            if not r["po"] or abs(r["oo_h"] - r["oo_a"]) < 1e-9 or not cond(r["f"]):
                continue
            for p, pc, o in ((r["p"], r["pc"], r["oo_h"]), (1 - r["p"], 1 - r["pc"], r["oo_a"])):
                if edge <= p * o - 1 <= EDGE_MAX:
                    b.append(pc * o - 1)
        out[blk] = b
    return out


def early(games, feats):
    st = {}
    for f in feats:
        st[f["season"]] = min(st.get(f["season"], f["dt"]), f["dt"])
    return {f["game_id"]: [float((f["dt"] - st[f["season"]]).days <= 45)] for f in feats}


TZ = {**{t: -6 for t in ("CHI", "DAL", "MIN", "NSH", "STL", "WPG")}, **{t: -7 for t in ("COL", "UTA", "ARI", "CGY", "EDM")},
      **{t: -8 for t in ("ANA", "LAK", "SJS", "SEA", "VAN", "VGK")}}


def sched(games, feats):
    """跨時區飛行、4 天 3 賽、客場連戰（冰球體力消耗大）"""
    hist = defaultdict(list)
    out = {}
    for f in sorted(feats, key=lambda f: f["dt"]):
        tz = TZ.get(f["h"], -5)
        v = {}
        for side in ("h", "a"):
            h = hist[f[side]]
            last = h[-1] if h else None
            in4 = sum(1 for d, _, _ in h if 0 < (f["dt"] - d).days <= 3)
            road = sum(1 for d, _, aw in h if 0 < (f["dt"] - d).days <= 7 and aw)
            v[side] = [abs(tz - last[1]) if last else 0, float(in4 >= 2), road]
        out[f["game_id"]] = [a - b for a, b in zip(v["h"], v["a"])]
        hist[f["h"]].append((f["dt"], tz, False))
        hist[f["a"]].append((f["dt"], tz, True))
    return out


RULES = {
    "sched_15": ("加上賽程（跨時區、4 天 3 賽、客場連戰）＋看好 ≥ 15%", "冰球體力消耗大，長途客場和密集賽程開盤可能沒算夠",
                 lambda F: rule(F, 0.15, extra=sched(None, F))),
    "edge_10": ("模型比開盤多看好 ≥ 10%", "跟 MLB 一樣：只挑跟開盤差很多的", lambda F: rule(F, 0.10)),
    "edge_15": ("模型比開盤多看好 ≥ 15%", "MLB 打贏莊家的同一條規則", lambda F: rule(F, 0.15)),
    "edge_15_clean": ("看好 15%–30%（地基檢查後的乾淨算法）", "重算同一條規則：不再用未來挑比賽，改排除佔位價和差太多的", lambda F: rule(F, 0.15)),
    "sched_15_clean": ("賽程＋看好 15%–30%（乾淨算法）", "冰球體力消耗大，長途客場和密集賽程開盤可能沒算夠", lambda F: rule(F, 0.15, extra=sched(None, F))),
    "edge_20_clean": ("看好 20%–30%（乾淨算法）", "只挑更確定的，看注數少了以後每注是不是更好", lambda F: rule(F, 0.20)),
    "early_10": ("開季 45 天內＋看好 ≥ 10%", "開季時莊家資料最少（MLB、NBA、足球都有這個現象）",
                 lambda F: rule(F, 0.10, lambda f: f["dt"].month in (10, 11))),
}


def main(names):
    games, feats = base()
    log = json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else {"sport": "nhl", "tries": []}
    if "--base" in names:
        for blk in BLOCKS:
            s = score(predict(feats, {}, blk))
            print(blk, s["n"], round(s["b"], 3), s["clv"])
        return
    for nm in names:
        label, why, fn = RULES[nm]
        per = fn(feats)
        res = {"blocks": [], "better_blocks": 0}
        allb = []
        for blk, b in per.items():
            allb += b
            m = float(np.mean(b)) if b else 0.0
            res["blocks"].append({"seasons": f"{blk[0]}–{blk[1]}", "n": len(b), "clv": round(m, 4)})
            res["better_blocks"] += int(m > 0)
        a = np.array(allb)
        res["z"] = round(float(a.mean() / (a.std() / math.sqrt(len(a)))), 2) if len(a) > 1 else 0.0
        res["clv_all"] = [round(float(a.mean()), 4), round(float(a.std() / math.sqrt(len(a))), 4), len(a)]
        w = np.clip(a, -0.1, 0.1)               # 截掉極端值（防止少數資料錯拉高平均）
        res["robust"] = {"median": round(float(np.median(a)), 4), "beat_close": round(float((a > 0).mean()), 3),
                         "trimmed": round(float(w.mean()), 4), "z_trimmed": round(float(w.mean() / (w.std() / math.sqrt(len(w)))), 2)}
        res["z"] = min(res["z"], res["robust"]["z_trimmed"])     # 兩種算法取比較差的那個
        n = len(log["tries"]) + 1
        thr = S.threshold(n)
        ok = res["z"] >= thr and res["better_blocks"] >= 3
        log["tries"].append({"n": n, "name": "rule_" + nm, "kind": "rule", "label": label, "why": why,
                             "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "z_needed": thr, "pass": ok, **res})
        json.dump(log, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"#{n} {nm}：CLV {res['clv_all']}，z={res['z']}（門檻 {thr}），{res['better_blocks']}/4 段 → {'打贏' if ok else '沒有'}", flush=True)
        for b in res["blocks"]:
            print("   ", b, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
