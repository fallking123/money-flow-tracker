"""
職業版・第 2 階段：MLB 模型（不看賠率）
================================================================
資料：Retrosheet 逐打席（2005–2025，pro/fetch_us.py 在 GitHub Actions 上整理成每場每位投手、每隊打擊）。
每一場開賽前，只用之前的比賽算：
- 先發投手：三振、四壞＋觸身、全壘打（每個打席），算成 FIP（投手自己能控制的部分，比失分穩定），
  場數少的往聯盟平均拉；還有平均每場投幾個打席（決定先發吃掉多少比賽、剩下交給牛棚）。
- 牛棚：這隊後援投手最近的 FIP。
- 打線：這隊打者最近每個打席的 wOBA（保送、安打、長打各有權重）、三振率。
- 球場：這個球場最近幾年每場總得分比聯盟平均多或少。
越近的比賽越重要（各自的半衰期）。
第二層（用之前幾季學）：主勝機率＝羅吉斯迴歸（打線差、先發差、牛棚差、主場）；總得分＝線性迴歸 → 負二項分布算大分機率。
驗證 2016–2023 挑設定；最後兩季 2024、2025 只考一次。跟美國收盤比；SBRO／ESPN 有開盤，可以看「收盤有沒有往模型移」。
資料來源：Retrosheet（The information used here was obtained free of charge from and is copyrighted by Retrosheet.
Interested parties may contact Retrosheet at www.retrosheet.org.）

用法：python3 -m pro.mlb_model --tune   /   --final-test
"""
import csv
import glob
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from scipy.stats import nbinom
from sklearn.linear_model import LogisticRegression

from pro import us_eval as E

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "docs", "data", "pro", "mlb")
HIST = os.path.join(ROOT, "docs", "data", "mlb", "history")
OUT = os.path.join(ROOT, "docs", "data", "pro")
VALID = (2016, 2023)
TEST = (2024, 2025)
FIRST_TRAIN = 2008
W = {"BB": 0.69, "HBP": 0.72, "1B": 0.88, "2B": 1.25, "3B": 1.58, "HR": 2.03, "ROE": 0.88}   # wOBA 權重（大約值）


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def load():
    games = {r["game_id"]: r for r in csv.DictReader(open(os.path.join(D, "games.csv"), encoding="utf-8"))}
    pl = defaultdict(list)
    for r in csv.DictReader(open(os.path.join(D, "pitch_lines.csv"), encoding="utf-8")):
        pl[r["game_id"]].append(r)
    bl = defaultdict(dict)
    for r in csv.DictReader(open(os.path.join(D, "bat_lines.csv"), encoding="utf-8")):
        bl[r["game_id"]][r["team"]] = r
    # 收盤／開盤獨贏、大小：用日期＋比分對（不同資料來源隊名寫法不一樣）
    hist = defaultdict(list)
    for f in glob.glob(os.path.join(HIST, "*.csv")):
        if f.endswith(".txt"):
            continue
        try:
            for r in csv.DictReader(open(f, encoding="utf-8")):
                hs, as_ = fnum(r.get("home_score")), fnum(r.get("away_score"))
                if hs is None or as_ is None:
                    continue
                hist[(r["date"], int(hs), int(as_))].append(r)
        except Exception:
            continue
    gl = []
    for gid, g in games.items():
        try:
            g["hs"], g["as"] = int(g["home_score"]), int(g["vis_score"])
        except ValueError:
            continue
        g["dt"] = datetime.strptime(g["date"], "%Y-%m-%d")
        g["season"] = g["dt"].year
        cand = hist.get((g["date"], g["hs"], g["as"]), [])
        h = cand[0] if len(cand) == 1 else None
        g["oc_h"], g["oc_a"] = (E.american(h["ml_close_home"]), E.american(h["ml_close_away"])) if h else (None, None)
        g["oo_h"], g["oo_a"] = (E.american(h["ml_open_home"]), E.american(h["ml_open_away"])) if h else (None, None)
        g["total_line"] = fnum(h.get("total_close")) if h else None
        g["lines"], g["bats"] = pl.get(gid, []), bl.get(gid, {})
        gl.append(g)
    gl.sort(key=lambda g: (g["dt"], g["game_id"]))
    return gl


class Decay:
    """指數衰減的累計：每個對象一組（加權和），隨時間每過半衰期就變一半"""

    def __init__(self, hl):
        self.hl = hl
        self.s = {}
        self.t = {}

    def get(self, k, now):
        if k not in self.s:
            return None
        f = 0.5 ** ((now - self.t[k]) / self.hl)
        return {a: v * f for a, v in self.s[k].items()}

    def add(self, k, now, vals):
        cur = self.get(k, now) or {}
        for a, v in vals.items():
            cur[a] = cur.get(a, 0.0) + v
        self.s[k], self.t[k] = cur, now


def rates(c):
    pa = c["pa"]
    k = c["K"] / pa
    bb = (c["BB"] + c["HBP"]) / pa
    hr = c["HR"] / pa
    fip = (13 * c["HR"] + 3 * (c["BB"] + c["HBP"]) - 2 * c["K"]) / pa
    woba = sum(W[x] * c[x] for x in W) / pa
    return k, bb, hr, fip, woba


def line_counts(r):
    return {x: float(r[x]) for x in ("pa", "K", "BB", "HBP", "HR", "1B", "2B", "3B", "ROE")}


def shrink(c, lg, kpa):
    """往聯盟平均拉：加上 kpa 個「聯盟平均」打席"""
    if not c or c.get("pa", 0) <= 0:
        return dict(lg)
    tot = sum(lg.values()) and lg["pa"]
    return {a: c.get(a, 0) + lg[a] / tot * kpa for a in lg}


def features(games, cfg):
    hl_sp, k_sp, hl_tm, hl_bp, hl_pk = cfg["hl_sp"], cfg["k_sp"], cfg["hl_team"], cfg["hl_bp"], 3 * 365
    SP, BP, BAT, PARK, LG, SPPA = Decay(hl_sp), Decay(hl_bp), Decay(hl_tm), Decay(hl_pk), Decay(365), Decay(hl_sp)
    out = []
    by_day = defaultdict(list)
    for g in games:
        by_day[g["dt"]].append(g)
    for day in sorted(by_day):
        now = (day - datetime(2000, 1, 1)).days
        lg = LG.get("lg", now)
        if lg and lg["pa"] > 20000:
            lgr = {a: v / lg["pa"] for a, v in lg.items()}
            lg_runs = lg["runs"] / lg["games"] if lg.get("games") else 4.5
            for g in by_day[day]:
                f = {}
                for side, team, opp, sp in (("h", g["home"], g["vis"], g["home_sp"]), ("a", g["vis"], g["home"], g["vis_sp"])):
                    c = shrink(SP.get(sp, now), {a: lgr[a] * 1000 for a in ("pa", "K", "BB", "HBP", "HR", "1B", "2B", "3B", "ROE")}, k_sp)
                    k, bb, hr, fip, woba = rates(c)
                    sppa = SPPA.get(sp, now)
                    share = min(0.85, max(0.3, (sppa["pa"] / sppa["n"]) / 38.5)) if sppa and sppa["n"] > 0.5 else 0.55
                    b = shrink(BP.get(team, now), {a: lgr[a] * 1000 for a in ("pa", "K", "BB", "HBP", "HR", "1B", "2B", "3B", "ROE")}, 300)
                    bat = shrink(BAT.get(team, now), {a: lgr[a] * 1000 for a in ("pa", "K", "BB", "HBP", "HR", "1B", "2B", "3B", "ROE")}, 400)
                    f[side] = {"sp_fip": fip, "sp_kbb": k - bb, "sp_woba": woba, "share": share, "bp_fip": rates(b)[3],
                               "bat_woba": rates(bat)[4], "bat_k": rates(bat)[0]}
                pk = PARK.get(g["park"], now)
                park = ((pk["runs"] + lg_runs * 2 * 30) / (pk["games"] + 30)) / (2 * lg_runs) if pk else 1.0
                h, a = f["h"], f["a"]
                # 每一隊「面對的投手」＝對方先發 × 先發吃掉的比例 ＋ 對方牛棚 × 剩下
                pit_vs_h = a["share"] * a["sp_fip"] + (1 - a["share"]) * a["bp_fip"]
                pit_vs_a = h["share"] * h["sp_fip"] + (1 - h["share"]) * h["bp_fip"]
                g2 = {k: g[k] for k in ("game_id", "date", "season", "home", "vis", "hs", "as", "oc_h", "oc_a", "oo_h", "oo_a", "total_line")}
                g2["x"] = [h["bat_woba"] - a["bat_woba"], pit_vs_a - pit_vs_h, a["sp_fip"] - h["sp_fip"], a["bp_fip"] - h["bp_fip"],
                           h["sp_kbb"] - a["sp_kbb"], a["bat_k"] - h["bat_k"]]
                g2["xt"] = [h["bat_woba"] + a["bat_woba"], pit_vs_h + pit_vs_a, park, h["sp_kbb"] + a["sp_kbb"]]
                out.append(g2)
        # 更新（這一天的比賽都算完才更新）
        for g in by_day[day]:
            for r in g["lines"]:
                c = line_counts(r)
                if r["starter"] == "1":
                    SP.add(r["pitcher"], now, c)
                    SPPA.add(r["pitcher"], now, {"pa": c["pa"], "n": 1.0})
                else:
                    SP.add(r["pitcher"], now, {a: v * 0.5 for a, v in c.items()})     # 後援出賽也算，但打折
                    BP.add(r["team"], now, c)
                LG.add("lg", now, c)
            for team, r in g["bats"].items():
                BAT.add(team, now, line_counts(r))
            PARK.add(g["park"], now, {"runs": g["hs"] + g["as"], "games": 1.0})
            LG.add("lg", now, {"runs": g["hs"] + g["as"], "games": 1.0})
    return out


def second_stage(feats, season):
    tr = [f for f in feats if FIRST_TRAIN <= f["season"] < season]
    te = [f for f in feats if f["season"] == season]
    if len(tr) < 3000 or not te:
        return []
    X = np.array([f["x"] for f in tr])
    mu, sd = X.mean(0), X.std(0) + 1e-9
    y = np.array([int(f["hs"] > f["as"]) for f in tr])
    lr = LogisticRegression(C=1.0, max_iter=1000).fit((X - mu) / sd, y)
    Xt = np.array([[1, *f["xt"]] for f in tr])
    yt = np.array([f["hs"] + f["as"] for f in tr], float)
    bt = np.linalg.lstsq(Xt, yt, rcond=None)[0]
    m = Xt @ bt
    var = float(np.mean((yt - m) ** 2))
    mbar = float(m.mean())
    r_disp = max(2.0, mbar ** 2 / max(var - mbar, 0.5))           # 負二項分布的離散程度
    out = []
    pr = lr.predict_proba((np.array([f["x"] for f in te]) - mu) / sd)[:, 1]
    for f, p in zip(te, pr):
        tm = float(np.array([1, *f["xt"]]) @ bt)
        r = {"season": f["season"], "date": f["date"], "home": f["home"], "away": f["vis"], "p": float(p), "y": int(f["hs"] > f["as"]),
             "oc_h": f["oc_h"], "oc_a": f["oc_a"], "oo_h": f["oo_h"], "oo_a": f["oo_a"],
             "pc": E.devig2(f["oc_h"], f["oc_a"]), "po": E.devig2(f["oo_h"], f["oo_a"]), "pred_t": tm, "total": f["hs"] + f["as"]}
        T = f["total_line"]
        if T:
            pnb = r_disp / (r_disp + tm)
            r["ou"] = float(1 - nbinom.cdf(math.floor(T), r_disp, pnb)) / (1 - (float(nbinom.pmf(int(T), r_disp, pnb)) if T == int(T) else 0))
            r["ou_hit"] = None if r["total"] == T else int(r["total"] > T)
            r["total_line"] = T
        out.append(r)
    return out


def run(games, cfg, seasons):
    feats = features(games, cfg)
    preds = []
    for s in range(seasons[0], seasons[1] + 1):
        preds += second_stage(feats, s)
    return preds


def evaluate(preds, blend=None):
    return {"ml": E.ml_eval(preds, blend), "total": E.line_eval(preds, "ou"), "n_games": len(preds)}


GRID = [{"hl_sp": a, "k_sp": b, "hl_team": c, "hl_bp": d} for a in (180, 365, 730) for b in (100, 250) for c in (60, 180) for d in (60, 180)]


def main():
    rep_path = os.path.join(OUT, "us_report.json")
    rep = json.load(open(rep_path, encoding="utf-8")) if os.path.exists(rep_path) else {}
    R = rep.setdefault("mlb", {})
    games = load()
    print(f"MLB {len(games)} 場，有收盤 {sum(1 for g in games if g['oc_h'])}、有開盤 {sum(1 for g in games if g['oo_h'])}", flush=True)
    if "--tune" in sys.argv:
        grid = []
        for cfg in GRID:
            ev = evaluate(run(games, cfg, VALID))
            grid.append({**cfg, "ll_model": ev["ml"]["ll_model"], "ll_close": ev["ml"]["ll_close"], "ll_base": ev["ml"]["ll_base"], "n": ev["ml"]["n"]})
            print(json.dumps(grid[-1]), flush=True)
        best = min(grid, key=lambda g: g["ll_model"])
        c = {k: best[k] for k in ("hl_sp", "k_sp", "hl_team", "hl_bp")}
        ev = evaluate(run(games, c, VALID))
        R.update({"grid": grid, "chosen": c, "valid": ev, "blend_ab": [ev["ml"]["blend"]["a"], ev["ml"]["blend"]["b"]],
                  "tuned_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                  "data": {"games": len(games), "first": games[0]["date"], "last": games[-1]["date"]}})
        E.save_sport(rep_path, "mlb", R)
        print("MLB 驗證完成：", c, ev["ml"]["ll_model"], ev["ml"]["ll_close"])
    elif "--final-test" in sys.argv:
        if R.get("test"):
            print("MLB 最後兩季已經考過了，不能重考")
            return
        c = R["chosen"]
        ev = evaluate(run(games, c, TEST), blend=R["blend_ab"])
        R["test"] = {"run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "config": c, **ev}
        E.save_sport(rep_path, "mlb", R)
        log = os.path.join(OUT, "test_log.json")
        hist = json.load(open(log)) if os.path.exists(log) else []
        hist.append({"stage": 2, "sport": "mlb", "run_utc": R["test"]["run_utc"], "config": c})
        json.dump(hist, open(log, "w"), ensure_ascii=False, indent=1)
        print("MLB 最後兩季考試完成：", ev["ml"]["ll_model"], ev["ml"]["ll_close"])


if __name__ == "__main__":
    main()
