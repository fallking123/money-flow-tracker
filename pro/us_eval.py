"""
職業版・美國運動共用：隊伍評分（加權嶺迴歸）、成績單（跟收盤比、混合、CLV、讓分／大小）
"""
import math

import numpy as np
from scipy.optimize import minimize


def ridge_ratings(off_idx, def_idx, home, y, w, n_teams, ridge):
    """y ≈ mu + off[off_idx] − def[def_idx] + h·home；w＝權重（已含時間衰減）；回傳 mu, off, def, h
    （加權最小平方＋往 0 拉；n_teams 很小，直接解正規方程）"""
    n = len(y)
    P = 2 * n_teams + 2
    X = np.zeros((n, P))
    X[:, 0] = 1
    X[np.arange(n), 1 + off_idx] = 1
    X[np.arange(n), 1 + n_teams + def_idx] = -1
    X[:, -1] = home
    W = w
    A = X.T @ (X * W[:, None])
    reg = np.full(P, ridge)
    reg[0] = reg[-1] = 1e-6
    A[np.diag_indices(P)] += reg
    b = X.T @ (W * y)
    beta = np.linalg.solve(A, b)
    return beta[0], beta[1:1 + n_teams], beta[1 + n_teams:1 + 2 * n_teams], beta[-1]


def devig2(oh, oa):
    if not oh or not oa or oh <= 1 or oa <= 1:
        return None
    ih, ia = 1 / oh, 1 / oa
    return ih / (ih + ia)


def american(x):
    try:
        a = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(a) or abs(a) < 100:
        return None
    return 1 + a / 100 if a > 0 else 1 + 100 / -a


def ll2(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -math.log(p if y else 1 - p)


def ms(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    m = float(np.mean(xs))
    se = float(np.std(xs, ddof=1) / math.sqrt(len(xs))) if len(xs) > 1 else None
    return [round(m, 5), round(se, 5) if se is not None else None, len(xs)]


def blend_fit(pm, pk, y):
    lm, lk = np.log(pm / (1 - pm)), np.log(pk / (1 - pk))

    def f(ab):
        z = ab[0] * lk + ab[1] * lm
        p = 1 / (1 + np.exp(-z))
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    r = minimize(f, [1.0, 0.0], method="Nelder-Mead")
    return [float(r.x[0]), float(r.x[1])]


def ml_eval(rows, blend=None):
    """rows：每場 {p: 模型主勝機率, y: 主隊贏(1/0), pc: 收盤公平主勝, po: 開盤公平主勝(可無), oc_h, oc_a, oo_h, oo_a: 十進位賠率}"""
    rs = [r for r in rows if r.get("pc") is not None and r["y"] is not None]
    if not rs:
        return None
    y = np.array([r["y"] for r in rs], float)
    pm = np.clip(np.array([r["p"] for r in rs]), 1e-4, 1 - 1e-4)
    pk = np.clip(np.array([r["pc"] for r in rs]), 1e-4, 1 - 1e-4)
    base = y.mean()
    llm = float(np.mean([ll2(p, t) for p, t in zip(pm, y)]))
    llk = float(np.mean([ll2(p, t) for p, t in zip(pk, y)]))
    llb = float(np.mean([ll2(base, t) for t in y]))
    po = [r for r in rs if r.get("po") is not None]
    llo = float(np.mean([ll2(r["po"], r["y"]) for r in po])) if po else None
    llo_c = float(np.mean([ll2(r["pc"], r["y"]) for r in po])) if po else None
    llo_m = float(np.mean([ll2(r["p"], r["y"]) for r in po])) if po else None
    ab = blend or blend_fit(pm, pk, y)
    z = ab[0] * np.log(pk / (1 - pk)) + ab[1] * np.log(pm / (1 - pm))
    pmix = np.clip(1 / (1 + np.exp(-z)), 1e-6, 1 - 1e-6)
    dif = np.array([ll2(a, t) - ll2(b, t) for a, b, t in zip(pk, pmix, y)])     # 正＝混合比較好
    out = {"n": len(rs), "ll_model": round(llm, 5), "ll_close": round(llk, 5), "ll_base": round(llb, 5),
           "n_open": len(po), "ll_open": round(llo, 5) if llo else None, "ll_close_o": round(llo_c, 5) if llo_c else None,
           "ll_model_o": round(llo_m, 5) if llo_m else None,
           "blend": {"a": round(ab[0], 3), "b": round(ab[1], 3), "gain": round(float(dif.mean()), 5), "se": round(float(dif.std(ddof=1) / math.sqrt(len(dif))), 5)},
           "calib": calib(pm, y)}
    out["clv"] = clv(rs)
    out["roi_close"] = roi_close(rs)
    return out


def calib(p, y):
    out = []
    for lo in np.arange(0, 1, 0.1):
        m = (p >= lo) & (p < lo + 0.1)
        if m.sum() >= 30:
            out.append({"bin": f"{int(lo * 100)}–{int(lo * 100 + 10)}%", "n": int(m.sum()), "pred": round(float(p[m].mean() * 100), 1),
                        "real": round(float(y[m].mean() * 100), 1)})
    return out


def clv(rs):
    """用開盤賠率下注：模型勝率 × 開盤賠率 − 1 ≥ 門檻 → 收盤有沒有往這邊移（dp）、CLV（開盤賠率 × 收盤公平勝率 − 1）、實際投報率"""
    out = {}
    pool = [r for r in rs if r.get("po") is not None and r.get("oo_h") and r.get("oo_a")]
    if not pool:
        return out
    for th in (0.0, 0.03, 0.05, 0.10):
        dp, cl, roi = [], [], []
        for r in pool:
            for side, p, po, pc, o in (("h", r["p"], r["po"], r["pc"], r["oo_h"]), ("a", 1 - r["p"], 1 - r["po"], 1 - r["pc"], r["oo_a"])):
                ev = p * o - 1
                if ev < th or ev > 1:
                    continue
                dp.append(pc - po)
                cl.append(o * pc - 1)
                won = r["y"] if side == "h" else 1 - r["y"]
                roi.append(o - 1 if won else -1)
        if dp:
            out[str(th)] = {"n": len(dp), "dp": ms(dp), "clv": ms(cl), "roi": ms(roi),
                            "toward": round(sum(x > 0.002 for x in dp) / len(dp), 3), "away": round(sum(x < -0.002 for x in dp) / len(dp), 3)}
    # 穩健檢查：排除開盤到收盤大動（≥ 8 個百分點，常是臨時換先發、傷兵等「開盤時還不知道」的事）的比賽，結果還在才算數
    calm = [r for r in pool if abs(r["pc"] - r["po"]) < 0.08]
    for th in (0.0, 0.03, 0.05, 0.10):
        dp, cl, roi = [], [], []
        for r in calm:
            for side, p, po, pc, o in (("h", r["p"], r["po"], r["pc"], r["oo_h"]), ("a", 1 - r["p"], 1 - r["po"], 1 - r["pc"], r["oo_a"])):
                if th <= p * o - 1 <= 1:
                    dp.append(pc - po)
                    cl.append(o * pc - 1)
                    won = r["y"] if side == "h" else 1 - r["y"]
                    roi.append(o - 1 if won else -1)
        if dp:
            out["calm_" + str(th)] = {"n": len(dp), "dp": ms(dp), "clv": ms(cl), "roi": ms(roi), "toward": round(sum(x > 0.002 for x in dp) / len(dp), 3),
                                      "away": round(sum(x < -0.002 for x in dp) / len(dp), 3), "excluded_games": len(pool) - len(calm)}
    x = np.array([r["p"] - r["po"] for r in pool])
    yy = np.array([r["pc"] - r["po"] for r in pool])
    if len(x) > 30 and (x * x).sum() > 0:
        s = float((x * yy).sum() / (x * x).sum())
        res = yy - s * x
        out["slope"] = {"n": len(x), "slope": round(s, 4), "se": round(float(math.sqrt((res ** 2).sum() / (len(x) - 1) / (x * x).sum())), 4)}
    return out


def roi_close(rs):
    out = {}
    for th in (0.0, 0.03, 0.05):
        roi = []
        for r in rs:
            if not r.get("oc_h") or not r.get("oc_a"):
                continue
            for p, o, won in ((r["p"], r["oc_h"], r["y"]), (1 - r["p"], r["oc_a"], 1 - r["y"])):
                ev = p * o - 1
                if th <= ev <= 1:
                    roi.append(o - 1 if won else -1)
        if roi:
            out[str(th)] = ms(roi)
    return out


def line_eval(rows, key):
    """讓分或大小：rows 每場 {pc: 模型「主隊過盤／大分」機率, hit: 1/0（走盤 None）}；跟 50% 比、模型有把握時的命中率"""
    rs = [r for r in rows if r.get(key) is not None and r.get(key + "_hit") is not None]
    if not rs:
        return None
    ll = np.mean([ll2(r[key], r[key + "_hit"]) for r in rs])
    out = {"n": len(rs), "ll_model": round(float(ll), 5), "ll_coin": round(math.log(2), 5)}
    for th in (0.0, 0.03, 0.05, 0.08):
        hits = []
        for r in rs:
            p = r[key]
            if p >= 0.5 + th:
                hits.append(r[key + "_hit"])
            elif p <= 0.5 - th:
                hits.append(1 - r[key + "_hit"])
        if hits:
            out[str(th)] = ms(hits)
    return out


def save_sport(path, key, data):
    """只更新自己那個運動：存檔前重新讀一次（避免同時跑的另一個程式蓋掉別的運動）"""
    import json
    import os
    rep = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    rep[key] = data
    json.dump(rep, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
