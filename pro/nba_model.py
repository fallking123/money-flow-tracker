"""
職業版・第 3 階段：NBA 模型（不看賠率）
================================================================
資料：hoopR / sportsdataverse（CC BY 4.0）每場球隊數據、每位球員上場分鐘和正負值（2005 起；正負值 2008 起）。
第一層（每週重算，只用之前的比賽；越近越重要）：
- 進攻／防守效率：每 100 個回合得幾分（回合＝出手 − 進攻籃板 ＋ 失誤 ＋ 0.44×罰球），加權嶺迴歸同時扣掉對手強弱、主場。
- 節奏：每場大約打幾個回合。
- 誰缺陣：每位球員最近平均上場分鐘、每分鐘正負值（往 0 拉很多）；這場「平常會上場、這場沒上」的球員，
  他們的價值加起來＝缺陣損失（這場有誰上場，開賽前看傷兵名單大致就知道）。
- 背靠背、休息天數。
第二層（用之前幾季學）：分差＝效率差×節奏＋缺陣差＋主場＋背靠背；總分＝節奏×效率和＋缺陣。分差、總分當常態分布 → 主勝、過盤、大分機率。
驗證 2015–16 到 2023–24 挑設定；最後兩季 2024–25、2025–26 只考一次。跟美國收盤比；2023–24 起有開盤，看收盤有沒有往模型移。

用法：python3 -m pro.nba_model --tune   /   --final-test
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
D = os.path.join(ROOT, "docs", "data", "pro", "nba")
HIST = os.path.join(ROOT, "docs", "data", "nba", "history")
OUT = os.path.join(ROOT, "docs", "data", "pro")
VALID = (2016, 2024)      # hoopR 季別＝結束那一年
TEST = (2025, 2026)
FIRST_TRAIN = 2010


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def load():
    rows = list(csv.DictReader(open(os.path.join(D, "team_games.csv"), encoding="utf-8")))
    cnt = defaultdict(int)
    for r in rows:
        cnt[(r["season"], r["team"])] += 1
    by = defaultdict(dict)
    for r in rows:
        if r["season_type"] not in ("2", "3", "5") or cnt[(r["season"], r["team"])] < 40:
            continue                                    # 明星賽、表演賽
        by[r["game_id"]][r["home_away"]] = r
    games = []
    for gid, x in by.items():
        h, a = x.get("home"), x.get("away")
        if not h or not a:
            continue
        def poss(t):
            fga, orb, fta = fnum(t["fga"]), fnum(t["orb"]), fnum(t["fta"])
            tov = fnum(t.get("total_tov")) or fnum(t.get("tov"))
            if None in (fga, orb, fta, tov):
                return None
            return fga - orb + tov + 0.44 * fta
        ph, pa = poss(h), poss(a)
        hs, as_ = fnum(h["pts"]), fnum(a["pts"])
        if None in (ph, pa, hs, as_) or ph < 60 or pa < 60:
            continue
        games.append({"game_id": gid, "season": int(h["season"]), "date": h["date"][:10], "dt": datetime.strptime(h["date"][:10], "%Y-%m-%d"),
                      "home": h["team"], "away": a["team"], "hs": hs, "as": as_, "poss": (ph + pa) / 2, "playoff": h["season_type"] == "3"})
    games.sort(key=lambda g: (g["dt"], g["game_id"]))
    # 球員
    pl = defaultdict(list)
    for r in csv.DictReader(open(os.path.join(D, "player_games.csv"), encoding="utf-8")):
        m = fnum(r["min"])
        if m and m > 0:
            pm = fnum(r["pm"].replace("+", "")) if r["pm"] not in ("--", "", None) else None
            pl[r["game_id"]].append((r["team"], r["player"], m, pm))
    # 盤口：日期＋比分對
    hist = defaultdict(list)
    for f in glob.glob(os.path.join(HIST, "*.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            hs, as_ = fnum(r.get("home_score")), fnum(r.get("away_score"))
            if hs is None or as_ is None:
                continue
            hist[(r["date"], int(hs), int(as_))].append(r)
    for g in games:
        h = None
        for dd in (0, -1, 1):
            c = hist.get(((g["dt"] + timedelta(days=dd)).strftime("%Y-%m-%d"), int(g["hs"]), int(g["as"])), [])
            if len(c) == 1:
                h = c[0]
                break
        g["oc_h"], g["oc_a"] = (E.american(h.get("ml_close_home")), E.american(h.get("ml_close_away"))) if h else (None, None)
        g["oo_h"], g["oo_a"] = (E.american(h.get("ml_open_home")), E.american(h.get("ml_open_away"))) if h else (None, None)
        g["spread"] = fnum(h.get("spread_close_home")) if h else None
        g["total_line"] = fnum(h.get("total_close")) if h else None
        g["players"] = pl.get(g["game_id"], [])
    return games


class Ratings:
    def __init__(self, games, hl, ridge):
        self.hl, self.ridge = hl, ridge
        self.teams = sorted({g["home"] for g in games} | {g["away"] for g in games})
        self.ti = {t: i for i, t in enumerate(self.teams)}
        rows = []
        for g in games:
            for t, o, hm, pts in ((g["home"], g["away"], 1, g["hs"]), (g["away"], g["home"], -1, g["as"])):
                rows.append(((g["dt"] - datetime(2000, 1, 1)).days, self.ti[t], self.ti[o], hm, 100 * pts / g["poss"], g["poss"]))
        rows.sort(key=lambda r: r[0])
        self.rows = rows
        self.t = np.array([r[0] for r in rows], float)

    def fit(self, cutoff):
        ct = (cutoff - datetime(2000, 1, 1)).days
        idx = np.where((self.t < ct) & (self.t > ct - 5 * self.hl))[0]
        if len(idx) < 400:
            return None
        rs = [self.rows[i] for i in idx]
        dec = np.power(0.5, (ct - self.t[idx]) / self.hl)
        off = np.array([r[1] for r in rs])
        dfn = np.array([r[2] for r in rs])
        hm = np.array([r[3] for r in rs], float)
        T = len(self.teams)
        rt = E.ridge_ratings(off, dfn, hm, np.array([r[4] for r in rs]), dec, T, self.ridge)
        pace = E.ridge_ratings(off, dfn, hm * 0, np.array([r[5] for r in rs]), dec, T, self.ridge)
        return rt, pace


def features(games, hl, ridge, k_min, hl_pl):
    R = Ratings(games, hl, ridge)
    out = []
    weeks = defaultdict(list)
    for g in games:
        weeks[g["dt"] - timedelta(days=g["dt"].weekday())].append(g)
    # 球員：衰減的上場分鐘（最近的出賽）、正負值
    pm_s, pm_m, exp_min, last_t = defaultdict(float), defaultdict(float), defaultdict(float), {}
    roster = defaultdict(set)          # 隊 → 最近有上場的球員
    last_game = {}
    for wk in sorted(weeks):
        fit = R.fit(wk)
        for g in sorted(weeks[wk], key=lambda x: x["dt"]):
            now = (g["dt"] - datetime(2000, 1, 1)).days

            def decay_val(key):
                t0 = last_t.get(key)
                return 0.0 if t0 is None else 0.5 ** ((now - t0) / hl_pl)

            def team_value(team, played):
                full = act = mins = mins_act = 0.0
                for p in list(roster[team]):
                    f = decay_val((team, p))
                    em = exp_min[(team, p)] * f
                    if em < 0.5:
                        continue
                    v = pm_s[p] / (pm_m[p] + k_min)          # 每分鐘正負值（往 0 拉）
                    full += em * v
                    mins += em
                    if p in played:
                        act += em * v
                        mins_act += em
                return full - act, (mins - mins_act) / mins if mins else 0.0

            played = {s: {p for t, p, m, pm in g["players"] if t == g[s]} for s in ("home", "away")}
            miss_h, miss_mh = team_value(g["home"], played["home"]) if played["home"] else (0.0, 0.0)
            miss_a, miss_ma = team_value(g["away"], played["away"]) if played["away"] else (0.0, 0.0)
            rest = {}
            for s in ("home", "away"):
                p = last_game.get(g[s])
                rest[s] = (g["dt"] - p).days if p else 3
            if fit:
                (mu, o, d, h), (pmu, po, pd, _) = fit
                i, j = R.ti[g["home"]], R.ti[g["away"]]
                eh = mu + o[i] - d[j] + h
                ea = mu + o[j] - d[i] - h
                pace = pmu + po[i] + po[j] - pd[i] - pd[j]
                b2b = lambda x: 1.0 if x <= 1 else 0.0
                out.append({**{k: g[k] for k in ("game_id", "season", "date", "home", "away", "hs", "as", "oc_h", "oc_a", "oo_h", "oo_a", "spread", "total_line", "playoff")},
                            "x_m": [(eh - ea) * pace / 100, miss_h - miss_a, miss_mh - miss_ma, b2b(rest["home"]) - b2b(rest["away"]),
                                    max(-3, min(3, rest["home"] - rest["away"])), 1.0 if g["playoff"] else 0.0],
                            "x_t": [(eh + ea) * pace / 100, pace, miss_h + miss_a, b2b(rest["home"]) + b2b(rest["away"])],
                            "margin": g["hs"] - g["as"], "total": g["hs"] + g["as"]})
            # 更新球員
            for t, p, m, pm in g["players"]:
                key = (t, p)
                f = decay_val(key)
                exp_min[key] = exp_min[key] * f * 0.0 + (exp_min[key] * f * 0.6 + m * 0.4 if key in last_t else m)
                last_t[key] = now
                roster[t].add(p)
                if pm is not None:
                    pm_s[p] = pm_s[p] * 0.995 + pm
                    pm_m[p] = pm_m[p] * 0.995 + m
            last_game[g["home"]] = last_game[g["away"]] = g["dt"]
    return out


def second_stage(feats, season):
    tr = [f for f in feats if FIRST_TRAIN <= f["season"] < season]
    te = [f for f in feats if f["season"] == season]
    if len(tr) < 3000 or not te:
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
        r = {"season": f["season"], "date": f["date"], "home": f["home"], "away": f["away"], "pred_m": m, "pred_t": t,
             "p": float(norm.cdf(m / sm)), "y": int(f["margin"] > 0), "margin": f["margin"], "total": f["total"],
             "oc_h": f["oc_h"], "oc_a": f["oc_a"], "oo_h": f["oo_h"], "oo_a": f["oo_a"],
             "pc": E.devig2(f["oc_h"], f["oc_a"]), "po": E.devig2(f["oo_h"], f["oo_a"])}
        if f["spread"] is not None:
            line = -f["spread"]                      # 收盤讓分（主隊角度：主隊要贏幾分才過盤）
            r["sp"] = float(1 - norm.cdf((line - m) / sm))
            r["sp_hit"] = None if f["margin"] == line else int(f["margin"] > line)
            r["spread_line"] = line
        if f["total_line"]:
            r["ou"] = float(1 - norm.cdf((f["total_line"] - t) / st))
            r["ou_hit"] = None if f["total"] == f["total_line"] else int(f["total"] > f["total_line"])
        out.append(r)
    return out


def run(games, cfg, seasons):
    feats = features(games, cfg["half_life"], cfg["ridge"], cfg["k_min"], cfg["hl_pl"])
    preds = []
    for s in range(seasons[0], seasons[1] + 1):
        preds += second_stage(feats, s)
    return preds


def evaluate(preds, blend=None):
    out = {"ml": E.ml_eval(preds, blend), "spread": E.line_eval(preds, "sp"), "total": E.line_eval(preds, "ou"), "n_games": len(preds)}
    sp = [p for p in preds if p.get("spread_line") is not None]
    if sp:
        out["mae"] = {"model": round(float(np.mean([abs(p["margin"] - p["pred_m"]) for p in sp])), 3),
                      "market": round(float(np.mean([abs(p["margin"] - p["spread_line"]) for p in sp])), 3), "n": len(sp)}
    return out


GRID = [{"half_life": hl, "ridge": rd, "k_min": k, "hl_pl": hp} for hl in (60, 120, 240) for rd in (5.0, 20.0) for k in (500.0, 2000.0) for hp in (20.0,)]


def main():
    rep_path = os.path.join(OUT, "us_report.json")
    rep = json.load(open(rep_path, encoding="utf-8")) if os.path.exists(rep_path) else {}
    R = rep.get("nba", {})
    games = load()
    print(f"NBA {len(games)} 場，有收盤 {sum(1 for g in games if g['oc_h'])}、有開盤 {sum(1 for g in games if g['oo_h'])}", flush=True)
    if "--tune" in sys.argv:
        grid = []
        for cfg in GRID:
            ev = evaluate(run(games, cfg, VALID))
            grid.append({**cfg, "ll_model": ev["ml"]["ll_model"], "ll_close": ev["ml"]["ll_close"], "ll_base": ev["ml"]["ll_base"],
                         "n": ev["ml"]["n"], "mae": ev.get("mae")})
            print(json.dumps(grid[-1]), flush=True)
        best = min(grid, key=lambda g: g["ll_model"])
        c = {k: best[k] for k in ("half_life", "ridge", "k_min", "hl_pl")}
        ev = evaluate(run(games, c, VALID))
        R.update({"grid": grid, "chosen": c, "valid": ev, "blend_ab": [ev["ml"]["blend"]["a"], ev["ml"]["blend"]["b"]],
                  "tuned_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                  "data": {"games": len(games), "first": games[0]["date"], "last": games[-1]["date"]}})
        E.save_sport(rep_path, "nba", R)
        print("NBA 驗證完成：", c, ev["ml"]["ll_model"], ev["ml"]["ll_close"])
    elif "--final-test" in sys.argv:
        if R.get("test"):
            print("NBA 最後兩季已經考過了，不能重考")
            return
        c = R["chosen"]
        ev = evaluate(run(games, c, TEST), blend=R["blend_ab"])
        R["test"] = {"run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "config": c, **ev}
        E.save_sport(rep_path, "nba", R)
        log = os.path.join(OUT, "test_log.json")
        hist = json.load(open(log)) if os.path.exists(log) else []
        hist.append({"stage": 3, "sport": "nba", "run_utc": R["test"]["run_utc"], "config": c})
        json.dump(hist, open(log, "w"), ensure_ascii=False, indent=1)
        print("NBA 最後兩季考試完成：", ev["ml"]["ll_model"], ev["ml"]["ll_close"])


if __name__ == "__main__":
    main()
