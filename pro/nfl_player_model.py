"""
職業版・NFL 第 2 版：四分衛＋各位置「誰上場」（職業團隊的做法）
================================================================
第 1 版：球隊攻守效率（EPA）＋「這場傳球最多的四分衛」。問題：
  傳球最多的人是比賽打完才知道（先發受傷換替補，等於偷看結果）；其他位置誰缺陣完全沒算。
第 2 版（資料：nflverse 出場次數 2013 起、官方傷兵報告、每一次傳球回合）：
- 四分衛評分跟著人走：自己每一次傳球回合（含被擒殺、自己跑）的平均 EPA，越近越重要；
  回合數少的往「新人／替補平均」拉（替補通常比平均差）。換隊也帶著。
- 先發四分衛 vs 這隊平常的四分衛：差多少（第 1 版的球隊效率裡已經含平常那位）。
- 其他位置：每位球員自己的「平常出場比例」（教練覺得他多好），跟著人走，新秀用選秀順位起步。
  這場這隊每個位置（跑衛、外接、近端鋒、進攻線、防守線、線衛、防守後衛）取前幾名加起來＝這個位置今天的完整度。
- 再加上第 1 版的球隊效率、主場、休息天數、天氣。
三種「知道誰上場」的方式（公平檢查）：
  actual＝這場實際上場的人（開賽前 90 分鐘公布不上場名單，收盤時知道）
  report＝前 3 場有上場的人，扣掉這週官方傷兵報告 Out／Doubtful（週五就知道）
  prev＝前 3 場有上場的人（開盤時就知道）
注意：2024、2025 兩季第 1 版考過，第 2 版在那兩季只當參考；NFL 沒有歷史開盤，沒辦法看盤口移動。
用法：python3 -m pro.nfl_player_model --tune / --lineups / --reference-test
"""
import csv
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

from pro import nfl_model as V1
from pro import us_eval as E

D = V1.D
OUT = V1.OUT
GROUPS = {"RB": ("RB", "FB", "HB"), "WR": ("WR",), "TE": ("TE",), "OL": ("T", "G", "C", "OL", "OT", "OG", "LT", "RT", "LG", "RG"),
          "DL": ("DE", "DT", "NT", "DL"), "LB": ("LB", "ILB", "OLB", "MLB"), "DB": ("CB", "S", "SS", "FS", "DB")}
TOPK = {"RB": 1, "WR": 3, "TE": 1, "OL": 5, "DL": 4, "LB": 2, "DB": 5}
OFF = {"RB", "WR", "TE", "OL"}
GROUP_OF = {p: g for g, ps in GROUPS.items() for p in ps}
ROUND_PRIOR = {1: 0.6, 2: 0.45, 3: 0.32, 4: 0.22, 5: 0.15}


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_players():
    by_pfr, gsis2pfr = {}, {}
    for r in csv.DictReader(open(os.path.join(D, "players.csv"), encoding="utf-8")):
        rd = fnum(r["draft_round"])
        if r["pfr"]:
            by_pfr[r["pfr"]] = {"round": int(rd) if rd else None, "pos": r["pos"]}
        if r["gsis"] and r["pfr"]:
            gsis2pfr[r["gsis"]] = r["pfr"]
    return by_pfr, gsis2pfr


def load_extra():
    snaps = defaultdict(list)
    with gzip.open(os.path.join(D, "snaps.csv.gz"), "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            g = GROUP_OF.get(r["pos"])
            if not g:
                continue
            pct = fnum(r["off_pct"] if g in OFF else r["def_pct"]) or 0.0
            n = fnum(r["off"] if g in OFF else r["def"]) or 0.0
            if n > 0:
                snaps[r["game_id"]].append((V1.MOVE.get(r["team"], r["team"]), r["pfr"], g, pct))
    qb = defaultdict(list)
    with gzip.open(os.path.join(D, "qb_games.csv.gz"), "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            qb[r["game_id"]].append((V1.MOVE.get(r["team"], r["team"]), r["qb"], float(r["dropbacks"]), float(r["epa"]), r["starter"] == "1"))
    inj = defaultdict(set)
    with gzip.open(os.path.join(D, "injuries.csv.gz"), "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["report_status"] in ("Out", "Doubtful"):
                inj[(int(r["season"]), int(r["week"]), V1.MOVE.get(r["team"], r["team"]))].add(r["gsis_id"])
    ros = {}
    with gzip.open(os.path.join(D, "rosters.csv.gz"), "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            k = (int(r["season"]), int(r["week"]), V1.MOVE.get(r["team"], r["team"]))
            for pid in (r["pfr"], r["gsis"]):
                if pid:
                    ros[(*k, pid)] = r["status"]
    return snaps, qb, inj, ros


class Decay:
    def __init__(self, hl):
        self.hl, self.v = hl, {}

    def get(self, k, now):
        x = self.v.get(k)
        if not x:
            return None
        f = 0.5 ** ((now - x[0]) / self.hl)
        return [a * f for a in x[1]]

    def add(self, k, now, vals):
        cur = self.get(k, now) or [0.0] * len(vals)
        self.v[k] = (now, [a + b for a, b in zip(cur, vals)])


def features(games, tg, extra, players, cfg):
    snaps, qbg, inj, ros = extra
    seen = defaultdict(dict)                  # 隊 → 球員 → (最後一次幫這隊上場的時間, 位置)
    by_pfr, gsis2pfr = players
    R = V1.Ratings(games, tg, cfg["team_hl"], cfg["team_ridge"])
    QB = Decay(cfg["hl_qb"])                  # 四分衛：回合數、EPA
    TQ = Decay(cfg["hl_tq"])                  # 這隊各四分衛的回合數（找「平常那位」）
    SH = Decay(cfg["hl_share"])               # 球員：出場比例和、場數
    KQ, KS = cfg["k_qb"], 2.0
    mode = cfg.get("lineup", "actual")
    recent = defaultdict(list)                # 隊 → 最近 3 場上場名單 [(pfr, group)]
    last_start = {}                           # 隊 → 上一場先發四分衛
    cur_team = {}
    # 新人／替補四分衛的平均（2009 年以前的資料算，之後固定）
    pri_s, pri_n, career = 0.0, 0.0, defaultdict(float)
    prior_qb = -0.1
    by_week = defaultdict(list)
    for g in games:
        by_week[(g["season"], g["week"], g["season_type"])].append(g)
    out = []
    for key in sorted(by_week, key=lambda k: min(x["dt"] for x in by_week[k])):
        gs = by_week[key]
        wk_dt = min(x["dt"] for x in gs)
        now = (wk_dt - datetime(2000, 1, 1)).days
        if wk_dt.year >= 2009 and pri_n > 0 and prior_qb == -0.1:
            prior_qb = pri_s / pri_n
        fit = R.fit(wk_dt) if gs[0]["season"] >= V1.FIRST_PRED else None

        def qb_rating(q):
            x = QB.get(q, now)
            n, e = (x if x else (0.0, 0.0))
            return (e + prior_qb * KQ) / (n + KQ)

        def share(p, g):
            x = SH.get(p, now)
            info = by_pfr.get(p) or {}
            pr = ROUND_PRIOR.get(info.get("round"), 0.1) if info.get("round") else 0.1
            s, n = (x if x else (0.0, 0.0))
            return (s + pr * KS) / (n + KS)

        for g in gs:
            if not fit:
                continue
            gid = g["game_id"]
            feats = {}
            for side in ("home", "away"):
                t = g[side]
                # 這場的名單
                if mode == "actual" or not recent.get(t):
                    lu = [(p, grp) for (tm, p, grp, pct) in snaps.get(gid, []) if tm == t]
                else:
                    pool = {}
                    for game_lu in recent[t]:
                        for p, grp in game_lu:
                            if cur_team.get(p) == t:
                                pool[p] = grp
                    if mode == "report":
                        # 週中就知道的：每週名單（傷兵名單 RES、被釋出的不算；從傷兵名單回來的算回去）＋官方傷兵報告 Out／Doubtful
                        wk = (g["season"], int(g["week"]), t)
                        for p, (tl, grp) in seen[t].items():
                            if cur_team.get(p) == t and now - tl < 300 and ros.get((*wk, p)) == "ACT":
                                pool[p] = grp
                        out_p = {gsis2pfr.get(x) for x in inj.get(wk, set())}
                        pool = {p: grp for p, grp in pool.items() if p not in out_p and ros.get((*wk, p), "ACT") in ("ACT", "INA")}
                    lu = list(pool.items())
                have_snaps = bool(snaps.get(gid))
                grp_val = {}
                for grp in GROUPS:
                    vals = sorted((share(p, gg) for p, gg in lu if gg == grp), reverse=True)[:TOPK[grp]]
                    vals += [0.05] * (TOPK[grp] - len(vals))
                    grp_val[grp] = sum(vals) if have_snaps else None
                # 先發四分衛
                rows = [x for x in qbg.get(gid, []) if x[0] == t]
                actual_st = next((x[1] for x in rows if x[4]), None)
                if mode == "actual" or t not in last_start:
                    st = actual_st
                else:
                    st = last_start[t]
                    if mode == "report":
                        wk = (g["season"], int(g["week"]), t)
                        outs = inj.get(wk, set()) | {q for (tt, q) in TQ.v if tt == t and ros.get((*wk, q), "ACT") not in ("ACT", "INA")}
                        if st in outs:
                            cands = [(q, (TQ.get((t, q), now) or [0])[0]) for (tt, q) in TQ.v if tt == t and q != st and q not in outs]
                            st = max(cands, key=lambda c: c[1])[0] if cands else st
                usual = max(((q, (TQ.get((tt, q), now) or [0])[0]) for (tt, q) in list(TQ.v) if tt == t), key=lambda c: c[1], default=(None, 0))[0]
                q_st = qb_rating(st) if st else prior_qb
                q_us = qb_rating(usual) if usual else q_st
                feats[side] = (grp_val, q_st, q_us)
            mu_e, oe, de, he = fit["e"]
            mu_p, op, dp, hp = fit["p"]
            i, j = R.ti[g["home"]], R.ti[g["away"]]
            hm = 0 if g["neutral"] else 1
            eh, ea = mu_e + oe[i] - de[j] + he * hm, mu_e + oe[j] - de[i] - he * hm
            ph, pa = mu_p + op[i] - dp[j] + hp * hm, mu_p + op[j] - dp[i] - hp * hm
            ps, ss = fit["pass"], fit["succ"]
            pdh, pda = ps[1][i] - ps[2][j], ps[1][j] - ps[2][i]
            sdh, sda = ss[1][i] - ss[2][j], ss[1][j] - ss[2][i]
            (gh, qh, uh), (ga, qa, ua) = feats["home"], feats["away"]
            gd = [(gh[k] - ga[k]) if gh[k] is not None and ga[k] is not None else 0.0 for k in GROUPS]
            hs, as_ = float(g["home_score"]), float(g["away_score"])
            xm = [eh - ea, ph - pa, qh - qa, (qh - uh) - (qa - ua), hm, g["rest_d"], pdh - pda, sdh - sda, *gd]
            xt = [eh + ea, ph + pa, 1.0 if g["roof"] in ("dome", "closed") else 0.0,
                  min(fnum(g["wind"]) or 0, 30) if g["roof"] not in ("dome", "closed") else 0.0,
                  1.0 if (fnum(g["temp"]) or 60) < 35 and g["roof"] not in ("dome", "closed") else 0.0,
                  qh + qa, (qh - uh) + (qa - ua)]
            out.append({**g, "x_m": xm, "x_t": xt, "margin": hs - as_, "total": hs + as_})
        # 這一週打完才更新
        for g in gs:
            gid = g["game_id"]
            for side in ("home", "away"):
                t = g[side]
                lu = [(p, grp) for (tm, p, grp, pct) in snaps.get(gid, []) if tm == t]
                if lu:
                    recent[t] = (recent[t] + [lu])[-3:]
                for (tm, p, grp, pct) in snaps.get(gid, []):
                    if tm == t:
                        SH.add(p, now, [pct, 1.0])
                        cur_team[p] = t
                        seen[t][p] = (now, grp)
            for (t, q, n, e, st) in qbg.get(gid, []):
                if g["season"] < 2009 and career[q] < 150:
                    pri_s += e
                    pri_n += n
                career[q] += n
                QB.add(q, now, [n, e])
                TQ.add((t, q), now, [n])
                if st:
                    last_start[t] = q
    return out


def ridge_stage(feats, season, alpha):
    """跟第 1 版一樣（分差、總分線性 → 常態分布），但加一點嶺迴歸讓新特徵穩一點"""
    tr = [f for f in feats if f["season"] < season]
    te = [f for f in feats if f["season"] == season]
    if len(tr) < 300 or not te:
        return []
    from scipy.stats import norm

    def fit(X, y):
        mu, sd = X.mean(0), X.std(0) + 1e-9
        Z = (X - mu) / sd
        b = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
        return lambda Xn: y.mean() + ((Xn - mu) / sd) @ b
    Xm, ym = np.array([f["x_m"] for f in tr]), np.array([f["margin"] for f in tr])
    fm = fit(Xm, ym)
    sm = float(np.std(ym - fm(Xm)))
    Xt, yt = np.array([f["x_t"] for f in tr]), np.array([f["total"] for f in tr])
    ft = fit(Xt, yt)
    st = float(np.std(yt - ft(Xt)))
    pm_, pt_ = fm(np.array([f["x_m"] for f in te])), ft(np.array([f["x_t"] for f in te]))
    out = []
    for f, m, t in zip(te, pm_, pt_):
        sl, tl = fnum(f["spread_line"]), fnum(f["total_line"])
        r = {"season": f["season"], "date": f["date"], "home": f["home"], "away": f["away"], "pred_m": float(m), "pred_t": float(t),
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


def coefs(feats, season, alpha):
    tr = [f for f in feats if f["season"] < season]
    X, y = np.array([f["x_m"] for f in tr]), np.array([f["margin"] for f in tr])
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    b = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
    names = ["球隊效率", "得分評分", "先發四分衛", "四分衛換人", "主場", "休息差", "傳球效率", "成功率"] + [f"{g} 完整度" for g in GROUPS]
    return dict(zip(names, [round(float(x), 3) for x in b]))


def run(games, tg, extra, players, cfg, seasons):
    feats = features(games, tg, extra, players, cfg)
    preds = []
    for s in range(seasons[0], seasons[1] + 1):
        preds += ridge_stage(feats, s, cfg["alpha"])
    return preds, coefs(feats, seasons[1], cfg["alpha"])


# 第一輪 365／730 天 × 100／300 回合 × 120／365 天，最好的在邊角（730、100、365），所以往外再試一圈
GRID = [{"team_hl": 180, "team_ridge": 32.0, "hl_qb": hq, "k_qb": kq, "hl_tq": 120, "hl_share": hs, "alpha": 5.0}
        for hq in (365, 730, 1460) for kq in (50.0, 100.0, 300.0) for hs in (120, 365, 730)]


def main():
    rep_path = os.path.join(OUT, "us_report.json")
    rep = json.load(open(rep_path, encoding="utf-8")) if os.path.exists(rep_path) else {}
    R = rep.get("nfl2", {})
    games, tg = V1.load()
    extra, players = load_extra(), load_players()
    print(f"NFL v2：{len(games)} 場、{len(extra[0])} 場有出場資料", flush=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    if "--tune" in sys.argv:
        grid = []
        for cfg in GRID:
            preds, _ = run(games, tg, extra, players, cfg, V1.VALID)
            ev = V1.evaluate(preds)
            grid.append({**cfg, "ll_model": ev["ml"]["ll_model"], "ll_close": ev["ml"]["ll_close"], "ll_base": ev["ml"]["ll_base"],
                         "n": ev["ml"]["n"], "mae": ev.get("mae")})
            print(json.dumps(grid[-1]), flush=True)
        best = min(grid, key=lambda g: g["ll_model"])
        R.update({"grid": grid, "chosen": {k: best[k] for k in GRID[0]}, "tuned_utc": stamp})
        E.save_sport(rep_path, "nfl2", R)
        print("NFL v2 挑好：", R["chosen"])
    elif "--lineups" in sys.argv:
        base = {k: v for k, v in R["chosen"].items() if k != "lineup"}
        cmp_ = {}
        for mode in ("actual", "report", "prev"):
            preds, cf = run(games, tg, extra, players, {**base, "lineup": mode}, V1.VALID)
            ev = V1.evaluate(preds)
            cmp_[mode] = {"valid": ev, "coefs": cf, "blend_ab": [ev["ml"]["blend"]["a"], ev["ml"]["blend"]["b"]]}
            print(mode, ev["ml"]["ll_model"], ev["ml"]["ll_close"], ev["ml"]["blend"], ev.get("mae"), flush=True)
        R["chosen"] = {**base, "lineup": "actual"}
        R["valid"], R["coefs"], R["blend_ab"] = cmp_["actual"]["valid"], cmp_["actual"]["coefs"], cmp_["actual"]["blend_ab"]
        R["modes"] = {m: {"valid": cmp_[m]["valid"], "blend_ab": cmp_[m]["blend_ab"]} for m in ("report", "prev")}
        E.save_sport(rep_path, "nfl2", R)
    elif "--reference-test" in sys.argv:
        if R.get("ref_test"):
            print("NFL v2 參考考試已經跑過了")
            return
        c = R["chosen"]
        preds, _ = run(games, tg, extra, players, c, V1.TEST)
        ev = V1.evaluate(preds, blend=R["blend_ab"])
        modes = {}
        for m in ("report", "prev"):
            pm, _ = run(games, tg, extra, players, {**c, "lineup": m}, V1.TEST)
            modes[m] = V1.evaluate(pm, blend=R["modes"][m]["blend_ab"])
        R["ref_test"] = {"run_utc": stamp, "config": c, **ev, "modes": modes,
                         "note": "這兩季第 1 版考過；第 2 版只用驗證季挑設定，這裡跑一次當參考"}
        E.save_sport(rep_path, "nfl2", R)
        log = os.path.join(OUT, "test_log.json")
        L = json.load(open(log, encoding="utf-8"))
        L.append({"stage": 3, "sport": "nfl2", "run_utc": stamp, "config": c, "note": "第 2 版參考考試（只當參考）"})
        json.dump(L, open(log, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("NFL v2 參考：", ev["ml"]["ll_model"], ev["ml"]["ll_close"], {m: modes[m]["ml"]["ll_model"] for m in modes})


if __name__ == "__main__":
    main()
