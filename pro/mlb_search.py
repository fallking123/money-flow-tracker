"""
職業版・MLB 特徵搜尋（練習區）
================================================================
目標：找「開盤時莊家沒算好」的東西。成績單不是比收盤準，而是：
  模型跟開盤不一樣的地方，收盤有沒有往模型那邊移（＝我們比開盤早知道）。
做法（防止「試很多次總會有一個剛好贏」）：
- 練習區只用 2012–2021（這幾年有 SBRO 開盤）；切成 4 段：2012–14、2015–17、2018–19、2020–21。
- 基本模型＝MLB 第 2 版「開盤版」（只用上一場的打線），算一次存起來；每個候選特徵加上去重跑第二層。
- 主要成績：用「開盤＋b ×（模型 − 開盤）」預測收盤，誤差少了多少（每場配對比，算 z 值）。
  輔助：收盤往模型移的斜率、模型看好 ≥5% 時用開盤價下注的 CLV、比賽結果的準度。
- 通過標準（先訂好，不事後改）：主要成績 z ≥ 門檻，而且 4 段裡至少 3 段變好。
  門檻隨試過的次數提高（Bonferroni：總錯誤率 5%，單邊）。每一次嘗試都記在 docs/data/pro/search_log.json。
- 2024–2025 不看（已考過），2026 整季是最後的考試。
用法：python3 -m pro.mlb_search <候選名稱…>   （--list 列出候選）
"""
import json
import math
import os
import pickle
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression

from pro import mlb_model as V1
from pro import mlb_player_model as M2
from pro import us_eval as E

OUT = V1.OUT
LOG = os.path.join(OUT, "search_log.json")
CACHE = os.path.join(os.environ.get("PRO_CACHE", "/tmp"), "mlb_base_prev.pkl")
BLOCKS = [(2012, 2014), (2015, 2017), (2018, 2019), (2020, 2021)]
CALM = 0.08


def fix_odds(games, feats):
    """第 1 版用「日期＋比分」對盤口，同一年有兩個來源（2021 有 SBRO 和 ESPN）就對不到；這裡改成優先用有開盤的 SBRO"""
    import csv
    import glob
    hist = defaultdict(list)
    for f in sorted(glob.glob(os.path.join(V1.HIST, "*.csv"))):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            try:
                hist[(r["date"], int(float(r["home_score"])), int(float(r["away_score"])))].append(r)
            except (ValueError, TypeError, KeyError):
                pass
    by = {g["game_id"]: g for g in games}
    n = 0
    for f in feats:
        if f["oo_h"]:
            continue
        g = by[f["game_id"]]
        c = [r for r in hist.get((g["date"], g["hs"], g["as"]), []) if r.get("ml_open_home") and r.get("source") == "sbro"]
        if len(c) == 1:
            r = c[0]
            f["oc_h"], f["oc_a"] = E.american(r["ml_close_home"]), E.american(r["ml_close_away"])
            f["oo_h"], f["oo_a"] = E.american(r["ml_open_home"]), E.american(r["ml_open_away"])
            try:
                f["total_line"] = float(r["total_close"]) or f["total_line"]
            except (ValueError, TypeError):
                pass
            n += 1
    print(f"補對到盤口 {n} 場", flush=True)


def base_features():
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, "rb"))
    R = json.load(open(os.path.join(OUT, "us_report.json"), encoding="utf-8"))["mlb2"]["chosen"]
    games = V1.load()
    feats = M2.features(games, M2.load_lines(), M2.load_players(), {**R, "lineup": "prev"})
    fix_odds(games, feats)
    pickle.dump((games, feats), open(CACHE, "wb"))
    return games, feats


def predict(feats, extra, seasons):
    """第二層：羅吉斯迴歸，每一季只用之前的季學（跟第 2 版一樣），extra＝{game_id: [特徵…]}"""
    k = len(next(iter(extra.values()))) if extra else 0
    X = {f["game_id"]: np.array(f["x"] + (extra.get(f["game_id"], [0.0] * k) if k else [])) for f in feats}
    out = []
    for s in range(seasons[0], seasons[1] + 1):
        tr = [f for f in feats if V1.FIRST_TRAIN <= f["season"] < s]
        te = [f for f in feats if f["season"] == s]
        A = np.array([X[f["game_id"]] for f in tr])
        mu, sd = A.mean(0), A.std(0) + 1e-9
        lr = LogisticRegression(C=1.0, max_iter=2000).fit((A - mu) / sd, [int(f["hs"] > f["as"]) for f in tr])
        p = lr.predict_proba((np.array([X[f["game_id"]] for f in te]) - mu) / sd)[:, 1]
        for f, pp in zip(te, p):
            out.append({"game_id": f["game_id"], "season": s, "p": float(pp), "y": int(f["hs"] > f["as"]),
                        "pc": E.devig2(f["oc_h"], f["oc_a"]), "po": E.devig2(f["oo_h"], f["oo_a"]),
                        "oo_h": f["oo_h"], "oo_a": f["oo_a"], "oc_h": f["oc_h"], "oc_a": f["oc_a"]})
    return out


def score(preds):
    """每場：用開盤＋b×（模型−開盤）預測收盤的誤差；b 用這一段自己的資料（只有一個數字）"""
    rs = [r for r in preds if r["pc"] and r["po"] and abs(r["pc"] - r["po"]) < CALM]
    d = np.array([r["p"] - r["po"] for r in rs])
    m = np.array([r["pc"] - r["po"] for r in rs])
    b = float(d @ m / (d @ d)) if len(rs) else 0.0
    err = (m - b * d) ** 2
    clv = []
    for r in rs:
        for side, p, po, pc, o in ((1, r["p"], r["po"], r["pc"], r["oo_h"]), (0, 1 - r["p"], 1 - r["po"], 1 - r["pc"], r["oo_a"])):
            if p * o - 1 >= 0.05:
                clv.append(pc * o - 1)
    ll = [E.ll2(r["p"], r["y"]) for r in preds]
    return {"ids": [r["game_id"] for r in rs], "err": err, "b": b, "n": len(rs),
            "clv": (float(np.mean(clv)), float(np.std(clv) / math.sqrt(len(clv))) if len(clv) > 1 else None, len(clv)),
            "ll": float(np.mean(ll)), "ll_each": dict(zip([r["game_id"] for r in preds], ll))}


def compare(base, cand, blks=None):
    out = {"blocks": [], "better_blocks": 0}
    all_d, all_dl = [], []
    for (a, b) in (blks or BLOCKS):
        sb, sc = base[(a, b)], cand[(a, b)]
        eb = dict(zip(sb["ids"], sb["err"]))
        ec = dict(zip(sc["ids"], sc["err"]))
        common = [i for i in eb if i in ec]
        diff = np.array([eb[i] - ec[i] for i in common]) * 1e4      # 正的＝候選比較好
        dl = np.array([sb["ll_each"][i] - sc["ll_each"][i] for i in sb["ll_each"] if i in sc["ll_each"]])
        all_d.append(diff)
        all_dl.append(dl)
        z = float(diff.mean() / (diff.std() / math.sqrt(len(diff)))) if len(diff) > 1 and diff.std() > 0 else 0.0
        out["blocks"].append({"seasons": f"{a}–{b}", "n": len(common), "gain": round(float(diff.mean()), 4), "z": round(z, 2),
                              "b_base": round(sb["b"], 3), "b_cand": round(sc["b"], 3),
                              "clv_base": [round(x, 4) if isinstance(x, float) else x for x in sb["clv"]],
                              "clv_cand": [round(x, 4) if isinstance(x, float) else x for x in sc["clv"]],
                              "ll_gain": round(float(dl.mean()) * 1e3, 3)})
        out["better_blocks"] += int(diff.mean() > 0)
    D = np.concatenate(all_d)
    DL = np.concatenate(all_dl)
    out["z"] = round(float(D.mean() / (D.std() / math.sqrt(len(D)))), 2) if D.std() > 0 else 0.0
    out["z_ll"] = round(float(DL.mean() / (DL.std() / math.sqrt(len(DL)))), 2) if DL.std() > 0 else 0.0
    return out


def blocks(feats, extra):
    return {(a, b): score(predict(feats, extra, (a, b))) for (a, b) in BLOCKS}


def total_eval(feats, extra):
    """大小分：特徵能不能預測「實際總分 − 收盤大小線」。跟「只有平均偏差」的預測比（每場配對）"""
    rows = [f for f in feats if f.get("total_line") and f["game_id"] in extra]
    out = {"blocks": [], "better_blocks": 0}
    allg = []
    for (a, b) in BLOCKS:
        g_all, hits = [], []
        for s in range(a, b + 1):
            tr = [f for f in rows if V1.FIRST_TRAIN <= f["season"] < s]
            te = [f for f in rows if f["season"] == s]
            if len(tr) < 2000 or not te:
                continue
            X = np.array([[1.0, *extra[f["game_id"]]] for f in tr])
            y = np.array([f["hs"] + f["as"] - f["total_line"] for f in tr])
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            Xt = np.array([[1.0, *extra[f["game_id"]]] for f in te])
            yt = np.array([f["hs"] + f["as"] - f["total_line"] for f in te])
            pc, p0 = Xt @ beta, np.full(len(te), y.mean())
            g_all.append((yt - p0) ** 2 - (yt - pc) ** 2)
            for d, r in zip(pc - p0, yt):
                if abs(d) >= 0.3 and r != 0:
                    hits.append(int((d > 0) == (r > 0)))
        G = np.concatenate(g_all)
        allg.append(G)
        z = float(G.mean() / (G.std() / math.sqrt(len(G))))
        out["blocks"].append({"seasons": f"{a}–{b}", "n": len(G), "gain": round(float(G.mean()), 4), "z": round(z, 2),
                              "picks": len(hits), "hit": round(float(np.mean(hits)), 4) if hits else None})
        out["better_blocks"] += int(G.mean() > 0)
    A = np.concatenate(allg)
    out["z"] = round(float(A.mean() / (A.std() / math.sqrt(len(A)))), 2)
    out["z_ll"] = None
    return out


def load_log():
    return json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else {"sport": "mlb", "tries": []}


def threshold(n_tries):
    """試了 n 次，總錯誤率 5%（單邊）→ 每一次要 z ≥ 這個數"""
    return round(float(norm.ppf(1 - 0.05 / max(1, n_tries))), 2)


def run(names):
    from pro import mlb_candidates as C
    games, feats = base_features()
    base = blocks(feats, {})
    log = load_log()
    for nm in names:
        cand = C.CANDIDATES[nm]
        extra = cand["fn"](games, feats)
        res = total_eval(feats, extra) if cand.get("kind") == "total" else compare(base, blocks(feats, extra))
        n = len(log["tries"]) + 1
        thr = threshold(n)
        ok = res["z"] >= thr and res["better_blocks"] >= 3
        entry = {"n": n, "name": nm, "kind": cand.get("kind", "ml"), "label": cand["label"], "why": cand["why"], "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                 "z_needed": thr, "pass": ok, **res}
        log["tries"].append(entry)
        json.dump(log, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"#{n} {nm}：z={res['z']}（門檻 {thr}），{res['better_blocks']}/4 段變好，結果準度 z={res['z_ll']} → {'通過' if ok else '沒通過'}", flush=True)
        for b in res["blocks"]:
            print("   ", b, flush=True)


if __name__ == "__main__":
    if "--list" in sys.argv:
        from pro import mlb_candidates as C
        for k, v in C.CANDIDATES.items():
            print(k, "：", v["label"])
    elif "--base" in sys.argv:
        games, feats = base_features()
        b = blocks(feats, {})
        for k, v in b.items():
            print(k, v["n"], round(v["b"], 3), v["clv"], round(v["ll"], 5))
    else:
        run(sys.argv[1:])
