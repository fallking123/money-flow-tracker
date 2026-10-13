"""
職業版・「開盤＋我們的模型」合起來，離收盤（莊家最準的價錢）還差多少
================================================================
合併的比例用「其他年份」學、套到這一段（不在同一批比賽上學），所以不偷看。
- MLB、足球：預測勝負機率，比 log loss（越小越準）。
- NBA、NFL：預測分差，比平均誤差（分）。
「追上收盤」＝從開盤到收盤的距離，合併後走了幾成；100% 以上＝比收盤還準。
輸出 docs/data/pro/combo_report.json
"""
import json
import math
import os

import numpy as np
from scipy.optimize import minimize

from pro import mlb_search as S

OUT = S.OUT


def lg(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def fit_w(rows):
    """y ~ sigmoid(a·logit(開盤) + b·logit(模型))"""
    X = np.array([[lg(r[0]), lg(r[1])] for r in rows])
    y = np.array([r[2] for r in rows])

    def nll(w):
        z = X @ w
        return float(np.mean(np.log1p(np.exp(-z)) * y + np.log1p(np.exp(z)) * (1 - y)))
    return minimize(nll, [1.0, 0.0]).x


def mlb():
    games, feats = S.base_features()
    per = {}
    for blk in S.BLOCKS:
        per[blk] = [(r["po"], r["p"], r["y"], r["pc"]) for r in S.predict(feats, {}, blk) if r["po"] and r["pc"]]
    res = []
    for blk, rows in per.items():
        other = [x for b, rr in per.items() if b != blk for x in rr]
        w = fit_w(other)
        ll = lambda p, y: -math.log(p if y else 1 - p)
        lo = np.mean([ll(r[0], r[2]) for r in rows])
        lc = np.mean([ll(r[3], r[2]) for r in rows])
        lm = np.mean([ll(r[1], r[2]) for r in rows])
        lx = np.mean([ll(1 / (1 + math.exp(-(w[0] * lg(r[0]) + w[1] * lg(r[1])))), r[2]) for r in rows])
        res.append({"seasons": f"{blk[0]}–{blk[1]}", "n": len(rows), "open": round(lo, 5), "close": round(lc, 5), "model": round(lm, 5),
                    "combo": round(lx, 5), "w_model": round(float(w[1]), 3), "catch": round((lo - lx) / (lo - lc) * 100, 1)})
    return res


def spread(sport):
    from pro import spread_search as SS
    games, feats, R = SS.base(sport)
    per = {blk: [r for r in SS.predict(sport, feats, {}, blk, R.get("alpha", 5.0)) if r["so"] is not None] for blk in SS.CFG[sport]["blocks"]}
    res = []
    for blk, rows in per.items():
        other = [r for b, rr in per.items() if b != blk for r in rr]
        d = np.array([r["pm"] - r["so"] for r in other])
        e = np.array([r["margin"] - r["so"] for r in other])
        w = float(d @ e / (d @ d))
        mae = lambda f: float(np.mean([abs(r["margin"] - f(r)) for r in rows]))
        mo, mc, mm = mae(lambda r: r["so"]), mae(lambda r: r["sc"]), mae(lambda r: r["pm"])
        mx = mae(lambda r: r["so"] + w * (r["pm"] - r["so"]))
        res.append({"seasons": f"{blk[0]}–{blk[1]}", "n": len(rows), "open": round(mo, 3), "close": round(mc, 3), "model": round(mm, 3),
                    "combo": round(mx, 3), "w_model": round(w, 3), "catch": round((mo - mx) / (mo - mc) * 100, 1) if mo != mc else None})
    return res


def soccer():
    from pro import soccer_search as SC
    rows, preds = SC.load()
    per = {}
    for blk in SC.BLOCKS:
        per[blk] = [p for p in SC.predict(preds, {}, int(blk[0]), int(blk[1])) if p["po"] and p["pc"]]
    from sklearn.linear_model import LogisticRegression
    x = lambda p: [math.log(p["po"][0] / p["po"][1]), math.log(p["po"][2] / p["po"][1]), math.log(p["q"][0] / p["q"][1]), math.log(p["q"][2] / p["q"][1])]
    res = []
    for blk, rr in per.items():
        other = [p for b, v in per.items() if b != blk for p in v]
        m = LogisticRegression(C=10.0, max_iter=3000).fit([x(p) for p in other], [p["y"] for p in other])
        P = m.predict_proba([x(p) for p in rr])
        L = lambda q, y: -math.log(q[y])
        lo = np.mean([L(p["po"], p["y"]) for p in rr])
        lc = np.mean([L(p["pc"], p["y"]) for p in rr])
        lm = np.mean([L(p["q"], p["y"]) for p in rr])
        lx = np.mean([L(q, p["y"]) for p, q in zip(rr, P)])
        res.append({"seasons": f"{blk[0]}–{int(blk[1]) - 1}", "n": len(rr), "open": round(lo, 5), "close": round(lc, 5), "model": round(lm, 5),
                    "combo": round(lx, 5), "catch": round((lo - lx) / (lo - lc) * 100, 1)})
    return res


if __name__ == "__main__":
    rep = {"mlb": mlb(), "nba": spread("nba"), "nfl": spread("nfl"), "soccer": soccer()}
    json.dump(rep, open(os.path.join(OUT, "combo_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, v in rep.items():
        print(k)
        for b in v:
            print("   ", b)
