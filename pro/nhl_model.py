"""
職業版・第 2 階段：NHL 模型（不看賠率）
================================================================
資料：MoneyPuck 每隊每場的射門品質（xG＝每一次射門依位置、角度、類型算出「平均會進幾球」），2008 起。
每週重算（只用之前的比賽），用加權嶺迴歸同時算每隊的進攻分、防守分（會扣掉對手強弱）：
- 5 對 5：每 60 分鐘製造／被製造多少 xG（已做比分和主客場調整）
- 多一人（5 對 4）：進攻＝強力進攻、防守＝少一人防守；再乘上每場平均拿到／送出幾次犯規
- 終結和守門：實際進球 − xG（進攻＝射門準、防守＝守門員好），拉回比較多（運氣成分大）
- 背靠背（前一天有比賽，常換替補守門員）、休息天數
第二層（用之前幾季學）：主勝（含延長、PK）＝羅吉斯迴歸；總進球＝線性迴歸 → 卜瓦松分布算大分機率。
驗證 2016–17 到 2023–24 挑設定；最後兩季 2024–25、2025–26 只考一次。跟美國收盤比（2022–23 起的 ESPN 盤；更早的舊資料品質較差）。
資料來源：MoneyPuck.com（非商業使用）。

用法：python3 -m pro.nhl_model --tune   /   --final-test
"""
import csv
import glob
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.stats import poisson
from sklearn.linear_model import LogisticRegression

from pro import us_eval as E

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "docs", "data", "pro", "nhl")
HIST = os.path.join(ROOT, "docs", "data", "nhl", "history")
OUT = os.path.join(ROOT, "docs", "data", "pro")
VALID = (2016, 2023)       # MoneyPuck 的季別：2016＝2016–17
TEST = (2024, 2025)
FIRST_TRAIN = 2010
CODE = {"L.A": "LAK", "N.J": "NJD", "S.J": "SJS", "T.B": "TBL", "ATL": "WPG", "ARI": "UTA"}
KEYW = [("anaheim", "ANA"), ("arizona", "UTA"), ("phoenix", "UTA"), ("utah", "UTA"), ("atlanta", "WPG"), ("winnipeg", "WPG"), ("boston", "BOS"),
        ("buffalo", "BUF"), ("carolina", "CAR"), ("columbus", "CBJ"), ("calgary", "CGY"), ("chicago", "CHI"), ("colorado", "COL"),
        ("dallas", "DAL"), ("detroit", "DET"), ("edmonton", "EDM"), ("florida", "FLA"), ("losangeles", "LAK"), ("minnesota", "MIN"),
        ("montreal", "MTL"), ("newjersey", "NJD"), ("islanders", "NYI"), ("rangers", "NYR"), ("ottawa", "OTT"), ("philadelphia", "PHI"),
        ("pittsburgh", "PIT"), ("sanjose", "SJS"), ("seattle", "SEA"), ("stlouis", "STL"), ("st.louis", "STL"), ("tampa", "TBL"),
        ("toronto", "TOR"), ("vancouver", "VAN"), ("vegas", "VGK"), ("washington", "WSH")]


def canon(name):
    s = re.sub(r"[^a-z.]", "", (name or "").lower())
    for k, c in KEYW:
        if k in s:
            return c
    return None


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def load():
    tg = defaultdict(dict)
    for r in csv.DictReader(open(os.path.join(D, "team_games.csv"), encoding="utf-8")):
        tg[(r["gameId"], CODE.get(r["playerTeam"], r["playerTeam"]))][r["situation"]] = r
    games = {}
    for (gid, team), sits in tg.items():
        a = sits.get("all")
        if not a:
            continue
        g = games.setdefault(gid, {"game_id": gid, "season": int(a["season"]), "dt": datetime.strptime(a["gameDate"], "%Y%m%d")})
        side = "h" if a["home_or_away"] == "HOME" else "a"
        g[side] = team
        g[side + "_s"] = sits
    gl = [g for g in games.values() if "h" in g and "a" in g]
    hist = {}
    for f in glob.glob(os.path.join(HIST, "*.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            h, a = canon(r.get("home")), canon(r.get("away"))
            if h and a and r.get("date"):
                hist[(r["date"], h, a)] = r
    for g in gl:
        h = None
        for dd in (0, -1, 1):
            k = ((g["dt"] + timedelta(days=dd)).strftime("%Y-%m-%d"), g["h"], g["a"])
            if k in hist:
                h = hist[k]
                break
        g["src"] = h.get("source") if h else None
        g["oc_h"], g["oc_a"] = (E.american(h.get("ml_close_home")), E.american(h.get("ml_close_away"))) if h else (None, None)
        g["oo_h"], g["oo_a"] = (E.american(h.get("ml_open_home")), E.american(h.get("ml_open_away"))) if h else (None, None)
        g["total_line"] = fnum(h.get("total_close")) if h else None
        gh, ga = fnum(g["h_s"]["all"]["goalsFor"]), fnum(g["a_s"]["all"]["goalsFor"])
        hs, as_ = (fnum(h.get("home_score")), fnum(h.get("away_score"))) if h else (None, None)
        g["gh"], g["ga"] = gh, ga
        # 誰贏（含 PK）：有賠率資料的比分最準；沒有就用進球（PK 大戰會是平手 → 不知道）
        if hs is not None and as_ is not None and hs != as_:
            g["y"] = int(hs > as_)
        elif gh is not None and ga is not None and gh != ga:
            g["y"] = int(gh > ga)
        else:
            g["y"] = None
        g["total"] = (hs + as_ - (1 if hs is not None and as_ is not None and abs(hs - as_) == 1 and gh == ga else 0)) if hs is not None else None
    gl.sort(key=lambda g: (g["dt"], g["game_id"]))
    return gl


def per60(sits, sit, k):
    s = sits.get(sit)
    if not s:
        return None, 0.0
    t = fnum(s.get("iceTime")) or 0
    v = fnum(s.get(k))
    if not t or v is None:
        return None, 0.0
    return v * 3600 / t, t / 3600


class Ratings:
    def __init__(self, games, hl, ridge):
        self.hl, self.ridge = hl, ridge
        self.teams = sorted({g["h"] for g in games} | {g["a"] for g in games})
        self.ti = {t: i for i, t in enumerate(self.teams)}
        rows = []
        for g in games:
            for side, opp, hm in (("h", "a", 1), ("a", "h", -1)):
                s = g[side + "_s"]
                x5, w5 = per60(s, "5on5", "scoreVenueAdjustedxGoalsFor")
                xp, wp = per60(s, "5on4", "xGoalsFor")
                a = s["all"]
                fin = (fnum(a["goalsFor"]) or 0) - (fnum(a["xGoalsFor"]) or 0)
                rows.append(((g["dt"] - datetime(2000, 1, 1)).days, self.ti[g[side]], self.ti[g[opp]], hm, x5, w5, xp, wp, fin,
                             fnum(a["goalsFor"]) or 0, fnum(a["penaltiesAgainst"]) or 0, fnum(a["penaltiesFor"]) or 0))
        rows.sort(key=lambda r: r[0])
        self.rows = rows
        self.t = np.array([r[0] for r in rows], float)

    def fit(self, cutoff):
        ct = (cutoff - datetime(2000, 1, 1)).days
        idx = np.where((self.t < ct) & (self.t > ct - 5 * self.hl))[0]
        if len(idx) < 300:
            return None
        rs = [self.rows[i] for i in idx]
        dec = np.power(0.5, (ct - self.t[idx]) / self.hl)
        off = np.array([r[1] for r in rs])
        dfn = np.array([r[2] for r in rs])
        hm = np.array([r[3] for r in rs], float)
        T = len(self.teams)
        out = {}
        for key, yi, wi, rd in (("x5", 4, 5, 1.0), ("pp", 6, 7, 3.0)):
            ok = np.array([r[yi] is not None for r in rs])
            y = np.array([r[yi] if r[yi] is not None else 0 for r in rs])
            w = dec * np.array([r[wi] for r in rs]) * ok
            out[key] = E.ridge_ratings(off, dfn, hm, y, w, T, self.ridge * rd)
        out["fin"] = E.ridge_ratings(off, dfn, hm, np.array([r[8] for r in rs]), dec, T, self.ridge * 6)
        out["gf"] = E.ridge_ratings(off, dfn, hm, np.array([r[9] for r in rs]), dec, T, self.ridge * 2)
        # 每場拿到／送出幾次犯規（多一人的機會）
        drawn, taken, n = np.zeros(T), np.zeros(T), np.zeros(T)
        for r, w in zip(rs, dec):
            drawn[r[1]] += w * r[10]
            taken[r[1]] += w * r[11]
            n[r[1]] += w
        out["drawn"], out["taken"] = (drawn + 3 * 3) / (n + 3), (taken + 3 * 3) / (n + 3)
        return out


def features(games, hl, ridge):
    R = Ratings(games, hl, ridge)
    last = {}
    out = []
    weeks = defaultdict(list)
    for g in games:
        weeks[g["dt"] - timedelta(days=g["dt"].weekday())].append(g)
    for wk in sorted(weeks):
        fit = R.fit(wk) if weeks[wk][0]["season"] >= FIRST_TRAIN - 1 else None
        for g in sorted(weeks[wk], key=lambda x: x["dt"]):
            rest = {}
            for s in ("h", "a"):
                prev = last.get(g[s])
                rest[s] = (g["dt"] - prev).days if prev else 5
            if fit:
                i, j = R.ti[g["h"]], R.ti[g["a"]]
                def ex(key, a, b, home):
                    mu, o, d, h = fit[key]
                    return mu + o[a] - d[b] + h * home
                x5h, x5a = ex("x5", i, j, 1), ex("x5", j, i, -1)
                pph = ex("pp", i, j, 1) * fit["drawn"][i] * 2 / 60
                ppa = ex("pp", j, i, -1) * fit["drawn"][j] * 2 / 60
                fh, fa = ex("fin", i, j, 1), ex("fin", j, i, -1)
                gh, ga = ex("gf", i, j, 1), ex("gf", j, i, -1)
                b2b = lambda d: 1.0 if d <= 1 else 0.0
                out.append({**{k: g[k] for k in ("game_id", "season", "dt", "h", "a", "y", "oc_h", "oc_a", "oo_h", "oo_a", "total_line", "total", "src")},
                            "x": [x5h - x5a, pph - ppa, fh - fa, gh - ga, b2b(rest["h"]) - b2b(rest["a"]), max(-3, min(3, rest["h"] - rest["a"]))],
                            "xt": [x5h + x5a, pph + ppa, fh + fa, gh + ga]})
            last[g["h"]] = last[g["a"]] = g["dt"]
    return out


def second_stage(feats, season):
    tr = [f for f in feats if FIRST_TRAIN <= f["season"] < season and f["y"] is not None]
    te = [f for f in feats if f["season"] == season]
    if len(tr) < 3000 or not te:
        return []
    X = np.array([f["x"] for f in tr])
    mu, sd = X.mean(0), X.std(0) + 1e-9
    lr = LogisticRegression(C=1.0, max_iter=1000).fit((X - mu) / sd, np.array([f["y"] for f in tr]))
    trt = [f for f in tr if f["total"] is not None]
    Xt = np.array([[1, *f["xt"]] for f in trt])
    bt = np.linalg.lstsq(Xt, np.array([f["total"] for f in trt], float), rcond=None)[0]
    pr = lr.predict_proba((np.array([f["x"] for f in te]) - mu) / sd)[:, 1]
    out = []
    for f, p in zip(te, pr):
        tm = float(np.array([1, *f["xt"]]) @ bt)
        r = {"season": f["season"], "date": f["dt"].strftime("%Y-%m-%d"), "home": f["h"], "away": f["a"], "p": float(p), "y": f["y"], "src": f["src"],
             "oc_h": f["oc_h"], "oc_a": f["oc_a"], "oo_h": f["oo_h"], "oo_a": f["oo_a"],
             "pc": E.devig2(f["oc_h"], f["oc_a"]), "po": E.devig2(f["oo_h"], f["oo_a"]), "pred_t": tm}
        T = f["total_line"]
        if T and f["total"] is not None:
            r["ou"] = float(1 - poisson.cdf(math.floor(T), tm))
            r["ou_hit"] = None if f["total"] == T else int(f["total"] > T)
        out.append(r)
    return out


def run(games, hl, rd, seasons):
    feats = features(games, hl, rd)
    preds = []
    for s in range(seasons[0], seasons[1] + 1):
        preds += second_stage(feats, s)
    return preds


def evaluate(preds, blend=None):
    """舊的 SBRO 冰球盤口有問題（開盤算出 +20% CLV、押冷門長期 +15%，不可能），只拿 2022–23 起的 ESPN 盤比；
    挑設定只看模型自己對比賽結果的準度（不需要盤口）"""
    rs = [p for p in preds if p["y"] is not None]
    espn = [dict(p, po=None, oo_h=None, oo_a=None) for p in rs if p.get("src") == "espn"]      # ESPN 沒有可靠的開盤
    ll_all = float(np.mean([E.ll2(p["p"], p["y"]) for p in rs])) if rs else None
    base = float(np.mean([p["y"] for p in rs])) if rs else 0.5
    return {"ll_model_all": round(ll_all, 5), "ll_base_all": round(float(np.mean([E.ll2(base, p["y"]) for p in rs])), 5), "n_all": len(rs),
            "ml": E.ml_eval(espn, blend) if len(espn) > 300 else None,
            "total": E.line_eval([p for p in preds if p.get("src") == "espn"], "ou"), "n_games": len(preds)}


GRID = [(hl, rd) for hl in (60, 120, 240) for rd in (2.0, 8.0)]


def main():
    rep_path = os.path.join(OUT, "us_report.json")
    rep = json.load(open(rep_path, encoding="utf-8")) if os.path.exists(rep_path) else {}
    R = rep.setdefault("nhl", {})
    games = load()
    print(f"NHL {len(games)} 場，有收盤 {sum(1 for g in games if g['oc_h'])}、有開盤 {sum(1 for g in games if g['oo_h'])}", flush=True)
    if "--tune" in sys.argv:
        grid = []
        for hl, rd in GRID:
            ev = evaluate(run(games, hl, rd, VALID))
            grid.append({"half_life": hl, "ridge": rd, "ll_model": ev["ll_model_all"], "ll_base": ev["ll_base_all"], "n": ev["n_all"],
                         "ll_close_espn": (ev["ml"] or {}).get("ll_close"), "ll_model_espn": (ev["ml"] or {}).get("ll_model")})
            print(json.dumps(grid[-1]), flush=True)
        best = min(grid, key=lambda g: g["ll_model"])
        c = {"half_life": best["half_life"], "ridge": best["ridge"]}
        ev = evaluate(run(games, c["half_life"], c["ridge"], VALID))
        R.update({"grid": grid, "chosen": c, "valid": ev, "blend_ab": [ev["ml"]["blend"]["a"], ev["ml"]["blend"]["b"]],
                  "tuned_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                  "data": {"games": len(games), "first": games[0]["dt"].strftime("%Y-%m-%d"), "last": games[-1]["dt"].strftime("%Y-%m-%d")}})
        E.save_sport(rep_path, "nhl", R)
        print("NHL 驗證完成：", c, ev["ll_model_all"], (ev["ml"] or {}).get("ll_close"))
    elif "--final-test" in sys.argv:
        if R.get("test"):
            print("NHL 最後兩季已經考過了，不能重考")
            return
        c = R["chosen"]
        ev = evaluate(run(games, c["half_life"], c["ridge"], TEST), blend=R["blend_ab"])
        R["test"] = {"run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "config": c, **ev}
        E.save_sport(rep_path, "nhl", R)
        log = os.path.join(OUT, "test_log.json")
        hist = json.load(open(log)) if os.path.exists(log) else []
        hist.append({"stage": 2, "sport": "nhl", "run_utc": R["test"]["run_utc"], "config": c})
        json.dump(hist, open(log, "w"), ensure_ascii=False, indent=1)
        print("NHL 最後兩季考試完成：", ev["ml"]["ll_model"], ev["ml"]["ll_close"])


if __name__ == "__main__":
    main()
