"""
職業版・第 2 階段：NFL 模型（不看賠率）
================================================================
資料：nflverse 每一個 play（2006 起，pro/nfl_data.py 整理成每場每隊）。
第一層（每週重算，只用之前的比賽）：
- 進攻／防守效率：每一場進攻的「每個 play 平均 EPA」（比賽還沒定局時的 play），用加權嶺迴歸同時算
  每隊進攻分、防守分、主場優勢（會扣掉對手強弱）。越近的比賽越重要（半衰期）。
- 得分版：同樣方法，改用實際得分（包含特勤組、防守達陣等 EPA 沒算到的）。
- 四分衛：這場先發四分衛過去每次傳球的平均 EPA（場數少的往聯盟平均拉）。
第二層（用之前幾季學）：分差＝a×效率差＋b×得分評分差＋c×四分衛差＋主場＋休息天數差；
  總分＝效率和＋得分評分和＋室內／風／冷。分差、總分的誤差當常態分布 → 主勝機率、過盤機率、大分機率。
驗證 2017–2023 挑設定；最後兩季 2024、2025 只考一次。跟收盤（nflverse 的收盤讓分／大小、ESPN／nflverse 收盤獨贏）比。
NFL 沒有歷史開盤，所以沒辦法做「收盤有沒有往模型移」，只能看我們自己記的（之後累積）。

用法：python3 -m pro.nfl_model --tune   /   --final-test
"""
import csv
import glob
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.stats import norm

from pro import us_eval as E

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "docs", "data", "pro", "nfl")
HIST = os.path.join(ROOT, "docs", "data", "nfl", "history")
OUT = os.path.join(ROOT, "docs", "data", "pro")
MOVE = {"OAK": "LV", "SD": "LAC", "STL": "LA"}
VALID = (2017, 2023)
TEST = (2024, 2025)
FIRST_PRED = 2009
EXTRA = "--basic" not in sys.argv     # 傳球效率、成功率（驗證季比較過才決定要不要用）


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def load():
    games = {}
    for r in csv.DictReader(open(os.path.join(D, "games.csv"), encoding="utf-8")):
        if r["home_score"] in ("", None):
            continue
        r["home"], r["away"] = MOVE.get(r["home"], r["home"]), MOVE.get(r["away"], r["away"])
        r["dt"] = datetime.strptime(r["date"], "%Y-%m-%d")
        r["season"] = int(r["season"])
        games[r["game_id"]] = r
    tg = defaultdict(dict)
    for r in csv.DictReader(open(os.path.join(D, "team_games.csv"), encoding="utf-8")):
        if r["game_id"] in games:
            tg[r["game_id"]][MOVE.get(r["team"], r["team"])] = r
    # 收盤獨贏、中立場、休息天數（舊的歷史檔）
    hist = {}
    for f in glob.glob(os.path.join(HIST, "nflverse_*.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            h, a = MOVE.get(r["home"], r["home"]), MOVE.get(r["away"], r["away"])
            hist[(r["date"], h, a)] = r
    for g in games.values():
        h = None
        for dd in (0, -1, 1):
            k = ((g["dt"] + timedelta(days=dd)).strftime("%Y-%m-%d"), g["home"], g["away"])
            if k in hist:
                h = hist[k]
                break
        g["oc_h"], g["oc_a"] = (E.american(h["ml_close_home"]), E.american(h["ml_close_away"])) if h else (None, None)
        g["neutral"] = 1 if h and h.get("neutral") == "True" else 0
        rh, ra = (fnum(h.get("home_rest")), fnum(h.get("away_rest"))) if h else (None, None)
        g["rest_d"] = max(-7, min(7, (rh or 7) - (ra or 7)))
    gl = sorted(games.values(), key=lambda g: (g["dt"], g["game_id"]))
    return gl, tg


class Ratings:
    def __init__(self, games, tg, half_life, ridge):
        self.hl, self.ridge = half_life, ridge
        self.teams = sorted({g["home"] for g in games} | {g["away"] for g in games})
        self.ti = {t: i for i, t in enumerate(self.teams)}
        rows = []
        for g in games:
            for side in ("home", "away"):
                t = g[side]
                o = g["away"] if side == "home" else g["home"]
                r = tg.get(g["game_id"], {}).get(t)
                if not r:
                    continue
                npl = fnum(r["n_plays"]) or 0
                pts = fnum(g["home_score"] if side == "home" else g["away_score"])
                npa = fnum(r["n_pass"]) or 0
                rows.append((g["dt"], self.ti[t], self.ti[o], 0 if g["neutral"] else (1 if side == "home" else -1),
                             (fnum(r["n_epa"]) or 0) / npl if npl else None, npl, pts, r["qb"], fnum(r["pass"]) or 0, fnum(r["pass_epa"]) or 0,
                             (fnum(r["n_pass_epa"]) or 0) / npa if npa else None, npa, (fnum(r["n_succ"]) or 0) / npl if npl else None))
        rows.sort(key=lambda x: x[0])
        self.rows = rows
        self.t = np.array([(x[0] - datetime(2000, 1, 1)).days for x in rows], float)

    def fit(self, cutoff):
        ct = (cutoff - datetime(2000, 1, 1)).days
        m = (self.t < ct) & (self.t > ct - 5 * self.hl)
        idx = np.where(m)[0]
        if len(idx) < 100:
            return None
        rs = [self.rows[i] for i in idx]
        dec = np.power(0.5, (ct - self.t[idx]) / self.hl)
        off = np.array([r[1] for r in rs])
        dfn = np.array([r[2] for r in rs])
        home = np.array([r[3] for r in rs], float)
        T = len(self.teams)
        ok = np.array([r[4] is not None for r in rs])
        epa = np.array([r[4] if r[4] is not None else 0 for r in rs])
        w_e = dec * np.array([r[5] for r in rs]) / 60 * ok
        mu_e, off_e, def_e, h_e = E.ridge_ratings(off, dfn, home, epa, w_e, T, self.ridge)
        pts = np.array([r[6] for r in rs], float)
        mu_p, off_p, def_p, h_p = E.ridge_ratings(off, dfn, home, pts, dec, T, self.ridge / 2)
        okp = np.array([r[10] is not None for r in rs])
        pe = np.array([r[10] if r[10] is not None else 0 for r in rs])
        w_p = dec * np.array([r[11] for r in rs]) / 35 * okp
        pass_r = E.ridge_ratings(off, dfn, home, pe, w_p, T, self.ridge)
        sc = np.array([r[12] if r[12] is not None else 0 for r in rs])
        succ_r = E.ridge_ratings(off, dfn, home, sc, w_e, T, self.ridge)
        # 四分衛：過去每次傳球平均 EPA（往 0 拉 150 次傳球）
        qs, qn = defaultdict(float), defaultdict(float)
        for r, w in zip(rs, dec):
            if r[7] and r[8] > 0:
                qs[r[7]] += w * r[9]
                qn[r[7]] += w * r[8]
        qb = {k: qs[k] / (qn[k] + 150) for k in qs}
        return {"e": (mu_e, off_e, def_e, h_e), "p": (mu_p, off_p, def_p, h_p), "qb": qb, "pass": pass_r, "succ": succ_r}


def features(games, tg, half_life, ridge):
    R = Ratings(games, tg, half_life, ridge)
    out = []
    by_week = defaultdict(list)
    for g in games:
        if g["season"] >= FIRST_PRED:
            by_week[(g["season"], g["week"], g["season_type"])].append(g)
    for key in sorted(by_week, key=lambda k: min(x["dt"] for x in by_week[k])):
        gs = by_week[key]
        fit = R.fit(min(x["dt"] for x in gs))
        if not fit:
            continue
        mu_e, oe, de, he = fit["e"]
        mu_p, op, dp, hp = fit["p"]
        for g in gs:
            i, j = R.ti[g["home"]], R.ti[g["away"]]
            hm = 0 if g["neutral"] else 1
            eh, ea = mu_e + oe[i] - de[j] + he * hm, mu_e + oe[j] - de[i] - he * hm
            ph, pa = mu_p + op[i] - dp[j] + hp * hm, mu_p + op[j] - dp[i] - hp * hm
            qh = fit["qb"].get(tg.get(g["game_id"], {}).get(g["home"], {}).get("qb"), 0.0)
            qa = fit["qb"].get(tg.get(g["game_id"], {}).get(g["away"], {}).get("qb"), 0.0)
            hs, as_ = float(g["home_score"]), float(g["away_score"])
            ps, ss = fit["pass"], fit["succ"]
            pdh, pda = ps[1][i] - ps[2][j], ps[1][j] - ps[2][i]
            sdh, sda = ss[1][i] - ss[2][j], ss[1][j] - ss[2][i]
            xm = [eh - ea, ph - pa, qh - qa, hm, g["rest_d"]] + ([pdh - pda, sdh - sda] if EXTRA else [])
            out.append({**g, "x_m": xm,
                        "x_t": [eh + ea, ph + pa, 1.0 if g["roof"] in ("dome", "closed") else 0.0,
                                min(fnum(g["wind"]) or 0, 30) if g["roof"] not in ("dome", "closed") else 0.0,
                                1.0 if (fnum(g["temp"]) or 60) < 35 and g["roof"] not in ("dome", "closed") else 0.0],
                        "margin": hs - as_, "total": hs + as_})
    return out


def second_stage(feats, season):
    tr = [f for f in feats if f["season"] < season]
    te = [f for f in feats if f["season"] == season]
    if len(tr) < 300 or not te:
        return []
    Xm = np.array([[1, *f["x_m"]] for f in tr])
    ym = np.array([f["margin"] for f in tr])
    bm = np.linalg.lstsq(Xm, ym, rcond=None)[0]
    sm = float(np.std(ym - Xm @ bm))
    Xt = np.array([[1, *f["x_t"]] for f in tr])
    yt = np.array([f["total"] for f in tr])
    bt = np.linalg.lstsq(Xt, yt, rcond=None)[0]
    st = float(np.std(yt - Xt @ bt))
    out = []
    for f in te:
        m = float(np.array([1, *f["x_m"]]) @ bm)
        t = float(np.array([1, *f["x_t"]]) @ bt)
        sl, tl = fnum(f["spread_line"]), fnum(f["total_line"])
        r = {"season": f["season"], "date": f["date"], "home": f["home"], "away": f["away"], "pred_m": m, "pred_t": t,
             "p": float(norm.cdf(m / sm)), "y": None if f["margin"] == 0 else int(f["margin"] > 0),
             "oc_h": f["oc_h"], "oc_a": f["oc_a"], "pc": E.devig2(f["oc_h"], f["oc_a"]), "po": None,
             "spread_line": sl, "total_line": tl, "margin": f["margin"], "total": f["total"]}
        if sl is not None:
            r["sp"] = float(1 - norm.cdf((sl - m) / sm))
            r["sp_hit"] = None if f["margin"] == sl else int(f["margin"] > sl)
        if tl is not None:
            r["ou"] = float(1 - norm.cdf((tl - t) / st))
            r["ou_hit"] = None if f["total"] == tl else int(f["total"] > tl)
        out.append(r)
    return out


def run(games, tg, hl, rd, seasons):
    feats = features(games, tg, hl, rd)
    preds = []
    for s in range(seasons[0], seasons[1] + 1):
        preds += second_stage(feats, s)
    return preds


def evaluate(preds, blend=None):
    rs = [p for p in preds if p["y"] is not None]
    out = {"ml": E.ml_eval(rs, blend), "spread": E.line_eval(preds, "sp"), "total": E.line_eval(preds, "ou"), "n_games": len(preds)}
    # 分差預測 vs 收盤讓分：誰比較接近實際分差
    sp = [p for p in preds if p["spread_line"] is not None]
    if sp:
        out["mae"] = {"model": round(float(np.mean([abs(p["margin"] - p["pred_m"]) for p in sp])), 3),
                      "market": round(float(np.mean([abs(p["margin"] - p["spread_line"]) for p in sp])), 3), "n": len(sp)}
    return out


GRID = [(hl, rd) for hl in (120, 150, 180, 240, 480) for rd in (8.0, 32.0, 64.0, 128.0)]


def main():
    rep_path = os.path.join(OUT, "us_report.json")
    rep = json.load(open(rep_path, encoding="utf-8")) if os.path.exists(rep_path) else {}
    R = rep.setdefault("nfl", {})
    games, tg = load()
    if "--tune" in sys.argv:
        grid = []
        for hl, rd in GRID:
            ev = evaluate(run(games, tg, hl, rd, VALID))
            grid.append({"half_life": hl, "ridge": rd, "ll_model": ev["ml"]["ll_model"], "ll_close": ev["ml"]["ll_close"],
                         "ll_base": ev["ml"]["ll_base"], "mae": ev.get("mae"), "n": ev["ml"]["n"]})
            print(json.dumps(grid[-1], ensure_ascii=False), flush=True)
        best = min(grid, key=lambda g: g["ll_model"])
        c = {"half_life": best["half_life"], "ridge": best["ridge"]}
        ev = evaluate(run(games, tg, c["half_life"], c["ridge"], VALID))
        R.update({"grid": grid, "chosen": c, "valid": ev, "blend_ab": [ev["ml"]["blend"]["a"], ev["ml"]["blend"]["b"]],
                  "tuned_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                  "data": {"games": len(games), "first": games[0]["date"], "last": games[-1]["date"]}})
        json.dump(rep, open(rep_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("NFL 驗證完成：", c, ev["ml"]["ll_model"], ev["ml"]["ll_close"])
    elif "--final-test" in sys.argv:
        if R.get("test"):
            print("NFL 最後兩季已經考過了，不能重考")
            return
        c = R["chosen"]
        preds = run(games, tg, c["half_life"], c["ridge"], TEST)
        ev = evaluate(preds, blend=R["blend_ab"])
        R["test"] = {"run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "config": c, **ev}
        json.dump(rep, open(rep_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log = os.path.join(OUT, "test_log.json")
        hist = json.load(open(log)) if os.path.exists(log) else []
        hist.append({"stage": 2, "sport": "nfl", "run_utc": R["test"]["run_utc"], "config": c})
        json.dump(hist, open(log, "w"), ensure_ascii=False, indent=1)
        print("NFL 最後兩季考試完成：", ev["ml"]["ll_model"], ev["ml"]["ll_close"])


if __name__ == "__main__":
    main()
