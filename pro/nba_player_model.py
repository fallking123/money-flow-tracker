"""
職業版・NBA 第 2 版：用「球員」組出球隊（職業團隊的做法）
================================================================
第 1 版用「球隊」算球隊：交易、新秀、休賽季換人都要打好幾場才反映。這一版改成：
- 每位球員自己的評分（跟著球員走，換隊也帶著）：每 36 分鐘的
  得分效率（得分 − 出手數，投得準才高）、出手量、三分出手、進攻／防守籃板、助攻、抄截、火鍋、失誤、犯規、場上正負值；
  多季記憶（越近越重要），上場分鐘少的往「新人／替補平均」拉。
- 年齡（年輕會進步、老將會退步）、新秀用選秀順位當起始評分。
- 預計上場分鐘：每位球員最近平均打幾分鐘（不管在哪一隊）。
- 這場這隊有誰上場（開賽前看先發名單／傷兵報告就知道），用預計分鐘當權重加起來＝這隊今天的強度。
  交易：球員到新隊第一場就算進新隊；新秀：用選秀順位；休賽季：新陣容開季第一場就用上。
- 再加上第 1 版的球隊效率（教練、戰術這些球員數據看不到的）、主場、背靠背、休息天數。
第二層（用之前幾季學每個特徵值多少分）：分差、總分 → 主勝、過盤、大分機率。

注意：2024–25、2025–26 兩季第 1 版已經考過，這一版在那兩季的成績只當「參考」；
真正的考試是即將開打的 2026–27 季（第 4 階段每天記錄）。挑設定只看驗證季。
用法：python3 -m pro.nba_player_model --tune   /   --reference-test
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.stats import norm

from pro import nba_model as V1
from pro import us_eval as E

D = V1.D
OUT = V1.OUT
STATS = ["min", "pts", "fga", "fta", "fg3a", "oreb", "dreb", "ast", "stl", "blk", "tov", "pf"]
FEAT = ["eff", "usg", "fg3a", "oreb", "dreb", "ast", "stl", "blk", "tov", "pf", "pm", "age", "age2", "rookie_pick"]


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def load_players():
    info = {}
    for r in csv.DictReader(open(os.path.join(D, "players.csv"), encoding="utf-8")):
        pid = str(int(float(r["athlete_id"]))) if r.get("athlete_id") else None
        if not pid:
            continue
        dob = r.get("date_of_birth") or ""
        try:
            dob = datetime.strptime(dob[:10], "%Y-%m-%d")
        except ValueError:
            dob = None
        pick = fnum(r.get("draft_selection"))
        rnd = fnum(r.get("draft_round"))
        overall = (pick + (30 if rnd == 2 else 0)) if pick else None
        info[pid] = {"dob": dob, "pick": overall, "draft_year": fnum(r.get("draft_year"))}
    return info


def load_box():
    box = defaultdict(list)
    for r in csv.DictReader(open(os.path.join(D, "player_games.csv"), encoding="utf-8")):
        m = fnum(r["min"])
        if not m or m <= 0:
            continue
        pid = str(int(float(r["player"]))) if r["player"] else None
        if not pid:
            continue
        v = {k: (fnum(r.get(k)) or 0.0) for k in STATS[1:]}
        v["min"] = m
        pm = r["pm"]
        v["pm"] = fnum(pm.replace("+", "")) if pm not in ("--", "", None) else None
        box[r["game_id"]].append((r["team"], pid, v))
    return box


class PlayerState:
    def __init__(self, hp, hm):
        self.hp, self.hm = hp, hm
        self.s = {}          # pid → (t, np.array 統計), 加上 pm 的 (和, 分鐘)
        self.pm = {}
        self.em = {}         # pid → (t, 平均分鐘)
        self.n = defaultdict(float)   # 生涯分鐘

    def _dec(self, t0, now, hl):
        return 0.5 ** ((now - t0) / hl)

    def get(self, pid, now):
        x = self.s.get(pid)
        st = x[1] * self._dec(x[0], now, self.hp) if x else np.zeros(len(STATS))
        y = self.pm.get(pid)
        pm = (y[1] * self._dec(y[0], now, self.hp), y[2] * self._dec(y[0], now, self.hp)) if y else (0.0, 0.0)
        return st, pm

    def exp_min(self, pid, now):
        x = self.em.get(pid)
        if not x:
            return None
        return x[1] if now - x[0] < 120 else x[1] * 0.85       # 很久沒上場（休賽季、長期傷停）打個折

    def add(self, pid, now, v):
        st, (ps, pmn) = self.get(pid, now)
        st = st + np.array([v[k] for k in STATS])
        self.s[pid] = (now, st)
        if v["pm"] is not None:
            self.pm[pid] = (now, ps + v["pm"], pmn + v["min"])
        e = self.em.get(pid)
        if e and now - e[0] < 120:
            a = 1 - self._dec(0, 3.0, self.hm)      # 每場往新數字靠一點
            self.em[pid] = (now, e[1] * (1 - a) + v["min"] * a)
        else:
            self.em[pid] = (now, v["min"])
        self.n[pid] += v["min"]


def player_vec(ps, pid, now, info, dt, prior, K, Kpm):
    st, (pms, pmm) = ps.get(pid, now)
    mins = st[0]
    rate = lambda i: (st[i] + prior[STATS[i]] * K / 36) / (mins + K) * 36
    d = {s: rate(i) for i, s in enumerate(STATS) if i > 0}
    eff = d["pts"] - 1.0 * (d["fga"] + 0.44 * d["fta"])
    usg = d["fga"] + 0.44 * d["fta"] + d["tov"]
    pm = (pms + prior["pm"] * Kpm / 36) / (pmm + Kpm) * 36
    i = info.get(pid) or {}
    age = ((dt - i["dob"]).days / 365.25) if i.get("dob") else 26.0
    a = age - 27.0
    young = ps.n[pid] < 1500
    pick = i.get("pick")
    rp = (max(0.0, 61 - pick) / 60 if pick else 0.0) if young else 0.0
    return np.array([eff, usg, d["fg3a"], d["oreb"], d["dreb"], d["ast"], d["stl"], d["blk"], d["tov"], d["pf"], pm, a, a * a, rp])


def features(games, box, info, cfg):
    hp, hm, K, Kpm = cfg["hp"], cfg["hm"], cfg["K"], cfg["Kpm"]
    ps = PlayerState(hp, hm)
    # 新人／替補平均（只用 2009 年以前的資料算，避免偷看未來）
    tot, pmt, pmm = defaultdict(float), 0.0, 0.0
    first = {}
    R = V1.Ratings(games, cfg["team_hl"], 5.0)
    weeks = defaultdict(list)
    for g in games:
        weeks[g["dt"] - timedelta(days=g["dt"].weekday())].append(g)
    prior = {s: 0.0 for s in STATS}
    prior["pm"] = -2.0
    prior_set = False
    last_game = {}
    last_lineup, cur_team = {}, {}
    mode = cfg.get("lineup", "actual")
    out = []
    for wk in sorted(weeks):
        fit = R.fit(wk)
        if not prior_set and wk.year >= 2009 and tot["min"] > 0:
            for s in STATS[1:]:
                prior[s] = tot[s] / tot["min"] * 36
            prior["pm"] = pmt / pmm * 36 if pmm else -2.0
            prior_set = True
        for g in sorted(weeks[wk], key=lambda x: x["dt"]):
            now = (g["dt"] - datetime(2000, 1, 1)).days
            plist = box.get(g["game_id"], [])
            agg = {}
            for side in ("home", "away"):
                ws, vs = [], []
                if mode == "prev":       # 開盤時：只知道這隊上一場誰上場（不偷看今天的名單）
                    roster = [p for p in last_lineup.get(g[side], []) if cur_team.get(p) == g[side]]
                else:                    # 收盤時：今天有上場的人（開賽前先發／傷兵名單就知道）
                    roster = [pid for team, pid, v in plist if team == g[side]]
                for pid in roster:
                    em = ps.exp_min(pid, now)
                    if mode == "actual10" and em is not None and em < 10:
                        continue         # 垃圾時間才上的替補不算（避免「大比分才會上場」偷看到結果）
                    em = em or 12.0
                    ws.append(em)
                    vs.append(player_vec(ps, pid, now, info, g["dt"], prior, K, Kpm))
                if ws:
                    w = np.array(ws) / sum(ws)
                    agg[side] = (np.array(vs) * w[:, None]).sum(0)
            rest = {s: ((g["dt"] - last_game[g[s]]).days if g[s] in last_game else 3) for s in ("home", "away")}
            if fit and len(agg) == 2 and prior_set:
                (mu, o, d, h), (pmu, po, pd, _) = fit
                i, j = R.ti[g["home"]], R.ti[g["away"]]
                eh, ea = mu + o[i] - d[j] + h, mu + o[j] - d[i] - h
                pace = pmu + po[i] + po[j] - pd[i] - pd[j]
                b2b = lambda x: 1.0 if x <= 1 else 0.0
                diff = agg["home"] - agg["away"]
                summ = agg["home"] + agg["away"]
                out.append({**{k: g[k] for k in ("game_id", "season", "date", "home", "away", "hs", "as", "oc_h", "oc_a", "oo_h", "oo_a", "spread", "total_line", "playoff")},
                            "x_m": [*diff, (eh - ea) * pace / 100, b2b(rest["home"]) - b2b(rest["away"]), max(-3, min(3, rest["home"] - rest["away"])), 1.0 if g["playoff"] else 0.0],
                            "x_t": [*summ[:3], summ[10], (eh + ea) * pace / 100, pace, b2b(rest["home"]) + b2b(rest["away"])],
                            "margin": g["hs"] - g["as"], "total": g["hs"] + g["as"]})
            # 更新
            for team, pid, v in plist:
                if g["dt"].year < 2009 or not prior_set:
                    if pid not in first:
                        first[pid] = g["season"]
                    if first[pid] == g["season"]:
                        for s in STATS:
                            tot[s] += v[s]
                        if v["pm"] is not None:
                            pmt += v["pm"]
                            pmm += v["min"]
                ps.add(pid, now, v)
                cur_team[pid] = team
            for side in ("home", "away"):
                lu = [pid for team, pid, v in plist if team == g[side]]
                if lu:
                    last_lineup[g[side]] = lu
            last_game[g["home"]] = last_game[g["away"]] = g["dt"]
    return out


def ridge_fit(X, y, alpha):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    A = Z.T @ Z + alpha * np.eye(Z.shape[1])
    b = np.linalg.solve(A, Z.T @ (y - y.mean()))
    return lambda Xn: y.mean() + ((Xn - mu) / sd) @ b, b


def second_stage(feats, season, alpha):
    tr = [f for f in feats if V1.FIRST_TRAIN <= f["season"] < season]
    te = [f for f in feats if f["season"] == season]
    if len(tr) < 3000 or not te:
        return [], None
    Xm, ym = np.array([f["x_m"] for f in tr]), np.array([f["margin"] for f in tr], float)
    fm, coef = ridge_fit(Xm, ym, alpha)
    sm = float(np.std(ym - fm(Xm)))
    Xt, yt = np.array([f["x_t"] for f in tr]), np.array([f["total"] for f in tr], float)
    ft, _ = ridge_fit(Xt, yt, alpha)
    st = float(np.std(yt - ft(Xt)))
    pm_, pt_ = fm(np.array([f["x_m"] for f in te])), ft(np.array([f["x_t"] for f in te]))
    out = []
    for f, m, t in zip(te, pm_, pt_):
        r = {"season": f["season"], "date": f["date"], "home": f["home"], "away": f["away"], "pred_m": float(m), "pred_t": float(t),
             "p": float(norm.cdf(m / sm)), "y": int(f["margin"] > 0), "margin": f["margin"], "total": f["total"],
             "oc_h": f["oc_h"], "oc_a": f["oc_a"], "oo_h": f["oo_h"], "oo_a": f["oo_a"],
             "pc": E.devig2(f["oc_h"], f["oc_a"]), "po": E.devig2(f["oo_h"], f["oo_a"])}
        if f["spread"] is not None:
            line = -f["spread"]
            r["sp"] = float(1 - norm.cdf((line - m) / sm))
            r["sp_hit"] = None if f["margin"] == line else int(f["margin"] > line)
            r["spread_line"] = line
        if f["total_line"]:
            r["ou"] = float(1 - norm.cdf((f["total_line"] - t) / st))
            r["ou_hit"] = None if f["total"] == f["total_line"] else int(f["total"] > f["total_line"])
        out.append(r)
    names = FEAT + ["球隊效率", "背靠背", "休息差", "季後賽"]
    return out, dict(zip(names, [round(float(x), 3) for x in coef]))


def run(games, box, info, cfg, seasons):
    feats = features(games, box, info, cfg)
    preds, coefs = [], None
    for s in range(seasons[0], seasons[1] + 1):
        p, c = second_stage(feats, s, cfg["alpha"])
        preds += p
        coefs = c or coefs
    return preds, coefs


# 第一輪（365／730 天 × 250／1000 分鐘 × 拉回 1／30）最好的在邊角，所以往外再試一圈；拉回 1 和 30 幾乎一樣，只留 30
GRID = [{"hp": hp, "hm": 21.0, "K": k, "Kpm": kp, "team_hl": th, "alpha": al}
        for hp in (180.0, 365.0, 730.0) for k in (100.0, 250.0, 1000.0) for kp in (1500.0,) for th in (120.0,) for al in (30.0,)]


def main():
    rep_path = os.path.join(OUT, "us_report.json")
    rep = json.load(open(rep_path, encoding="utf-8")) if os.path.exists(rep_path) else {}
    R = rep.get("nba2", {})
    games = V1.load()
    box = load_box()
    info = load_players()
    print(f"NBA v2：{len(games)} 場、{sum(len(v) for v in box.values())} 球員場次、{len(info)} 位球員資料", flush=True)
    if "--tune" in sys.argv:
        grid = []
        for cfg in GRID:
            preds, coefs = run(games, box, info, cfg, V1.VALID)
            ev = V1.evaluate(preds)
            grid.append({**cfg, "ll_model": ev["ml"]["ll_model"], "ll_close": ev["ml"]["ll_close"], "ll_base": ev["ml"]["ll_base"],
                         "n": ev["ml"]["n"], "mae": ev.get("mae")})
            print(json.dumps(grid[-1]), flush=True)
        best = min(grid, key=lambda g: g["ll_model"])
        c = {k: best[k] for k in ("hp", "hm", "K", "Kpm", "team_hl", "alpha")}
        preds, coefs = run(games, box, info, c, V1.VALID)
        ev = V1.evaluate(preds)
        R.update({"grid": grid, "chosen": c, "valid": ev, "coefs": coefs, "blend_ab": [ev["ml"]["blend"]["a"], ev["ml"]["blend"]["b"]],
                  "tuned_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")})
        E.save_sport(rep_path, "nba2", R)
        print("NBA v2 驗證完成：", c, ev["ml"]["ll_model"], ev["ml"]["ll_close"], coefs)
    elif "--lineups" in sys.argv:
        # 同一組設定，比較三種「知道誰上場」的方式（只在驗證季）
        base = {k: v for k, v in R["chosen"].items() if k != "lineup"}
        out = {}
        for mode in ("actual", "actual10", "prev"):
            preds, coefs = run(games, box, info, {**base, "lineup": mode}, V1.VALID)
            ev = V1.evaluate(preds)
            out[mode] = {"valid": ev, "coefs": coefs, "blend_ab": [ev["ml"]["blend"]["a"], ev["ml"]["blend"]["b"]]}
            print(mode, ev["ml"]["ll_model"], ev["ml"]["ll_close"], ev["ml"]["blend"], ev["ml"]["clv"].get("calm_0.03"), flush=True)
        # 收盤時用的模型：actual10 跟 actual 差不到 0.0005 就用比較保險的 actual10
        close_mode = "actual10" if out["actual10"]["valid"]["ml"]["ll_model"] - out["actual"]["valid"]["ml"]["ll_model"] < 0.0005 else "actual"
        R["chosen"] = {**base, "lineup": close_mode}
        R["valid"], R["coefs"], R["blend_ab"] = out[close_mode]["valid"], out[close_mode]["coefs"], out[close_mode]["blend_ab"]
        R["open_model"] = {"lineup": "prev", **out["prev"]}
        R["lineup_cmp"] = {m: {"ll_model": out[m]["valid"]["ml"]["ll_model"], "blend": out[m]["valid"]["ml"]["blend"]} for m in out}
        E.save_sport(rep_path, "nba2", R)
        print("收盤模型用", close_mode)
    elif "--reference-test" in sys.argv:
        if R.get("ref_test"):
            print("NBA v2 參考考試已經跑過了")
            return
        c = R["chosen"]
        preds, coefs = run(games, box, info, c, V1.TEST)
        ev = V1.evaluate(preds, blend=R["blend_ab"])
        po, _ = run(games, box, info, {**c, "lineup": "prev"}, V1.TEST)
        evo = V1.evaluate(po, blend=R["open_model"]["blend_ab"])
        R["ref_test"] = {"run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "config": c, **ev,
                         "open_model": evo,
                         "note": "這兩季第 1 版考過；第 2 版只用驗證季挑設定，這裡跑一次當參考，真正的考試是 2026–27 季"}
        E.save_sport(rep_path, "nba2", R)
        print("NBA v2 參考考試：", ev["ml"]["ll_model"], ev["ml"]["ll_close"], evo["ml"]["ll_model"], evo["ml"]["clv"].get("calm_0.03"))


if __name__ == "__main__":
    main()
