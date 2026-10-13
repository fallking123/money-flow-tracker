"""
職業版・MLB 第 2 版：每位打者、每位投手各自預測，再一個一個對決（職業團隊的做法）
================================================================
第 1 版：先發投手是個人，但打線、牛棚是「整隊平均」。第 2 版：
- 每位打者、每位投手各自的「預測」：三振、保送（含觸身）、全壘打、一壘、二壘、三壘安打各算各的，
  越近越重要；打席少的往聯盟平均拉，而且每一項拉的程度不同（三振幾十個打席就看得出來，安打要上千個）。
  投手的安打率幾乎是運氣，拉得最多。
- 對決：打者 × 投手用「勝算比」合起來（強打遇強投 ≈ 平均），再加上左右投打的差別（左打打右投比較好…）。
- 今天的打線（棒次越前面打越多次）× 對方先發投手，加上先發平常投幾個打者、剩下交給牛棚。
- 牛棚：最近幫這隊後援的每一位投手，依出場多少加權；昨天投很多、或連投兩天的，今天大概不能投，扣掉。
- 年齡（打線平均、先發投手）、球隊最近的得失分（守備、跑壘、教練這些個人數據看不到的）。
- 新秀和換隊：評分跟著人走，換隊第一場就算進新隊。投手上場打擊用「投手打擊平均」。
兩種名單（公平檢查）：actual＝今天實際先發打線（開賽前 2–4 小時公布）；prev＝這隊上一場的先發打線（開盤時就知道）。
先發投手兩種都用實際的（開盤時大多已經公布；臨時換人的比賽在 CLV 計算時排除）。
注意：2024、2025 兩季第 1 版考過，第 2 版在那兩季只當參考。
資料來源：Retrosheet（The information used here was obtained free of charge from and is copyrighted by Retrosheet.
Interested parties may contact Retrosheet at www.retrosheet.org.）；生日：Chadwick Baseball Bureau register。
用法：python3 -m pro.mlb_player_model --tune / --lineups / --reference-test
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
from scipy.stats import nbinom
from sklearn.linear_model import LogisticRegression

from pro import mlb_model as V1
from pro import us_eval as E

D = V1.D
OUT = V1.OUT
COMP = ["K", "BBH", "HR", "1B", "2B", "3B", "ROE"]             # 每個打席的結果（其餘是出局）
WOBA = np.array([0.0, 0.70, 2.03, 0.88, 1.25, 1.58, 0.88])
KB = np.array([60, 120, 170, 600, 900, 1500, 1500], float)      # 打者：每一項拉回聯盟平均的打席數
KP = np.array([70, 170, 400, 900, 1200, 2000, 2000], float)     # 投手
SLOT_PA = np.array([4.65, 4.55, 4.45, 4.35, 4.25, 4.13, 4.01, 3.90, 3.77])


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def vec(r, suf=""):
    """[PA, K, BB+HBP, HR, 1B, 2B, 3B, ROE]"""
    g = lambda k: fnum(r.get(k + suf))
    return np.array([g("pa"), g("K"), g("BB") + g("HBP"), g("HR"), g("1B"), g("2B"), g("3B"), g("ROE")])


def load_players():
    hands = {r["id"]: (r["bats"], r["throws"]) for r in csv.DictReader(open(os.path.join(D, "players.csv"), encoding="utf-8"))}
    birth = {}
    for r in csv.DictReader(open(os.path.join(D, "birth.csv"), encoding="utf-8")):
        try:
            birth[r["id"]] = datetime.strptime(r["birth"], "%Y-%m-%d")
        except ValueError:
            pass
    return hands, birth


def load_lines():
    bat, pit = defaultdict(list), defaultdict(list)
    with gzip.open(os.path.join(D, "bat_players.csv.gz"), "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            bat[r["game_id"]].append((r["team"], r["batter"], int(r["slot"]), r["starter"] == "1", vec(r), vec(r, "_L")))
    with gzip.open(os.path.join(D, "pitch_players.csv.gz"), "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pit[r["game_id"]].append((r["team"], r["pitcher"], r["starter"] == "1", fnum(r["pitches"]), vec(r), vec(r, "_L")))
    return bat, pit


class Decay:
    def __init__(self, hl):
        self.hl, self.v = hl, {}

    def get(self, k, now):
        x = self.v.get(k)
        if x is None:
            return None
        return x[1] * 0.5 ** ((now - x[0]) / self.hl)

    def add(self, k, now, arr):
        cur = self.get(k, now)
        self.v[k] = (now, arr.copy() if cur is None else cur + arr)


def odds(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return p / (1 - p)


def log5(b, p, lg):
    """勝算比：打者機率 × 投手機率 ÷ 聯盟（每一項各自算）"""
    o = odds(b) * odds(p) / odds(lg)
    return o / (1 + o)


def features(games, lines, players, cfg):
    bat, pit = lines
    hands, birth = players
    kmul = cfg["kmul"]
    BAT, PIT = Decay(cfg["hl_bat"]), Decay(cfg["hl_pit"])
    BATL, PITL = Decay(cfg["hl_bat"]), Decay(cfg["hl_pit"])       # 面對左投／左打
    LG = Decay(365.0)                                             # 聯盟：全部、四種左右組合、投手打擊
    SPBF = Decay(cfg["hl_pit"])                                   # 先發：每場面對幾個打者
    RELU = Decay(cfg["hl_rel"])                                   # (隊, 後援) 出場量
    TEAMR = Decay(180.0)                                          # 球隊得分、失分、場數
    PK = Decay(3 * 365.0)
    recent_pitch = defaultdict(list)                              # 投手 → [(日, 投球數)]
    RELT = defaultdict(set)                                       # 隊 → 幫這隊後援過的投手
    last_lu, cur_team, pitchers = {}, {}, set()
    mode = cfg.get("lineup", "actual")
    out = []
    by_day = defaultdict(list)
    for g in games:
        by_day[g["dt"]].append(g)
    for day in sorted(by_day):
        now = (day - datetime(2000, 1, 1)).days
        lg = LG.get("all", now)
        if lg is not None and lg[0] > 30000:
            lgr = lg[1:] / lg[0]
            plat = {}
            for bh in "LR":
                for ph in "LR":
                    x = LG.get(bh + ph, now)
                    plat[bh + ph] = (x[1:] / x[0]) / lgr if x is not None and x[0] > 2000 else np.ones(7)
            pb = LG.get("pbat", now)
            pbat = pb[1:] / pb[0] if pb is not None and pb[0] > 500 else lgr * np.array([1.8, 0.5, 0.2, 0.7, 0.5, 0.3, 0.8])
            runs = TEAMR.get("lg", now)
            lg_runs = runs[0] / runs[2] if runs is not None else 4.5

            def batter_rates(b):
                x = BAT.get(b, now)
                pa = x[0] if x is not None else 0.0
                base = pbat if (b in pitchers and pa < 300) else lgr
                k = KB * kmul
                return ((x[1:] if x is not None else 0) + base * k) / (pa + k), pa

            def pitcher_rates(p):
                x = PIT.get(p, now)
                pa = x[0] if x is not None else 0.0
                k = KP * kmul
                # 新投手（沒什麼紀錄）比平均差一點
                base = lgr * np.array([0.93, 1.08, 1.08, 1.02, 1.03, 1.0, 1.0]) if pa < 100 else lgr
                return ((x[1:] if x is not None else 0) + base * k) / (pa + k)

            def eff_hand(b, ph):
                bh = hands.get(b, ("R", "R"))[0]
                return ("R" if ph == "L" else "L") if bh == "B" else (bh if bh in "LR" else "R")

            def lineup_arrays(lineup):
                """打線每位打者的預測（n×7）、權重、面對左投／右投時的左右修正"""
                B = np.array([batter_rates(b)[0] for b, _ in lineup])
                W_ = np.array([w for _, w in lineup])
                P = {ph: np.array([plat[eff_hand(b, ph) + ph] for b, _ in lineup]) for ph in "LR"}
                return B, W_, P

            def matchup(arrs, p_rates, ph):
                """這個投手面對這個打線，平均每個打席的 wOBA"""
                if arrs is None:
                    return float(WOBA @ lgr)
                B, W_, P = arrs
                pr = log5(B, p_rates[None, :], lgr[None, :]) * P[ph]
                return float(W_ @ (pr @ WOBA))

            for g in by_day[day]:
                gid = g["game_id"]
                f = {}
                for side, team, opp, sp, osp in (("h", g["home"], g["vis"], g["home_sp"], g["vis_sp"]), ("a", g["vis"], g["home"], g["vis_sp"], g["home_sp"])):
                    # 打線
                    starters = sorted([(slot, b) for (t, b, slot, st, v, vl) in bat.get(gid, []) if t == team and st and 1 <= slot <= 9])
                    if mode == "prev" and team in last_lu:
                        starters = [(s, b) for s, b in last_lu[team] if cur_team.get(b) == team]
                    w = SLOT_PA[[s - 1 for s, _ in starters]] if starters else np.array([])
                    lineup = [(b, wi / w.sum()) for (s, b), wi in zip(starters, w)] if starters else []
                    arrs = lineup_arrays(lineup) if lineup else None
                    # 對方先發
                    ph = hands.get(osp, ("R", "R"))[1]
                    ph = ph if ph in "LR" else "R"
                    spr = pitcher_rates(osp)
                    vs_sp = matchup(arrs, spr, ph)
                    bf = SPBF.get(osp, now)
                    share = min(0.8, max(0.3, (bf[0] / bf[1]) / 38.5)) if bf is not None and bf[1] > 0.5 else 0.5
                    # 對方牛棚：最近幫對方後援的人，依出場量加權；昨天投很多或連兩天投的扣掉
                    rel = [(p, RELU.get((opp, p), now)[0]) for p in RELT[opp] if cur_team.get(p) == opp]
                    rel = [(p, u) for p, u in rel if u > 0.5]
                    tot_u, avail_u, vs_bp = 0.0, 0.0, 0.0
                    for p, u in rel:
                        rp = [(d, n) for d, n in recent_pitch.get(p, []) if now - d <= 3]
                        y = sum(n for d, n in rp if now - d == 1)
                        tired = y >= 25 or (any(now - d == 1 for d, _ in rp) and any(now - d == 2 for d, _ in rp)) or sum(n for _, n in rp) >= 50
                        tot_u += u
                        if not tired:
                            avail_u += u
                            rph = hands.get(p, ("R", "R"))[1]
                            vs_bp += u * matchup(arrs, pitcher_rates(p), rph if rph in "LR" else "R")
                    vs_bp = vs_bp / avail_u if avail_u > 0 else float(WOBA @ lgr) * 1.03
                    tired_frac = 1 - avail_u / tot_u if tot_u > 0 else 0.0
                    tr = TEAMR.get(team, now)
                    rs, ra = ((tr[0] + lg_runs * 10) / (tr[2] + 10), (tr[1] + lg_runs * 10) / (tr[2] + 10)) if tr is not None else (lg_runs, lg_runs)
                    ages = [((day - birth[b]).days / 365.25) for b, _ in lineup if b in birth]
                    f[side] = {"vs_sp": vs_sp, "vs_bp": vs_bp, "share": share, "tired": tired_frac, "rs": rs, "ra": ra,
                               "age": float(np.mean(ages)) if ages else 28.5,
                               "sp_age": ((day - birth[osp]).days / 365.25) if osp in birth else 29.0,
                               "sp_k": float(spr[0] - spr[1]), "n_lu": len(lineup)}
                h, a = f["h"], f["a"]
                eh = h["share"] * h["vs_sp"] + (1 - h["share"]) * h["vs_bp"]
                ea = a["share"] * a["vs_sp"] + (1 - a["share"]) * a["vs_bp"]
                pk = PK.get(g["park"], now)
                park = ((pk[0] + lg_runs * 2 * 30) / (pk[1] + 30)) / (2 * lg_runs) if pk is not None else 1.0
                g2 = {k: g[k] for k in ("game_id", "date", "season", "home", "vis", "hs", "as", "oc_h", "oc_a", "oo_h", "oo_a", "total_line")}
                # h["sp_age"] 是對方（客隊）先發的年齡
                g2["x"] = [eh - ea, h["vs_sp"] - a["vs_sp"], h["vs_bp"] - a["vs_bp"], h["tired"] - a["tired"],
                           (h["rs"] - h["ra"]) - (a["rs"] - a["ra"]), h["age"] - a["age"], h["sp_age"] - a["sp_age"], a["sp_k"] - h["sp_k"]]
                g2["xt"] = [eh + ea, park, h["tired"] + a["tired"], h["rs"] + h["ra"] + a["rs"] + a["ra"]]
                out.append(g2)
        # 更新（這一天的比賽都算完才更新）
        for g in by_day[day]:
            gid = g["game_id"]
            for (t, p, st, npitch, v, vl) in pit.get(gid, []):
                pitchers.add(p)
                cur_team[p] = t
                PIT.add(p, now, v)
                PITL.add(p, now, vl)
                if st:
                    SPBF.add(p, now, np.array([v[0], 1.0]))
                else:
                    RELU.add((t, p), now, np.array([v[0]]))
                    RELT[t].add(p)
                recent_pitch[p] = [(d, n) for d, n in recent_pitch[p] if now - d < 4] + [(now, npitch)]
                ph = hands.get(p, ("R", "R"))[1]
                ph = ph if ph in "LR" else "R"
                vr = v - vl                                           # 面對右打
                for bh, vv in (("L", vl), ("R", vr)):
                    if vv[0] > 0:
                        LG.add(bh + ph, now, vv)
            lu = []
            for (t, b, slot, st, v, vl) in bat.get(gid, []):
                BAT.add(b, now, v)
                BATL.add(b, now, vl)
                cur_team[b] = t
                LG.add("all", now, v)
                if b in pitchers and (BAT.get(b, now)[0] < 300):
                    LG.add("pbat", now, v)
                if st and 1 <= slot <= 9:
                    lu.append((t, slot, b))
            for t in {x[0] for x in lu}:
                last_lu[t] = sorted((s, b) for tt, s, b in lu if tt == t)
            TEAMR.add(g["home"], now, np.array([g["hs"], g["as"], 1.0]))
            TEAMR.add(g["vis"], now, np.array([g["as"], g["hs"], 1.0]))
            TEAMR.add("lg", now, np.array([g["hs"] + g["as"], 0.0, 2.0]))
            PK.add(g["park"], now, np.array([g["hs"] + g["as"], 1.0]))
    return out


NAMES = ["整體對決", "打線 vs 先發", "打線 vs 牛棚", "對方牛棚累", "球隊得失分", "打線年齡", "對方先發年齡", "先發三振減保送"]


def second_stage(feats, season, C):
    tr = [f for f in feats if V1.FIRST_TRAIN <= f["season"] < season]
    te = [f for f in feats if f["season"] == season]
    if len(tr) < 3000 or not te:
        return [], None
    X = np.array([f["x"] for f in tr])
    mu, sd = X.mean(0), X.std(0) + 1e-9
    y = np.array([int(f["hs"] > f["as"]) for f in tr])
    lr = LogisticRegression(C=C, max_iter=2000).fit((X - mu) / sd, y)
    Xt = np.array([[1, *f["xt"]] for f in tr])
    yt = np.array([f["hs"] + f["as"] for f in tr], float)
    bt = np.linalg.lstsq(Xt, yt, rcond=None)[0]
    m = Xt @ bt
    var, mbar = float(np.mean((yt - m) ** 2)), float(m.mean())
    r_disp = max(2.0, mbar ** 2 / max(var - mbar, 0.5))
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
    return out, dict(zip(NAMES, [round(float(x), 3) for x in lr.coef_[0]]))


def run(games, lines, players, cfg, seasons):
    feats = features(games, lines, players, cfg)
    preds, coefs = [], None
    for s in range(seasons[0], seasons[1] + 1):
        p, c = second_stage(feats, s, cfg["C"])
        preds += p
        coefs = c or coefs
    return preds, coefs


GRID = [{"hl_bat": hb, "hl_pit": hp, "hl_rel": 30.0, "kmul": km, "C": 1.0}
        for hb in (365.0, 730.0) for hp in (365.0, 730.0) for km in (0.6, 1.0, 1.6)]


def main():
    rep_path = os.path.join(OUT, "us_report.json")
    rep = json.load(open(rep_path, encoding="utf-8")) if os.path.exists(rep_path) else {}
    R = rep.get("mlb2", {})
    games = V1.load()
    lines, players = load_lines(), load_players()
    print(f"MLB v2：{len(games)} 場", flush=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    if "--smoke" in sys.argv:
        cfg = {**GRID[0], "lineup": sys.argv[-1] if sys.argv[-1] in ("actual", "prev") else "actual"}
        preds, coefs = run(games, lines, players, cfg, (2018, 2019))
        ev = V1.evaluate(preds)
        print(json.dumps({"ll": ev["ml"]["ll_model"], "close": ev["ml"]["ll_close"], "base": ev["ml"]["ll_base"], "blend": ev["ml"]["blend"],
                          "calm": ev["ml"]["clv"].get("calm_0.03")}, ensure_ascii=False), coefs)
    elif "--tune" in sys.argv:
        grid = []
        for cfg in GRID:
            preds, _ = run(games, lines, players, cfg, V1.VALID)
            ev = V1.evaluate(preds)
            grid.append({**cfg, "ll_model": ev["ml"]["ll_model"], "ll_close": ev["ml"]["ll_close"], "ll_base": ev["ml"]["ll_base"], "n": ev["ml"]["n"]})
            print(json.dumps(grid[-1]), flush=True)
        best = min(grid, key=lambda g: g["ll_model"])
        R.update({"grid": grid, "chosen": {k: best[k] for k in GRID[0]}, "tuned_utc": stamp})
        E.save_sport(rep_path, "mlb2", R)
        print("MLB v2 挑好：", R["chosen"])
    elif "--lineups" in sys.argv:
        base = {k: v for k, v in R["chosen"].items() if k != "lineup"}
        cmp_ = {}
        for mode in ("actual", "prev"):
            preds, cf = run(games, lines, players, {**base, "lineup": mode}, V1.VALID)
            ev = V1.evaluate(preds)
            cmp_[mode] = {"valid": ev, "coefs": cf, "blend_ab": [ev["ml"]["blend"]["a"], ev["ml"]["blend"]["b"]]}
            print(mode, ev["ml"]["ll_model"], ev["ml"]["ll_close"], ev["ml"]["blend"], ev["ml"]["clv"].get("calm_0.03"), flush=True)
        R["chosen"] = {**base, "lineup": "actual"}
        R["valid"], R["coefs"], R["blend_ab"] = cmp_["actual"]["valid"], cmp_["actual"]["coefs"], cmp_["actual"]["blend_ab"]
        R["open_model"] = {"lineup": "prev", **cmp_["prev"]}
        E.save_sport(rep_path, "mlb2", R)
    elif "--reference-test" in sys.argv:
        if R.get("ref_test"):
            print("MLB v2 參考考試已經跑過了")
            return
        c = R["chosen"]
        preds, _ = run(games, lines, players, c, V1.TEST)
        ev = V1.evaluate(preds, blend=R["blend_ab"])
        po, _ = run(games, lines, players, {**c, "lineup": "prev"}, V1.TEST)
        evo = V1.evaluate(po, blend=R["open_model"]["blend_ab"])
        R["ref_test"] = {"run_utc": stamp, "config": c, **ev, "open_model": evo,
                         "note": "這兩季第 1 版考過；第 2 版只用驗證季挑設定，這裡跑一次當參考"}
        E.save_sport(rep_path, "mlb2", R)
        log = os.path.join(OUT, "test_log.json")
        L = json.load(open(log, encoding="utf-8"))
        L.append({"stage": 3, "sport": "mlb2", "run_utc": stamp, "config": c, "note": "第 2 版參考考試（只當參考）"})
        json.dump(L, open(log, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("MLB v2 參考：", ev["ml"]["ll_model"], ev["ml"]["ll_close"], evo["ml"]["ll_model"], evo["ml"]["clv"].get("calm_0.03"))


if __name__ == "__main__":
    main()
